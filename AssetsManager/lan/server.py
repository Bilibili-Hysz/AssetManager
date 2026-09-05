"""LAN server — aiohttp application lifecycle management.

Lifecycle machinery (stop/cleanup "single-owner" protocol, worker-loop state machine) lives in ``AssetsManager/lan/server_lifecycle.py``.
"""
import asyncio
import inspect
import concurrent.futures
import logging
import ssl
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast

from aiohttp import web

from AssetsManager.lan.api import setup_routes
from AssetsManager.lan.auth import hash_key, hash_password, is_password_hash, verify_key, verify_token_async, verify_auth_token
from AssetsManager.lan.guarded_tunnel import _GuardedTunnel
from AssetsManager.lan.routes._errors import error_contract_middleware, error_response
from AssetsManager.lan.routes._helpers import AUTH_SERVICE_APP_KEY, LAN_APP_KEY, ZIP_EXECUTOR_APP_KEY, ActivityLog, OnlineUsers, LanScopedServices
from AssetsManager.lan.runtime_validation import (
    _MISSING,
    _derive_local_ui_auth_secret,
    _observe_broadcast,
    _runtime_operation,
    _runtime_services_snapshot,
    _validate_runtime_service_bindings,
)
from AssetsManager.lan.token_revocations import TokenRevocationRegistry
from AssetsManager.lan.ws import WebSocketManager
from AssetsManager.lan.scanner import DirectoryScanner
from AssetsManager.lan.tunnel import TunnelManager
from AssetsManager.lan import tunnel_identity
from AssetsManager.lan.security import RateLimiter, AuthRateLimiter, IPBlacklist, create_security_middleware
from AssetsManager.lan.route_policy import request_policy
from AssetsManager.lan.server_lifecycle import LanServerLifecycleMixin
from AssetsManager.lan.utils import get_local_ip

_log = logging.getLogger(__name__)


