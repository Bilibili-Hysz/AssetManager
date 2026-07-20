"""Directory metadata cache — SQLite-backed cache for subdirectory summaries."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from AssetsManager.core.database import db_write_lock


@dataclass(frozen=True)
class DirCacheEntry:
    item_count: int
    preview_path: str | None
    mtime: float
    scanned_at: float


class DirectoryCache:
    """Cache for directory item_count and preview_path, persisted in per-library SQLite."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def get(self, dir_path: str, mtime: float | None = None) -> DirCacheEntry | None:
        """Return cached entry, or None if missing/stale."""
        row = self._conn.execute(
            "SELECT item_count, preview_path, mtime, scanned_at FROM directory_cache WHERE dir_path=?",
            (dir_path,),
        ).fetchone()
        if row is None:
            return None
        entry = DirCacheEntry(item_count=row[0], preview_path=row[1], mtime=row[2], scanned_at=row[3])
        if mtime is not None and entry.mtime != mtime:
            return None
        return entry

    def get_batch(self, dir_paths: list[str]) -> dict[str, DirCacheEntry]:
        """Return cached entries for paths with bounded SQLite parameter batches."""
        entries: dict[str, DirCacheEntry] = {}
        for offset in range(0, len(dir_paths), 500):
            paths = dir_paths[offset:offset + 500]
            if not paths:
                continue
            placeholders = ", ".join("?" for _ in paths)
            rows = self._conn.execute(
                "SELECT dir_path, item_count, preview_path, mtime, scanned_at "
                f"FROM directory_cache WHERE dir_path IN ({placeholders})",
                paths,
            ).fetchall()
            for path, item_count, preview_path, mtime, scanned_at in rows:
                entries[path] = DirCacheEntry(item_count, preview_path, mtime, scanned_at)
        return entries

    def set(self, dir_path: str, item_count: int, preview_path: str | None, mtime: float) -> None:
        """Store or update a directory cache entry."""
        with db_write_lock(self._conn):
            self._conn.execute(
                "INSERT INTO directory_cache (dir_path, item_count, preview_path, mtime, scanned_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(dir_path) DO UPDATE SET "
                "item_count=excluded.item_count, preview_path=excluded.preview_path, "
                "mtime=excluded.mtime, scanned_at=excluded.scanned_at",
                (dir_path, item_count, preview_path, mtime, time.time()),
            )
            self._conn.commit()

    def set_batch(self, entries: list[tuple[str, int, str | None, float]]) -> None:
        """Batch insert/update cache entries."""
        now = time.time()
        with db_write_lock(self._conn):
            self._conn.executemany(
                "INSERT INTO directory_cache (dir_path, item_count, preview_path, mtime, scanned_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(dir_path) DO UPDATE SET "
                "item_count=excluded.item_count, preview_path=excluded.preview_path, "
                "mtime=excluded.mtime, scanned_at=excluded.scanned_at",
                [(path, count, preview, mtime, now) for path, count, preview, mtime in entries],
            )
            self._conn.commit()

    def invalidate(self, dir_path: str) -> None:
        """Remove a single cache entry."""
        with db_write_lock(self._conn):
            self._conn.execute("DELETE FROM directory_cache WHERE dir_path=?", (dir_path,))
            self._conn.commit()

    def clear(self) -> None:
        """Remove all cache entries."""
        with db_write_lock(self._conn):
            self._conn.execute("DELETE FROM directory_cache")
            self._conn.commit()
