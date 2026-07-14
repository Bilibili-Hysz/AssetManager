"""Sidebar favorites — persistent folder favorites with rename/icon/reorder."""
import logging
import tempfile
from pathlib import Path

from AssetsManager.core.database import get_library_dir
from AssetsManager.core.json_store import JsonStore

_log = logging.getLogger(__name__)


class SidebarFavorites(JsonStore):
    def __init__(self, library_root: str = ""):
        self._items: list[dict] = []
        path = Path(tempfile.gettempdir()) / "AssetsManager_favorites.json"
        super().__init__(path)
        if library_root:
            self.set_library_root(library_root)

    def set_library_root(self, library_root: str):
        if not library_root or library_root == ".":
            return
        old_data = list(self._items) if self._loaded else None
        self._path = get_library_dir(library_root) / "favorites.json"
        self._loaded = False
        self._ensure_loaded()
        if old_data and not self._items:
            self._items = old_data
            self._save()

    # ── JsonStore hooks ─────────────────────────────────────────

    def _default_data(self):
        return []

    def _on_loaded(self, data):
        if isinstance(data, list):
            self._items = data
        else:
            self._items = []
        self._prune_missing()

    def _on_before_save(self):
        return self._items

    # ── Internal helpers ────────────────────────────────────────

    def _prune_missing(self):
        self._items = [i for i in self._items if Path(i.get("path", "")).exists()]

    # ── Public API ──────────────────────────────────────────────

    def list_all(self) -> list[dict]:
        self._ensure_loaded()
        return list(self._items)

    def add(self, path: str, name: str | None = None, icon: str = "⭐"):
        self._ensure_loaded()
        path = str(Path(path).resolve())
        for item in self._items:
            if item.get("path") == path:
                return False
        self._items.append({
            "path": path,
            "name": name or Path(path).name,
            "icon": icon,
        })
        self._save()
        return True

    def remove(self, path: str):
        self._ensure_loaded()
        path = str(Path(path).resolve())
        before = len(self._items)
        self._items = [i for i in self._items if i.get("path") != path]
        if len(self._items) != before:
            self._save()
            return True
        return False

    def rename(self, path: str, new_name: str):
        self._ensure_loaded()
        path = str(Path(path).resolve())
        for item in self._items:
            if item.get("path") == path:
                item["name"] = new_name
                self._save()
                return True
        return False

    def set_icon(self, path: str, icon: str):
        self._ensure_loaded()
        path = str(Path(path).resolve())
        for item in self._items:
            if item.get("path") == path:
                item["icon"] = icon
                self._save()
                return True
        return False

    def reorder(self, from_index: int, to_index: int):
        self._ensure_loaded()
        if 0 <= from_index < len(self._items) and 0 <= to_index < len(self._items):
            item = self._items.pop(from_index)
            self._items.insert(to_index, item)
            self._save()

    def is_favorite(self, path: str) -> bool:
        self._ensure_loaded()
        path = str(Path(path).resolve())
        return any(i.get("path") == path for i in self._items)

    def clear(self):
        self._items = []
        self._save()
