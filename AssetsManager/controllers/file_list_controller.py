"""File list controller — business logic for the file browser panel.

Extracts non-UI business logic from FileListPanel to make it testable
without Qt. The panel delegates to this controller for:
- Search history persistence
- Status text computation
- First image cache
- Total size computation
- File operation orchestration (rename, delete, undo/redo)
"""
from __future__ import annotations

import os
from pathlib import Path

from AssetsManager.application.asset_filters import IMAGE_EXTS


class FileListController:
    """Business logic for file browsing operations."""

    def __init__(self):
        self._first_image_cache: dict[str, str | None] = {}
        self._first_image_cache_max = 5000
        self._cached_total_size: int = -1
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
        """Save a search term to settings."""
        if not term.strip():
            return
        from AssetsManager.core.settings import AppSettings
        settings = AppSettings.instance()
        settings.prepend_list("search_history", term.strip(), max_items=20)
        settings.save()

    # ── First image cache ────────────────────────────────────────

    def find_first_image(self, dir_path: str) -> str | None:
        """Find the first image file in a directory, with caching."""
        if dir_path in self._first_image_cache:
            return self._first_image_cache[dir_path]
        result = self._scan_first_image(dir_path)
        if len(self._first_image_cache) >= self._first_image_cache_max:
            self._first_image_cache.clear()
        self._first_image_cache[dir_path] = result
        return result

    def clear_first_image_cache(self) -> None:
        """Clear the first image cache."""
        self._first_image_cache.clear()

    @staticmethod
    def _scan_first_image(dir_path: str) -> str | None:
        """Scan a directory for the first image file."""
        try:
            with os.scandir(dir_path) as scanner:
                for i, entry in enumerate(scanner):
                    if i > 500:
                        break
                    if entry.is_file() and Path(entry.name).suffix.lower() in IMAGE_EXTS:
                        return entry.path
        except OSError:
            pass
        return None

    # ── Status computation ───────────────────────────────────────

    @staticmethod
    def compute_status_text(
        total: int,
        selected: int,
        total_size: int,
        view_mode: str,
    ) -> str:
        """Compute the status bar text."""
        sz_str = ""
        if total_size > 0:
            sz_str = f"  |  {_fmt_size(total_size)}"
        if selected:
            return f"{selected} selected / {total} items{sz_str}  |  {view_mode}"
        return f"{total} items{sz_str}  |  {view_mode}"

    @staticmethod
    def compute_total_size(entries: list, stat_cache: dict) -> int:
        """Compute total size of non-directory entries.

        Accepts both os.DirEntry and Path objects.
        """
        total = 0
        for entry in entries:
            if entry.is_dir():
                continue
            path = getattr(entry, "path", str(entry))
            cached = stat_cache.get(path)
            if cached is not None:
                try:
                    total += cached.st_size
                except AttributeError:
                    pass
            else:
                try:
                    total += entry.stat().st_size
                except OSError:
                    pass
        return total


def _fmt_size(sz: int) -> str:
    """Format bytes as human-readable size."""
    size = float(sz)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"
