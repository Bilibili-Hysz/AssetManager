"""Thumbnail cache repository — thin wrapper around thumbnail_cache table."""
from __future__ import annotations

import os
from sqlite3 import Connection

from AssetsManager.core.database import db_write_lock


class ThumbnailRepository:
    """Encapsulate all thumbnail_cache DB operations."""

    def __init__(self, conn: Connection):
        self._conn = conn

    def get_source_mtime(self, cache_key: str) -> float | None:
        """Return cached source mtime, or None if not found."""
        row = self._conn.execute(
            "SELECT source_mtime FROM thumbnail_cache WHERE cache_key=?",
            (cache_key,),
        ).fetchone()
        return row[0] if row else None

    def delete_entry(self, cache_key: str) -> None:
        """Delete a single cache entry."""
        with db_write_lock(self._conn):
            self._conn.execute("DELETE FROM thumbnail_cache WHERE cache_key=?", (cache_key,))
            self._conn.commit()

    def touch_access(self, cache_key: str) -> None:
        """Update last_access timestamp."""
        with db_write_lock(self._conn):
            self._conn.execute(
                "UPDATE thumbnail_cache SET last_access=strftime('%s','now') WHERE cache_key=?",
                (cache_key,),
            )
            self._conn.commit()

    def upsert_entry(
        self,
        cache_key: str,
        source_path: str,
        source_mtime: float,
        source_size: int,
        baked_size: int,
        cache_size: int,
    ) -> None:
        """Insert or update a thumbnail cache entry."""
        with db_write_lock(self._conn):
            self._conn.execute(
                "INSERT OR REPLACE INTO thumbnail_cache "
                "(cache_key, source_path, source_mtime, source_size, baked_size, cache_size, last_access) "
                "VALUES (?,?,?,?,?,?,strftime('%s','now'))",
                (cache_key, source_path, source_mtime, source_size, baked_size, cache_size),
            )
            self._conn.commit()

    def list_all(self) -> list[tuple[str, str]]:
        """Return all (cache_key, source_path) rows."""
        rows = self._conn.execute(
            "SELECT cache_key, source_path FROM thumbnail_cache"
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def list_all_with_metadata(self) -> list[tuple[str, str, float]]:
        """Return all cache rows needed for baked-thumbnail validation."""
        rows = self._conn.execute(
            "SELECT cache_key, source_path, source_mtime "
            "FROM thumbnail_cache ORDER BY source_mtime DESC, cache_key"
        ).fetchall()
        return [(row[0], row[1], row[2]) for row in rows]

    def delete_by_key(self, cache_key: str) -> None:
        """Delete entry by cache key (for orphan cleanup)."""
        with db_write_lock(self._conn):
            self._conn.execute("DELETE FROM thumbnail_cache WHERE cache_key=?", (cache_key,))
            self._conn.commit()

    def delete_path(self, source_path: str) -> list[str]:
        """Delete cache rows for a path and its descendants, returning keys."""
        escaped = source_path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with db_write_lock(self._conn):
            rows = self._conn.execute(
                "SELECT cache_key FROM thumbnail_cache WHERE source_path=? OR source_path LIKE ? ESCAPE '\\'",
                (source_path, escaped + os.sep.replace("\\", "\\\\") + "%"),
            ).fetchall()
            self._conn.execute(
                "DELETE FROM thumbnail_cache WHERE source_path=? OR source_path LIKE ? ESCAPE '\\'",
                (source_path, escaped + os.sep.replace("\\", "\\\\") + "%"),
            )
            self._conn.commit()
            return [row[0] for row in rows]

    def clear_all(self) -> None:
        """Delete all entries from the thumbnail cache table."""
        with db_write_lock(self._conn):
            self._conn.execute("DELETE FROM thumbnail_cache")
            self._conn.commit()

    def commit(self) -> None:
        """Commit pending changes."""
        self._conn.commit()
