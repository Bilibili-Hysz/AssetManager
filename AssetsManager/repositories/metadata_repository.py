from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from sqlite3 import Connection
from typing import Any, Callable, TypeVar

from AssetsManager.core.database import DatabaseManager, db_write_lock
from AssetsManager.core.path_resolver import (
    RootIdentity,
    path_key_separator,
    remap_path_subtree,
    root_identity,
    sql_like_descendant_pattern,
)
from AssetsManager.core.session_contract import require_library_session

_log = logging.getLogger(__name__)
_R = TypeVar("_R")


def _repository_operation(method: Callable[..., _R]) -> Callable[..., _R]:
    @wraps(method)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> _R:
        with self._operation_scope():
            return method(self, *args, **kwargs)

    return wrapped


def _session_root(session: Any) -> RootIdentity:
    identity = getattr(getattr(session, "context", None), "root_identity", None)
    if isinstance(identity, RootIdentity):
        return identity
    raise TypeError(
        "MetadataRepository canonical session must expose a captured root identity"
    )


def _require_session_contract(
    session: Any,
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    # A managed connection alone is not a lifecycle lease.  Reject structural
    # fakes whose null operation scope would let close race an in-flight query.
    require_library_session(session)
    operation = getattr(session, "operation", None)
    if not callable(operation):
        raise TypeError(
            "MetadataRepository canonical session requires callable operation()"
        )
    connection_for = getattr(session, "connection_for", None)
    if not callable(connection_for):
        raise TypeError(
            "MetadataRepository canonical session requires callable connection_for()"
        )
    return operation, connection_for


class MetadataRepository:
    """Encapsulates all file_meta database operations.

    Raw ``MetadataRepository(conn)`` remains the explicit legacy adapter.
    Canonical callers should use :meth:`for_session`, which binds connection
    ownership, path containment, and repository lifetime to one LibrarySession.
    """

    def __init__(
        self,
        conn: Connection,
        *,
        library_root: str | Path | RootIdentity | None = None,
        session: Any | None = None,
    ):
        self._conn = conn
        self._session: Any | None = None
        self._library_root_key: str | None = None
        self._library_root: Path | None = None
        self._binding_lock = threading.RLock()
        self._raw_operation_started = False
        if library_root is not None:
            identity = root_identity(library_root, strict=False)
            self._library_root_key = identity.map_key
            self._library_root = identity.display_path
            DatabaseManager.validate_connection_owner(
                identity, conn, allow_unmanaged=True
            )
        if session is not None:
            self._bind_session(session, library_root=library_root)

    @classmethod
    def for_session(
        cls,
        session: Any,
        *,
        library_root: str | Path | RootIdentity | None = None,
    ) -> "MetadataRepository":
        """Build a strictly session/root-bound metadata repository."""
        operation, connection_for = _require_session_contract(session)
        with operation():
            session_root = _session_root(session)
            conn = connection_for(session_root)
            conn = DatabaseManager.require_managed_connection_owner(
                session_root, conn
            )
            repository = cls(conn)
            repository._bind_session(session, library_root=library_root)
            return repository

    @contextmanager
    def _operation_scope(self):
        with self._binding_lock:
            session = self._session
            if session is None:
                # Once a published raw repository has admitted work, converting
                # it into a session-bound object would leave an unleased operation
                # running through the binding publication point.
                self._raw_operation_started = True
        if session is None:
            yield
            return
        with session.operation():
            yield

    def _bind_session(
        self,
        session: Any,
        *,
        library_root: str | Path | RootIdentity | None = None,
    ) -> None:
        operation, connection_for = _require_session_contract(session)
        session_identity = _session_root(session)
        if library_root is not None:
            explicit_identity = root_identity(library_root, strict=False)
            if explicit_identity.map_key != session_identity.map_key:
                raise ValueError(
                    "MetadataRepository library_root does not match "
                    "the LibrarySession"
                )

        with self._binding_lock:
            if self._session is not None:
                if self._session is session:
                    return
                raise RuntimeError(
                    "MetadataRepository is already bound to another LibrarySession"
                )
            if self._raw_operation_started:
                raise RuntimeError(
                    "MetadataRepository cannot bind after raw operations have started"
                )
            if (
                self._library_root_key is not None
                and self._library_root_key != session_identity.map_key
            ):
                raise ValueError(
                    "MetadataRepository belongs to a different library root"
                )

            with operation():
                conn = connection_for(session_identity)
                conn = DatabaseManager.require_managed_connection_owner(
                    session_identity, conn
                )
                if conn is not self._conn:
                    raise ValueError(
                        "MetadataRepository connection does not belong to "
                        "the LibrarySession"
                    )

                def publish_binding() -> None:
                    self._library_root_key = session_identity.map_key
                    self._library_root = session_identity.display_path
                    self._session = session

                session._publish_while_live(publish_binding)

    def _path_key(self, file_path: str | Path) -> str:
        """Return a canonical key and enforce bound-root containment."""
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

    @contextmanager
    def _write_scope(self, operation_name: str):
        """Commit raw writes, but preserve caller transactions when bound."""
        with db_write_lock(self._conn):
            if self._session is None:
                yield
                self._conn.commit()
                return

            outer_transaction = self._conn.in_transaction
            savepoint = (
                f"metadata_{operation_name}_{id(self):x}_{time.monotonic_ns():x}"
            )
            savepoint_active = False
            try:
                self._conn.execute(f"SAVEPOINT {savepoint}")
                savepoint_active = True
                yield
                self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                savepoint_active = False
                if not outer_transaction:
                    self._conn.commit()
            except BaseException as exc:
                cleanup_errors: list[BaseException] = []
                if savepoint_active:
                    for statement in (
                        f"ROLLBACK TO SAVEPOINT {savepoint}",
                        f"RELEASE SAVEPOINT {savepoint}",
                    ):
                        try:
                            self._conn.execute(statement)
                        except BaseException as cleanup_exc:
                            cleanup_errors.append(cleanup_exc)
                if not outer_transaction and self._conn.in_transaction:
                    try:
                        self._conn.rollback()
                    except BaseException as cleanup_exc:
                        cleanup_errors.append(cleanup_exc)
                if cleanup_errors:
                    exc.add_note(
                        "MetadataRepository transaction cleanup also failed: "
                        + "; ".join(str(error) for error in cleanup_errors)
                    )
                raise

    # ── Notes ────────────────────────────────────────────────────

    @_repository_operation
    def get_notes(self, file_path: str) -> str:
        """Return notes for a file path."""
        file_path = self._path_key(file_path)
        row = self._conn.execute(
            "SELECT notes FROM file_meta WHERE file_path=?",
            (file_path,),
        ).fetchone()
        return row[0] if row else ""

    @_repository_operation
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
        """Add a URL under the process write lock. Returns updated URLs if changed.

        Concurrency note: the JSON column is updated via a read-modify-write
        cycle that is only atomic on this connection. Concurrent add/remove
        calls from *other* connections can overwrite each other's changes
        (the last writer wins). This is accepted for the current single-LAN
        server topology; do not rely on it under multi-connection writers.
        """
        file_path = self._path_key(file_path)
        with self._write_scope("add_url"):
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
            return urls

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
    def get_cached_file_count(self, file_path: str) -> int | None:
        """Return cached file count, or None if not cached."""
        file_path = self._path_key(file_path)
        row = self._conn.execute(
            "SELECT cached_file_count FROM file_meta "
            "WHERE file_path=? AND cached_file_count IS NOT NULL",
            (file_path,),
        ).fetchone()
        if row and row[0] is not None:
            return int(row[0])
        return None

    @_repository_operation
    def set_cached_file_count(self, file_path: str, count: int) -> None:
        """Cache a file count."""
        file_path = self._path_key(file_path)
        with self._write_scope("set_cached_file_count"):
            self._conn.execute(
                "INSERT INTO file_meta (file_path, cached_file_count) VALUES (?, ?) "
                "ON CONFLICT(file_path) DO UPDATE SET cached_file_count=excluded.cached_file_count",
                (file_path, count),
            )

    @_repository_operation
    def batch_get_cached_file_counts(self, file_paths: list[str]) -> dict[str, int]:
        """Return {path: count} for directories that have cached file counts."""
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
                f"WHERE file_path IN ({placeholders}) AND cached_file_count IS NOT NULL",
                chunk,
            ).fetchall()
            for r in rows:
                if r[1] is not None:
                    results[r[0]] = int(r[1])
        return results

    @_repository_operation
    def batch_set_cached_file_counts(self, entries: dict[str, int]) -> None:
        """Cache file counts for multiple directories in a single transaction."""
        if not entries:
            return
        entries = {self._path_key(path): count for path, count in entries.items()}
        with self._write_scope("batch_set_cached_file_counts"):
            self._conn.executemany(
                "INSERT INTO file_meta (file_path, cached_file_count) VALUES (?, ?) "
                "ON CONFLICT(file_path) DO UPDATE SET cached_file_count=excluded.cached_file_count",
                list(entries.items()),
            )

    # ── Stats ────────────────────────────────────────────────────

    @_repository_operation
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
                "UPDATE file_meta SET cached_size=NULL, cached_mtime=NULL, cached_file_count=NULL "
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
                "SELECT file_path, notes, cached_size, cached_mtime, cached_file_count, urls "
                "FROM file_meta WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                (old_path, descendant_pattern),
            ).fetchall()
            count = 0
            for path, notes, cached_size, cached_mtime, cached_file_count, urls in rows:
                mapped = remap_path_subtree(old_path, new_path, path)
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
                    (old_path, descendant_pattern),
                )
            return count
