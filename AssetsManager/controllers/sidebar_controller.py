"""SidebarController — business logic for the sidebar navigation panel.

Centralizes favorites management, recent paths, search state, and
settings persistence so the SidebarPanel stays focused on UI rendering.
"""
from __future__ import annotations


class SidebarController:
    """Non-UI business logic for the sidebar panel."""

    def __init__(self):
        self._search_gen: int = 0

    # ── Search state ──────────────────────────────────────────────

    @property
    def search_gen(self) -> int:
        return self._search_gen

    def next_search_gen(self) -> int:
        self._search_gen += 1
        return self._search_gen

    def is_current_search(self, gen: int) -> bool:
        return gen == self._search_gen
