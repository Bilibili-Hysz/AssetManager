"""ShareManager — single source of truth for all sharing state.

Coordinates LAN server, tunnel, and authentication lifecycle.
UI code should only interact with ShareManager, never directly with
LanServer or TunnelManager.

Usage:
    mgr = ShareManager()
    mgr.start(port=8080, lib_root="...", ...)
    mgr.start_tunnel("cloudflared")
    print(mgr.status())
    mgr.stop()  # stops both server and tunnel
"""
import inspect
import logging
from typing import Any, Callable, Protocol, cast

from AssetsManager.lan.ports import build_lan_server
from AssetsManager.lan.tunnel import TunnelManager, is_available as is_tunnel_available

_log = logging.getLogger(__name__)


class _TunnelHandle(Protocol):
    """Common lifecycle surface for direct and server-guarded tunnels."""

    @property
    def is_running(self) -> bool: ...

    @property
    def public_url(self) -> str | None: ...

    def start(self, timeout: int = 30) -> str | None: ...

    def stop(self) -> None: ...


class ShareManager:
    """Unified sharing state manager."""

    def __init__(self, server_factory: Callable[..., Any] | None = None):
        self._server_factory = server_factory
        self._server = None  # LanServer instance
        self._tunnel: _TunnelHandle | None = None
        self._state: dict = {
            "running": False,
            "port": 8080,
            "bind": "0.0.0.0",
            "local_url": None,
            "share_name": "AssetManager",
            "tunnel_running": False,
            "public_url": None,
            "auth_enabled": False,
            "share_state": "off",
            "tunnel_state": "stopped",
            "confirmation_required": False,
            "trusted_network_confirmed": False,
            "failure_reason": None,
            "security": None,
            "connections": 0,
            "requests": 0,
            "bytes_transferred": 0,
        }
        self._callbacks: list[Callable] = []

    # ── Lifecycle ────────────────────────────────────────────

    def start(self, *, port: int = 8080, bind: str = "0.0.0.0",
              password: str | None = None, access_key: str | None = None,
              auth_mode: str | None = None,
              share_name: str = "AssetManager",
              rate_limit: int = 100, blocked_ips: list[str] | None = None,
              blur_tags: list[str] | None = None,
              ssl_cert: str | None = None, ssl_key: str | None = None,
              runtime=None, preflight=None) -> dict:
        """Start the LAN server. Returns status dict."""
        if self._state["running"]:
            return self.status()

        from AssetsManager import lan
        if not lan.is_available():
            _log.error("aiohttp not installed")
            return self.status()

        if runtime is None:
            raise TypeError("ShareManager.start requires runtime")

        # A failed stop() retains the server handle because the underlying
        # thread may still hold the port.  Retry stopping any leftover
        # server here so a fresh server can bind the port; a failed retry
        # is logged but does not block the startup flow.
        residual = self._server
        if residual is not None:
            try:
                residual.stop()
                self._server = None
            except Exception:
                _log.exception("Error stopping leftover LAN server before restart")

        from AssetsManager.application.security_preflight import security_preflight_from_settings

        if preflight is None:
            preflight = security_preflight_from_settings()
        configured_auth = self._configured_auth_status(
            password=password,
            access_key=access_key,
            auth_mode=auth_mode,
            runtime=runtime,
        )
        snapshot = preflight.snapshot(
            sharing=True,
            bind=bind,
            auth_status=configured_auth,
        )
        self._apply_security_snapshot(snapshot)
        if snapshot.share_state != "local_active":
            return self.status()

        server_factory = self._server_factory
        if server_factory is None:
            server_factory = build_lan_server
        server = server_factory(
            runtime=runtime,
            preflight=preflight,
            share_name=share_name,
            password=password,
            access_key=access_key,
            auth_mode=auth_mode,
            rate_limit=rate_limit,
            blocked_ips=blocked_ips,
            blur_tags=blur_tags,
            ssl_cert=ssl_cert,
            ssl_key=ssl_key,
        )
        start_result = server.start(port=port, bind=bind, preflight=preflight)
        if isinstance(start_result, dict) and start_result.get("share_state") != "local_active":
            self._apply_security_snapshot(start_result)
            server_running = self._server_is_running(server, start_result)
            self._state.update(
                running=server_running,
                share_state="failed" if server_running else start_result.get("share_state", "off"),
                local_url=(self._state.get("local_url") if server_running else None),
            )
            # Keep a leftover handle when the fresh server failed to come up
            # and a residual stop retry also failed, so stop can be retried.
            self._server = (
                server if server_running
                else (residual if residual is not None else None)
            )
            self._notify()
            return self.status()
        self._server = server

        from AssetsManager.lan.server import get_local_ip
        ip = get_local_ip()
        actual_auth = configured_auth
        auth_status = getattr(server, "auth_status", None)
        if callable(auth_status):
            try:
                actual_auth = auth_status()
            except Exception:
                _log.exception("Unable to read effective LAN auth status")
                actual_auth = (False, "none")
        snapshot = preflight.snapshot(
            sharing=True,
            bind=bind,
            auth_status=actual_auth,
        )
        self._apply_security_snapshot(snapshot)
        if snapshot.share_state != "local_active":
            rollback_failed = False
            try:
                server.stop()
            except Exception:
                rollback_failed = True
                _log.exception("Failed to roll back LAN startup after auth re-check")
            server_running = self._server_is_running(
                server,
                {
                    "rollback_failed": rollback_failed,
                    "running": rollback_failed,
                },
            )
            if rollback_failed or server_running:
                self._server = server
                self._state.update(
                    running=True,
                    share_state="failed",
                    local_url=self._state.get("local_url"),
                    failure_reason="security_post_start_rollback_failed",
                )
            else:
                self._server = None
                self._state.update(
                    running=False,
                    local_url=None,
                    share_state=snapshot.share_state,
                    failure_reason=(
                        getattr(snapshot, "failure_reason", None)
                        if not isinstance(snapshot, dict)
                        else snapshot.get("failure_reason")
                    ),
                )
            self._notify()
            return self.status()
        self._state.update(
            running=True,
            port=port,
            bind=bind,
            local_url=f"http://{ip}:{port}",
            share_name=share_name,
            auth_enabled=bool(snapshot.effective_auth.get("enabled")),
            failure_reason=None,
        )
        self._notify()
        _log.info("Sharing started: %s", self._state["local_url"])
        return self.status()

    @staticmethod
    def _server_is_running(server, start_result):
        """Resolve whether a failed server startup retained a live server."""
        if start_result.get("rollback_failed"):
            return True
        is_running = getattr(server, "is_running", None)
        if callable(is_running):
            try:
                return bool(is_running())
            except Exception:
                _log.exception("Unable to inspect server state after startup failure")
                return True
        return bool(start_result.get("running"))

    def stop(self):
        """Stop server AND tunnel. Cleans up all resources."""
        self.stop_tunnel()
        stop_error = None
        if self._server:
            try:
                self._server.stop()
            except Exception:
                _log.exception("Error stopping LAN server; state kept retryable")
                stop_error = "server_stop_failed"
            else:
                # Only drop the handle on a successful stop; on failure the
                # underlying thread may still hold the port, so keep the
                # reference for a later stop/start retry.
                self._server = None
        if self._tunnel is not None and not self._tunnel_is_running(self._tunnel):
            self._tunnel = None
        tunnel_cleanup_failed = self._tunnel is not None
        state_update = {
            "running": False,
            "local_url": None,
            "share_state": "failed" if stop_error else "off",
            "confirmation_required": False,
            "connections": 0,
            "requests": 0,
            "bytes_transferred": 0,
        }
        if tunnel_cleanup_failed:
            state_update["tunnel_state"] = "failed"
            state_update["failure_reason"] = "tunnel_cleanup_failed"
        elif stop_error:
            state_update["tunnel_state"] = "stopped"
            state_update["failure_reason"] = stop_error
        else:
            state_update["tunnel_state"] = "stopped"
            state_update["failure_reason"] = None
        self._state.update(state_update)
        self._sync_security_tunnel_state()
        self._notify()
        _log.info("Sharing stopped")

    def is_running(self) -> bool:
        return self._state["running"]

    # ── Tunnel ───────────────────────────────────────────────

    def start_tunnel(self, timeout: int = 30) -> str | None:
        """Start Cloudflare tunnel. Returns public URL or None."""
        if not self._state["running"]:
            _log.error("Cannot start tunnel: server not running")
            return None
        if self._state["tunnel_running"]:
            return self._state["public_url"]

        auth_status = getattr(self._server, "auth_status", None)
        if not callable(auth_status):
            self._state.update(
                tunnel_state="blocked",
                failure_reason="authentication_status_unavailable",
            )
            self._sync_security_tunnel_state()
            _log.warning("Refusing to start public tunnel without auth_status capability")
            self._notify()
            return None
        try:
            auth_enabled, auth_mode = cast(
                Callable[[], tuple[bool, str | None]], auth_status
            )()
        except Exception:
            self._state.update(
                tunnel_state="blocked",
                failure_reason="authentication_status_unavailable",
            )
            self._sync_security_tunnel_state()
            _log.exception("Unable to read LAN authentication status before tunnel startup")
            self._notify()
            return None
        if not auth_enabled:
            self._state.update(
                tunnel_state="blocked",
                failure_reason="tunnel_authentication_required",
            )
            self._sync_security_tunnel_state()
            _log.warning(
                "Refusing to start public tunnel without LAN authentication (auth_mode=%s)",
                auth_mode,
            )
            self._notify()
            return None

        self._state.update(
            tunnel_state="starting",
            failure_reason=None,
        )
        self._sync_security_tunnel_state()
        self._notify()

        # LanServer is the production lifecycle owner.  The TunnelManager
        # fallback keeps compatibility with legacy/fake server adapters that do
        # not expose the guarded server-owned tunnel contract.
        candidate = self._server_tunnel_handle()
        if candidate is None:
            candidate = TunnelManager(self._state["port"])
        try:
            url = candidate.start(timeout=timeout)
        except Exception:
            _log.exception("Tunnel startup failed")
            cleanup_ok = self._cleanup_failed_tunnel(candidate)
            self._record_tunnel_failure(
                candidate,
                cleanup_ok=cleanup_ok,
                reason="tunnel_start_failed",
            )
            return None

        if not url:
            _log.warning("Tunnel startup returned no public URL")
            cleanup_ok = self._cleanup_failed_tunnel(candidate)
            self._record_tunnel_failure(
                candidate,
                cleanup_ok=cleanup_ok,
                reason="tunnel_start_failed",
            )
            return None

        self._tunnel = candidate
        self._state.update(
            tunnel_running=True,
            public_url=url,
            tunnel_state="public_active",
            failure_reason=None,
        )
        self._sync_security_tunnel_state()
        self._notify()
        _log.info("Tunnel started: %s", url)
        return url

    def _server_tunnel_handle(self) -> _TunnelHandle | None:
        server = self._server
        if server is None:
            return None
        missing = object()
        descriptor = inspect.getattr_static(server, "tunnel", missing)
        if descriptor is missing:
            return None
        try:
            return cast(_TunnelHandle, server.tunnel)
        except Exception:
            _log.exception("Unable to resolve server-owned tunnel handle")
            return None

    @staticmethod
    def _tunnel_is_running(tunnel: _TunnelHandle) -> bool:
        value = getattr(tunnel, "is_running", None)
        if isinstance(value, bool):
            return value
        if callable(value):
            try:
                return bool(value())
            except Exception:
                _log.exception("Unable to determine tunnel liveness")
                return True
        return True if value is None else bool(value)

    @staticmethod
    def _cleanup_failed_tunnel(tunnel: _TunnelHandle) -> bool:
        """Clean up a failed candidate and report whether it is fully stopped."""
        try:
            tunnel.stop()
        except Exception:
            _log.exception("Error cleaning up failed tunnel")
            return False
        return not ShareManager._tunnel_is_running(tunnel)

    def _record_tunnel_failure(
        self, candidate: _TunnelHandle, *, cleanup_ok: bool, reason: str
    ) -> None:
        """Publish a failed tunnel state while preserving any live cleanup handle."""
        if cleanup_ok:
            self._state.update(
                tunnel_running=False,
                public_url=None,
                tunnel_state="stopped",
                failure_reason=reason,
            )
        else:
            self._tunnel = candidate
            running = ShareManager._tunnel_is_running(candidate)
            self._state.update(
                tunnel_running=running,
                public_url=getattr(candidate, "public_url", None),
                tunnel_state="failed",
                failure_reason="tunnel_cleanup_failed",
            )
        self._sync_security_tunnel_state()
        self._notify()

    def stop_tunnel(self):
        """Stop internet tunnel only, retaining a failed handle for retry."""
        if self._tunnel:
            try:
                self._tunnel.stop()
            except Exception:
                _log.exception("Error stopping tunnel")
                self._state.update(
                    tunnel_running=ShareManager._tunnel_is_running(self._tunnel),
                    public_url=getattr(self._tunnel, "public_url", None),
                    tunnel_state="failed",
                    failure_reason="tunnel_cleanup_failed",
                )
                self._sync_security_tunnel_state()
                self._notify()
                return
            if ShareManager._tunnel_is_running(self._tunnel):
                self._state.update(
                    tunnel_running=True,
                    public_url=getattr(self._tunnel, "public_url", None),
                    tunnel_state="failed",
                    failure_reason="tunnel_cleanup_failed",
                )
                self._sync_security_tunnel_state()
                self._notify()
                return
            self._tunnel = None
        self._state.update(
            tunnel_running=False,
            public_url=None,
            tunnel_state="stopped",
            failure_reason=None,
        )
        self._sync_security_tunnel_state()
        self._notify()
        _log.info("Tunnel stopped")

    def _sync_security_tunnel_state(self):
        security = self._state.get("security")
        if isinstance(security, dict):
            security = dict(security)
            security["tunnel_state"] = self._state.get("tunnel_state", "stopped")
            security["failure_reason"] = self._state.get("failure_reason")
            self._state["security"] = security

    def is_tunnel_running(self) -> bool:
        return self._state["tunnel_running"]

    # ── Status ───────────────────────────────────────────────

    def status(self) -> dict:
        """Return current state snapshot."""
        # Update live stats from server if available
        if self._server:
            try:
                server_status = self._server.status()
                self._state["connections"] = server_status.get("connections", 0)
                self._state["requests"] = server_status.get("requests", 0)
                self._state["bytes_transferred"] = server_status.get("bytes_transferred", 0)
            except Exception:
                pass
        return dict(self._state)

    def is_tunnel_available(self) -> bool:
        """Check if Cloudflare tunnel is available."""
        return is_tunnel_available()

    # ── State change callbacks ───────────────────────────────

    @staticmethod
    def _configured_auth_status(*, password, access_key, auth_mode, runtime=None):
        if access_key:
            return True, "key"
        if password:
            return True, "password"
        if auth_mode in {"user", "users"}:
            services = getattr(runtime, "sharing_services", None)
            auth_service = getattr(services, "auth_service", None)
            has_active_users = getattr(auth_service, "has_active_users", None)
            if callable(has_active_users):
                try:
                    return (True, "user") if has_active_users() else (False, "none")
                except Exception:
                    _log.exception(
                        "Unable to inspect active LAN users before startup; "
                        "assuming user authentication is configured"
                    )
                    return True, "user"
            return False, "none"
        return False, "none"

    def _apply_security_snapshot(self, snapshot):
        if hasattr(snapshot, "to_dict"):
            payload = snapshot.to_dict()
            effective_auth = snapshot.effective_auth
        else:
            payload = dict(snapshot)
            effective_auth = payload.get("effective_auth", {})
        self._state.update(
            share_state=payload.get("share_state", self._state.get("share_state", "off")),
            tunnel_state=payload.get("tunnel_state", self._state.get("tunnel_state", "stopped")),
            confirmation_required=bool(payload.get("confirmation_required", False)),
            trusted_network_confirmed=bool(payload.get("trusted_network_confirmed", False)),
            failure_reason=payload.get("failure_reason"),
            auth_enabled=bool(effective_auth.get("enabled")),
            security=payload,
        )
        self._notify()

    def on_state_change(self, callback: Callable):
        """Register a callback for state changes."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable):
        """Remove a registered callback."""
        try:
            self._callbacks.remove(callback)
        except ValueError:
            pass

    def _notify(self):
        """Notify all registered callbacks of state change."""
        state = self.status()
        for cb in self._callbacks:
            try:
                cb(state)
            except Exception:
                _log.exception("Error in state change callback")
