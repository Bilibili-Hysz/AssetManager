"""Metadata repository — CRUD operations for the file_meta table."""
from __future__ import annotations

import json
import logging
import os
from sqlite3 import Connection

from AssetsManager.core.database import db_write_lock

_log = logging.getLogger(__name__)


class MetadataRepository:
    """Encapsulates all file_meta database operations.

    This repository provides a clean interface for metadata CRUD without
    exposing raw SQL to application services.
    """

    def __init__(self, conn: Connection):
        self._conn = conn

    # ── Notes ────────────────────────────────────────────────────

    def get_notes(self, file_path: str) -> str:
        """Return notes for a file path."""
        row = self._conn.execute(
            "SELECT notes FROM file_meta WHERE file_path=?",
            (file_path,),
        ).fetchone()
        return row[0] if row else ""

    def get_notes_and_urls(self, file_path: str) -> tuple[str, list[str]]:
        """Return notes and URLs for a file path from one metadata row."""
        row = self._conn.execute(
            "SELECT notes, urls FROM file_meta WHERE file_path=?",
            (file_path,),
        ).fetchone()
        if not row:
            return ("", [])
        return (row[0] or "", self._decode_urls(file_path, row[1]))

    def set_notes(self, file_path: str, notes: str) -> None:
        """Set notes for a file path."""
        with db_write_lock(self._conn):
            self._conn.execute(
                "INSERT INTO file_meta (file_path, notes) VALUES (?, ?) "
                "ON CONFLICT(file_path) DO UPDATE SET notes=excluded.notes",
                (file_path, notes),
            )
            self._conn.commit()

    # ── URLs ─────────────────────────────────────────────────────

    def get_urls(self, file_path: str) -> list[str]:
        """Return URLs for a file path."""
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

    def set_urls(self, file_path: str, urls: list[str]) -> None:
        """Set URLs for a file path."""
        with db_write_lock(self._conn):
            data = json.dumps(urls, ensure_ascii=False)
            self._conn.execute(
                "INSERT INTO file_meta (file_path, urls) VALUES (?, ?) "
                "ON CONFLICT(file_path) DO UPDATE SET urls=excluded.urls",
                (file_path, data),
            )
            self._conn.commit()

    def add_url(self, file_path: str, url: str) -> list[str] | None:
        """Add a URL under the process write lock. Returns updated URLs if changed."""
        with db_write_lock(self._conn):
            urls = self.get_urls(file_path)
            if url in urls:
                return None
            urls.append(url)
            data = json.dumps(urls, ensure_ascii=False)
            self._conn.execute(
                "INSERT INTO file_meta (file_path, urls) VALUES (?, ?) "
                "ON CONFLICT(file_path) DO UPDATE SET urls=excluded.urls",
                (file_path, data),
            )
            self._conn.commit()
            return urls

    def remove_url(self, file_path: str, url: str) -> list[str] | None:
        """Remove a URL under the process write lock. Returns updated URLs if changed."""
        with db_write_lock(self._conn):
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
            self._conn.commit()
            return urls

    # ── Size cache ───────────────────────────────────────────────

    def get_cached_size(self, file_path: str) -> tuple[int, float] | None:
        """Return (cached_size, cached_mtime) or None if not cached."""
        row = self._conn.execute(
            "SELECT cached_size, cached_mtime FROM file_meta "
            "WHERE file_path=? AND cached_size IS NOT NULL",
            (file_path,),
        ).fetchone()
        if row and row[0] is not None and row[1] is not None:
            return (row[0], row[1])
        return None

    def set_cached_size(self, file_path: str, size: int, mtime: float) -> None:
        """Cache a directory size."""
        with db_write_lock(self._conn):
            self._conn.execute(
                "INSERT INTO file_meta (file_path, cached_size, cached_mtime) VALUES (?, ?, ?) "
                "ON CONFLICT(file_path) DO UPDATE SET "
                "cached_size=excluded.cached_size, cached_mtime=excluded.cached_mtime",
                (file_path, size, mtime),
            )
            self._conn.commit()

    def get_cached_file_count(self, file_path: str) -> int | None:
        """Return cached file count, or None if not cached."""
        row = self._conn.execute(
            "SELECT cached_file_count FROM file_meta "
            "WHERE file_path=? AND cached_file_count IS NOT NULL",
            (file_path,),
        ).fetchone()
        if row and row[0] is not None and row[0] > 0:
            return row[0]
        return None

    def set_cached_file_count(self, file_path: str, count: int) -> None:
        """Cache a file count."""
        with db_write_lock(self._conn):
            self._conn.execute(
                "INSERT INTO file_meta (file_path, cached_file_count) VALUES (?, ?) "
                "ON CONFLICT(file_path) DO UPDATE SET cached_file_count=excluded.cached_file_count",
                (file_path, count),
            )
            self._conn.commit()

    def batch_get_cached_file_counts(self, file_paths: list[str]) -> dict[str, int]:
        """Return {path: count} for directories that have cached file counts."""
        if not file_paths:
            return {}
        results: dict[str, int] = {}
        # Chunk to avoid SQLite variable limit
        chunk_size = 900
        for i in range(0, len(file_paths), chunk_size):
            chunk = file_paths[i:i + chunk_size]
            placeholders = ",".join("?" * len(chunk))
            rows = self._conn.execute(
                f"SELECT file_path, cached_file_count FROM file_meta "
                f"WHERE file_path IN ({placeholders}) AND cached_file_count IS NOT NULL",
                chunk,
            ).fetchall()
            for r in rows:
                if r[1] and r[1] > 0:
                    results[r[0]] = r[1]
        return results

    def batch_set_cached_file_counts(self, entries: dict[str, int]) -> None:
        """Cache file counts for multiple directories in a single transaction."""
        if not entries:
            return
        with db_write_lock(self._conn):
            self._conn.executemany(
                "INSERT INTO file_meta (file_path, cached_file_count) VALUES (?, ?) "
                "ON CONFLICT(file_path) DO UPDATE SET cached_file_count=excluded.cached_file_count",
                list(entries.items()),
            )
            self._conn.commit()

    # ── Stats ────────────────────────────────────────────────────

    def get_cached_stats(self, file_paths: list[str]) -> dict[str, tuple[int, float]]:
        """Return {path: (cached_size, cached_mtime)} for given paths."""
        if not file_paths:
            return {}
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

    def get_library_total_size(self, library_path: str) -> int:
        """Return total size from library_stats, or 0 if not available."""
        row = self._conn.execute(
            "SELECT total_size FROM library_stats WHERE library_path=?",
            (library_path,),
        ).fetchone()
        return (row[0] or 0) if row else 0

    def set_library_total_size(self, library_path: str, size: int) -> None:
        """Update library_stats total_size."""
        with db_write_lock(self._conn):
            self._conn.execute(
                "INSERT OR REPLACE INTO library_stats (library_path, total_size) VALUES (?, ?)",
                (library_path, size),
            )
            self._conn.commit()

    # ── Invalidation ─────────────────────────────────────────────

    def invalidate_size_cache(self, file_path: str) -> None:
        """Clear cached size/count for a path and its children."""
        escaped = file_path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with db_write_lock(self._conn):
            self._conn.execute(
                "UPDATE file_meta SET cached_size=NULL, cached_mtime=NULL, cached_file_count=NULL "
                "WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                (file_path, escaped + "%"),
            )
            self._conn.commit()

    def delete_path(self, file_path: str, *, commit: bool = True) -> int:
        """Delete metadata for a path and its descendants."""
        escaped = file_path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        separator = "\\" if "\\" in file_path else "/" if "/" in file_path else os.sep
        prefix = escaped + separator.replace("\\", "\\\\") + "%"
        with db_write_lock(self._conn):
            cur = self._conn.execute(
                "DELETE FROM file_meta WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                (file_path, prefix),
            )
            if commit:
                self._conn.commit()
            return cur.rowcount

    # ── Migration ────────────────────────────────────────────────

    def migrate_path(self, old_path: str, new_path: str) -> int:
        """Move metadata from old_path to new_path. Returns rows affected."""
        escaped = old_path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with db_write_lock(self._conn):
            rows = self._conn.execute(
                "SELECT file_path, notes, cached_size, cached_mtime, cached_file_count, urls "
                "FROM file_meta WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                (old_path, escaped + "/%"),
            ).fetchall()
            count = 0
            for path, notes, cached_size, cached_mtime, cached_file_count, urls in rows:
                mapped = new_path + path[len(old_path):] if path.startswith(old_path + "/") else new_path
                self._conn.execute(
                    "INSERT INTO file_meta "
                    "(file_path, notes, cached_size, cached_mtime, cached_file_count, urls) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(file_path) DO UPDATE SET "
                    "notes=CASE WHEN excluded.notes!='' THEN excluded.notes ELSE file_meta.notes END, "
                    "cached_size=COALESCE(excluded.cached_size, file_meta.cached_size), "
                    "cached_mtime=COALESCE(excluded.cached_mtime, file_meta.cached_mtime), "
                    "cached_file_count=COALESCE(excluded.cached_file_count, file_meta.cached_file_count), "
                    "urls=CASE WHEN excluded.urls!='[]' THEN excluded.urls ELSE file_meta.urls END",
                    (mapped, notes, cached_size, cached_mtime, cached_file_count, urls),
                )
                count += 1
            if rows:
                self._conn.execute(
                    "DELETE FROM file_meta WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                    (old_path, escaped + "/%"),
                )
            self._conn.commit()
            return count
