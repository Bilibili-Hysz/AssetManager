"""LAN implementation of the desktop ports plus the single server assembly.

``application/desktop_ports`` owns the protocol shapes; this module owns the
only production ``LanServer(...)`` construction point.  Desktop widgets get
``build_lan_server`` and ``LanDesktopAdapter`` injected through the window
composition root and never import ``AssetsManager.lan`` themselves.
"""
from __future__ import annotations

from typing import Any

from AssetsManager.application.desktop_ports import LanControlPort, ShareSettingsPort


class LanDesktopAdapter(ShareSettingsPort):
    """Delegate ShareSettingsPort calls lazily to LAN utility modules.

    Lazy imports keep the adapter cheap to construct and avoid pulling the
    tunnel helpers into every desktop process until the dialog needs them.
    """

    def tunnel_is_available(self) -> bool:
        from AssetsManager.lan.tunnel import is_available
        return is_available()

    def ensure_tunnel_available(self) -> str | None:
        from AssetsManager.lan.tunnel import ensure_available
        return ensure_available()

    def local_ip(self) -> str:
        from AssetsManager.lan.utils import get_local_ip
        return get_local_ip()

    def auth_headers(self, token_secret: str) -> dict[str, str]:
        from AssetsManager.lan.utils import get_auth_headers
        return get_auth_headers(token_secret)


def build_lan_server(
    runtime: Any, *, preflight: Any = None, **options: Any
) -> LanControlPort:
    """Construct a LAN server facade — the single production assembly point.

    The package attribute is resolved at call time (rather than at import
    time) so tests and embedding hosts can substitute a server implementation
    before the first construction.
    """
    from AssetsManager import lan

    return lan.LanServer(runtime=runtime, preflight=preflight, **options)
