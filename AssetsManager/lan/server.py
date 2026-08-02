"""LAN server — aiohttp application lifecycle management."""
import asyncio
from contextlib import nullcontext
import inspect
import concurrent.futures
import logging
import os
import ssl
import threading
import time
from pathlib import Path

from aiohttp import web

from AssetsManager.lan.api import setup_routes, stop_runtime_realtime
from AssetsManager.lan.auth import hash_key, hash_password, is_password_hash, verify_key, verify_token, verify_auth_token
from AssetsManager.lan.routes._helpers import AUTH_SERVICE_APP_KEY, LAN_APP_KEY, ActivityLog, OnlineUsers, LanScopedServices
from AssetsManager.lan.ws import WebSocketManager
from AssetsManager.lan.scanner import DirectoryScanner
from AssetsManager.lan.tunnel import TunnelManager
from AssetsManager.lan.security import RateLimiter, AuthRateLimiter, IPBlacklist, create_security_middleware
from AssetsManager.lan.utils import get_local_ip

_log = logging.getLogger(__name__)

_MISSING = object()


def _runtime_services_snapshot(runtime):
    """Return the canonical snapshot and whether test-double fallback was used."""
    if inspect.getattr_static(runtime, "services_snapshot", _MISSING) is not _MISSING:
        return runtime.services_snapshot, False
    # Temporary compatibility for legacy runtime-shaped test doubles. Remove
    # after those fixtures expose the canonical services_snapshot contract.
    return getattr(runtime, "services", None), True


def _runtime_operation(runtime, session):
    operation = getattr(session, "operation", None)
    if callable(operation):
        return operation()

    # Real LibraryRuntime instances always carry a LibrarySession operation
    # boundary. Only lightweight legacy test doubles may omit it.
    from AssetsManager.application.runtime import LibraryRuntime

    if isinstance(runtime, LibraryRuntime):
        raise ValueError("runtime session must provide an operation boundary")
    return nullcontext()


def _provider_matches_session(service, session) -> bool:
    provider = getattr(service, "_connection_provider", None)
    expected_provider = session.connection_for
    provider_self = getattr(provider, "__self__", None)
    provider_func = getattr(provider, "__func__", None)
    if provider_self is not None:
        return (
            provider_self is session
            and provider_func is getattr(expected_provider, "__func__", None)
        )
    return provider == expected_provider


def _service_session_matches(service, session, *, required: bool) -> bool:
    has_session_binding = (
        inspect.getattr_static(service, "_session", _MISSING) is not _MISSING
    )
    if not has_session_binding:
        return not required
    bound_session = service._session
    if required:
        return bound_session is session
    return bound_session is None or bound_session is session


def _validate_runtime_service_bindings(
    runtime_services,
    lan_services,
    session,
    db_conn,
    *,
    strict_session_binding: bool,
) -> None:
    for owner, name, requires_session in (
        (runtime_services, "metadata_service", True),
        (runtime_services, "tag_service", True),
        (runtime_services, "thumbnail_service", True),
        (lan_services, "project_service", True),
        (lan_services, "search_service", False),
    ):
        service = getattr(owner, name, None)
        if (
            service is None
            or not _provider_matches_session(service, session)
            or not _service_session_matches(
                service,
                session,
                required=strict_session_binding and requires_session,
            )
        ):
            raise ValueError(
                f"runtime {name} provider is not bound to its LibrarySession"
            )

    project_service = getattr(lan_services, "project_service", None)
    for name in ("_metadata_svc", "_tag_svc"):
        nested = getattr(project_service, name, None)
        if (
            nested is None
            or not _provider_matches_session(nested, session)
            or not _service_session_matches(
                nested, session, required=strict_session_binding
            )
        ):
            raise ValueError(
                "runtime project_service internals are not bound to its LibrarySession"
            )

    asset_service = getattr(lan_services, "asset_service", None)
    directory_cache = getattr(asset_service, "_directory_cache", None)
    if directory_cache is None or getattr(directory_cache, "_conn", _MISSING) is not db_conn:
        raise ValueError(
            "runtime asset_service cache is not bound to its LibrarySession"
        )

