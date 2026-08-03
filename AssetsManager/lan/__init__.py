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

_log = logging.getLogger(__name__)

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
                  services=None):
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

    def start(self, port: int = 8080, bind: str = "0.0.0.0"):
        """Start the server on the given port. Raises OSError if port is in use."""
        self._impl.start(port=port, bind=bind)

    def stop(self):
        """Stop the server."""
        self._impl.stop()

    def is_running(self) -> bool:
        """Return True if the server is currently running."""
        return self._impl.is_running()

    def status(self) -> dict:
        """Return server status info (ip, port, url, running)."""
        return self._impl.status()

    def broadcast(self, event_type: str, data: dict | None = None):
        """Send a WebSocket event to all connected clients."""
        self._impl.broadcast(event_type, data)

    def start_tunnel(self, timeout: int = 30) -> str | None:
        """Start a public Cloudflare tunnel. Returns public URL or None."""
        return self._impl.start_tunnel(timeout=timeout)

    def stop_tunnel(self):
        """Stop the public internet tunnel."""
        self._impl.stop_tunnel()

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
