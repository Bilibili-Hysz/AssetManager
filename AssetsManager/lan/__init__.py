"""LAN sharing module — optional aiohttp-based web server.

Allows sharing the asset library over the local network or internet.
Other devices can browse, search, preview, and download files
through a web browser.

Usage:
    from AssetsManager import lan
    if lan.is_available():
        mgr = lan.ShareManager()
        mgr.start(port=8080, lib_root="...", ...)
        mgr.start_tunnel("cloudflared")  # optional: share to internet
        print(mgr.status())
        mgr.stop()

This module is optional. If aiohttp is not installed, is_available()
returns False and all other functions raise RuntimeError.
"""
import logging
from pathlib import Path
from typing import Protocol, cast

_log = logging.getLogger(__name__)

class _AuthStatusProvider(Protocol):
    def auth_status(self) -> tuple[bool, str]: ...


try:
    from aiohttp import web as _web
    _HAS_AIOHTTP = True
except ImportError:
    _HAS_AIOHTTP = False
    _web = None


def is_available() -> bool:
    """Return True if aiohttp is installed and LAN sharing can be used."""
    return _HAS_AIOHTTP


class LanServer:
    """LAN sharing server facade. Wraps _LanServerImpl when aiohttp is available."""

    def __init__(self, runtime=None,
                 *, share_name: str = "AssetManager", password: str | None = None,
                  access_key: str | None = None,
                  auth_mode: str | None = None,
                  rate_limit: int = 100, blocked_ips: list[str] | None = None,
                  ip_whitelist: list[str] | None = None,
                  blur_tags: list[str] | None = None,
                  ssl_cert: str | None = None, ssl_key: str | None = None,
                  performance_recorder=None, session_token: str | None = None,
                  services=None, preflight=None):
        if runtime is None:
            raise TypeError("LanServer(runtime=...) requires a live LibraryRuntime")
        if not _HAS_AIOHTTP:
            raise RuntimeError(
                "LAN sharing requires aiohttp. Install with: pip install aiohttp"
            )
        from AssetsManager.lan.server import _LanServerImpl
        self._impl = _LanServerImpl(
            runtime=runtime,
            share_name=share_name,
            password=password,
            access_key=access_key,
            auth_mode=auth_mode,
            rate_limit=rate_limit,
            blocked_ips=blocked_ips,
            ip_whitelist=ip_whitelist,
            blur_tags=blur_tags,
            ssl_cert=ssl_cert,
            ssl_key=ssl_key,
            performance_recorder=performance_recorder,
            session_token=session_token,
            services=services,
        )
        self._last_security_snapshot = None
        self._default_preflight = preflight

    def start(self, port: int = 8080, bind: str = "0.0.0.0", *, preflight=None):
        """Start the server after the shared security preflight gate."""
        from AssetsManager.application.security_preflight import (
            persist_successful_share_security_history,
            security_preflight_from_settings,
        )

        if preflight is None:
            preflight = self._default_preflight or security_preflight_from_settings()
        # Keep the exact holder across restart/stop and make explicit and
        # constructor-injected paths equivalent.
        self._default_preflight = preflight
        auth_status = getattr(self._impl, "auth_status", None)
        effective_status = auth_status() if callable(auth_status) else None
        snapshot = preflight.snapshot(
            sharing=True,
            bind=bind,
            auth_status=effective_status,
        )
        self._last_security_snapshot = snapshot
        if snapshot.share_state != "local_active":
            return snapshot.to_dict()
        start_result = self._impl.start(port=port, bind=bind, preflight=preflight)
        if isinstance(start_result, dict) and start_result.get("share_state") != "local_active":
            self._last_security_snapshot = start_result
            return start_result
        # Re-read the real service-owned auth status after construction/start.
        auth_status = getattr(self._impl, "auth_status", None)
        effective_status = auth_status() if callable(auth_status) else effective_status
        post_snapshot = preflight.snapshot(
            sharing=True,
            bind=bind,
            auth_status=effective_status,
        )
        self._last_security_snapshot = post_snapshot
        if post_snapshot.share_state != "local_active":
            try:
                self._impl.stop()
            except Exception:
                failure = post_snapshot.to_dict()
                failure["share_state"] = "failed"
                failure["failure_reason"] = "security_post_start_rollback_failed"
                failure["rollback_failed"] = True
                failure["running"] = True
                self._last_security_snapshot = failure
                _log.exception("Failed to roll back LAN startup after auth re-check")
                return failure
            return post_snapshot.to_dict()

        persisted = persist_successful_share_security_history(
            preflight, bind=bind, auth_status=effective_status
        )
        if persisted is False:
            _log.warning(
                "LAN sharing started, but the last successful security posture "
                "could not be persisted; the next start will require safe re-confirmation"
            )
        return None

    def stop(self):
        """Stop the server and clear the exposed security activity snapshot."""
        self._impl.stop()
        snapshot = getattr(self, "_last_security_snapshot", None)
        if snapshot is not None:
            try:
                from AssetsManager.application.security_preflight import (
                    security_preflight_from_settings,
                )

                preflight = self._default_preflight or security_preflight_from_settings()
                auth_status = self.auth_status()
                self._last_security_snapshot = preflight.snapshot(
                    sharing=False,
                    bind=getattr(self._impl, "_bind", "localhost"),
                    auth_status=auth_status,
                )
            except Exception:
                self._last_security_snapshot = None

    def is_running(self) -> bool:
        """Return True if the server is currently running."""
        return self._impl.is_running()

    def status(self) -> dict:
        """Return server status info (ip, port, url, running)."""
        raw_status = self._impl.status()
        status = dict(raw_status) if isinstance(raw_status, dict) else raw_status
        snapshot = getattr(self, "_last_security_snapshot", None)
        if snapshot is not None:
            security = snapshot.to_dict() if hasattr(snapshot, "to_dict") else dict(snapshot)
            if isinstance(status, dict):
                status["security"] = security
        return status

    def auth_status(self) -> tuple[bool, str]:
        """Return the effective authentication status from the server."""
        method = getattr(self._impl, "auth_status", None)
        if not callable(method):
            return False, "none"
        provider = cast(_AuthStatusProvider, self._impl)
        return provider.auth_status()

    @property
    def security_snapshot(self):
        """Return the latest UI-neutral security preflight snapshot."""
        return getattr(self, "_last_security_snapshot", None)

    def _update_security_tunnel_state(self, tunnel_state: str, failure_reason: str | None):
        snapshot = getattr(self, "_last_security_snapshot", None)
        if snapshot is None:
            return
        if hasattr(snapshot, "to_dict"):
            from dataclasses import replace
            self._last_security_snapshot = replace(
                snapshot,
                tunnel_state=tunnel_state,
                failure_reason=failure_reason,
            )
        elif isinstance(snapshot, dict):
            updated = dict(snapshot)
            updated["tunnel_state"] = tunnel_state
            updated["failure_reason"] = failure_reason
            self._last_security_snapshot = updated

    @property
    def tunnel_start_block_reason(self) -> str | None:
        return getattr(self._impl, "tunnel_start_block_reason", None)

    @property
    def tunnel(self):
        """Return the server-owned, security-guarded tunnel handle."""
        return self._impl.tunnel

    def broadcast(self, event_type: str, data: dict | None = None):
        """Send a WebSocket event to all connected clients."""
        self._impl.broadcast(event_type, data)

    def start_tunnel(self, timeout: int = 30) -> str | None:
        """Start a public Cloudflare tunnel. Returns public URL or None."""
        url = self._impl.start_tunnel(timeout=timeout)
        from AssetsManager.application.security_preflight import TunnelState
        if url:
            self._update_security_tunnel_state(TunnelState.PUBLIC_ACTIVE.value, None)
        else:
            block_reason = self.tunnel_start_block_reason
            try:
                auth_enabled, _auth_mode = self.auth_status()
            except Exception:
                auth_enabled = False
            if block_reason == "authentication_required" or not auth_enabled:
                state = TunnelState.BLOCKED.value
                reason = block_reason or "tunnel_authentication_required"
            else:
                state = TunnelState.FAILED.value
                reason = block_reason or "tunnel_start_failed"
            self._update_security_tunnel_state(state, reason)
        return url

    def stop_tunnel(self):
        """Stop the public internet tunnel."""
        self._impl.stop_tunnel()
        from AssetsManager.application.security_preflight import TunnelState
        self._update_security_tunnel_state(TunnelState.STOPPED.value, None)

    def is_tunnel_running(self) -> bool:
        """Return True if a tunnel is currently active."""
        return self._impl.tunnel.is_running if self._impl.tunnel else False

    def reload_settings(self, settings: dict):
        """Reload settings that don't require server restart."""
        self._impl.reload_settings(settings)

    @property
    def current_settings(self) -> dict:
        """Return current settings for API handlers."""
        return self._impl.current_settings

    @property
    def library_root(self) -> Path:
        """Return the shared library root path."""
        return self._impl.library_root

    @property
    def _port(self) -> int:
        """Return the server port."""
        return self._impl._port

    @property
    def _bind(self) -> str:
        """Return the server bind address."""
        return self._impl._bind

    @property
    def _token_secret(self) -> str:
        """Return the Runtime-owned sharing token secret."""
        return self._impl._token_secret

    @property
    def token_secret(self) -> str:
        """Return the local UI API secret (legacy desktop compatibility alias).

        Runtime sharing consumers should use ``runtime_token_secret`` instead.
        """
        return self._impl.token_secret

    @property
    def runtime_token_secret(self) -> str:
        """Return the Runtime-owned AuthService/ShareService token secret."""
        return self._impl.runtime_token_secret

    @property
    def local_ui_auth_secret(self) -> str:
        """Return the auth-config-bound secret for local UI access-key tokens."""
        return self._impl.local_ui_auth_secret

    def local_ui_token(self) -> str | None:
        """Mint a signed local-UI credential, only while LAN auth is active.

        The server accepts this token as the ``local_ui`` principal (full
        capabilities, unaffected by guest-facing preview restrictions).
        Returns None when authentication is off (no credential needed) or
        the signing secret is unavailable.
        """
        enabled, _mode = self.auth_status()
        if not enabled:
            return None
        secret = getattr(self._impl, "local_ui_auth_secret", None)
        if not secret:
            return None
        from AssetsManager.lan.utils import generate_auth_token

        return generate_auth_token(secret)

    @property
    def ssl_active(self) -> bool:
        """Return whether the active listener actually uses TLS."""
        return self._impl.ssl_active

    @property
    def endpoint_protocol(self) -> str:
        """Return the active endpoint protocol (http or https)."""
        return self._impl.endpoint_protocol


# Lazy import ShareManager to avoid circular imports
def ShareManager():
    """Create a new ShareManager instance."""
    from AssetsManager.lan.manager import ShareManager as _SM
    return _SM()
