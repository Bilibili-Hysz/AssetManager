"""Thumbnail cache repository — thin wrapper around thumbnail_cache table."""
from __future__ import annotations

from dataclasses import dataclass
from sqlite3 import Connection
import time
from typing import Callable, Iterable, TypeVar

from AssetsManager.core.database import (
    SQLITE_BUSY_RETRY_ATTEMPTS,
    db_write_lock,
    is_sqlite_busy_error,
    sqlite_busy_retry_delay,
)
from AssetsManager.core.path_resolver import sql_like_descendant_pattern

_T = TypeVar("_T")


@dataclass(frozen=True)
class ThumbnailMetadata:
    cache_key: str
    source_path: str
    source_mtime: float
    source_mtime_ns: int | None
    source_size: int
    baked_size: int
    cache_size: int
    artifact_kind: str
    created_at: float
    last_access: float
    render_profile: str | None = None


class ThumbnailRepository:
    """Encapsulate all thumbnail_cache DB operations."""

    def _write(self, operation: Callable[[], _T], *, commit: bool = True) -> _T:
        """Run one complete metadata write with bounded busy retry."""
        outer_transaction = self._conn.in_transaction
        attempts = 1 if not commit or outer_transaction else SQLITE_BUSY_RETRY_ATTEMPTS
        owns_commit = commit
        for attempt in range(attempts):
            try:
                with db_write_lock(self._conn):
                    result = operation()
                    if owns_commit:
                        self._conn.commit()
                    return result
            except Exception as error:
                if not is_sqlite_busy_error(error) or attempt + 1 >= attempts:
                    raise
                if not outer_transaction:
                    try:
                        with db_write_lock(self._conn):
                            self._conn.rollback()
                    except Exception:
                        pass
                    time.sleep(sqlite_busy_retry_delay(attempt))
                else:
                    raise
        raise AssertionError("unreachable thumbnail write retry state")

    _SELECT_METADATA = (
        "SELECT cache_key, source_path, source_mtime, source_mtime_ns, "
        "source_size, baked_size, cache_size, artifact_kind, created_at, last_access, "
        "render_profile "
        "FROM thumbnail_cache"
    )

    def __init__(self, conn: Connection):
        self._conn = conn

    @staticmethod
    def _metadata(row) -> ThumbnailMetadata:
        return ThumbnailMetadata(
            cache_key=str(row[0]),
            source_path=str(row[1]),
            source_mtime=float(row[2]),
            source_mtime_ns=None if row[3] is None else int(row[3]),
            source_size=int(row[4] or 0),
            baked_size=int(row[5] or 0),
            cache_size=int(row[6] or 0),
            artifact_kind=str(row[7] or "webp"),
            created_at=float(row[8]),
            last_access=float(row[9]),
            render_profile=None if len(row) < 11 or row[10] is None else str(row[10]),
        )

    def get_entry(self, cache_key: str) -> ThumbnailMetadata | None:
        with db_write_lock(self._conn):
            row = self._conn.execute(
                self._SELECT_METADATA + " WHERE cache_key=?", (cache_key,)
            ).fetchone()
            return self._metadata(row) if row else None

    def get_source_mtime(self, cache_key: str) -> float | None:
        """Return cached source mtime, or None if not found."""
        entry = self.get_entry(cache_key)
        return entry.source_mtime if entry else None

    def delete_entry(self, cache_key: str, *, commit: bool = True) -> None:
        self.delete_entries((cache_key,), commit=commit)

    def touch_access(self, cache_key: str, *, commit: bool = True) -> None:
        """Update last_access timestamp."""
        def update() -> None:
            self._conn.execute(
                "UPDATE thumbnail_cache SET last_access=strftime('%s','now') WHERE cache_key=?",
                (cache_key,),
            )

        self._write(update, commit=commit)

    def upsert_entry(
        self,
        cache_key: str,
        source_path: str,
        source_mtime: float,
        source_size: int,
        baked_size: int,
        cache_size: int,
        *,
        source_mtime_ns: int | None = None,
        artifact_kind: str = "webp",
        render_profile: str | None = None,
        commit: bool = True,
    ) -> None:
        """Insert or update one thumbnail cache metadata entry."""
        if artifact_kind not in {"webp", "jpg"}:
            raise ValueError(f"unsupported thumbnail artifact kind: {artifact_kind}")
        def upsert() -> None:
            self._conn.execute(
                "INSERT INTO thumbnail_cache "
                "(cache_key, source_path, source_mtime, source_size, baked_size, "
                "cache_size, source_mtime_ns, artifact_kind, render_profile, last_access) "
                "VALUES (?,?,?,?,?,?,?,?,?,strftime('%s','now')) "
                "ON CONFLICT(cache_key) DO UPDATE SET "
                "source_path=excluded.source_path, "
                "source_mtime=excluded.source_mtime, "
                "source_size=excluded.source_size, "
                "baked_size=excluded.baked_size, "
                "cache_size=excluded.cache_size, "
                "source_mtime_ns=excluded.source_mtime_ns, "
                "artifact_kind=excluded.artifact_kind, "
                "render_profile=excluded.render_profile, "
                "last_access=excluded.last_access",
                (
                    cache_key, source_path, source_mtime, source_size, baked_size,
                    cache_size, source_mtime_ns, artifact_kind, render_profile,
                ),
            )

        self._write(upsert, commit=commit)

    def list_all(self) -> list[tuple[str, str]]:
        """Return all (cache_key, source_path) rows."""
        with db_write_lock(self._conn):
            rows = self._conn.execute(
                "SELECT cache_key, source_path FROM thumbnail_cache"
            ).fetchall()
            return [(r[0], r[1]) for r in rows]

    def list_all_with_metadata(self) -> list[tuple[str, str, float]]:
        """Return legacy three-column metadata rows."""
        with db_write_lock(self._conn):
            rows = self._conn.execute(
                "SELECT cache_key, source_path, source_mtime "
                "FROM thumbnail_cache ORDER BY source_mtime DESC, cache_key"
            ).fetchall()
            return [(row[0], row[1], row[2]) for row in rows]

    def list_metadata(self, *, limit: int | None = None) -> list[ThumbnailMetadata]:
        sql = self._SELECT_METADATA + " ORDER BY last_access ASC, created_at ASC, cache_key ASC"
        params: tuple[int, ...] = ()
        if limit is not None:
            if limit < 1:
                return []
            sql += " LIMIT ?"
            params = (limit,)
        with db_write_lock(self._conn):
            return [self._metadata(row) for row in self._conn.execute(sql, params).fetchall()]

    def list_eviction_candidates(self, limit: int | None = None) -> list[ThumbnailMetadata]:
        return self.list_metadata(limit=limit)

    def delete_entries(self, cache_keys: Iterable[str], *, commit: bool = True) -> int:
        keys = tuple(dict.fromkeys(str(key) for key in cache_keys))
        if not keys:
            return 0

        def delete() -> int:
            placeholders = ", ".join("?" for _ in keys)
            cursor = self._conn.execute(
                f"DELETE FROM thumbnail_cache WHERE cache_key IN ({placeholders})", keys
            )
            return max(cursor.rowcount, 0)

        return self._write(delete, commit=commit)

    def delete_if_matches(
        self,
        metadata: ThumbnailMetadata,
        *,
        commit: bool = True,
    ) -> bool:
        """Delete one row only if its observed metadata is unchanged."""
        def delete() -> bool:
            cursor = self._conn.execute(
                "DELETE FROM thumbnail_cache WHERE cache_key=? "
                "AND source_path=? AND source_mtime=? AND "
                "(source_mtime_ns IS ? OR source_mtime_ns=?) AND source_size=? "
                    "AND baked_size=? AND cache_size=? AND artifact_kind=? "
                    "AND (render_profile IS ? OR render_profile=?) AND created_at=?",

                (
                    metadata.cache_key,
                    metadata.source_path,
                    metadata.source_mtime,
                    metadata.source_mtime_ns,
                    metadata.source_mtime_ns,
                    metadata.source_size,
                    metadata.baked_size,
                    metadata.cache_size,
                    metadata.artifact_kind,
                    metadata.render_profile,
                    metadata.render_profile,
                    metadata.created_at,
                ),
            )
            return cursor.rowcount > 0

        return self._write(delete, commit=commit)

    def delete_by_key(self, cache_key: str, *, commit: bool = True) -> None:
        """Delete entry by key (for orphan cleanup)."""
        self.delete_entries((cache_key,), commit=commit)

    def delete_path(self, source_path: str, *, commit: bool = True) -> list[str]:
        """Delete cache rows for a path and its descendants."""
        descendant_pattern = sql_like_descendant_pattern(source_path)

        def delete() -> list[str]:
            rows = self._conn.execute(
                "SELECT cache_key FROM thumbnail_cache WHERE source_path=? OR source_path LIKE ? ESCAPE '\\'",
                (source_path, descendant_pattern),
            ).fetchall()
            self._conn.execute(
                "DELETE FROM thumbnail_cache WHERE source_path=? OR source_path LIKE ? ESCAPE '\\'",
                (source_path, descendant_pattern),
            )
            return [row[0] for row in rows]

        return self._write(delete, commit=commit)

    def clear_all(self, *, commit: bool = True) -> None:
        """Delete all entries from the thumbnail cache table."""
        self._write(
            lambda: self._conn.execute("DELETE FROM thumbnail_cache"),
            commit=commit,
        )

    def commit(self) -> None:
        with db_write_lock(self._conn):
            self._conn.commit()
