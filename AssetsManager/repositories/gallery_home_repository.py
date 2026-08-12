"""Gallery home projection repository — persisted across process restarts.

The full-library gallery walk takes tens of seconds on very large
libraries; the resulting projection is stored as one row per library
(the single-row ``gallery_home`` table) so a restart serves it instantly.
"""
from __future__ import annotations

from sqlite3 import Connection

from AssetsManager.core.database import db_write_lock


class GalleryHomeRepository:
    """Encapsulate the gallery_home table (single persisted row)."""

    def __init__(self, conn: Connection):
        self._conn = conn

    def get(self) -> tuple[float, str] | None:
        """Return (saved_at, projection_json) or None when not persisted.

        Serialized through the connection's db_write_lock like the write
        operations: the gallery home build thread and the file-event
        invalidation handler share one sqlite3 connection, and concurrent
        access to a single connection surfaces as SQLITE_MISUSE
        (InterfaceError).
        """
        with db_write_lock(self._conn):
            row = self._conn.execute(
                "SELECT saved_at, projection FROM gallery_home WHERE id = 1"
            ).fetchone()
            return (row[0], row[1]) if row else None

    def save(self, saved_at: float, projection_json: str, *, commit: bool = True) -> None:
        """Insert or replace the persisted projection atomically."""
        with db_write_lock(self._conn):
            self._conn.execute(
                "INSERT OR REPLACE INTO gallery_home (id, saved_at, projection) "
                "VALUES (1, ?, ?)",
                (saved_at, projection_json),
            )
            if commit:
                self._conn.commit()

    def delete(self, *, commit: bool = True) -> None:
        """Remove the persisted projection (library changed)."""
        with db_write_lock(self._conn):
            self._conn.execute("DELETE FROM gallery_home WHERE id = 1")
            if commit:
                self._conn.commit()
