"""Sidebar favorites — persistent folder favorites with rename/icon/reorder."""
import logging
import tempfile
from pathlib import Path

from AssetsManager.core import icons
from AssetsManager.core.path_resolver import library_data_dir
from AssetsManager.core.json_store import JsonStore

_log = logging.getLogger(__name__)


class SidebarFavorites(JsonStore):
    def __init__(self, library_root: str = ""):
        self._items: list[dict] = []
        path = Path(tempfile.gettempdir()) / "AssetsManager_favorites.json"
        super().__init__(path)
        if library_root:
            self.set_library_root(library_root)

    def set_library_root(self, library_root: str, data_dir: Path | None = None):
        if not library_root or library_root == ".":
            return
        # NOTE: no fallback that copies the previous library's items here.
        # The old behavior migrated favorites from the previously active
        # library into the new library's file, silently mixing data across
        # libraries. A fresh library shows an empty favorites list instead.
        self._path = (data_dir or library_data_dir(library_root)) / "favorites.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._loaded = False
        self._ensure_loaded()

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
        before = len(self._items)
        self._items = [
            i for i in self._items
            if isinstance(i, dict) and Path(i.get("path", "")).exists()
        ]
        if len(self._items) != before:
            self._save()

    # ── Public API ──────────────────────────────────────────────

    def list_all(self) -> list[dict]:
        with self._lock:
            self._ensure_loaded()
            return list(self._items)

    def add(self, path: str, name: str | None = None, icon: str = "star"):
        with self._lock:
            self._ensure_loaded()
            path = str(Path(path).resolve())
            for item in self._items:
                if item.get("path") == path:
                    return False
            self._items.append({
                "path": path,
                "name": name or Path(path).name,
                "icon": icons.normalize(str(icon or ""), fallback="star"),
            })
            self._save()
            return True

    def remove(self, path: str):
        with self._lock:
            self._ensure_loaded()
            path = str(Path(path).resolve())
            before = len(self._items)
            self._items = [i for i in self._items if i.get("path") != path]
            if len(self._items) != before:
                self._save()
                return True
            return False

    def rename(self, path: str, new_name: str):
        with self._lock:
            self._ensure_loaded()
            path = str(Path(path).resolve())
            for item in self._items:
                if item.get("path") == path:
                    item["name"] = new_name
                    self._save()
                    return True
            return False

    def set_icon(self, path: str, icon: str):
        with self._lock:
            self._ensure_loaded()
            path = str(Path(path).resolve())
            for item in self._items:
                if item.get("path") == path:
                    item["icon"] = icons.normalize(str(icon or ""), fallback="star")
                    self._save()
                    return True
            return False

    def reorder(self, from_index: int, to_index: int):
        with self._lock:
            self._ensure_loaded()
            # ``to_index == len`` moves the item to the very end.
            if 0 <= from_index < len(self._items) and 0 <= to_index <= len(self._items):
                item = self._items.pop(from_index)
                self._items.insert(to_index, item)
                self._save()

    def is_favorite(self, path: str) -> bool:
        with self._lock:
            self._ensure_loaded()
            path = str(Path(path).resolve())
            return any(i.get("path") == path for i in self._items)

    def clear(self):
        with self._lock:
            self._items = []
            self._save()