class _LanServerImpl(LanServerLifecycleMixin):
    """Internal server implementation. Do not use directly — use LanServer facade."""

    _library_root: Path
    _thumbnail_dir: Path
    _db_conn: Any
    _token_secret: str
    _local_ui_auth_secret: str
    performance_recorder: Any
    session_token: str | None
    _scanner: DirectoryScanner
    _auth_service: Any
    _share_service: Any
    services: LanScopedServices
    _services: LanScopedServices

    def __init__(self, *, runtime=None,
                 share_name: str = "AssetManager", password: str | None = None,
                 access_key: str | None = None,
                 auth_mode: str | None = None,
                 rate_limit: int = 100, blocked_ips: list[str] | None = None,
                  ip_whitelist: list[str] | None = None,
                  blur_tags: list[str] | None = None,
                  ssl_cert: str | None = None, ssl_key: str | None = None,
                  performance_recorder=None, session_token: str | None = None,
                  services=None):
        self._runtime_adapter_registered = False
        self._runtime_adapter_lock = threading.Lock()
        self._runtime_adapter_condition_lock = threading.Condition(self._runtime_adapter_lock)
        self._runtime_adapter_state = "unregistered"
        self._runtime_adapter_registration_thread = None
        self.runtime = runtime
        self._requires_preflight = True
        session = getattr(runtime, "session", None)
        if session is None:
            raise ValueError("runtime must be live and canonical for its LibrarySession")
        if getattr(session, "is_closed", False):
            raise ValueError("runtime session must be live")
        self._share_name = share_name
        self._auth_mode = auth_mode
        self._password_hash = self._password_hash_for(password)
        self._access_key_hash = hash_key(access_key) if access_key else None
        self._password_value = password
        self._access_key_value = access_key
        # Auth-config-bound local-UI secret cache: (config key, secret). The
        # config key mirrors (_password_value, _access_key_value, _auth_mode);
        # readers hit the cache while the config is unchanged and re-derive
        # from the fields they just read on a miss, so publishing the mutated
        # fields before a new cache entry keeps every reader correct without
        # a lock (the HMAC cost on a racing reader is the only downside).
        self._local_ui_auth_secret_cache: (
            tuple[tuple[str | None, str | None, str | None], str] | None
        ) = None
        self._ws_manager = WebSocketManager(on_connection_change=self._set_connection_count)
        self._tunnel = TunnelManager()
        self._tunnel_start_block_reason: str | None = None
        self._blur_tags = set(blur_tags or [])
        # L3: ZIP builds run on a server-owned bounded executor (published on
        # the app in _build_app) so shutdown can cancel/close it; the gallery
        # prewarm thread is tracked so shutdown can join it.
        self._zip_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="lan-zip"
        )
        # Public shutdown state for the executor: _shutdown flips this to
        # True and _ensure_zip_executor rebuilds on the next start(), so a
        # stop→start cycle never republishes a dead executor to the app.
        self._zip_executor_shutdown = False
        self._gallery_prewarm_thread: threading.Thread | None = None

        # Security
        self._rate_limit_value = rate_limit
        self._blocked_ips = list(blocked_ips or [])
        self._ip_whitelist = list(ip_whitelist or [])
        self._rate_limiter = RateLimiter(max_requests=rate_limit)
        # L2: heavy public browsing surfaces get a generous dedicated budget
        # (600/min/IP) instead of sharing the tight general budget or being
        # skip-open like thumbnail/media polling.
        self._browse_rate_limiter = RateLimiter(max_requests=600, window_seconds=60)
        self._auth_rate_limiter = AuthRateLimiter(max_attempts=10, window_seconds=300)
        # Credential-bearing media/status requests still run the expensive
        # authentication chain.  Keep anonymous polling unrestricted while
        # bounding random-token PBKDF2/DB probes on routes classified as skip.
        self._skip_auth_rate_limiter = RateLimiter(max_requests=120, window_seconds=60)
        self._ip_blacklist = IPBlacklist()
        if blocked_ips:
            self._ip_blacklist.load_from_settings(blocked_ips)

        # SSL
        self._ssl_cert = ssl_cert
        self._ssl_key = ssl_key
        self._ssl_active = False

        # Hot-reloadable settings (initialized to defaults)
        self._theme_color = None
        self._welcome_msg = None
        self._footer_text = None
        self._show_hidden = False
        self._max_depth = 0
        self._include_types = None
        self._exclude_patterns = None

        self._app: web.Application | None = None

        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._port: int = 8080
        self._bind: str = "0.0.0.0"
        self._running = False
        self._lifecycle_state = "stopped"
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._cleanup_complete = True
        self._shutdown_future: concurrent.futures.Future[Any] | None = None
        self._lifecycle_lock = threading.Lock()
        self._lifecycle_generation = 0
        self._stop_reservations = 0
        self._stop_reservation_generation = 0
        self._startup_result_event: threading.Event | None = None
        self._startup_result: tuple[str, int] | None = None
        self._startup_cancel_generation = None
        self._cleanup_started_event = None
        self._startup_cleanup_failed = False
        # Cleanup is a single-owner protocol.  The future is useful for
        # awaiting the coroutine, but the attempt event is the authoritative
        # cross-thread publication: the owner publishes its terminal state
        # before releasing the event, so stop() cannot observe a stale future
        # immediately at the timeout boundary.
        self._cleanup_attempt_future = None
        self._cleanup_attempt_event: threading.Event | None = None
        self._cleanup_attempt_state = "idle"
        self._cleanup_attempt_owner = None
        self._cleanup_attempt_error: BaseException | None = None
        self._cleanup_retry_used = False
        self._startup_cleanup_retry_used = False
        self._connections: int = 0
        self._requests: int = 0
        self._bytes_transferred: int = 0
        self._started_at: float | None = None
        self._metrics_lock = threading.Lock()

        # User existence cache (avoid DB query on every request).
        # _has_users_cache is read from both the event-loop thread
        # (_auth_middleware) and the UI thread (status/auth_status), so the
        # check/read/write pair is guarded by its own lock.
        self._has_users_cache: bool | None = None
        self._has_users_cache_time: float = 0
        self._has_users_cache_ttl: float = 30.0  # Cache for 30 seconds
        self._has_users_cache_lock = threading.Lock()
        # Concurrency contract: only the server event-loop thread reads or
        # writes _revoked_tokens (auth middleware + logout handler). Keep
        # every facade path off it, or add synchronization first.
        self._revoked_tokens: dict[str, float] = {}
        # Durable revocation: rows persist in the library DB (via the bound
        # AuthService) so a token signed with the persisted password hash
        # cannot resurrect after an app restart. Loaded once on first use.
        self._revoked_loaded = False
        self._token_revocations = TokenRevocationRegistry(self)

        with _runtime_operation(runtime, session):
            runtime_services = _runtime_services_snapshot(runtime)
            if runtime_services is None:
                raise ValueError(
                    "runtime must be live and canonical for its LibrarySession"
                )

            has_snapshot_session = (
                inspect.getattr_static(runtime_services, "session", _MISSING)
                is not _MISSING
            )
            snapshot_session = (
                runtime_services.session if has_snapshot_session else _MISSING
            )
            if snapshot_session is not session:
                raise ValueError(
                    "runtime must be live and canonical for its LibrarySession"
                )

            has_lan_projection = (
                inspect.getattr_static(runtime_services, "lan_services", _MISSING)
                is not _MISSING
            )
            if not has_lan_projection:
                raise ValueError("runtime snapshot has no LAN service projection")
            lan_runtime_services = runtime_services.lan_services
            if lan_runtime_services is None:
                raise ValueError("runtime snapshot has no LAN service projection")

            has_sharing_projection = (
                inspect.getattr_static(runtime_services, "sharing_services", _MISSING)
                is not _MISSING
            )
            if not has_sharing_projection:
                raise ValueError("runtime snapshot has no sharing service projection")
            sharing_runtime_services = runtime_services.sharing_services
            if sharing_runtime_services is None:
                raise ValueError("runtime snapshot has no sharing service projection")

            library_root = session.root
            thumbnail_dir = session.thumb_dir
            db_conn = session.connection_for(session.root)
            runtime_performance_recorder = getattr(
                runtime_services, "performance_recorder", performance_recorder
            )
            runtime_session_token = session.event_token
            event_library_root = getattr(session, "root_str", str(library_root))

            _validate_runtime_service_bindings(
                runtime_services,
                lan_runtime_services,
                sharing_runtime_services,
                session,
                db_conn,
            )

            auth_service = sharing_runtime_services.auth_service
            share_service = sharing_runtime_services.share_service
            token_secret = sharing_runtime_services.token_secret

            scanner = DirectoryScanner(library_root, db_conn)
            scoped_services = LanScopedServices(
                auth_service=auth_service,
                metadata_service=runtime_services.metadata_service,
                project_service=lan_runtime_services.project_service,
                tag_service=runtime_services.tag_service,
                search_service=lan_runtime_services.search_service,
                thumbnail_service=runtime_services.thumbnail_service,
                asset_service=lan_runtime_services.asset_service,
                share_service=share_service,
                gallery_service=getattr(lan_runtime_services, "gallery_service", None),
                favorite_service=getattr(lan_runtime_services, "favorite_service", None),
                collection_service=getattr(runtime_services, "collection_service", None),
                activity_log=ActivityLog(
                    library_root=event_library_root,
                    session_token=runtime_session_token,
                    connection_provider=lambda: db_conn,
                ),
                online_users=OnlineUsers(
                    library_root=event_library_root,
                    session_token=runtime_session_token,
                ),
                runtime_services=runtime_services,
            )

            def publish_runtime_binding():
                self._library_root = Path(library_root)
                self._thumbnail_dir = Path(thumbnail_dir)
                self._db_conn = db_conn
                self._token_secret = token_secret
                local_ui_secret = _derive_local_ui_auth_secret(
                    token_secret,
                    password=self._password_value,
                    access_key=self._access_key_value,
                    auth_mode=self._auth_mode,
                )
                self._local_ui_auth_secret = local_ui_secret
                self._local_ui_auth_secret_cache = (
                    (self._password_value, self._access_key_value, self._auth_mode),
                    local_ui_secret,
                )
                self.performance_recorder = runtime_performance_recorder
                self.session_token = runtime_session_token
                self._scanner = scanner
                self._auth_service = auth_service
                self._share_service = share_service
                self.services = scoped_services

            publish_while_live = getattr(session, "_publish_while_live", None)
            if callable(publish_while_live):
                publish_while_live(publish_runtime_binding)
            else:
                if getattr(session, "is_closed", False):
                    raise ValueError("runtime session must be live")
                publish_runtime_binding()

        self._services = self.services
        self._build_app()

    def _ensure_zip_executor(self) -> concurrent.futures.ThreadPoolExecutor:
        """Return a live ZIP executor, rebuilding one after a prior shutdown.

        ``_shutdown`` closes the server-owned executor symmetrically with the
        rest of the loop resources; a later ``start()`` on the same instance
        must publish a usable executor, so ``_build_app`` resolves the app key
        through this method instead of reusing the stale handle directly.
        """
        executor = getattr(self, "_zip_executor", None)
        if executor is None or getattr(self, "_zip_executor_shutdown", False):
            executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="lan-zip"
            )
            self._zip_executor = executor
            self._zip_executor_shutdown = False
        return executor

    @staticmethod
    def _password_hash_for(password: str | None) -> str | None:
        """Normalize a configured password into its stored hash.

        Accepts both plaintext and pre-hashed passwords for backward
        compatibility: new settings save hashes, old settings may contain
        plaintext.
        """
        if not password:
            return None
        return password if is_password_hash(password) else hash_password(password)

    def _build_app(self) -> None:
        """Build a fresh aiohttp application for the next event loop."""
        security_mw = create_security_middleware(
            self._rate_limiter,
            self._ip_blacklist,
            self._auth_rate_limiter,
            browse_rate_limiter=self._browse_rate_limiter,
            # ``getattr`` keeps lightweight test/compatibility skeletons that
            # predate this defensive bucket valid; production __init__ always
            # creates the limiter above.
            skip_auth_rate_limiter=getattr(self, "_skip_auth_rate_limiter", None),
            ip_whitelist=self._ip_whitelist,
            tunnel_active=self._tunnel_active,
            tunnel_identity_resolver=self._tunnel_identity_resolver,
            tunnel_identity_minter=self._tunnel_identity_minter,
        )
        # error_contract_middleware is the innermost (handler-adjacent) layer:
        # it only normalizes what escapes a route handler into the shared JSON
        # error contract; security/auth failures are owned by their own layers.
        app = web.Application(middlewares=[security_mw, self._metrics_middleware, self._auth_middleware, error_contract_middleware])
        self._app = app
        app[LAN_APP_KEY] = self
        app[ZIP_EXECUTOR_APP_KEY] = self._ensure_zip_executor()
        setup_routes(app)

    def _tunnel_identity_resolver(self, request) -> str | None:
        """Validated visitor-cookie client id for tunnel-mode limiter keys."""
        secret = tunnel_identity.signing_secret(self)
        token = tunnel_identity.valid_token(
            request.cookies.get(tunnel_identity.COOKIE_NAME), secret
        )
        return tunnel_identity.token_client_id(token) if token else None

    def _tunnel_identity_minter(self) -> tuple[str, str]:
        """Mint ``(client_id, cookie_token)`` for a first-contact visitor."""
        secret = tunnel_identity.signing_secret(self)
        token = tunnel_identity.new_token(secret)
        return tunnel_identity.token_client_id(token), token

    def _tunnel_active(self) -> bool:
        """True while the cloudflared tunnel is up (loopback whitelist bypass)."""
        try:
            return bool(self._tunnel.is_running)
        except Exception:
            return False

    @web.middleware
    async def _metrics_middleware(self, request, handler):
        with self._metrics_lock:
            self._requests += 1
        response = await handler(request)
        # Best-effort cumulative transfer size: declared content lengths only
        # (streaming/chunked bodies are not counted rather than guessed).
        length = getattr(response, "content_length", None)
        if isinstance(length, int) and length > 0:
            with self._metrics_lock:
                self._bytes_transferred += length
        return response

    # ── Public API ──────────────────────────────────────────────

    def start(self, port: int = 8080, bind: str = "0.0.0.0", *, preflight=None):
        """Start the server on the given port.

        The public LanServer facade owns the normal preflight gate. Keep
        this optional argument for direct lifecycle adapters and re-check it
        when supplied; legacy internal lifecycle tests that call this private
        implementation without a preflight remain unchanged.
        """
        from AssetsManager.application.security_preflight import SecurityPreflight

        if preflight is None and getattr(self, "_requires_preflight", False):
            preflight = SecurityPreflight()
        if preflight is not None:
            if not isinstance(preflight, SecurityPreflight):
                raise TypeError("preflight must be SecurityPreflight")
            snapshot = preflight.snapshot(
                sharing=True,
                bind=bind,
                auth_status=self.auth_status(),
            )
            if snapshot.share_state != "local_active":
                return snapshot.to_dict()
        with self._lifecycle_lock:
            if (self._lifecycle_state == "stopping"
                    or getattr(self, "_stop_reservations", 0)):
                raise RuntimeError("Cannot start while previous stop is still finalizing")
            if self._thread is not None:
                if self._thread.is_alive() and self._running and self._lifecycle_state == "running":
                    _log.warning("Server already running on port %d", self._port)
                    return
                if self._thread.is_alive():
                    raise RuntimeError("Cannot start while previous server thread is still alive")
                if not self._cleanup_complete:
                    raise RuntimeError("Cannot start: previous server cleanup incomplete")
            if not self._cleanup_complete:
                raise RuntimeError("Cannot start: previous server cleanup incomplete")
            if self._running:
                _log.warning("Server already running on port %d", self._port)
                return
            self._loop = None
            self._thread = None
            self._lifecycle_generation = getattr(self, "_lifecycle_generation", 0) + 1
            generation = self._lifecycle_generation
            self._startup_result_event = threading.Event()
            self._startup_result = None
            self._startup_cancel_generation = None
            self._cleanup_started_event = threading.Event()
            self._startup_cleanup_failed = False
            self._cleanup_attempt_future = None
            self._cleanup_attempt_event = threading.Event()
            self._cleanup_attempt_state = "idle"
            self._cleanup_attempt_owner = None
            self._cleanup_attempt_error = None
            self._cleanup_retry_used = False
            self._startup_cleanup_retry_used = False
            self._lifecycle_state = "starting"
            self._cleanup_complete = False
            self._port = port
            self._bind = bind
            self._ssl_active = False
            self._build_app()
            self._thread = threading.Thread(target=self._run, daemon=True)
        try:
            self._thread.start()
        except Exception:
            if not self._thread.is_alive() and self._loop is None:
                self._thread = None
                self._lifecycle_state = "stopped"
                self._cleanup_complete = True
                with self._lifecycle_lock:
                    self._shutdown_future = None
            else:
                self._lifecycle_state = "failed"
            raise
        # Lightweight test/thread adapters may set the running state directly;
        # treat that state as the worker's explicit completion publication.
        if self._running and self._lifecycle_state == "running":
            self._publish_startup_result("success")
        # Startup has a definitive per-generation result.  The timeout is only
        # a bounded wait: it requests cancellation and leaves reconciliation to
        # the owner loop before this generation may be replaced.
        startup_event = self._startup_result_event
        assert startup_event is not None
        if not startup_event.wait(timeout=8):
            with self._lifecycle_lock:
                if self._lifecycle_generation == generation:
                    self._startup_cancel_generation = generation
                    self._lifecycle_state = "failed"
            raise OSError(f"Failed to start server on port {port}: startup timed out")
        cleanup_started = getattr(self, "_cleanup_started_event", None)
        if self._startup_result and self._startup_result[0] == "failure" and cleanup_started:
            cleanup_started.wait(timeout=8)
        result = self._startup_result
        if not result or result[0] != "success":
            thread = self._thread
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=8)
            with self._lifecycle_lock:
                if self._lifecycle_generation == generation and self._cleanup_complete:
                    self._running = False
                    self._lifecycle_state = "stopped"
                    if self._thread is thread and (thread is None or not thread.is_alive()):
                        self._shutdown_future = None
            raise OSError(f"Failed to start server on port {port}. Port may be in use.")

    def is_running(self) -> bool:
        return self._running and self._lifecycle_state == "running"

    def status(self) -> dict:
        ip = get_local_ip()
        protocol = self.endpoint_protocol
        thread = self._thread
        loop = self._loop
        thread_alive = thread is not None and thread.is_alive()
        loop_active = loop is not None and not loop.is_closed()
        restart_ready = (
            self._lifecycle_state == "stopped"
            and self._cleanup_complete
            and (thread is None or not thread_alive)
            and (loop is None or not loop_active)
            and self._runner is None
            and self._site is None
            and self._shutdown_future is None
        )
        return {
            "running": self.is_running(),
            "lifecycle_state": self._lifecycle_state,
            "cleanup_complete": self._cleanup_complete,
            "owner_thread_alive": thread_alive,
            "loop_active": loop_active,
            "runner_retained": self._runner is not None,
            "restart_ready": restart_ready,
            "ip": ip,
            "port": self._port,
            "url": f"{protocol}://{ip}:{self._port}",
            "ssl_active": self._ssl_active,
            "share_name": self._share_name,
            "library_root": str(self._library_root),
            "auth_enabled": self.auth_status()[0],
            "connections": self._connections,
            "requests": self._requests,
            "bytes_transferred": self._bytes_transferred,
            "uptime": max(0.0, time.monotonic() - self._started_at)
            if self._started_at
            else 0.0,
        }


    def auth_status(self) -> tuple[bool, str]:
        """Return the effective LAN authentication state and mode."""
        has_key = self._access_key_hash is not None
        has_password = self._password_hash is not None
        has_users = self._has_active_users()

        if has_key:
            mode = "key"
        elif has_users:
            mode = "user"
        elif has_password:
            mode = "password"
        else:
            mode = "none"
        return has_key or has_password or has_users, mode

    def broadcast(self, event_type: str, data: dict | None = None):
        """Send a WebSocket event to all connected clients."""
        loop = self._loop
        if not (loop and self._running and not loop.is_closed()):
            return
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._ws_manager.broadcast(event_type, data), loop
            )
        except (RuntimeError, ValueError):
            _log.warning("WebSocket broadcast skipped: event loop unavailable")
            return
        future.add_done_callback(_observe_broadcast)

    _TOKEN_REVOCATION_TTL = 86400.0
    _TOKEN_REVOCATION_MAX = 10_000

    def _token_revocation_registry(self) -> TokenRevocationRegistry:
        """Return the (lazily built) host-bound token revocation registry.

        Built on first use so ``object.__new__(_LanServerImpl)`` skeleton test
        fixtures that bypass ``__init__`` keep working unchanged.
        """
        registry = getattr(self, "_token_revocations", None)
        if registry is None:
            registry = TokenRevocationRegistry(self)
            self._token_revocations = registry
        return registry

    def revoke_auth_token(self, token: str):
        """Server-side revocation of a presented auth token (TTL 24h).

        Delegates to the host-bound :class:`TokenRevocationRegistry`, which
        stores the in-memory table on this instance (``_revoked_tokens``) and
        persists through the bound AuthService.
        """
        self._token_revocation_registry().revoke_auth_token(token)

    def is_auth_token_revoked(self, token: str) -> bool:
        """Return True when a presented auth token has been revoked."""
        return self._token_revocation_registry().is_auth_token_revoked(token)

    async def is_auth_token_revoked_async(self, token: str) -> bool:
        """Check revocation without blocking the LAN event loop."""
        return await asyncio.to_thread(self.is_auth_token_revoked, token)

    async def revoke_auth_token_async(self, token: str) -> None:
        """Persist revocation without blocking the LAN event loop."""
        await asyncio.to_thread(self.revoke_auth_token, token)

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
        """Return the live LAN session connection for this library root."""
        session = getattr(self.runtime, "session", None)
        provider = getattr(session, "connection_for", None)
        if callable(provider):
            try:
                connection = provider(library_root)
            except ValueError as exc:
                raise ValueError(
                    "Requested library does not match the active LAN server library"
                ) from exc
            if connection is not self._db_conn:
                raise RuntimeError(
                    "LAN session returned a connection different from its runtime connection"
                )
            return connection
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

    def _set_connection_count(self, count: int) -> None:
        with self._metrics_lock:
            self._connections = count

    @property
    def password_hash(self) -> str | None:
        return self._password_hash

    @property
    def access_key_hash(self) -> str | None:
        return self._access_key_hash

    @property
    def blur_tags(self) -> set[str]:
        return self._blur_tags

    def _current_local_ui_auth_secret(self) -> str:
        """Return the UI credential derived from the live runtime secret.

        The derivation is cached per auth-config tuple so repeated reads
        (per-request principal resolution, desktop token minting) do not
        re-run the HMAC.  A reader that races a rotation either matches the
        cached config key or re-derives from the fields it just read, so
        the returned value always reflects the current credential fields.
        """
        config_key = (self._password_value, self._access_key_value, self._auth_mode)
        cache = getattr(self, "_local_ui_auth_secret_cache", None)
        if cache is not None and cache[0] == config_key:
            return cache[1]
        secret = _derive_local_ui_auth_secret(
            self._token_secret,
            password=self._password_value,
            access_key=self._access_key_value,
            auth_mode=self._auth_mode,
        )
        self._local_ui_auth_secret_cache = (config_key, secret)
        return secret

    @property
    def token_secret(self) -> str:
        """Local UI API secret retained under the legacy public name."""
        return self._current_local_ui_auth_secret()

    @property
    def runtime_token_secret(self) -> str:
        """Runtime-owned secret shared by AuthService and ShareService."""
        return self._token_secret

    @property
    def local_ui_auth_secret(self) -> str:
        """Auth-config-bound secret used only for local UI access-key tokens."""
        return self._current_local_ui_auth_secret()

    @property
    def ssl_active(self) -> bool:
        return self._ssl_active

    @property
    def endpoint_protocol(self) -> str:
        return "https" if self._ssl_active else "http"

    @property
    def tunnel(self) -> _GuardedTunnel:
        return _GuardedTunnel(self)

    def start_tunnel(self, timeout: int = 30) -> str | None:
        """Start a public Cloudflare tunnel. Returns public URL or None."""
        auth_enabled, auth_mode = self.auth_status()
        if not auth_enabled:
            # Keep the historical None failure contract for desktop callers,
            # but never expose an unauthenticated LAN server through a tunnel.
            self._tunnel_start_block_reason = "authentication_required"
            _log.warning(
                "Refusing to start public tunnel without LAN authentication "
                "(auth_mode=%s)",
                auth_mode,
            )
            return None

        self._tunnel_start_block_reason = None
        self._tunnel._port = self._port
        return self._tunnel.start(timeout=timeout)

    @property
    def tunnel_start_block_reason(self) -> str | None:
        """Return the last security reason that blocked tunnel startup."""
        return self._tunnel_start_block_reason

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

        Auth-config keys (``password``/``access_key``/``auth_mode``) are also
        accepted.  Applying one of them rotates the derived local-UI signing
        secret on the live server; every established local_ui-authority
        WebSocket is then evicted (see :meth:`_apply_auth_config_settings`).
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
        self._apply_auth_config_settings(settings)

        _log.info("Settings reloaded (hot)")

    _AUTH_CONFIG_SETTINGS_KEYS = ("password", "access_key", "auth_mode")

    def _apply_auth_config_settings(self, settings: dict) -> None:
        """Apply live auth-config changes and evict rotated local_ui sockets.

        The desktop shell rotates authentication through a full server
        restart (auth keys are restart-required there and the teardown
        closes every socket), so this path exists for callers that apply
        the change against a live server.  The derived
        ``local_ui_auth_secret`` is bound to the auth config, so a change
        rotates it implicitly — but the local_ui WebSocket authorizer
        captured the secret at admission (routes/websocket.py), meaning
        its sockets would keep authenticating with the pre-rotation
        credential until they happen to disconnect.  Detect the rotation
        here by comparing the re-derived secret against the published one
        and evict every local_ui-authority socket through the manager's
        canonical :meth:`WebSocketManager.revoke_authority` boundary.
        Access-key/password sockets are not evicted here: their
        authorizers re-read the live hashes on each re-authorization and
        fail closed on the next heartbeat or broadcast.
        """
        if not any(key in settings for key in self._AUTH_CONFIG_SETTINGS_KEYS):
            return
        new_password = settings.get("password", self._password_value)
        new_access_key = settings.get("access_key", self._access_key_value)
        new_auth_mode = settings.get("auth_mode", self._auth_mode)
        rotated_secret = _derive_local_ui_auth_secret(
            self._token_secret,
            password=new_password,
            access_key=new_access_key,
            auth_mode=new_auth_mode,
        )
        cache = getattr(self, "_local_ui_auth_secret_cache", None)
        previous_secret = (
            cache[1] if cache is not None else self._current_local_ui_auth_secret()
        )
        if rotated_secret == previous_secret:
            # The derived secret is unchanged — no rotation, keep sockets.
            return
        self._password_value = new_password
        self._access_key_value = new_access_key
        self._auth_mode = new_auth_mode
        self._password_hash = self._password_hash_for(new_password)
        self._access_key_hash = hash_key(new_access_key) if new_access_key else None
        # Publish the credential fields before the cache entry (see
        # _current_local_ui_auth_secret) so a reader that misses the cache
        # re-derives from the new config instead of the old secret.
        self._local_ui_auth_secret_cache = (
            (new_password, new_access_key, new_auth_mode),
            rotated_secret,
        )
        self._local_ui_auth_secret = rotated_secret
        self._evict_local_ui_websockets()

    def _evict_local_ui_websockets(self) -> None:
        """Evict every local_ui-authority WebSocket on the server loop.

        reload_settings runs on desktop/request threads while the
        WebSocketManager owns its state through asyncio locks on the server
        event loop, so the revocation is bridged with
        run_coroutine_threadsafe exactly like :meth:`broadcast`; the future
        is observed for errors and never awaited by the caller.
        """
        loop = self._loop
        if not (loop and self._running and not loop.is_closed()):
            return
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._ws_manager.revoke_authority(("local_ui",), lambda: True),
                loop,
            )
        except (RuntimeError, ValueError):
            _log.warning(
                "local_ui WebSocket eviction skipped: event loop unavailable"
            )
            return
        future.add_done_callback(_observe_broadcast)

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

    async def _startup(self):
        self._ssl_active = False
        self._site_started = False
        await self._ws_manager.start_accepting()
        app = self._app
        assert app is not None
        app[AUTH_SERVICE_APP_KEY] = self._auth_service
        runner = web.AppRunner(
            app,
            access_log=None,  # Disable default access log
        )
        self._runner = runner
        await runner.setup()

        # SSL context for HTTPS. Explicit TLS configuration is fail-closed:
        # never silently downgrade a requested HTTPS server to HTTP.
        ssl_context = None
        if self._ssl_cert or self._ssl_key:
            if not self._ssl_cert or not self._ssl_key:
                raise ValueError("Both ssl_cert and ssl_key are required for TLS")
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_context.load_cert_chain(self._ssl_cert, self._ssl_key)
            _log.info("HTTPS enabled with cert: %s", self._ssl_cert)

        site = web.TCPSite(
            runner,
            self._bind,
            self._port,
            ssl_context=ssl_context,
        )
        self._site = site
        try:
            await site.start()
        except BaseException:
            _log.exception("Failed to start server on port %d", self._port)
            raise
        self._site_started = True
        self._ssl_active = ssl_context is not None
        if self._port == 0:
            sockets = getattr(getattr(self._site, "_server", None), "sockets", None)
            if sockets:
                self._port = int(sockets[0].getsockname()[1])
        with self._lifecycle_lock:
            cancelled = getattr(self, "_startup_cancel_generation", None) == self._lifecycle_generation
            if not cancelled:
                self._started_at = time.monotonic()
                self._running = True
        if cancelled:
            self._running = False
            assert runner is not None
            await runner.cleanup()
            self._site = None
            self._runner = None
            self._ssl_active = False
            self._cleanup_complete = True
            raise RuntimeError("startup cancelled")

        try:
            retained = self._register_runtime_adapter()
        except BaseException:
            with self._lifecycle_lock:
                self._running = False
                if self._lifecycle_state == "starting":
                    self._lifecycle_state = "failed"
            raise

        registration_cancelled = False
        with self._lifecycle_lock:
            registration_cancelled = (
                getattr(self, "_startup_cancel_generation", None)
                == self._lifecycle_generation
                or self._lifecycle_state != "starting"
                or not self._running
            )
            if retained is False:
                self._running = False
                self._lifecycle_state = "failed"
                raise RuntimeError("Runtime did not retain the LAN server lifecycle adapter")
            if not registration_cancelled:
                self._lifecycle_state = "running"
                self._publish_startup_result("success")

        if registration_cancelled:
            self._running = False
            self._unregister_runtime_adapter()
            with self._lifecycle_lock:
                cleanup_owned_here = self._shutdown_future is None
                if self._lifecycle_state == "starting":
                    self._lifecycle_state = "failed"
            if cleanup_owned_here:
                assert runner is not None
                await runner.cleanup()
                self._site = None
                self._runner = None
                self._cleanup_complete = True
            return
        protocol = self.endpoint_protocol
        _log.info("LAN sharing started on %s://%s:%d", protocol, get_local_ip(), self._port)

        # Start the scanner before prewarming the gallery: prewarm waits for
        # the scanner to finish so the two full-library traversals do not
        # compete for disk I/O (see _prewarm_gallery).
        scanner = self._scanner
        scanner.start_background_scan()
        self._prewarm_gallery()

        # Keep the loop running
        try:
            while not self._cleanup_complete:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    def _prewarm_gallery(self) -> None:
        """Build the gallery home projection in the background after startup.

        Very large libraries take tens of seconds to project; prewarming
        right after the LAN server starts means the first /gallery visit
        finds a warm cache instead of a building state. Runs on a daemon
        thread and never delays startup or shutdown.

        The build waits out the background scanner first: both traverse the
        same library with per-file stats, and running them concurrently
        halves their effective disk throughput on Windows (Defender hooks
        every file open), which alone can push the walk past its budget.
        """
        services = getattr(self, "services", None)
        gallery = getattr(services, "gallery_service", None)
        root = getattr(self, "_library_root", None)
        if gallery is None or root is None:
            return
        scanner = getattr(self, "_scanner", None)
        cancel_event = getattr(gallery, "cancel_event", None)

        def wait_for_scanner() -> None:
            if scanner is None:
                return
            deadline = time.monotonic() + 300.0
            while time.monotonic() < deadline:
                if (
                    getattr(self, "_cleanup_complete", False)
                    or (cancel_event is not None and cancel_event.is_set())
                    or not scanner.is_scanning()
                ):
                    return
                time.sleep(1.0)

        thread = threading.Thread(
            target=lambda: gallery.prewarm_home(root, pre_wait=wait_for_scanner),
            daemon=True,
            name="lan-gallery-prewarm",
        )
        self._gallery_prewarm_thread = thread
        thread.start()

    def _has_active_users(self) -> bool:
        """Check if there are active users, with caching to avoid DB query on every request.

        A failed check is cached like a successful one: the fail-closed
        decision stays in effect for the whole TTL, so a broken auth service
        is not re-queried (and re-logged) on every request.
        """
        if self._auth_mode == "none":
            return False
        import time
        now = time.time()
        with self._has_users_cache_lock:
            if self._has_users_cache is not None and (now - self._has_users_cache_time) < self._has_users_cache_ttl:
                return self._has_users_cache
        try:
            result = self._auth_service.has_active_users(raise_on_error=True)
        except Exception:
            # Fail closed and reuse the same TTL for the negative result; the
            # next request within the window hits the cache instead of the DB.
            with self._has_users_cache_lock:
                self._has_users_cache = True
                self._has_users_cache_time = now
            _log.warning(
                "Unable to inspect active LAN users; failing closed (auth required)"
            )
            return True
        with self._has_users_cache_lock:
            self._has_users_cache = result
            self._has_users_cache_time = now
        return result

    def invalidate_user_cache(self):
        """Invalidate the user existence cache (call when users are added/removed)."""
        with self._has_users_cache_lock:
            self._has_users_cache = None

    # ── Public-endpoint policy ─────────────────────────────────────
    #
    # Public shells (/login, /browse, share pages) are intentionally
    # reachable before LAN authentication: they render static UI and their
    # data calls (gallery, shares, quota) keep auth and are validated by
    # their handlers.
    #
    # The per-route auth/rate-limit policy is declared at registration time
    # in api.py and read back through route_policy.request_policy — there is
    # no hardcoded path list to keep aligned here.

    async def _resolve_principal(self, request):
        """Resolve a LAN credential into a principal, or ``None``.

        Single copy of the four-step credential chain (revocation → access
        key → local-UI token → user token → share password) shared by the
        ``public_optional`` and ``required`` auth paths so they cannot drift.
        A failing user-token lookup (e.g. database unavailable) degrades to
        "no credential" — fail-closed 401 on required routes — instead of a
        500, matching the optional path's historical behavior. ``auth_mode``
        is deliberately NOT consulted here: the optional branch handles the
        no-auth mode before calling this, and required routes keep denying
        even when users exist but the mode is "none".
        """
        from AssetsManager.lan.principal import principal_for_request
        from AssetsManager.lan.routes._helpers import get_auth_token

        token = get_auth_token(request)
        if not token:
            return None
        auth_service = getattr(self, "_auth_service", None)
        revocation_supported = (
            callable(getattr(auth_service, "load_active_revocations", None))
            or bool(getattr(self, "_revoked_tokens", None))
            or bool(getattr(self, "_revoked_loaded", False))
        )
        check_revoked = getattr(self, "is_auth_token_revoked_async", None)
        if revocation_supported:
            # The (database-touching) revocation check only runs when a
            # revocation source is available; the async hook is overridable on
            # test doubles, production uses the method below via to_thread.
            if callable(check_revoked):
                revoked = await cast("Callable[[str], Awaitable[bool]]", check_revoked)(token)
            else:
                revoked = await asyncio.to_thread(self.is_auth_token_revoked, token)
            if revoked:
                return None
        access_key_hash = getattr(self, "_access_key_hash", None)
        if access_key_hash is not None and await asyncio.to_thread(
            verify_key, token, access_key_hash
        ):
            return principal_for_request("access_key")
        try:
            local_ui_auth_secret = self.local_ui_auth_secret
        except AttributeError:
            local_ui_auth_secret = None
        if local_ui_auth_secret and verify_auth_token(token, local_ui_auth_secret):
            return principal_for_request("local_ui")
        if auth_service is not None:
            try:
                user = await asyncio.to_thread(auth_service.verify_user_token, token)
            except Exception:
                user = None
            if user:
                return principal_for_request("user", user=user)
        password_hash = getattr(self, "_password_hash", None)
        if password_hash is not None and await verify_token_async(token, password_hash):
            return principal_for_request("password")
        return None

    @web.middleware
    async def _auth_middleware(self, request, handler):
        """Authentication middleware — skip for public endpoints."""
        from AssetsManager.lan.principal import principal_for_request
        from AssetsManager.lan.routes._helpers import get_request_principal, set_request_principal

        def ensure_guest():
            if get_request_principal(request) is None:
                set_request_principal(request, principal_for_request("guest"))

        policy = request_policy(request)

        async def proceed():
            """Enforce declared capabilities, then dispatch to the handler."""
            from AssetsManager.lan.authorization import enforce_capabilities

            denied = await enforce_capabilities(request, policy)
            if denied is not None:
                return denied
            return await handler(request)

        if policy.auth == "public_optional":
            # Publicly readable, but reflect a valid credential in its
            # normalized identity when one is supplied (/api/info).
            if self._auth_mode == "none":
                ensure_guest()
                return await proceed()
            principal = await self._resolve_principal(request)
            if principal is not None:
                set_request_principal(request, principal)
            ensure_guest()
            return await proceed()
        if policy.auth == "public":
            ensure_guest()
            return await proceed()

        # Check if any auth is configured
        has_key = self._access_key_hash is not None
        has_password = self._password_hash is not None
        has_users = self._has_active_users()

        # No auth required if nothing configured
        if not has_key and not has_password and not has_users:
            set_request_principal(request, principal_for_request("guest"))
            return await proceed()

        principal = await self._resolve_principal(request)
        if principal is None:
            return error_response("Unauthorized", status=401, code="unauthorized")
        set_request_principal(request, principal)
        return await proceed()
