"""Asset index application service.

Manages the ``assets`` table for fast file lookup and project listing.
The table is populated lazily — entries are added when a directory is
scanned and cached for subsequent queries.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from sqlite3 import Connection

from AssetsManager.repositories.asset_index_repository import AssetIndexEntry, AssetIndexRepository


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
            existing = AssetIndexRepository(conn).count_by_parent(target, root)
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

        AssetIndexRepository(conn).replace_parent_entries(
            target, root, entries, clear_existing=force,
        )
        return len(entries)

    def index_directory_tree(
        self,
        conn: Connection,
        library_root: str | Path,
        dir_path: str | Path,
    ) -> int:
        """Force-index a directory and all nested directories."""
        count = 0
        for current, _, _ in os.walk(dir_path):
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
        return AssetIndexRepository(conn).query_by_parent(root, parent)

    def query_by_extension(
        self,
        conn: Connection,
        library_root: str | Path,
        extension: str,
    ) -> list[AssetIndexEntry]:
        """Return indexed entries with a given extension."""
        root = str(Path(library_root).resolve())
        return AssetIndexRepository(conn).query_by_extension(root, extension)

    def search_by_name(
        self,
        conn: Connection,
        library_root: str | Path,
        query: str,
        limit: int = 200,
    ) -> list[AssetIndexEntry]:
        """Search indexed entries by name substring."""
        root = str(Path(library_root).resolve())
        return AssetIndexRepository(conn).search_by_name(root, query, limit)

    def remove_entry(self, conn: Connection, file_path: str | Path) -> None:
        """Remove a single entry from the index."""
        AssetIndexRepository(conn).delete_entry(str(Path(file_path).resolve()))

    def remove_directory(self, conn: Connection, dir_path: str | Path) -> int:
        """Remove all entries under a directory. Returns count removed."""
        return AssetIndexRepository(conn).delete_path(str(Path(dir_path).resolve()))

    def count(self, conn: Connection, library_root: str | Path) -> int:
        """Return total indexed entries for a library."""
        root = str(Path(library_root).resolve())
        return AssetIndexRepository(conn).count(root)

    def get_entry(self, conn: Connection, file_path: str | Path) -> AssetIndexEntry | None:
        """Return a single entry by path, or None."""
        return AssetIndexRepository(conn).get_entry(str(Path(file_path).resolve()))
