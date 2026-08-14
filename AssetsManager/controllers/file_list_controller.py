"""File list controller — small, UI-independent helpers for the file browser panel.

The panel delegates search-history persistence and total-size formatting here so
they stay testable without Qt. File-operation orchestration (rename/delete/
undo/redo) lives in the panel's ActionsMixin, not here.
"""
from __future__ import annotations

import logging

from AssetsManager.core.format_utils import format_size

_log = logging.getLogger(__name__)


class FileListController:
    """Small helpers shared by the file browser panel."""

    def __init__(self):
        self._file_ops: object = None   # FileOperationService, set by panel
        self._undo_svc: object = None   # UndoService, set by panel

    def set_file_operations(self, file_ops, undo_svc) -> None:
        """Inject file operation and undo services (called by panel on library switch)."""
        self._file_ops = file_ops
        self._undo_svc = undo_svc

    # ── Search history ───────────────────────────────────────────

    @staticmethod
    def get_search_history(max_items: int = 20) -> list[str]:
        """Return recent search terms from settings."""
        from AssetsManager.core.settings import AppSettings
        return AppSettings.instance().get_list("search_history", [])[:max_items]

    @staticmethod
    def save_search_term(term: str) -> None:
        """Save a search term to settings.

        Skipped entirely when *term* already matches the most recently saved
        term, avoiding a full settings write (with fsync) on every debounced
        re-apply of an unchanged search.
        """
        if not term.strip():
            return
        from AssetsManager.core.settings import AppSettings
        settings = AppSettings.instance()
        term = term.strip()
        history = settings.get_list("search_history", [])
        if history and history[0] == term:
            return
        settings.prepend_list("search_history", term, max_items=20)
        if not settings.save():
            _log.warning("failed to persist search history term %r", term)

    # ── Status formatting ────────────────────────────────────────

    @staticmethod
    def format_total_size_suffix(total_size: int) -> str:
        """Return the optional, display-ready total-size status suffix."""
        if total_size <= 0:
            return ""
        return f"  |  {format_size(total_size)}"
