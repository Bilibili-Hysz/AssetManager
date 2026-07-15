"""Asset index application service.

Manages the ``assets`` table for fast file lookup and project listing.
The table is populated lazily — entries are added when a directory is
scanned and cached for subsequent queries.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
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


class AssetIndexService:
    """Populate and query the assets index table."""

    def index_directory(
        self,
        conn: Connection,
        library_root: str | Path,
        dir_path: str | Path,
        *,
        force: bool = False,
    ) -> int:
        """Scan a directory and upsert entries into the assets table.

        Returns the number of entries indexed.
        """
        root = str(Path(library_root).resolve())
        target = str(Path(dir_path).resolve())
        now = time.time()

        if not force:
            existing = conn.execute(
                "SELECT COUNT(*) FROM assets WHERE parent_path=? AND library_root=?",
                (target, root),
            ).fetchone()[0]
            if existing > 0:
                return existing

        entries = []
        try:
            for entry in os.scandir(target):
                ext = os.path.splitext(entry.name)[1].lower() if not entry.is_dir() else ""
                kind = "dir" if entry.is_dir() else "file"
                try:
                    stat = entry.stat(follow_symlinks=False)
                    size = 0 if entry.is_dir() else stat.st_size
                    mtime = stat.st_mtime
                except OSError:
                    size = 0
                    mtime = 0.0
                entries.append((
                    str(Path(entry.path).resolve()),
                    entry.name,
                    ext,
                    kind,
                    size,
                    mtime,
                    target,
                    root,
                    now,
                    now,
                ))
        except OSError:
            return 0

        if not entries:
            return 0

        with db_write_lock():
            conn.executemany(
                "INSERT INTO assets (file_path, name, extension, kind, size, mtime, "
                "parent_path, library_root, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(file_path) DO UPDATE SET "
                "name=excluded.name, extension=excluded.extension, kind=excluded.kind, "
                "size=excluded.size, mtime=excluded.mtime, updated_at=excluded.updated_at",
                entries,
            )
            conn.commit()
        return len(entries)

    def index_directory_tree(
        self,
        conn: Connection,
        library_root: str | Path,
        dir_path: str | Path,
    ) -> int:
        """Index a directory and every descendant directory."""
        count = 0
        for current, _, _ in os.walk(Path(dir_path)):
            count += self.index_directory(conn, library_root, current, force=True)
        return count

    def query_by_parent(
        self,
        conn: Connection,
        library_root: str | Path,
        parent_path: str | Path,
    ) -> list[AssetIndexEntry]:
        """Return indexed entries under a parent directory."""
        root = str(Path(library_root).resolve())
        parent = str(Path(parent_path).resolve())
        rows = conn.execute(
            "SELECT file_path, name, extension, kind, size, mtime, parent_path, library_root "
            "FROM assets WHERE parent_path=? AND library_root=? ORDER BY name",
            (parent, root),
        ).fetchall()
        return [AssetIndexEntry(*r) for r in rows]

    def query_by_extension(
        self,
        conn: Connection,
        library_root: str | Path,
        extension: str,
    ) -> list[AssetIndexEntry]:
        """Return indexed entries with a given extension."""
        root = str(Path(library_root).resolve())
        rows = conn.execute(
            "SELECT file_path, name, extension, kind, size, mtime, parent_path, library_root "
            "FROM assets WHERE extension=? AND library_root=? ORDER BY name",
            (extension.lower(), root),
        ).fetchall()
        return [AssetIndexEntry(*r) for r in rows]

    def search_by_name(
        self,
        conn: Connection,
        library_root: str | Path,
        query: str,
        limit: int = 200,
    ) -> list[AssetIndexEntry]:
        """Search indexed entries by name substring."""
        root = str(Path(library_root).resolve())
        escaped_query = query.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped_query}%"
        rows = conn.execute(
            "SELECT file_path, name, extension, kind, size, mtime, parent_path, library_root "
            "FROM assets WHERE library_root=? AND LOWER(name) LIKE ? ESCAPE '\\' "
            "ORDER BY name LIMIT ?",
            (root, pattern, limit),
        ).fetchall()
        return [AssetIndexEntry(*r) for r in rows]

    def remove_entry(self, conn: Connection, file_path: str | Path) -> None:
        """Remove a single entry from the index."""
        with db_write_lock():
            conn.execute("DELETE FROM assets WHERE file_path=?",
                         (str(Path(file_path).resolve()),))
            conn.commit()

    def remove_directory(self, conn: Connection, dir_path: str | Path) -> int:
        """Remove all entries under a directory. Returns count removed."""
        prefix = str(Path(dir_path).resolve())
        with db_write_lock():
            cur = conn.execute(
                "DELETE FROM assets WHERE file_path=? "
                "OR substr(file_path, 1, length(?) + 1)=?",
                (prefix, prefix, prefix + os.sep),
            )
            conn.commit()
            return cur.rowcount

    def count(self, conn: Connection, library_root: str | Path) -> int:
        """Return total indexed entries for a library."""
        root = str(Path(library_root).resolve())
        row = conn.execute(
            "SELECT COUNT(*) FROM assets WHERE library_root=?", (root,)
        ).fetchone()
        return row[0] if row else 0

    def get_entry(self, conn: Connection, file_path: str | Path) -> AssetIndexEntry | None:
        """Return a single entry by path, or None."""
        row = conn.execute(
            "SELECT file_path, name, extension, kind, size, mtime, parent_path, library_root "
            "FROM assets WHERE file_path=?",
            (str(Path(file_path).resolve()),),
        ).fetchone()
        return AssetIndexEntry(*row) if row else None
