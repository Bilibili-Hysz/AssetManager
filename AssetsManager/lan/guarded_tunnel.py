"""Read-only tunnel view for the LAN server.

Moved verbatim from ``lan/server.py``; the server keeps re-exporting
``_GuardedTunnel`` under the same name so call sites are unchanged.  The view
forces every tunnel mutation to pass through the owner's auth gate, so an
unauthenticated LAN server can never be exposed through a public tunnel.
"""
from __future__ import annotations


class _GuardedTunnel:
    """Read-only tunnel view whose lifecycle always passes the auth gate."""

    def __init__(self, owner):
        self._owner = owner

    @property
    def is_running(self) -> bool:
        return self._owner._tunnel.is_running

    @property
    def public_url(self) -> str | None:
        return self._owner._tunnel.public_url

    def start(self, timeout: int = 30) -> str | None:
        return self._owner.start_tunnel(timeout=timeout)

    def stop(self):
        return self._owner.stop_tunnel()
