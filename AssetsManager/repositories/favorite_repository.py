"""Repository for principal-scoped library favorites."""
from __future__ import annotations

from sqlite3 import Connection

from AssetsManager.core.database import db_write_lock
from AssetsManager.core.path_resolver import remap_path_subtree, sql_like_descendant_pattern
from AssetsManager.core.schema_defs import LIBRARY_FAVORITES_SCHEMA


class FavoriteRepository:
    """Persist favorite paths in the owning library database."""

    def __init__(self, conn: Connection):
        self._conn = conn

    def init_table(self) -> None:
        """Create the favorites table for explicit legacy/test compatibility."""
        with db_write_lock(self._conn):
            self._conn.executescript(LIBRARY_FAVORITES_SCHEMA)
            self._conn.commit()

    def list_paths(self, owner_key: str, *, limit: int = 500) -> list[str]:
        rows = self._conn.execute(
            "SELECT file_path FROM library_favorites WHERE owner_key=? "
            "ORDER BY created_at DESC, file_path LIMIT ?",
            (owner_key, max(1, min(int(limit), 5000))),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def contains(self, owner_key: str, file_path: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM library_favorites WHERE owner_key=? AND file_path=?",
            (owner_key, file_path),
        ).fetchone() is not None

    def add(self, owner_key: str, file_path: str, *, max_items: int = 500) -> bool:
        """Add a favorite atomically. False if already present; OverflowError at limit."""
        with db_write_lock(self._conn):
            # Single statement: the duplicate check, the per-owner count check
            # and the insert commit together, so concurrent adds cannot slip
            # past the limit (no separate count-then-insert window).
            cursor = self._conn.execute(
                "INSERT INTO library_favorites (owner_key, file_path) "
                "SELECT ?, ? "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM library_favorites WHERE owner_key=? AND file_path=?"
                ") AND (SELECT COUNT(*) FROM library_favorites WHERE owner_key=?) < ?",
                (owner_key, file_path, owner_key, file_path, owner_key, max_items),
            )
            self._conn.commit()
            if cursor.rowcount == 1:
                return True
            if self.contains(owner_key, file_path):
                return False
            raise OverflowError("favorite limit reached")

    def remove(self, owner_key: str, file_path: str) -> bool:
        with db_write_lock(self._conn):
            cursor = self._conn.execute(
                "DELETE FROM library_favorites WHERE owner_key=? AND file_path=?",
                (owner_key, file_path),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def delete_path(self, file_path: str, *, commit: bool = True) -> int:
        """Delete favorites for one path and all descendants, across owners."""
        descendant_pattern = sql_like_descendant_pattern(file_path)
        with db_write_lock(self._conn):
            cursor = self._conn.execute(
                "DELETE FROM library_favorites "
                "WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                (file_path, descendant_pattern),
            )
            if commit:
                self._conn.commit()
            return cursor.rowcount

    def migrate_path(self, old_path: str, new_path: str, *, commit: bool = True) -> int:
        """Remap favorites for a moved path and its descendants."""
        descendant_pattern = sql_like_descendant_pattern(old_path)
        with db_write_lock(self._conn):
            rows = self._conn.execute(
                "SELECT owner_key, file_path, created_at FROM library_favorites "
                "WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                (old_path, descendant_pattern),
            ).fetchall()
            for owner_key, file_path, created_at in rows:
                mapped = remap_path_subtree(old_path, new_path, str(file_path))
                self._conn.execute(
                    "INSERT OR IGNORE INTO library_favorites "
                    "(owner_key, file_path, created_at) VALUES (?, ?, ?)",
                    (owner_key, mapped, created_at),
                )
            if rows:
                self._conn.execute(
                    "DELETE FROM library_favorites "
                    "WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                    (old_path, descendant_pattern),
                )
            if commit:
                self._conn.commit()
            return len(rows)


__all__ = ["FavoriteRepository"]
