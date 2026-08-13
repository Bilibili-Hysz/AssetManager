"""LAN server — aiohttp application lifecycle management."""
import asyncio
import inspect
import concurrent.futures
import logging
import ssl
import threading
import time
from pathlib import Path
from typing import Any, cast

from aiohttp import web

from AssetsManager.lan.api import setup_routes, stop_runtime_realtime
from AssetsManager.lan.auth import hash_key, hash_password, is_password_hash, verify_key, verify_token, verify_auth_token
from AssetsManager.lan.guarded_tunnel import _GuardedTunnel
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import AUTH_SERVICE_APP_KEY, LAN_APP_KEY, ActivityLog, OnlineUsers, LanScopedServices
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
from AssetsManager.lan.security import RateLimiter, AuthRateLimiter, IPBlacklist, create_security_middleware
from AssetsManager.lan.route_policy import request_policy
from AssetsManager.lan.utils import get_local_ip

_log = logging.getLogger(__name__)


class _LanServerImpl:
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
        self._tunnel_start_block_reason: str | None = None
        self._blur_tags = set(blur_tags or [])

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
        self._bytes_transferred: int | None = None
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
                self._token_secret = token_secret
                self._local_ui_auth_secret = _derive_local_ui_auth_secret(
                    token_secret,
                    password=self._password_value,
                    access_key=self._access_key_value,
                    auth_mode=self._auth_mode,
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

    def _build_app(self) -> None:
        """Build a fresh aiohttp application for the next event loop."""
        security_mw = create_security_middleware(
            self._rate_limiter,
            self._ip_blacklist,
            self._auth_rate_limiter,
            ip_whitelist=self._ip_whitelist,
            tunnel_active=self._tunnel_active,
        )
        app = web.Application(middlewares=[security_mw, self._metrics_middleware, self._auth_middleware])
        self._app = app
        app[LAN_APP_KEY] = self
        setup_routes(app)

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
        return await handler(request)

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
    def stop(self):
        """Stop the server gracefully.

        Seller sessions are revoked before any early-return or tunnel cleanup
        path.  The server owns its tunnel process.  A tunnel cleanup failure is
        part of the same retryable lifecycle and must not be hidden by clearing
        the LAN owner handles.
        """
        # ``stop()`` can be called before the worker loop exists (or after a
        # failed startup).  Keep the auth boundary fail-closed even on those
        # paths; the normal async shutdown repeats this idempotently.
        self._revoke_seller_sessions()
        tunnel = getattr(self, "_tunnel", None)
        if tunnel is not None:
            tunnel_process = getattr(tunnel, "_process", None)
            try:
                tunnel_running = bool(tunnel.is_running)
            except Exception:
                tunnel_running = tunnel_process is not None
            if tunnel_process is not None or tunnel_running:
                self.stop_tunnel()

        unregister_after_lock = False
        submit_cleanup = False
        explicit_cleanup_protocol = False
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
                explicit_cleanup_protocol = getattr(self, "_cleanup_attempt_event", None) is not None
                future = self._shutdown_future
                if explicit_cleanup_protocol:
                    state = getattr(self, "_cleanup_attempt_state", "idle")
                    retry_startup_cleanup = (
                        state == "failed"
                        and getattr(self, "_startup_cleanup_failed", False)
                        and not getattr(self, "_startup_cleanup_retry_used", False)
                        and not self._cleanup_complete
                    )
                    retry_failed_cleanup = (
                        state == "failed"
                        and not getattr(self, "_cleanup_retry_used", False)
                        and not self._cleanup_complete
                    )
                    if retry_failed_cleanup:
                        self._cleanup_retry_used = True
                        if retry_startup_cleanup:
                            self._startup_cleanup_retry_used = True
                        future = self._reset_cleanup_attempt_locked("stop-retry")
                        submit_cleanup = True
                    elif state == "running" and future is not None:
                        pass
                    elif future is None or state in {"idle", "succeeded"}:
                        future = self._reset_cleanup_attempt_locked("stop")
                        submit_cleanup = True
                    elif state == "failed":
                        # A failed cleanup has already consumed its one retry.
                        # Keep the failed attempt available for the bounded wait
                        # below; do not overlap another cleanup coroutine.
                        pass
                else:
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
                        loop = self._loop
                        assert loop is not None
                        future = asyncio.run_coroutine_threadsafe(self._shutdown(), loop)
                        self._shutdown_future = future
                reservation_generation = generation
                if getattr(self, "_stop_reservation_generation", generation) != generation:
                    self._stop_reservations = 0
                self._stop_reservation_generation = generation
                self._stop_reservations = getattr(self, "_stop_reservations", 0) + 1

        if unregister_after_lock:
            self._unregister_runtime_adapter()
            return

        if submit_cleanup:
            loop = self._loop
            assert loop is not None
            future = self._submit_cleanup_attempt(loop, future)

        try:
            if explicit_cleanup_protocol:
                while True:
                    attempt_event = self._cleanup_attempt_event
                    assert attempt_event is not None
                    if not attempt_event.wait(timeout=8):
                        shutdown_error = TimeoutError(
                            "Server shutdown timed out or cleanup attempt did not finish"
                        )
                        _log.warning("Server shutdown timed out or failed: %s", shutdown_error)
                        break
                    with self._lifecycle_lock:
                        attempt_state = self._cleanup_attempt_state
                        retry_startup_cleanup = (
                            attempt_state == "failed"
                            and self._shutdown_future is future
                            and getattr(self, "_startup_cleanup_failed", False)
                            and not getattr(self, "_startup_cleanup_retry_used", False)
                            and not self._cleanup_complete
                        )
                        if retry_startup_cleanup:
                            self._cleanup_retry_used = True
                            self._startup_cleanup_retry_used = True
                            retry_placeholder = self._reset_cleanup_attempt_locked("stop-retry")
                        else:
                            retry_placeholder = None
                    if retry_startup_cleanup:
                        loop = self._loop
                        assert loop is not None
                        assert retry_placeholder is not None
                        future = self._submit_cleanup_attempt(loop, retry_placeholder)
                        continue
                    if attempt_state == "failed":
                        shutdown_error = self._cleanup_attempt_error or RuntimeError(
                            "LAN cleanup attempt failed"
                        )
                    else:
                        shutdown_error = None
                    break
            else:
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
                                loop = self._loop
                                assert loop is not None
                                future = asyncio.run_coroutine_threadsafe(
                                    self._shutdown(), loop
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
                                loop = self._loop
                                assert loop is not None
                                future = asyncio.run_coroutine_threadsafe(
                                    self._shutdown(), loop
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

            assert thread is not None
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
        """Derive the current UI credential from the live runtime secret."""
        return _derive_local_ui_auth_secret(
            self._token_secret,
            password=self._password_value,
            access_key=self._access_key_value,
            auth_mode=self._auth_mode,
        )

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
        loop = self._loop
        assert loop is not None
        asyncio.set_event_loop(loop)
        try:
            try:
                loop.run_until_complete(self._startup())
            except BaseException:
                self._running = False
                self._lifecycle_state = "failed"
                _log.exception("LAN server startup failed")
                with self._lifecycle_lock:
                    cleanup_future = self._shutdown_future
                    cleanup_owned_here = cleanup_future is None
                    if cleanup_owned_here:
                        cleanup_future = self._reset_cleanup_attempt_locked("startup")
                    elif not self._cleanup_complete:
                        # A concurrent stop owns cleanup.  The owner remains
                        # responsible for publishing the attempt result; this
                        # flag records that a failed startup needs one retry.
                        self._startup_cleanup_failed = True
                assert cleanup_future is not None
                if cleanup_owned_here and not cleanup_future.done():
                    cleanup_started = getattr(self, "_cleanup_started_event", None)
                    if cleanup_started is not None:
                        cleanup_started.set()
                    self._publish_startup_result("failure")
                    try:
                        loop.run_until_complete(self._run_cleanup_attempt())
                    except BaseException as exc:
                        if not cleanup_future.done():
                            cleanup_future.set_exception(exc)
                        _log.exception("LAN server startup cleanup failed")
                    else:
                        if not cleanup_future.done():
                            cleanup_future.set_result(None)
                self._publish_startup_result("failure")
                while not self._cleanup_complete:
                    loop.run_until_complete(asyncio.sleep(0.01))
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
                            cleanup_future = self._reset_cleanup_attempt_locked("startup")
                        elif not self._cleanup_complete:
                            self._startup_cleanup_failed = True
                    assert cleanup_future is not None
                    if cleanup_owned_here and not cleanup_future.done():
                        try:
                            cleanup_started = getattr(self, "_cleanup_started_event", None)
                            if cleanup_started is not None:
                                cleanup_started.set()
                            loop.run_until_complete(self._run_cleanup_attempt())
                        except BaseException as exc:
                            if not cleanup_future.done():
                                cleanup_future.set_exception(exc)
                        else:
                            if not cleanup_future.done():
                                cleanup_future.set_result(None)
                self._publish_startup_result(
                    "failure" if startup_cancelled else ("success" if self._running else "failure")
                )
                while not self._cleanup_complete:
                    loop.run_until_complete(asyncio.sleep(0.01))
        finally:
            loop = self._loop
            assert loop is not None
            loop.close()
            with self._lifecycle_lock:
                if self._cleanup_complete and not self._running:
                    self._lifecycle_state = "stopped"
            if self._cleanup_complete and not self._running:
                try:
                    self._unregister_runtime_adapter()
                except BaseException:
                    _log.exception("Failed to unregister LAN runtime lifecycle adapter")

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
        self._prewarm_gallery()

        # Start background file scanner for fast search
        scanner = self._scanner
        scanner.start_background_scan()

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
        """
        services = getattr(self, "services", None)
        gallery = getattr(services, "gallery_service", None)
        root = getattr(self, "_library_root", None)
        if gallery is None or root is None:
            return
        thread = threading.Thread(
            target=lambda: gallery.prewarm_home(root), daemon=True
        )
        thread.start()

    def _revoke_seller_sessions(self) -> None:
        """Revoke every already-assembled Seller service before shutdown.

        Commerce services may be reachable through the request cache, the
        canonical scoped bundle, or an injected/legacy alias.  These holders
        can point at the same service, so deduplicate by object identity.
        Revocation is best-effort per holder: one malformed provider must not
        prevent the remaining providers from being revoked or the transport
        cleanup from running.
        """
        holders = (
            getattr(self, "commerce_services", None),
            getattr(self, "_commerce_services", None),
            getattr(self, "services", None),
            getattr(self, "_services", None),
            getattr(self, "_injected_services", None),
        )
        candidates = []
        for holder in holders:
            if holder is None:
                continue
            for name in ("seller_auth", "seller_auth_service"):
                seller_auth = getattr(holder, name, None)
                if seller_auth is not None:
                    candidates.append(seller_auth)

        seen: set[int] = set()
        total_revoked = 0
        for seller_auth in candidates:
            if id(seller_auth) in seen:
                continue
            seen.add(id(seller_auth))
            revoke_all = getattr(seller_auth, "revoke_all", None)
            if not callable(revoke_all):
                continue
            try:
                total_revoked += int(cast(Any, revoke_all()) or 0)
            except Exception:
                _log.exception("Failed to revoke Seller sessions during LAN shutdown")
        if total_revoked:
            _log.info("Revoked %d Seller sessions during LAN shutdown", total_revoked)

    async def _shutdown(self):
        self._running = False
        scanner = getattr(self, "_scanner", None)
        if scanner is not None and callable(getattr(scanner, "stop", None)):
            try:
                scanner.stop()
            except Exception:
                _log.exception("Failed to stop background scanner during LAN shutdown")
        self._revoke_seller_sessions()
        try:
            stop_runtime_realtime(self)
            await self._ws_manager.close_all()
            if self._site and getattr(self, "_site_started", True):
                await self._site.stop()
            if self._runner:
                await self._runner.cleanup()
        except BaseException:
            self._cleanup_complete = False
            raise
        self._site = None
        self._runner = None
        self._site_started = False
        self._ssl_active = False
        self._cleanup_complete = True
        _log.info("LAN sharing stopped")

    async def _run_cleanup_attempt(self):
        """Run one cleanup attempt and publish its terminal state first.

        The attempt event/state is the cross-thread lifecycle contract.  It is
        deliberately published before the asyncio/concurrent future becomes
        done, so a waiter cannot infer a stale state from a timeout boundary.
        """
        try:
            await self._shutdown()
        except BaseException as exc:
            self._publish_cleanup_attempt("failed", exc)
            raise
        self._publish_cleanup_attempt("succeeded")

    def _publish_cleanup_attempt(self, state: str, error: BaseException | None = None) -> None:
        event = getattr(self, "_cleanup_attempt_event", None)
        if event is None:
            return
        with self._lifecycle_lock:
            self._cleanup_attempt_state = state
            self._cleanup_attempt_error = error
            if state == "failed" and self._cleanup_attempt_owner == "startup":
                self._startup_cleanup_failed = True
            event.set()

    def _reset_cleanup_attempt_locked(self, owner: str) -> concurrent.futures.Future[Any]:
        event = getattr(self, "_cleanup_attempt_event", None)
        if event is None:
            event = threading.Event()
            self._cleanup_attempt_event = event
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()
        self._cleanup_attempt_future = future
        self._shutdown_future = future
        event.clear()
        self._cleanup_attempt_state = "running"
        self._cleanup_attempt_owner = owner
        self._cleanup_attempt_error = None
        return future

    def _submit_cleanup_attempt(
        self,
        loop: asyncio.AbstractEventLoop,
        placeholder: concurrent.futures.Future[Any],
    ) -> concurrent.futures.Future[Any]:
        try:
            future = asyncio.run_coroutine_threadsafe(self._run_cleanup_attempt(), loop)
        except BaseException as exc:
            self._publish_cleanup_attempt("failed", exc)
            if not placeholder.done():
                placeholder.set_exception(exc)
            return placeholder
        with self._lifecycle_lock:
            if self._shutdown_future is placeholder:
                self._shutdown_future = future
            self._cleanup_attempt_future = future
        return future

    def _publish_startup_result(self, status: str) -> None:
        event = getattr(self, "_startup_result_event", None)
        if event is None or event.is_set():
            return
        self._startup_result = (status, getattr(self, "_lifecycle_generation", 0))
        event.set()

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
    # Storefront and seller pages are intentionally reachable before LAN
    # authentication: the former is a public buyer surface and the latter
    # performs its own seller-session gate.  Commerce APIs follow the same
    # rule; buyer credentials (guest state, receipts and delivery tokens)
    # and seller-session credentials are validated by their handlers.
    #
    # The per-route auth/rate-limit policy is declared at registration time
    # in api.py and read back through route_policy.request_policy — there is
    # no hardcoded path list to keep aligned here.

    @web.middleware
    async def _auth_middleware(self, request, handler):
        """Authentication middleware — skip for public endpoints."""
        from AssetsManager.lan.principal import principal_for_request
        from AssetsManager.lan.routes._helpers import get_request_principal, set_request_principal

        def ensure_guest():
            if get_request_principal(request) is None:
                set_request_principal(request, principal_for_request("guest"))

        def try_optional_principal() -> bool:
            """Resolve an optional LAN credential without blocking public Commerce."""
            if getattr(self, "_auth_mode", None) == "none":
                return False
            from AssetsManager.lan.routes._helpers import get_auth_token

            token = get_auth_token(request)
            if token and self.is_auth_token_revoked(token):
                token = ""
            if not token:
                return False
            access_key_hash = getattr(self, "_access_key_hash", None)
            if access_key_hash is not None and verify_key(token, access_key_hash):
                set_request_principal(request, principal_for_request("access_key"))
                return True
            try:
                local_ui_auth_secret = self.local_ui_auth_secret
            except AttributeError:
                local_ui_auth_secret = None
            if local_ui_auth_secret and verify_auth_token(token, local_ui_auth_secret):
                set_request_principal(request, principal_for_request("local_ui"))
                return True
            auth_service = getattr(self, "_auth_service", None)
            if auth_service is not None:
                try:
                    user = auth_service.verify_user_token(token)
                except Exception:
                    user = None
                if user:
                    set_request_principal(request, principal_for_request("user", user=user))
                    return True
            password_hash = getattr(self, "_password_hash", None)
            if password_hash is not None and verify_token(token, password_hash):
                set_request_principal(request, principal_for_request("password"))
                return True
            return False

        policy = request_policy(request)
        if policy.auth == "public_optional":
            # Publicly readable, but reflect a valid credential in its
            # normalized identity when one is supplied (/api/info, commerce).
            if self._auth_mode == "none":
                ensure_guest()
                return await handler(request)
            try_optional_principal()
            ensure_guest()
            return await handler(request)
        if policy.auth == "public":
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

        # Get token from cookie or Authorization header
        from AssetsManager.lan.routes._helpers import get_auth_token
        token = get_auth_token(request)
        if token and self.is_auth_token_revoked(token):
            token = ""

        # Try access key auth
        if has_key and token and self._access_key_hash is not None:
            if verify_key(token, self._access_key_hash):
                set_request_principal(request, principal_for_request("access_key"))
                return await handler(request)

        # Try local UI API token (signed with the auth-config-bound secret)
        local_ui_auth_secret = self.local_ui_auth_secret
        if local_ui_auth_secret and token:
            if verify_auth_token(token, local_ui_auth_secret):
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

        return error_response("Unauthorized", status=401, code="unauthorized")