class _LanServerImpl:
    """Internal server implementation. Do not use directly — use LanServer facade."""

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
        session = getattr(runtime, "session", None)
        if session is None:
            raise ValueError("runtime must be live and canonical for its LibrarySession")
        if getattr(session, "is_closed", False):
            raise ValueError("runtime session must be live")
        self._share_name = share_name
        self._auth_mode = auth_mode
        # Accept both plaintext and pre-hashed passwords for backward compatibility.
        # New settings save hashes; old settings may contain plaintext.
        if password:
            self._password_hash = password if is_password_hash(password) else hash_password(password)
        else:
            self._password_hash = None
        self._access_key_hash = hash_key(access_key) if access_key else None
        self._password_value = password
        self._access_key_value = access_key
        self._ws_manager = WebSocketManager(on_connection_change=self._set_connection_count)
        self._tunnel = TunnelManager()
        self._blur_tags = set(blur_tags or [])
        self._token_secret = os.urandom(32).hex()  # Random secret for token signing

        # Security
        self._rate_limit_value = rate_limit
        self._blocked_ips = list(blocked_ips or [])
        self._ip_whitelist = list(ip_whitelist or [])
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
        self._shutdown_future = None
        self._lifecycle_lock = threading.Lock()
        self._lifecycle_generation = 0
        self._stop_reservations = 0
        self._stop_reservation_generation = 0
        self._startup_result_event = None
        self._startup_result = None
        self._startup_cancel_generation = None
        self._cleanup_started_event = None
        self._startup_cleanup_failed = False
        self._connections: int = 0
        self._requests: int = 0
        self._bytes_transferred: int | None = None
        self._started_at: float | None = None
        self._metrics_lock = threading.Lock()

        # User existence cache (avoid DB query on every request)
        self._has_users_cache: bool | None = None
        self._has_users_cache_time: float = 0
        self._has_users_cache_ttl: float = 30.0  # Cache for 30 seconds

        with _runtime_operation(runtime, session):
            runtime_services, legacy_fallback = _runtime_services_snapshot(runtime)
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
            if legacy_fallback:
                if has_snapshot_session and snapshot_session is not session:
                    raise ValueError(
                        "runtime must be live and canonical for its LibrarySession"
                    )
            elif snapshot_session is not session:
                raise ValueError(
                    "runtime must be live and canonical for its LibrarySession"
                )

            has_lan_projection = (
                inspect.getattr_static(runtime_services, "lan_services", _MISSING)
                is not _MISSING
            )
            if has_lan_projection:
                lan_runtime_services = runtime_services.lan_services
            elif legacy_fallback:
                # Legacy low-level route fixtures used LanScopedServices itself
                # as runtime.services. Production snapshots must expose the
                # explicit LAN-only projection.
                lan_runtime_services = runtime_services
            else:
                raise ValueError("runtime snapshot has no LAN service projection")
            if lan_runtime_services is None:
                raise ValueError("runtime snapshot has no LAN service projection")

            library_root = session.root
            thumbnail_dir = session.thumb_dir
            db_conn = session.connection_for(session.root)
            runtime_performance_recorder = getattr(
                runtime_services, "performance_recorder", performance_recorder
            )
            runtime_session_token = session.event_token

            _validate_runtime_service_bindings(
                runtime_services,
                lan_runtime_services,
                session,
                db_conn,
                strict_session_binding=not legacy_fallback,
            )

            # Auth/Share remain LAN-owned. A3 only changes when the three
            # LAN-only application services are materialized.
            from AssetsManager.application.auth_service import AuthService
            from AssetsManager.application.share_service import ShareService

            auth_service = AuthService(db_conn, self._token_secret)
            share_service = ShareService(db_conn, self._token_secret)
            event_library_root = getattr(session, "root_str", str(library_root))
            for service in (auth_service, share_service):
                service._library_root = event_library_root
                service._session_token = runtime_session_token

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
                activity_log=ActivityLog(
                    library_root=event_library_root,
                    session_token=runtime_session_token,
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

    def _build_app(self) -> None:
        """Build a fresh aiohttp application for the next event loop."""
        security_mw = create_security_middleware(
            self._rate_limiter,
            self._ip_blacklist,
            self._auth_rate_limiter,
            ip_whitelist=self._ip_whitelist,
        )
        self._app = web.Application(middlewares=[security_mw, self._metrics_middleware, self._auth_middleware])
        self._app[LAN_APP_KEY] = self
        setup_routes(self._app)

    @web.middleware
    async def _metrics_middleware(self, request, handler):
        with self._metrics_lock:
            self._requests += 1
        return await handler(request)

    # ── Public API ──────────────────────────────────────────────

    def start(self, port: int = 8080, bind: str = "0.0.0.0"):
        """Start the server on the given port."""
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
            self._lifecycle_state = "starting"
            self._cleanup_complete = False
            self._port = port
            self._bind = bind
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
            with self._lifecycle_lock:
                if (self._lifecycle_generation == generation
                        and self._thread is not None
                        and not self._thread.is_alive()
                        and self._cleanup_complete):
                    self._lifecycle_state = "stopped"
                    self._loop = None
                    self._thread = None
            raise OSError(f"Failed to start server on port {port}. Port may be in use.")
    def stop(self):
        """Stop the server gracefully."""
        unregister_after_lock = False
        with self._lifecycle_lock:
            thread = self._thread
            generation = getattr(self, "_lifecycle_generation", 0)
            if thread is None:
                self._running = False
                self._lifecycle_state = "stopped"
                self._loop = None
                self._thread = None
                self._shutdown_future = None
                unregister_after_lock = True
            elif not thread.is_alive():
                if not self._cleanup_complete:
                    self._lifecycle_state = "failed"
                    raise RuntimeError("Server thread terminated with cleanup incomplete")
                self._running = False
                self._lifecycle_state = "stopped"
                self._loop = None
                self._thread = None
                self._shutdown_future = None
                unregister_after_lock = True
            if self._loop is None:
                if unregister_after_lock:
                    pass
                else:
                    self._lifecycle_state = "failed"
                    raise RuntimeError("Cannot stop live server thread without its event loop")
            elif unregister_after_lock:
                pass
            else:
                self._lifecycle_state = "stopping"
                future = self._shutdown_future
                if future is not None and getattr(future, "done", lambda: False)():
                    future_failed = False
                    try:
                        future_failed = future.exception() is not None
                    except concurrent.futures.CancelledError:
                        future_failed = True
                    except Exception:
                        pass
                    if future_failed and not self._cleanup_complete:
                        self._shutdown_future = None
                        future = None
                if future is None:
                    future = asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
                    self._shutdown_future = future
                reservation_generation = generation
                if getattr(self, "_stop_reservation_generation", generation) != generation:
                    self._stop_reservations = 0
                self._stop_reservation_generation = generation
                self._stop_reservations = getattr(self, "_stop_reservations", 0) + 1

        if unregister_after_lock:
            self._unregister_runtime_adapter()
            return

        try:
            while True:
                shutdown_error = None
                try:
                    future.result(timeout=8)
                except TimeoutError as exc:
                    with self._lifecycle_lock:
                        future_done = getattr(future, "done", lambda: False)()
                        retry_startup_cleanup = (
                            self._shutdown_future is future
                            and future_done
                            and getattr(self, "_startup_cleanup_failed", False)
                            and not self._cleanup_complete
                        )
                        if self._shutdown_future is future and (future_done or retry_startup_cleanup):
                            self._shutdown_future = None
                        if retry_startup_cleanup:
                            self._startup_cleanup_failed = False
                    if retry_startup_cleanup:
                        with self._lifecycle_lock:
                            future = asyncio.run_coroutine_threadsafe(
                                self._shutdown(), self._loop
                            )
                            self._shutdown_future = future
                        continue
                    shutdown_error = exc
                    _log.warning("Server shutdown timed out or failed: %s", exc)
                except BaseException as exc:
                    with self._lifecycle_lock:
                        retry_startup_cleanup = (
                            self._shutdown_future is future
                            and getattr(self, "_startup_cleanup_failed", False)
                            and not self._cleanup_complete
                        )
                        if self._shutdown_future is future:
                            self._shutdown_future = None
                        if retry_startup_cleanup:
                            self._startup_cleanup_failed = False
                    if retry_startup_cleanup:
                        with self._lifecycle_lock:
                            future = asyncio.run_coroutine_threadsafe(
                                self._shutdown(), self._loop
                            )
                            self._shutdown_future = future
                        continue
                    shutdown_error = exc
                    _log.warning("Server shutdown timed out or failed: %s", exc)
                break

            if shutdown_error is not None:
                with self._lifecycle_lock:
                    self._lifecycle_state = "failed"
                raise shutdown_error

            if thread is not threading.current_thread():
                thread.join(timeout=8)

            if thread.is_alive():
                with self._lifecycle_lock:
                    self._lifecycle_state = "failed"
                raise TimeoutError("Server thread did not terminate after shutdown")

            with self._lifecycle_lock:
                if (self._thread is not thread
                        or getattr(self, "_lifecycle_generation", 0) != generation):
                    return
                self._running = False
                self._cleanup_complete = True
                self._lifecycle_state = "stopped"
                self._loop = None
                self._thread = None
                self._shutdown_future = None
                self._startup_cleanup_failed = False
            self._unregister_runtime_adapter()
        finally:
            with self._lifecycle_lock:
                if (getattr(self, "_stop_reservation_generation", None)
                        == reservation_generation):
                    self._stop_reservations = max(
                        0, getattr(self, "_stop_reservations", 0) - 1
                    )

    def _unregister_runtime_adapter(self):
        runtime = getattr(self, "runtime", None)
        unregister_adapter = getattr(runtime, "unregister_lifecycle_adapter", None)
        if not callable(unregister_adapter):
            return
        condition = self._runtime_adapter_condition()
        with condition:
            while getattr(self, "_runtime_adapter_state", "unregistered") == "registering":
                if getattr(self, "_runtime_adapter_registration_thread", None) == threading.get_ident():
                    return
                condition.wait()
            if getattr(self, "_runtime_adapter_state", "unregistered") != "registered":
                return
            self._runtime_adapter_state = "unregistering"
            self._runtime_adapter_registered = False
        try:
            unregister_adapter(self)
        except BaseException:
            with condition:
                self._runtime_adapter_state = "registered"
                self._runtime_adapter_registered = True
                condition.notify_all()
            raise
        with condition:
            self._runtime_adapter_state = "unregistered"
            condition.notify_all()

    def _register_runtime_adapter(self):
        runtime = getattr(self, "runtime", None)
        register_adapter = getattr(runtime, "try_register_lifecycle_adapter", None)
        if not callable(register_adapter):
            register_adapter = getattr(runtime, "register_lifecycle_adapter", None)
        if not callable(register_adapter):
            return True
        condition = self._runtime_adapter_condition()
        with condition:
            state = getattr(self, "_runtime_adapter_state", "unregistered")
            if state == "registered":
                return True
            if state == "registering":
                if getattr(self, "_runtime_adapter_registration_thread", None) == threading.get_ident():
                    return False
                while getattr(self, "_runtime_adapter_state", "unregistered") == "registering":
                    condition.wait()
                if getattr(self, "_runtime_adapter_state", "unregistered") == "registered":
                    return True
            self._runtime_adapter_state = "registering"
            self._runtime_adapter_registration_thread = threading.get_ident()
        try:
            retained = register_adapter(self)
        except BaseException:
            with condition:
                self._runtime_adapter_state = "unregistered"
                self._runtime_adapter_registration_thread = None
                condition.notify_all()
            raise
        with condition:
            self._runtime_adapter_registration_thread = None
            self._runtime_adapter_state = "registered" if retained is not False else "unregistered"
            self._runtime_adapter_registered = retained is not False
            condition.notify_all()
            return retained is not False

    def _runtime_adapter_condition(self):
        condition = getattr(self, "_runtime_adapter_condition_lock", None)
        if condition is None:
            lock = getattr(self, "_runtime_adapter_lock", None)
            if lock is None:
                lock = threading.Lock()
                self._runtime_adapter_lock = lock
            condition = threading.Condition(lock)
            self._runtime_adapter_condition_lock = condition
        if not hasattr(self, "_runtime_adapter_state"):
            self._runtime_adapter_state = (
                "registered"
                if getattr(self, "_runtime_adapter_registered", False)
                else "unregistered"
            )
        if not hasattr(self, "_runtime_adapter_registration_thread"):
            self._runtime_adapter_registration_thread = None
        return condition

    def is_running(self) -> bool:
        return self._lifecycle_state != "stopped"

    def status(self) -> dict:
        ip = get_local_ip()
        return {
            "running": self.is_running(),
            "lifecycle_state": self._lifecycle_state,
            "ip": ip,
            "port": self._port,
            "url": f"http://{ip}:{self._port}",
            "share_name": self._share_name,
            "library_root": str(self._library_root),
            "auth_enabled": self.auth_status()[0],
            "connections": self._connections,
            "requests": self._requests,
            "bytes_transferred": self._bytes_transferred,
            "uptime": max(0.0, time.monotonic() - self._started_at) if self._started_at else 0.0,
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
        try:
            try:
                self._loop.run_until_complete(self._startup())
            except BaseException:
                self._running = False
                self._lifecycle_state = "failed"
                _log.exception("LAN server startup failed")
                with self._lifecycle_lock:
                    cleanup_future = self._shutdown_future
                    cleanup_owned_here = cleanup_future is None
                    if cleanup_future is None:
                        cleanup_future = concurrent.futures.Future()
                        self._shutdown_future = cleanup_future
                    elif not self._cleanup_complete:
                        # A concurrent stop owns cleanup.  If that shared
                        # future fails, stop() must be allowed to resubmit it
                        # during this same call.
                        self._startup_cleanup_failed = True
                if cleanup_owned_here and not cleanup_future.done():
                    cleanup_started = getattr(self, "_cleanup_started_event", None)
                    if cleanup_started is not None:
                        cleanup_started.set()
                    self._publish_startup_result("failure")
                    try:
                        self._loop.run_until_complete(self._shutdown())
                    except BaseException as exc:
                        self._startup_cleanup_failed = True
                        cleanup_future.set_exception(exc)
                        _log.exception("LAN server startup cleanup failed")
                    else:
                        cleanup_future.set_result(None)
                self._publish_startup_result("failure")
                while not self._cleanup_complete:
                    self._loop.run_until_complete(asyncio.sleep(0.01))
            else:
                with self._lifecycle_lock:
                    startup_cancelled = (
                        getattr(self, "_startup_cancel_generation", None)
                        == getattr(self, "_lifecycle_generation", 0)
                    )
                if startup_cancelled and self._running:
                    self._running = False
                    with self._lifecycle_lock:
                        cleanup_future = self._shutdown_future
                        cleanup_owned_here = cleanup_future is None
                        if cleanup_owned_here:
                            cleanup_future = concurrent.futures.Future()
                            self._shutdown_future = cleanup_future
                        elif not self._cleanup_complete:
                            self._startup_cleanup_failed = True
                    if cleanup_owned_here and not cleanup_future.done():
                        try:
                            cleanup_started = getattr(self, "_cleanup_started_event", None)
                            if cleanup_started is not None:
                                cleanup_started.set()
                            self._loop.run_until_complete(self._shutdown())
                        except BaseException as exc:
                            self._startup_cleanup_failed = True
                            cleanup_future.set_exception(exc)
                        else:
                            cleanup_future.set_result(None)
                self._publish_startup_result(
                    "failure" if startup_cancelled else ("success" if self._running else "failure")
                )
                while not self._cleanup_complete:
                    self._loop.run_until_complete(asyncio.sleep(0.01))
        finally:
            loop = self._loop
            loop.close()
            if self._cleanup_complete and not self._running:
                try:
                    self._unregister_runtime_adapter()
                except BaseException:
                    _log.exception("Failed to unregister LAN runtime lifecycle adapter")

    async def _startup(self):
        await self._ws_manager.start_accepting()
        self._auth_service.init_tables()
        self._share_service.init_table()
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
            self._cleanup_complete = True
            cleanup_started = getattr(self, "_cleanup_started_event", None)
            if cleanup_started is not None:
                cleanup_started.set()
            return
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
            await self._runner.cleanup()
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
                await self._runner.cleanup()
                self._cleanup_complete = True
            return
        protocol = "https" if ssl_context else "http"
        _log.info("LAN sharing started on %s://%s:%d", protocol, get_local_ip(), self._port)

        # Start background file scanner for fast search
        self._scanner.start_background_scan()

        # Keep the loop running
        try:
            while not self._cleanup_complete:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    async def _shutdown(self):
        self._running = False
        try:
            stop_runtime_realtime(self)
            await self._ws_manager.close_all()
            if self._site:
                await self._site.stop()
            if self._runner:
                await self._runner.cleanup()
        except BaseException:
            self._cleanup_complete = False
            raise
        self._cleanup_complete = True
        _log.info("LAN sharing stopped")

    def _publish_startup_result(self, status: str) -> None:
        event = getattr(self, "_startup_result_event", None)
        if event is None or event.is_set():
            return
        self._startup_result = (status, getattr(self, "_lifecycle_generation", 0))
        event.set()

    def _has_active_users(self) -> bool:
        """Check if there are active users, with caching to avoid DB query on every request."""
        if self._auth_mode == "none":
            return False
        import time
        now = time.time()
        if self._has_users_cache is not None and (now - self._has_users_cache_time) < self._has_users_cache_ttl:
            return self._has_users_cache
        try:
            result = self._auth_service.has_active_users(raise_on_error=True)
            self._has_users_cache = result
            self._has_users_cache_time = now
            return result
        except Exception:
            return self._has_users_cache or False

    def invalidate_user_cache(self):
        """Invalidate the user existence cache (call when users are added/removed)."""
        self._has_users_cache = None

    # ── Declarative public-endpoint list (keep aligned with api.py) ──

    _PUBLIC_PATHS: frozenset[str] = frozenset({
        "/api/auth/login",
        "/api/auth/register",
        "/api/auth/verify_key",
        "/login",
        "/browse",
        "/detail",
        "/",
        "/favicon.ico",
    })

    _PUBLIC_PATH_PREFIXES: tuple[str, ...] = (
        "/assets",
        "/s",
    )

    _PUBLIC_PATH_PREFIX_GET: tuple[str, ...] = ()

    @staticmethod
    def _path_matches_prefix(path: str, prefix: str) -> bool:
        return path == prefix or path.startswith(f"{prefix}/")

    def _is_public_share_endpoint(self, method: str, path: str) -> bool:
        prefix = "/api/shares/"
        if not path.startswith(prefix):
            return False
        parts = path[len(prefix):].split("/", 2)
        if len(parts) < 2 or not parts[0]:
            return False

        action = parts[1]
        has_tail = len(parts) == 3
        if method == "POST":
            return action == "verify" and not has_tail
        if method != "GET":
            return False
        if action == "info":
            return not has_tail
        return action in {"download", "preview"} and has_tail

    @web.middleware
    async def _auth_middleware(self, request, handler):
        """Authentication middleware — skip for public endpoints."""
        from AssetsManager.lan.principal import principal_for_request
        from AssetsManager.lan.routes._helpers import get_request_principal, set_request_principal

        def ensure_guest():
            if get_request_principal(request) is None:
                set_request_principal(request, principal_for_request("guest"))

        if request.path == "/api/info":
            # Keep the endpoint publicly readable, but reflect a valid
            # credential in its normalized identity when one is supplied.
            if self._auth_mode == "none":
                ensure_guest()
                return await handler(request)
            from AssetsManager.lan.routes._helpers import get_auth_token
            token = get_auth_token(request, allow_query=False)
            if token:
                if self._access_key_hash is not None and verify_key(token, self._access_key_hash):
                    set_request_principal(request, principal_for_request("access_key"))
                    return await handler(request)
                if self._token_secret and verify_auth_token(token, self._token_secret):
                    set_request_principal(request, principal_for_request("local_ui"))
                    return await handler(request)
                user = self._auth_service.verify_user_token(token)
                if user:
                    set_request_principal(request, principal_for_request("user", user=user))
                    return await handler(request)
                if self._password_hash is not None and verify_token(token, self._password_hash):
                    set_request_principal(request, principal_for_request("password"))
                    return await handler(request)
            ensure_guest()
            return await handler(request)
        if request.path in self._PUBLIC_PATHS:
            ensure_guest()
            return await handler(request)
        for prefix in self._PUBLIC_PATH_PREFIXES:
            if self._path_matches_prefix(request.path, prefix):
                ensure_guest()
                return await handler(request)
        if self._is_public_share_endpoint(request.method, request.path):
            ensure_guest()
            return await handler(request)
        if request.method == "GET":
            for prefix in self._PUBLIC_PATH_PREFIX_GET:
                if self._path_matches_prefix(request.path, prefix):
                    ensure_guest()
                    return await handler(request)

        # Check if any auth is configured
        has_key = self._access_key_hash is not None
        has_password = self._password_hash is not None
        has_users = self._has_active_users()

        # No auth required if nothing configured
        if not has_key and not has_password and not has_users:
            set_request_principal(request, principal_for_request("guest"))
            return await handler(request)

        # Get token from cookie, header, or query param
        from AssetsManager.lan.routes._helpers import get_auth_token
        token = get_auth_token(request, allow_query=request.path != "/ws")

        # Try access key auth
        if has_key and token and self._access_key_hash is not None:
            if verify_key(token, self._access_key_hash):
                set_request_principal(request, principal_for_request("access_key"))
                return await handler(request)

        # Try local UI API token (signed with token_secret)
        if self._token_secret and token:
            if verify_auth_token(token, self._token_secret):
                set_request_principal(request, principal_for_request("local_ui"))
                return await handler(request)

        # Try user-based token
        if token:
            user = self._auth_service.verify_user_token(token)
            if user:
                set_request_principal(request, principal_for_request("user", user=user))
                return await handler(request)

        # Try simple password token
        if has_password and token and self._password_hash is not None:
            if verify_token(token, self._password_hash):
                set_request_principal(request, principal_for_request("password"))
                return await handler(request)

        return web.json_response({"error": "Unauthorized"}, status=401)
