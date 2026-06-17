"""LAN server — aiohttp application lifecycle management."""
import asyncio
import logging
import os
import ssl
import threading
from pathlib import Path

from aiohttp import web

from AssetsManager.lan.api import setup_routes
from AssetsManager.lan.auth import hash_key, hash_password, is_password_hash, verify_key, verify_token, verify_auth_token
from AssetsManager.repositories.auth_repository import AuthRepository
from AssetsManager.lan.routes._helpers import AUTH_SERVICE_APP_KEY, LAN_APP_KEY
from AssetsManager.lan.ws import WebSocketManager
from AssetsManager.lan.scanner import DirectoryScanner
from AssetsManager.lan.tunnel import TunnelManager
from AssetsManager.lan.security import RateLimiter, AuthRateLimiter, IPBlacklist, create_security_middleware
from AssetsManager.lan.utils import get_local_ip

_log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


class _LanServerImpl:
    """Internal server implementation. Do not use directly — use LanServer facade."""

    def __init__(self, *, library_root: str, thumbnail_dir: str, db_conn,
                 share_name: str = "AssetManager", password: str | None = None,
                 access_key: str | None = None,
                 rate_limit: int = 100, blocked_ips: list[str] | None = None,
                 blur_tags: list[str] | None = None,
                 ssl_cert: str | None = None, ssl_key: str | None = None):
        self._library_root = Path(library_root)
        self._thumbnail_dir = Path(thumbnail_dir)
        self._db_conn = db_conn
        self._share_name = share_name
        # Accept both plaintext and pre-hashed passwords for backward compatibility.
        # New settings save hashes; old settings may contain plaintext.
        if password:
            self._password_hash = password if is_password_hash(password) else hash_password(password)
        else:
            self._password_hash = None
        self._access_key_hash = hash_key(access_key) if access_key else None
        self._ws_manager = WebSocketManager()
        self._scanner = DirectoryScanner(library_root, db_conn)
        self._tunnel = TunnelManager()
        self._blur_tags = set(blur_tags or [])
        self._token_secret = os.urandom(32).hex()  # Random secret for token signing

        # Security
        self._rate_limiter = RateLimiter(max_requests=rate_limit)
        self._auth_rate_limiter = AuthRateLimiter(max_attempts=10, window_seconds=300)
        self._ip_blacklist = IPBlacklist()
        if blocked_ips:
            self._ip_blacklist.load_from_settings(blocked_ips)

        # SSL
        self._ssl_cert = ssl_cert
        self._ssl_key = ssl_key

        # Hot-reloadable settings (initialized to defaults)
        self._theme_color = None
        self._welcome_msg = None
        self._footer_text = None
        self._show_hidden = False
        self._max_depth = 0
        self._include_types = None
        self._exclude_patterns = None

        # Build middleware chain
        security_mw = create_security_middleware(self._rate_limiter, self._ip_blacklist, self._auth_rate_limiter)
        self._app = web.Application(middlewares=[security_mw, self._auth_middleware])
        self._app[LAN_APP_KEY] = self
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._port: int = 8080
        self._bind: str = "0.0.0.0"
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._connections: int = 0
        self._requests: int = 0
        self._bytes_transferred: int = 0

        # User existence cache (avoid DB query on every request)
        self._has_users_cache: bool | None = None
        self._has_users_cache_time: float = 0
        self._has_users_cache_ttl: float = 30.0  # Cache for 30 seconds

        # Auth service — initialized here so middleware can use it even before
        # _startup() runs (e.g. in test scenarios).
        from AssetsManager.application.auth_service import AuthService
        self._auth_service = AuthService(self._db_conn, self._token_secret)

        setup_routes(self._app, STATIC_DIR)

    # ── Public API ──────────────────────────────────────────────

    def start(self, port: int = 8080, bind: str = "0.0.0.0"):
        """Start the server on the given port."""
        if self._running:
            _log.warning("Server already running on port %d", self._port)
            return
        self._port = port
        self._bind = bind
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        # Wait briefly for startup to complete
        self._thread.join(timeout=2)
        if not self._running:
            raise OSError(f"Failed to start server on port {port}. Port may be in use.")

    def stop(self):
        """Stop the server gracefully."""
        if not self._running or not self._loop:
            return
        try:
            future = asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
            future.result(timeout=8)
        except (TimeoutError, Exception) as e:
            _log.warning("Server shutdown timed out or failed: %s", e)
        finally:
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass
            self._running = False
            self._loop = None
            self._thread = None

    def is_running(self) -> bool:
        return self._running

    def status(self) -> dict:
        ip = get_local_ip()
        return {
            "running": self._running,
            "ip": ip,
            "port": self._port,
            "url": f"http://{ip}:{self._port}",
            "share_name": self._share_name,
            "library_root": str(self._library_root),
            "auth_enabled": self._password_hash is not None,
            "connections": self._connections,
            "requests": self._requests,
            "bytes_transferred": self._bytes_transferred,
        }

    def broadcast(self, event_type: str, data: dict | None = None):
        """Send a WebSocket event to all connected clients."""
        if self._loop and self._running:
            asyncio.run_coroutine_threadsafe(
                self._ws_manager.broadcast(event_type, data), self._loop
            )

    # ── Properties for API handlers ─────────────────────────────

    @property
    def library_root(self) -> Path:
        return self._library_root

    @property
    def thumbnail_dir(self) -> Path:
        return self._thumbnail_dir

    @property
    def db_conn(self):
        return self._db_conn

    def connection_for(self, library_root: str | Path | None = None):
        """Return the LAN session DB connection for this library root."""
        if library_root is not None:
            requested = Path(library_root).resolve()
            if requested != self._library_root.resolve():
                raise ValueError(
                    "Requested library does not match the active LAN server library"
                )
        return self._db_conn

    @property
    def share_name(self) -> str:
        return self._share_name

    @property
    def scanner(self) -> DirectoryScanner:
        return self._scanner

    @property
    def ws_manager(self) -> WebSocketManager:
        return self._ws_manager

    @property
    def password_hash(self) -> str | None:
        return self._password_hash

    @property
    def access_key_hash(self) -> str | None:
        return self._access_key_hash

    @property
    def blur_tags(self) -> set[str]:
        return self._blur_tags

    @property
    def token_secret(self) -> str:
        return self._token_secret

    @property
    def tunnel(self) -> TunnelManager:
        return self._tunnel

    def start_tunnel(self, timeout: int = 30) -> str | None:
        """Start a public Cloudflare tunnel. Returns public URL or None."""
        self._tunnel._port = self._port
        return self._tunnel.start(timeout=timeout)

    def stop_tunnel(self):
        """Stop the public tunnel."""
        self._tunnel.stop()

    def reload_settings(self, settings: dict):
        """Reload settings that don't require server restart.

        Hot-reloadable settings:
        - share_name
        - blur_tags
        - show_hidden
        - max_depth
        - include_types
        - exclude_patterns
        - theme_color
        - welcome_msg
        - footer_text
        """
        if "share_name" in settings:
            self._share_name = settings["share_name"]
        if "blur_tags" in settings:
            self._blur_tags = set(settings["blur_tags"])
        if "theme_color" in settings:
            self._theme_color = settings["theme_color"]
        if "welcome_msg" in settings:
            self._welcome_msg = settings["welcome_msg"]
        if "footer_text" in settings:
            self._footer_text = settings["footer_text"]
        if "show_hidden" in settings:
            self._show_hidden = settings["show_hidden"]
        if "max_depth" in settings:
            self._max_depth = settings["max_depth"]
        if "include_types" in settings:
            self._include_types = settings["include_types"]
        if "exclude_patterns" in settings:
            self._exclude_patterns = settings["exclude_patterns"]

        _log.info("Settings reloaded (hot)")

    @property
    def current_settings(self) -> dict:
        """Return current settings for API handlers."""
        return {
            "share_name": self._share_name,
            "blur_tags": self._blur_tags,
            "theme_color": self._theme_color,
            "welcome_msg": self._welcome_msg,
            "footer_text": self._footer_text,
            "show_hidden": self._show_hidden,
            "max_depth": self._max_depth,
            "include_types": self._include_types,
            "exclude_patterns": self._exclude_patterns,
        }

    # ── Internal ────────────────────────────────────────────────

    def _run(self):
        """Run the asyncio event loop in a background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._startup())

    async def _startup(self):
        AuthRepository(self._db_conn).init_tables()
        self._app[AUTH_SERVICE_APP_KEY] = self._auth_service
        self._runner = web.AppRunner(
            self._app,
            access_log=None,  # Disable default access log
        )
        await self._runner.setup()

        # SSL context for HTTPS
        ssl_context = None
        if self._ssl_cert and self._ssl_key:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            try:
                ssl_context.load_cert_chain(self._ssl_cert, self._ssl_key)
                _log.info("HTTPS enabled with cert: %s", self._ssl_cert)
            except Exception as e:
                _log.warning("Failed to load SSL cert: %s. Falling back to HTTP.", e)
                ssl_context = None

        self._site = web.TCPSite(
            self._runner,
            self._bind,
            self._port,
            ssl_context=ssl_context,
        )
        try:
            await self._site.start()
        except OSError as e:
            _log.error("Failed to start server on port %d: %s", self._port, e)
            self._running = False
            await self._runner.cleanup()
            return
        self._running = True
        protocol = "https" if ssl_context else "http"
        _log.info("LAN sharing started on %s://%s:%d", protocol, get_local_ip(), self._port)

        # Start background file scanner for fast search
        self._scanner.start_background_scan()

        # Keep the loop running
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    async def _shutdown(self):
        self._running = False
        await self._ws_manager.close_all()
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()
        _log.info("LAN sharing stopped")

    def _has_active_users(self) -> bool:
        """Check if there are active users, with caching to avoid DB query on every request."""
        import time
        now = time.time()
        if self._has_users_cache is not None and (now - self._has_users_cache_time) < self._has_users_cache_ttl:
            return self._has_users_cache
        try:
            row = self._db_conn.execute(
                "SELECT COUNT(*) FROM users WHERE is_active=1"
            ).fetchone()
            result = row[0] > 0 if row else False
            self._has_users_cache = result
            self._has_users_cache_time = now
            return result
        except Exception:
            return self._has_users_cache or False

    def invalidate_user_cache(self):
        """Invalidate the user existence cache (call when users are added/removed)."""
        self._has_users_cache = None

    @web.middleware
    async def _auth_middleware(self, request, handler):
        """Authentication middleware — skip for public endpoints."""
        if request.path in ("/api/auth/login", "/api/auth/register", "/api/auth/verify_key",
                            "/api/info", "/api/tunnel/status", "/ws", "/",
                            "/favicon.ico") or request.path.startswith("/static") \
                or request.path.startswith("/s/") \
                or (request.path.startswith("/api/shares/") and request.method == "GET"):
            return await handler(request)

        # Check if any auth is configured
        has_key = self._access_key_hash is not None
        has_password = self._password_hash is not None
        has_users = self._has_active_users()

        # No auth required if nothing configured
        if not has_key and not has_password and not has_users:
            return await handler(request)

        # Get token from cookie, header, or query param
        from AssetsManager.lan.routes._helpers import get_auth_token, set_request_auth_context
        token = get_auth_token(request)

        # Try access key auth
        if has_key and token and self._access_key_hash:
            if verify_key(token, self._access_key_hash):
                set_request_auth_context(request, "access_key", {"username": "access_key", "role": "admin"})
                return await handler(request)

        # Try local UI API token (signed with token_secret)
        if self._token_secret and token:
            if verify_auth_token(token, self._token_secret):
                set_request_auth_context(request, "local_ui", {"username": "local_ui", "role": "admin"})
                return await handler(request)

        # Try user-based token
        if token:
            user = self._auth_service.verify_user_token(token)
            if user:
                set_request_auth_context(request, "user", user)
                return await handler(request)

        # Try simple password token
        if self._password_hash and token:
            if verify_token(token, self._password_hash):
                set_request_auth_context(request, "password", {"username": "password", "role": "admin"})
                return await handler(request)

        return web.json_response({"error": "Unauthorized"}, status=401)
