"""Directory metadata cache — SQLite-backed cache for subdirectory summaries."""
from __future__ import annotations

import random
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from AssetsManager.core.database import DatabaseManager, db_write_lock
from AssetsManager.core.path_resolver import RootIdentity, root_identity

# Stale rows (older than this) are dropped probabilistically during reads.
_PRUNE_AGE_SECONDS = 30 * 86400
_PRUNE_PROBABILITY = 0.01


@dataclass(frozen=True)
class DirCacheEntry:
    item_count: int
    preview_path: str | None
    mtime: float
    scanned_at: float


class DirectoryCache:
    """Cache for directory item_count and preview_path, persisted in per-library SQLite."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        library_root: str | Path | RootIdentity | None = None,
        *,
        session: Any | None = None,
        liveness: Any | None = None,
    ):
        self._conn = conn
        self._session = session
        self._liveness = liveness
        self._library_root_key = (
            root_identity(library_root).map_key if library_root is not None else None
        )
        if library_root is not None:
            self.validate_for(library_root)

    def validate_for(self, library_root: str | Path | RootIdentity) -> None:
        """Reject use for a different library root.

        Raw/unregistered SQLite connections retain legacy compatibility. Managed
        connections are checked against the root captured by ``DatabaseManager``.
        """
        with self._lifecycle_scope():
            requested = root_identity(library_root)
            if self._library_root_key is not None and self._library_root_key != requested.map_key:
                raise ValueError(
                    "DirectoryCache belongs to a different library root: "
                    f"requested {requested.display_path}"
                )
            # Legacy cache API: raw connections remain accepted intentionally.
            DatabaseManager.validate_connection_owner(
                requested, self._conn, allow_unmanaged=True
            )

    def get(self, dir_path: str, mtime: float | None = None) -> DirCacheEntry | None:
        """Return cached entry, or None if missing/stale."""
        with self._lifecycle_scope(), db_write_lock(self._conn):
            # Reads share the connection's write lock (reentrant) so a GUI
            # thread never touches the SQLite connection while a worker is
            # writing cache entries.
            self._maybe_prune()
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
        with self._lifecycle_scope(), db_write_lock(self._conn):
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

    def _maybe_prune(self) -> None:
        """Drop stale rows on a low-probability basis during reads.

        Bounded, self-cleaning cache: rows whose ``scanned_at`` is older than
        ``_PRUNE_AGE_SECONDS`` are removed. Runs on ~1% of ``get()`` calls so
        the table cannot grow without limit while keeping the hot path cheap.
        """
        if random.random() >= _PRUNE_PROBABILITY:
            return
        cutoff = time.time() - _PRUNE_AGE_SECONDS
        outer_transaction = self._conn.in_transaction
        self._conn.execute(
            "DELETE FROM directory_cache WHERE scanned_at < ?", (cutoff,)
        )
        if not outer_transaction:
            self._conn.commit()

    def set(self, dir_path: str, item_count: int, preview_path: str | None, mtime: float) -> None:
        """Store or update a directory cache entry."""
        with self._lifecycle_scope(), db_write_lock(self._conn):
            # The hot path (list_directory / summarize_directories) never runs
            # inside an outer transaction, but if a caller owns one we must
            # not commit it early — leave the commit to the transaction owner.
            outer_transaction = self._conn.in_transaction
            self._conn.execute(
                "INSERT INTO directory_cache (dir_path, item_count, preview_path, mtime, scanned_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(dir_path) DO UPDATE SET "
                "item_count=excluded.item_count, preview_path=excluded.preview_path, "
                "mtime=excluded.mtime, scanned_at=excluded.scanned_at",
                (dir_path, item_count, preview_path, mtime, time.time()),
            )
            if not outer_transaction:
                self._conn.commit()

    def set_batch(self, entries: list[tuple[str, int, str | None, float]]) -> None:
        """Batch insert/update cache entries."""
        now = time.time()
        with self._lifecycle_scope(), db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            self._conn.executemany(
                "INSERT INTO directory_cache (dir_path, item_count, preview_path, mtime, scanned_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(dir_path) DO UPDATE SET "
                "item_count=excluded.item_count, preview_path=excluded.preview_path, "
                "mtime=excluded.mtime, scanned_at=excluded.scanned_at",
                [(path, count, preview, mtime, now) for path, count, preview, mtime in entries],
            )
            if not outer_transaction:
                self._conn.commit()

    def invalidate(self, dir_path: str) -> None:
        """Remove a single cache entry."""
        with self._lifecycle_scope(), db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            self._conn.execute("DELETE FROM directory_cache WHERE dir_path=?", (dir_path,))
            if not outer_transaction:
                self._conn.commit()

    def clear(self) -> None:
        """Remove all cache entries."""
        with self._lifecycle_scope(), db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            self._conn.execute("DELETE FROM directory_cache")
            if not outer_transaction:
                self._conn.commit()

    @contextmanager
    def _lifecycle_scope(self) -> Iterator[None]:
        if self._session is not None:
            with self._session.operation():
                yield
            return
        if self._liveness is not None:
            getattr(self._liveness, "ensure_live")()
        yield
