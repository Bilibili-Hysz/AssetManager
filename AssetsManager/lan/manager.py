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
import logging
from typing import Callable

from AssetsManager.lan.tunnel import TunnelManager, is_available as is_tunnel_available

_log = logging.getLogger(__name__)


class ShareManager:
    """Unified sharing state manager."""

    def __init__(self):
        self._server = None  # LanServer instance
        self._tunnel: TunnelManager | None = None
        self._state: dict = {
            "running": False,
            "port": 8080,
            "bind": "0.0.0.0",
            "local_url": None,
            "share_name": "AssetManager",
            "tunnel_running": False,
            "public_url": None,
            "auth_enabled": False,
            "connections": 0,
            "requests": 0,
            "bytes_transferred": 0,
        }
        self._callbacks: list[Callable] = []

    # ── Lifecycle ────────────────────────────────────────────

    def start(self, *, port: int = 8080, bind: str = "0.0.0.0",
              password: str | None = None, access_key: str | None = None,
              share_name: str = "AssetManager",
              rate_limit: int = 1000, blocked_ips: list[str] | None = None,
              blur_tags: list[str] | None = None,
              ssl_cert: str | None = None, ssl_key: str | None = None,
              runtime=None) -> dict:
        """Start the LAN server. Returns status dict."""
        if self._state["running"]:
            return self.status()

        from AssetsManager import lan
        if not lan.is_available():
            _log.error("aiohttp not installed")
            return self.status()

        options = dict(
            share_name=share_name, password=password, access_key=access_key,
            rate_limit=rate_limit, blocked_ips=blocked_ips, blur_tags=blur_tags,
            ssl_cert=ssl_cert, ssl_key=ssl_key,
        )
        if runtime is not None:
            self._server = lan.LanServer(runtime=runtime, **options)
        else:
            raise TypeError("ShareManager.start requires runtime")
        self._server.start(port=port, bind=bind)

        from AssetsManager.lan.server import get_local_ip
        ip = get_local_ip()
        self._state.update(
            running=True,
            port=port,
            bind=bind,
            local_url=f"http://{ip}:{port}",
            share_name=share_name,
            auth_enabled=password is not None,
        )
        self._notify()
        _log.info("Sharing started: %s", self._state["local_url"])
        return self.status()

    def stop(self):
        """Stop server AND tunnel. Cleans up all resources."""
        self.stop_tunnel()
        if self._server:
            self._server.stop()
            self._server = None
        self._state.update(
            running=False,
            local_url=None,
            connections=0,
            requests=0,
            bytes_transferred=0,
        )
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

        self._tunnel = TunnelManager(self._state["port"])
        url = self._tunnel.start(timeout=timeout)
        if url:
            self._state.update(
                tunnel_running=True,
                public_url=url,
            )
            self._notify()
            _log.info("Tunnel started: %s", url)
        return url

    def stop_tunnel(self):
        """Stop internet tunnel only."""
        if self._tunnel:
            try:
                self._tunnel.stop()
            except Exception:
                _log.exception("Error stopping tunnel")
            self._tunnel = None
        self._state.update(
            tunnel_running=False,
            public_url=None,
        )
        self._notify()
        _log.info("Tunnel stopped")

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
