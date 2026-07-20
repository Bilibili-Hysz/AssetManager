"""Persistence access for the lazily populated assets index."""
from __future__ import annotations

import os
from dataclasses import dataclass
from sqlite3 import Connection

from AssetsManager.core.database import db_write_lock


@dataclass(frozen=True)
class AssetIndexEntry:
    file_path: str
    name: str
    extension: str
    kind: str
    size: int
    mtime: float
    parent_path: str
    library_root: str


class AssetIndexRepository:
    """Encapsulate SQL access to the ``assets`` index table."""

    def __init__(self, conn: Connection):
        self._conn = conn

    def count_by_parent(self, parent_path: str, library_root: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM assets WHERE parent_path=? AND library_root=?",
            (parent_path, library_root),
        ).fetchone()
        return int(row[0]) if row else 0

    def replace_parent_entries(
        self,
        parent_path: str,
        library_root: str,
        entries: list[tuple[str, str, str, str, int, float, str, str, float, float]],
        *,
        clear_existing: bool,
    ) -> None:
        with db_write_lock(self._conn):
            if clear_existing:
                self._conn.execute(
                    "DELETE FROM assets WHERE parent_path=? AND library_root=?",
                    (parent_path, library_root),
                )
            if entries:
                self._conn.executemany(
                    "INSERT INTO assets (file_path, name, extension, kind, size, mtime, "
                    "parent_path, library_root, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(file_path) DO UPDATE SET "
                    "name=excluded.name, extension=excluded.extension, kind=excluded.kind, "
                    "size=excluded.size, mtime=excluded.mtime, updated_at=excluded.updated_at",
                    entries,
                )
            self._conn.commit()

    def query_by_parent(self, library_root: str, parent_path: str) -> list[AssetIndexEntry]:
        return self._entries(
            "FROM assets WHERE parent_path=? AND library_root=? ORDER BY name",
            (parent_path, library_root),
        )

    def query_by_extension(self, library_root: str, extension: str) -> list[AssetIndexEntry]:
        return self._entries(
            "FROM assets WHERE extension=? AND library_root=? ORDER BY name",
            (extension.lower(), library_root),
        )

    def search_by_name(self, library_root: str, query: str, limit: int) -> list[AssetIndexEntry]:
        escaped = query.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return self._entries(
            "FROM assets WHERE library_root=? AND LOWER(name) LIKE ? ESCAPE '\\' "
            "ORDER BY name LIMIT ?",
            (library_root, f"%{escaped}%", limit),
        )

    def delete_entry(self, file_path: str, *, commit: bool = True) -> int:
        with db_write_lock(self._conn):
            cur = self._conn.execute("DELETE FROM assets WHERE file_path=?", (file_path,))
            if commit:
                self._conn.commit()
            return cur.rowcount

    def delete_path(self, path: str, *, commit: bool = True) -> int:
        escaped = path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        separator = "\\" if "\\" in path else "/" if "/" in path else os.sep
        subtree = escaped + separator.replace("\\", "\\\\") + "%"
        with db_write_lock(self._conn):
            cur = self._conn.execute(
                "DELETE FROM assets WHERE file_path=? OR file_path LIKE ? ESCAPE '\\' "
                "OR parent_path=? OR parent_path LIKE ? ESCAPE '\\'",
                (path, subtree, path, subtree),
            )
            if commit:
                self._conn.commit()
            return cur.rowcount

    def count(self, library_root: str) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM assets WHERE library_root=?", (library_root,)).fetchone()
        return int(row[0]) if row else 0

    def get_entry(self, file_path: str) -> AssetIndexEntry | None:
        entries = self._entries("FROM assets WHERE file_path=?", (file_path,))
        return entries[0] if entries else None

    def _entries(self, clause: str, params: tuple[object, ...]) -> list[AssetIndexEntry]:
        rows = self._conn.execute(
            "SELECT file_path, name, extension, kind, size, mtime, parent_path, library_root " + clause,
            params,
        ).fetchall()
        return [AssetIndexEntry(*row) for row in rows]
