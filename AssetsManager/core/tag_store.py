"""Tag store — per-library tags via SQLite (file_tags table in per-library DB).

Tags are stored using canonical names resolved by TagLibrary.
Tags are shared across the library - same DB as file_meta.

This store delegates to TagRepository for all SQL operations.
"""
import threading
import warnings
from pathlib import Path
from sqlite3 import Connection

from AssetsManager.core.database import get_lib_db, db_write_lock
from AssetsManager.core.tag_library import get_library
from AssetsManager.repositories.tag_repository import TagRepository


class TagStore:
    _RESOLVE_CACHE_MAX = 10000

    def __init__(self, library_root: str, db_conn: Connection | None = None):
        self._root = str(Path(library_root).resolve())
        self._db = db_conn or get_lib_db(self._root)
        self._repo = TagRepository(self._db)
        self._resolve_cache: dict[str, str] = {}
        self._resolve_cache_lock = threading.Lock()

    def _resolve(self, filepath: str) -> str:
        """Cached Path.resolve() to avoid repeated filesystem I/O."""
        with self._resolve_cache_lock:
            cached = self._resolve_cache.get(filepath)
            if cached is not None:
                return cached
            if len(self._resolve_cache) >= self._RESOLVE_CACHE_MAX:
                self._resolve_cache.clear()
            resolved = str(Path(filepath).resolve())
            self._resolve_cache[filepath] = resolved
            return resolved

    def get_tags(self, filepath: str) -> list[str]:
        key = self._resolve(filepath)
        return self._repo.get_tags(key)

    def get_tags_for_files(self, filepaths: list[str]) -> dict[str, list[str]]:
        """Return tags keyed by resolved file path for many files at once."""
        keys = [self._resolve(p) for p in filepaths]
        return self._repo.get_tags_for_files(keys)

    def add_tag(self, filepath: str, tag: str):
        tag = get_library().canonical(tag)
        if not tag:
            return
        key = self._resolve(filepath)
        existing = self.get_tags(filepath)
        if tag.lower() in {t.lower() for t in existing}:
            return
        self._repo.add_tag(key, tag)

    def remove_tag(self, filepath: str, tag: str):
        key = self._resolve(filepath)
        existing = self.get_tags(filepath)
        match = next((t for t in existing if t.lower() == tag.lower()), None)
        if match:
            self._repo.remove_tag(key, match)

    def get_files_by_tag(self, tag: str) -> set[str]:
        return set(self._repo.get_files_by_tag(tag))

    def get_all_tags(self) -> list[str]:
        return self._repo.get_all_tags()

    def get_all_tagged_files(self) -> set[str]:
        rows = self._db.execute(
            "SELECT DISTINCT file_path FROM file_tags"
        ).fetchall()
        return {r[0] for r in rows}

    def remove_file(self, filepath: str):
        key = self._resolve(filepath)
        self._repo.remove_file(key)

    def clear_cache(self) -> None:
        """Drop the resolve cache. Called on session close."""
        with self._resolve_cache_lock:
            self._resolve_cache.clear()

    def save(self):
        """Persist pending changes. No-op for SQLite (auto-commit per operation)."""
        with db_write_lock():
            self._repo._conn.commit()


_stores: dict[str, TagStore] = {}
_stores_lock = threading.Lock()


def get_store(library_root: str, db_conn: Connection | None = None) -> TagStore:
    warnings.warn("get_store() is deprecated, use TagService instead", DeprecationWarning, stacklevel=2)
    key = str(Path(library_root).resolve())
    store = _stores.get(key)
    if store is not None:
        return store
    with _stores_lock:
        store = _stores.get(key)
        if store is None:
            store = TagStore(key, db_conn=db_conn)
            _stores[key] = store
        return store
