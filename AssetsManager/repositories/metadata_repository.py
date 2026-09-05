from __future__ import annotations

import json
import logging
from pathlib import Path

from AssetsManager.core.database import db_write_lock, locked_read
from AssetsManager.core.path_resolver import (
    path_key_separator,
    remap_path_subtree,
    root_identity,
    sql_like_descendant_pattern,
)
from AssetsManager.repositories._common import (
    _SessionBoundRepository,
    _repository_operation,
)

_log = logging.getLogger(__name__)


class MetadataRepository(_SessionBoundRepository):
    """Encapsulates all file_meta database operations.

    Raw ``MetadataRepository(conn)`` remains the explicit legacy adapter.
    Canonical callers should use :meth:`for_session`, which binds connection
    ownership, path containment, and repository lifetime to one LibrarySession.
    """

    def _path_key(self, file_path: str | Path) -> str:
        """Return a canonical key and enforce bound-root containment.

        Keys are resolve-only (no normcase), matching ProjectData._key: a
        normcase would lowercase drive letters on Windows and strand rows
        written by the other component (see project_data.py::_key notes).
        """
        if self._library_root is None:
            return str(file_path)
        target = Path(file_path).resolve()
        if not target.is_relative_to(self._library_root):
            raise ValueError(
                f"metadata path must be under library_root: {target} "
                f"(root {self._library_root})"
            )
        return str(target)

    def _path_keys(self, file_paths: list[str]) -> list[str]:
        return [self._path_key(file_path) for file_path in file_paths]

    def _root_path_key(self, library_path: str | Path) -> str:
        if self._library_root is None:
            return str(library_path)
        identity = root_identity(library_path, strict=False)
        if identity.map_key != self._library_root_key:
            raise ValueError(
                "metadata library_path does not match the bound library root"
            )
        return str(self._library_root)

    # ── Notes ────────────────────────────────────────────────────

    @_repository_operation
    @locked_read
    def get_notes(self, file_path: str) -> str:
        """Return notes for a file path."""
        file_path = self._path_key(file_path)
        row = self._conn.execute(
            "SELECT notes FROM file_meta WHERE file_path=?",
            (file_path,),
        ).fetchone()
        return row[0] if row else ""

    @_repository_operation
    @locked_read
    def get_notes_and_urls(self, file_path: str) -> tuple[str, list[str]]:
        """Return notes and URLs for a file path from one metadata row."""
        file_path = self._path_key(file_path)
        row = self._conn.execute(
            "SELECT notes, urls FROM file_meta WHERE file_path=?",
            (file_path,),
        ).fetchone()
        if not row:
            return ("", [])
        return (row[0] or "", self._decode_urls(file_path, row[1]))

    @_repository_operation
    @locked_read
    def get_notes_urls_rating(
        self, file_path: str
    ) -> tuple[str, list[str], int | None]:
        """Return notes, URLs, and rating from one metadata row.

        Single-row variant of :meth:`get_notes_and_urls` that also carries
        the v37 rating column, so metadata reads never pay a second
        file_meta query for the rating. A missing row means unrated.
        """
        file_path = self._path_key(file_path)
        row = self._conn.execute(
            "SELECT notes, urls, rating FROM file_meta WHERE file_path=?",
            (file_path,),
        ).fetchone()
        if not row:
            return ("", [], None)
        rating = row[2]
        return (
            row[0] or "",
            self._decode_urls(file_path, row[1]),
            int(rating) if rating is not None else None,
        )

    @_repository_operation
    @locked_read
    def list_file_metadata(self) -> list[tuple[str, str, list[str]]]:
        """Return all file metadata rows for export and maintenance reads."""
        rows = self._conn.execute(
            "SELECT file_path, notes, urls FROM file_meta ORDER BY file_path"
        ).fetchall()
        return [
            (str(file_path), notes or "", self._decode_urls(str(file_path), urls))
            for file_path, notes, urls in rows
        ]

    @_repository_operation
    def set_notes(self, file_path: str, notes: str) -> None:
        """Set notes for a file path."""
        file_path = self._path_key(file_path)
        with self._write_scope("set_notes"):
            self._conn.execute(
                "INSERT INTO file_meta (file_path, notes) VALUES (?, ?) "
                "ON CONFLICT(file_path) DO UPDATE SET notes=excluded.notes",
                (file_path, notes),
            )

    # ── URLs ─────────────────────────────────────────────────────

    @_repository_operation
    @locked_read
    def get_urls(self, file_path: str) -> list[str]:
        """Return URLs for a file path."""
        file_path = self._path_key(file_path)
        row = self._conn.execute(
            "SELECT urls FROM file_meta WHERE file_path=?",
            (file_path,),
        ).fetchone()
        if not row:
            return []
        return self._decode_urls(file_path, row[0])

    @staticmethod
    def _decode_urls(file_path: str, value: str | None) -> list[str]:
        try:
            result = json.loads(value or "[]")
            if not isinstance(result, list):
                _log.warning("URLs JSON is not a list for %s: %r", file_path, value)
                return []
            return result
        except (json.JSONDecodeError, TypeError):
            _log.warning("Malformed URLs JSON for %s: %r", file_path, value)
            return []

    @_repository_operation
    def set_urls(self, file_path: str, urls: list[str]) -> None:
        """Set URLs for a file path."""
        file_path = self._path_key(file_path)
        with self._write_scope("set_urls"):
            data = json.dumps(urls, ensure_ascii=False)
            self._conn.execute(
                "INSERT INTO file_meta (file_path, urls) VALUES (?, ?) "
                "ON CONFLICT(file_path) DO UPDATE SET urls=excluded.urls",
                (file_path, data),
            )

    @_repository_operation
    def add_url(self, file_path: str, url: str) -> list[str] | None:
        """Add a URL atomically via a single JSON-append statement.

        The append happens inside one UPDATE, so concurrent writers on
        *different* connections cannot lose each other's entries (the old
        read-modify-write cycle was last-writer-wins across connections).
        Duplicates are suppressed with a NOT EXISTS guard; a missing row is
        inserted on first use.
        """
        file_path = self._path_key(file_path)
        with self._write_scope("add_url"):
            cur = self._conn.execute(
                "UPDATE file_meta "
                "SET urls = json_insert("
                "  CASE WHEN json_valid(urls) THEN urls ELSE '[]' END,"
                "  '$[#]', ?) "
                "WHERE file_path = ? "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM json_each("
                "    CASE WHEN json_valid(file_meta.urls) "
                "         THEN file_meta.urls ELSE '[]' END"
                "  ) WHERE value = ?)",
                (url, file_path, url),
            )
            if cur.rowcount == 1:
                return self.get_urls(file_path)
            row = self._conn.execute(
                "SELECT 1 FROM file_meta WHERE file_path = ?", (file_path,)
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO file_meta (file_path, urls) VALUES (?, ?)",
                    (file_path, json.dumps([url], ensure_ascii=False)),
                )
                return [url]
            # The row exists and the URL is already present.
            return None

    @_repository_operation
    def remove_url(self, file_path: str, url: str) -> list[str] | None:
        """Remove a URL under the process write lock. Returns updated URLs if changed.

        Concurrency note: same non-atomic read-modify-write caveat as
        :meth:`add_url` — only atomic per connection, not across connections.
        """
        file_path = self._path_key(file_path)
        with self._write_scope("remove_url"):
            urls = self.get_urls(file_path)
            if url not in urls:
                return None
            urls.remove(url)
            data = json.dumps(urls, ensure_ascii=False)
            self._conn.execute(
                "INSERT INTO file_meta (file_path, urls) VALUES (?, ?) "
                "ON CONFLICT(file_path) DO UPDATE SET urls=excluded.urls",
                (file_path, data),
            )
            return urls

    # ── Size cache ───────────────────────────────────────────────

    @_repository_operation
    @locked_read
    def get_cached_size(self, file_path: str) -> tuple[int, float] | None:
        """Return (cached_size, cached_mtime) or None if not cached."""
        file_path = self._path_key(file_path)
        row = self._conn.execute(
            "SELECT cached_size, cached_mtime FROM file_meta "
            "WHERE file_path=? AND cached_size IS NOT NULL",
            (file_path,),
        ).fetchone()
        if row and row[0] is not None and row[1] is not None:
            return (row[0], row[1])
        return None

    @_repository_operation
    def set_cached_size(self, file_path: str, size: int, mtime: float) -> None:
        """Cache a directory size."""
        file_path = self._path_key(file_path)
        with self._write_scope("set_cached_size"):
            self._conn.execute(
                "INSERT INTO file_meta (file_path, cached_size, cached_mtime) VALUES (?, ?, ?) "
                "ON CONFLICT(file_path) DO UPDATE SET "
                "cached_size=excluded.cached_size, cached_mtime=excluded.cached_mtime",
                (file_path, size, mtime),
            )

    @_repository_operation
    @locked_read
    def get_cached_file_count(self, file_path: str) -> int | None:
        """Return cached file count, or None if not cached or stale.

        Rows without a ``cached_file_count_mtime`` stamp (all pre-v35 rows)
        are treated as a cache miss, matching the :meth:`get_cached_size`
        contract that requires both value and mtime.
        """
        file_path = self._path_key(file_path)
        row = self._conn.execute(
            "SELECT cached_file_count FROM file_meta "
            "WHERE file_path=? AND cached_file_count IS NOT NULL "
            "AND cached_file_count_mtime IS NOT NULL",
            (file_path,),
        ).fetchone()
        if row and row[0] is not None:
            return int(row[0])
        return None

    @_repository_operation
    @locked_read
    def get_cached_file_count_with_mtime(
        self, file_path: str
    ) -> tuple[int, float] | None:
        """Return (cached_file_count, cached_file_count_mtime) or None.

        Mirrors :meth:`get_cached_size`: callers compare the stored mtime
        against the live source-directory mtime before trusting the count.
        Rows missing either value are a cache miss.
        """
        file_path = self._path_key(file_path)
        row = self._conn.execute(
            "SELECT cached_file_count, cached_file_count_mtime FROM file_meta "
            "WHERE file_path=? AND cached_file_count IS NOT NULL",
            (file_path,),
        ).fetchone()
        if row and row[0] is not None and row[1] is not None:
            return (int(row[0]), float(row[1]))
        return None

    @_repository_operation
    def set_cached_file_count(
        self, file_path: str, count: int, mtime: float | None = None
    ) -> None:
        """Cache a file count with the source directory's mtime.

        ``mtime`` is the directory ``st_mtime`` observed when the count was
        computed; ``None`` records an always-stale entry (reads treat it as
        a miss and recompute).
        """
        file_path = self._path_key(file_path)
        with self._write_scope("set_cached_file_count"):
            self._conn.execute(
                "INSERT INTO file_meta (file_path, cached_file_count, cached_file_count_mtime) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(file_path) DO UPDATE SET "
                "cached_file_count=excluded.cached_file_count, "
                "cached_file_count_mtime=excluded.cached_file_count_mtime",
                (file_path, count, mtime),
            )

    @_repository_operation
    @locked_read
    def batch_get_cached_file_counts(self, file_paths: list[str]) -> dict[str, int]:
        """Return {path: count} for directories with mtime-stamped counts."""
        if not file_paths:
            return {}
        file_paths = self._path_keys(file_paths)
        results: dict[str, int] = {}
        # Chunk to avoid SQLite variable limit
        chunk_size = 900
        for i in range(0, len(file_paths), chunk_size):
            chunk = file_paths[i:i + chunk_size]
            placeholders = ",".join("?" * len(chunk))
            rows = self._conn.execute(
                f"SELECT file_path, cached_file_count FROM file_meta "
                f"WHERE file_path IN ({placeholders}) AND cached_file_count IS NOT NULL "
                f"AND cached_file_count_mtime IS NOT NULL",
                chunk,
            ).fetchall()
            for r in rows:
                if r[1] is not None:
                    results[r[0]] = int(r[1])
        return results

    @_repository_operation
    @locked_read
    def batch_get_cached_file_counts_with_mtime(
        self, file_paths: list[str]
    ) -> dict[str, tuple[int, float]]:
        """Return {path: (count, mtime)} for mtime-stamped cached counts.

        Batch form of :meth:`get_cached_file_count_with_mtime`; entries
        without a stored mtime are omitted so callers recompute them.
        """
        if not file_paths:
            return {}
        file_paths = self._path_keys(file_paths)
        results: dict[str, tuple[int, float]] = {}
        chunk_size = 900
        for i in range(0, len(file_paths), chunk_size):
            chunk = file_paths[i:i + chunk_size]
            placeholders = ",".join("?" * len(chunk))
            rows = self._conn.execute(
                f"SELECT file_path, cached_file_count, cached_file_count_mtime "
                f"FROM file_meta "
                f"WHERE file_path IN ({placeholders}) AND cached_file_count IS NOT NULL",
                chunk,
            ).fetchall()
            for r in rows:
                if r[1] is not None and r[2] is not None:
                    results[r[0]] = (int(r[1]), float(r[2]))
        return results

    @_repository_operation
    def batch_set_cached_file_counts(
        self, entries: dict[str, int | tuple[int, float]]
    ) -> None:
        """Cache file counts for multiple directories in a single transaction.

        Values are either a bare count (recorded without an mtime and
        therefore always treated as stale on read) or a ``(count,
        dir_mtime)`` pair stamped with the source directory's mtime.
        """
        if not entries:
            return
        entries = {self._path_key(path): value for path, value in entries.items()}
        rows = [
            (path, value[0], value[1])
            if isinstance(value, tuple)
            else (path, value, None)
            for path, value in entries.items()
        ]
        with self._write_scope("batch_set_cached_file_counts"):
            self._conn.executemany(
                "INSERT INTO file_meta (file_path, cached_file_count, cached_file_count_mtime) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(file_path) DO UPDATE SET "
                "cached_file_count=excluded.cached_file_count, "
                "cached_file_count_mtime=excluded.cached_file_count_mtime",
                rows,
            )

    # ── Stats ────────────────────────────────────────────────────

    @_repository_operation
    @locked_read
    def get_cached_stats(self, file_paths: list[str]) -> dict[str, tuple[int, float]]:
        """Return {path: (cached_size, cached_mtime)} for given paths."""
        if not file_paths:
            return {}
        file_paths = self._path_keys(file_paths)
        results: dict[str, tuple[int, float]] = {}
        chunk_size = 900
        for i in range(0, len(file_paths), chunk_size):
            chunk = file_paths[i:i + chunk_size]
            placeholders = ",".join("?" * len(chunk))
            rows = self._conn.execute(
                f"SELECT file_path, cached_size, cached_mtime FROM file_meta "
                f"WHERE file_path IN ({placeholders})",
                chunk,
            ).fetchall()
            results.update({r[0]: (r[1], r[2]) for r in rows if r[1] is not None and r[2] is not None})
        return results

    @_repository_operation
    @locked_read
    def get_library_total_size(self, library_path: str) -> int:
        """Return total size from library_stats, or 0 if not available."""
        library_path = self._root_path_key(library_path)
        row = self._conn.execute(
            "SELECT total_size FROM library_stats WHERE library_path=?",
            (library_path,),
        ).fetchone()
        return (row[0] or 0) if row else 0

    @_repository_operation
    def set_library_total_size(self, library_path: str, size: int) -> None:
        """Update total size without replacing the rest of the stats row."""
        library_path = self._root_path_key(library_path)
        with self._write_scope("set_library_total_size"):
            columns = {
                str(row[1])
                for row in self._conn.execute("PRAGMA table_info(library_stats)")
            }
            if "updated_at" in columns:
                self._conn.execute(
                    "INSERT INTO library_stats (library_path, total_size, updated_at) "
                    "VALUES (?, ?, strftime('%s','now')) "
                    "ON CONFLICT(library_path) DO UPDATE SET "
                    "total_size=excluded.total_size, updated_at=excluded.updated_at",
                    (library_path, size),
                )
            else:
                # Legacy/minimal fixtures may predate the timestamp column.
                # Preserve the same non-destructive upsert contract there.
                self._conn.execute(
                    "INSERT INTO library_stats (library_path, total_size) VALUES (?, ?) "
                    "ON CONFLICT(library_path) DO UPDATE SET total_size=excluded.total_size",
                    (library_path, size),
                )

    # ── Invalidation ─────────────────────────────────────────────

    @_repository_operation
    def invalidate_size_cache(self, file_path: str) -> None:
        """Clear cached size/count for a path and its children."""
        file_path = self._path_key(file_path)
        descendant_pattern = sql_like_descendant_pattern(file_path)
        with self._write_scope("invalidate_size_cache"):
            self._conn.execute(
                "UPDATE file_meta SET cached_size=NULL, cached_mtime=NULL, "
                "cached_file_count=NULL, cached_file_count_mtime=NULL "
                "WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                (file_path, descendant_pattern),
            )

    @_repository_operation
    def delete_path(self, file_path: str, *, commit: bool = True) -> int:
        """Delete metadata for a path and its descendants."""
        file_path = self._path_key(file_path)
        descendant_pattern = sql_like_descendant_pattern(file_path)

        def delete_rows() -> int:
            cur = self._conn.execute(
                "DELETE FROM file_meta WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                (file_path, descendant_pattern),
            )
            return cur.rowcount

        if commit:
            with self._write_scope("delete_path"):
                return delete_rows()
        with db_write_lock(self._conn):
            return delete_rows()

    # ── Rating ──────────────────────────────────────────────────

    @_repository_operation
    @locked_read
    def get_rating(self, file_path: str) -> int | None:
        """Return the 0-5 rating for a file path, or None when unrated."""
        file_path = self._path_key(file_path)
        row = self._conn.execute(
            "SELECT rating FROM file_meta WHERE file_path=?",
            (file_path,),
        ).fetchone()
        if not row or row[0] is None:
            return None
        return int(row[0])

    @_repository_operation
    def set_rating(self, file_path: str, rating: int | None) -> None:
        """Set (or clear) the 0-5 rating for a file path.

        ``rating=None`` clears the rating back to unrated (NULL); a missing
        row needs no write because NULL is already the default state.
        Values outside 0-5 raise :class:`ValueError`.
        """
        if rating is not None and not (
            isinstance(rating, int)
            and not isinstance(rating, bool)
            and 0 <= rating <= 5
        ):
            raise ValueError(
                f"rating must be an integer 0-5 or None, got {rating!r}"
            )
        file_path = self._path_key(file_path)
        with self._write_scope("set_rating"):
            if rating is None:
                self._conn.execute(
                    "UPDATE file_meta SET rating=NULL WHERE file_path=?",
                    (file_path,),
                )
            else:
                self._conn.execute(
                    "INSERT INTO file_meta (file_path, rating) VALUES (?, ?) "
                    "ON CONFLICT(file_path) DO UPDATE SET rating=excluded.rating",
                    (file_path, rating),
                )

    # ── Migration ────────────────────────────────────────────────

    @_repository_operation
    def migrate_path(self, old_path: str, new_path: str) -> int:
        """Move metadata from old_path to new_path. Returns rows affected."""
        old_path = self._path_key(old_path)
        new_path = self._path_key(new_path)
        if old_path == new_path:
            return 0
        if new_path.startswith(old_path + path_key_separator(old_path)):
            raise ValueError("metadata migration target cannot be inside source subtree")
        descendant_pattern = sql_like_descendant_pattern(old_path)
        with self._write_scope("migrate_path"):
            rows = self._conn.execute(
                "SELECT file_path, notes, cached_size, cached_mtime, cached_file_count, urls, rating "
                "FROM file_meta WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                (old_path, descendant_pattern),
            ).fetchall()
            count = 0
            for path, notes, cached_size, cached_mtime, cached_file_count, urls, rating in rows:
                mapped = remap_path_subtree(old_path, new_path, path)
                self._conn.execute(
                    "INSERT INTO file_meta "
                    "(file_path, notes, cached_size, cached_mtime, cached_file_count, urls, rating) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(file_path) DO UPDATE SET "
                    "notes=CASE WHEN excluded.notes!='' THEN excluded.notes ELSE file_meta.notes END, "
                    "cached_size=COALESCE(excluded.cached_size, file_meta.cached_size), "
                    "cached_mtime=COALESCE(excluded.cached_mtime, file_meta.cached_mtime), "
                    "cached_file_count=COALESCE(excluded.cached_file_count, file_meta.cached_file_count), "
                    "urls=CASE WHEN excluded.urls!='[]' THEN excluded.urls ELSE file_meta.urls END, "
                    "rating=COALESCE(excluded.rating, file_meta.rating)",
                    (mapped, notes, cached_size, cached_mtime, cached_file_count, urls, rating),
                )
                count += 1
            if rows:
                self._conn.execute(
                    "DELETE FROM file_meta WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                    (old_path, descendant_pattern),
                )
            return count
