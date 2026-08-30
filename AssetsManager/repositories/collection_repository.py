"""Collection repository — CRUD for user collections and their members.

Two table shapes back the feature (migration v38): ``asset_collections``
holds one row per collection with a ``kind`` of ``'manual'`` (physical
membership rows below) or ``'smart'`` (the structured predicate JSON in
``query_json``, evaluated at read time — no membership rows).  Members are
pure references: the repository never moves or copies files.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from sqlite3 import Connection, IntegrityError
from typing import Any, Callable, Literal, TypeVar

from AssetsManager.core.database import DatabaseManager, db_write_lock, locked_read
from AssetsManager.core.path_resolver import RootIdentity, root_identity
from AssetsManager.core.session_contract import require_library_session
from AssetsManager.domain.errors import DuplicateError, NotFoundError

_R = TypeVar("_R")

CollectionKind = Literal["manual", "smart"]

_KINDS: tuple[str, ...] = ("manual", "smart")


def _collection_kind(kind: str) -> CollectionKind:
    """Route ``kind`` through a controlled whitelist before SQL use."""
    if kind not in _KINDS:
        raise ValueError(f"unknown collection kind: {kind!r}")
    return kind  # type: ignore[return-value]


def _repository_operation(method: Callable[..., _R]) -> Callable[..., _R]:
    """Lease a canonical session for one complete repository operation."""
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
        "CollectionRepository canonical session must expose a captured root identity"
    )


def _require_session_contract(
    session: Any,
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    """Validate the real-session marker and the lifecycle/provider surface."""
    require_library_session(session)
    operation = getattr(session, "operation", None)
    if not callable(operation):
        raise TypeError(
            "CollectionRepository canonical session requires callable operation()"
        )
    connection_for = getattr(session, "connection_for", None)
    if not callable(connection_for):
        raise TypeError(
            "CollectionRepository canonical session requires callable connection_for()"
        )
    return operation, connection_for


class CollectionRepository:
    """Encapsulate all user-collection database operations.

    ``CollectionRepository(conn)`` remains the explicit raw compatibility
    path. Canonical callers should use :meth:`for_session`, which binds
    connection ownership, root containment, transaction lifetime, and close
    semantics to one real ``LibrarySession``.
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
    ) -> "CollectionRepository":
        """Build a strictly session/root-bound collection repository."""
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
                    "CollectionRepository library_root does not match the LibrarySession"
                )

        with self._binding_lock:
            if self._session is not None:
                if self._session is session:
                    return
                raise RuntimeError(
                    "CollectionRepository is already bound to another LibrarySession"
                )
            if self._raw_operation_started:
                raise RuntimeError(
                    "CollectionRepository cannot bind after raw operations have started"
                )
            if (
                self._library_root_key is not None
                and self._library_root_key != session_identity.map_key
            ):
                raise ValueError(
                    "CollectionRepository belongs to a different library root"
                )

            with operation():
                conn = connection_for(session_identity)
                conn = DatabaseManager.require_managed_connection_owner(
                    session_identity, conn
                )
                if conn is not self._conn:
                    raise ValueError(
                        "CollectionRepository connection does not belong to the LibrarySession"
                    )

                def publish_binding() -> None:
                    self._library_root_key = session_identity.map_key
                    self._library_root = session_identity.display_path
                    self._session = session

                session._publish_while_live(publish_binding)

    def _path_key(self, file_path: str | Path) -> str:
        """Return a canonical path and enforce bound-root containment."""
        if self._library_root is None:
            return str(file_path)
        target = Path(file_path).resolve()
        if not target.is_relative_to(self._library_root):
            raise ValueError(
                f"collection path must be under library_root: {target} "
                f"(root {self._library_root})"
            )
        return str(target)

    @contextmanager
    def _write_scope(
        self, operation_name: str, *, require_clean_transaction: bool = False
    ):
        """Commit raw writes, but preserve caller transactions when bound."""
        with db_write_lock(self._conn):
            if self._session is None:
                yield
                self._conn.commit()
                return

            if require_clean_transaction and self._conn.in_transaction:
                raise RuntimeError(
                    "CollectionRepository mutation requires a clean transaction boundary"
                )
            outer_transaction = self._conn.in_transaction
            savepoint = (
                f"collection_{operation_name}_{id(self):x}_{time.monotonic_ns():x}"
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
                        "CollectionRepository transaction cleanup also failed: "
                        + "; ".join(str(error) for error in cleanup_errors)
                    )
                raise

    # ── Reads ─────────────────────────────────────────────────────

    @_repository_operation
    @locked_read
    def get(self, collection_id: int) -> dict | None:
        """Return one collection row, or None when the id is unknown."""
        row = self._conn.execute(
            "SELECT id, name, kind, query_json, created_at, updated_at "
            "FROM asset_collections WHERE id=?",
            (collection_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "name": row[1],
            "kind": row[2],
            "query_json": row[3],
            "created_at": row[4],
            "updated_at": row[5],
        }

    @_repository_operation
    @locked_read
    def list_collections(self) -> list[dict]:
        """Return all collections with member counts, sorted by name.

        Smart collections have no membership rows, so their count is 0; the
        count is informational (sidebar badges), not authoritative.
        """
        rows = self._conn.execute(
            "SELECT c.id, c.name, c.kind, c.query_json, c.created_at, c.updated_at, "
            "COUNT(m.file_path) AS member_count "
            "FROM asset_collections c "
            "LEFT JOIN asset_collection_members m ON m.collection_id = c.id "
            "GROUP BY c.id ORDER BY c.name COLLATE NOCASE, c.id"
        ).fetchall()
        return [
            {
                "id": row[0],
                "name": row[1],
                "kind": row[2],
                "query_json": row[3],
                "created_at": row[4],
                "updated_at": row[5],
                "member_count": row[6],
            }
            for row in rows
        ]

    @_repository_operation
    @locked_read
    def get_members(self, collection_id: int) -> list[dict]:
        """Return membership rows ordered by insertion time.

        Missing-on-disk paths are deliberately NOT pruned here: the collection
        is a reference set, and readers tolerate absent members (the service
        layer marks them with ``exists`` so consumers can skip them).
        """
        rows = self._conn.execute(
            "SELECT file_path, added_at FROM asset_collection_members "
            "WHERE collection_id=? ORDER BY added_at, file_path",
            (collection_id,),
        ).fetchall()
        return [{"file_path": row[0], "added_at": row[1]} for row in rows]

    @_repository_operation
    @locked_read
    def count_members(self, collection_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM asset_collection_members WHERE collection_id=?",
            (collection_id,),
        ).fetchone()
        return int(row[0]) if row is not None else 0

    # ── Writes ────────────────────────────────────────────────────

    @_repository_operation
    def create(
        self,
        kind: str,
        name: str,
        query_json: str,
        *,
        commit: bool = True,
        require_clean_transaction: bool = False,
    ) -> dict:
        """Create a collection; duplicate names raise DuplicateError."""
        _collection_kind(kind)
        now = time.time()

        def insert() -> dict:
            duplicate = self._conn.execute(
                "SELECT 1 FROM asset_collections WHERE name=?", (name,)
            ).fetchone()
            if duplicate is not None:
                raise DuplicateError("collection", name)
            try:
                cursor = self._conn.execute(
                    "INSERT INTO asset_collections "
                    "(name, kind, query_json, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (name, kind, query_json, now, now),
                )
            except IntegrityError as exc:
                raise DuplicateError("collection", name) from exc
            return {
                "id": cursor.lastrowid,
                "name": name,
                "kind": kind,
                "query_json": query_json,
                "created_at": now,
                "updated_at": now,
                "member_count": 0,
            }

        if commit:
            with self._write_scope(
                "create", require_clean_transaction=require_clean_transaction
            ):
                return insert()
        return insert()

    @_repository_operation
    def rename(
        self,
        collection_id: int,
        new_name: str,
        *,
        commit: bool = True,
        require_clean_transaction: bool = False,
    ) -> None:
        """Rename a collection; duplicate names raise DuplicateError."""
        def rename() -> None:
            row = self._conn.execute(
                "SELECT 1 FROM asset_collections WHERE id=?", (collection_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("collection", str(collection_id))
            duplicate = self._conn.execute(
                "SELECT 1 FROM asset_collections WHERE name=? AND id<>?",
                (new_name, collection_id),
            ).fetchone()
            if duplicate is not None:
                raise DuplicateError("collection", new_name)
            self._conn.execute(
                "UPDATE asset_collections SET name=?, updated_at=? WHERE id=?",
                (new_name, time.time(), collection_id),
            )

        if commit:
            with self._write_scope(
                "rename", require_clean_transaction=require_clean_transaction
            ):
                rename()
            return
        with db_write_lock(self._conn):
            rename()

    @_repository_operation
    def set_query(
        self,
        collection_id: int,
        query_json: str,
        *,
        commit: bool = True,
        require_clean_transaction: bool = False,
    ) -> None:
        """Replace the structured predicate JSON of a smart collection."""
        def set_query() -> None:
            row = self._conn.execute(
                "SELECT 1 FROM asset_collections WHERE id=?", (collection_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("collection", str(collection_id))
            self._conn.execute(
                "UPDATE asset_collections SET query_json=?, updated_at=? WHERE id=?",
                (query_json, time.time(), collection_id),
            )

        if commit:
            with self._write_scope(
                "set_query", require_clean_transaction=require_clean_transaction
            ):
                set_query()
            return
        with db_write_lock(self._conn):
            set_query()

    @_repository_operation
    def delete(
        self,
        collection_id: int,
        *,
        commit: bool = True,
        require_clean_transaction: bool = False,
    ) -> bool:
        """Delete one collection; membership rows cascade (v38 FK)."""
        def delete() -> bool:
            cursor = self._conn.execute(
                "DELETE FROM asset_collections WHERE id=?", (collection_id,)
            )
            return cursor.rowcount > 0

        if commit:
            with self._write_scope(
                "delete", require_clean_transaction=require_clean_transaction
            ):
                return delete()
        with db_write_lock(self._conn):
            return delete()

    @_repository_operation
    def add_members(
        self,
        collection_id: int,
        file_paths: list[str],
        *,
        commit: bool = True,
        require_clean_transaction: bool = False,
    ) -> int:
        """Add member references; duplicates are an idempotent no-op.

        Returns the number of newly inserted rows.
        """
        canonical = list(dict.fromkeys(self._path_key(p) for p in file_paths))

        def insert() -> int:
            row = self._conn.execute(
                "SELECT 1 FROM asset_collections WHERE id=?", (collection_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("collection", str(collection_id))
            added = 0
            now = time.time()
            for path in canonical:
                cursor = self._conn.execute(
                    "INSERT OR IGNORE INTO asset_collection_members "
                    "(collection_id, file_path, added_at) VALUES (?, ?, ?)",
                    (collection_id, path, now),
                )
                added += cursor.rowcount
            if added:
                self._conn.execute(
                    "UPDATE asset_collections SET updated_at=? WHERE id=?",
                    (now, collection_id),
                )
            return added

        if commit:
            with self._write_scope(
                "add_members", require_clean_transaction=require_clean_transaction
            ):
                return insert()
        with db_write_lock(self._conn):
            return insert()

    @_repository_operation
    def remove_members(
        self,
        collection_id: int,
        file_paths: list[str],
        *,
        commit: bool = True,
        require_clean_transaction: bool = False,
    ) -> int:
        """Remove member references; missing rows are an idempotent no-op."""
        canonical = list(dict.fromkeys(self._path_key(p) for p in file_paths))

        def remove() -> int:
            removed = 0
            for path in canonical:
                cursor = self._conn.execute(
                    "DELETE FROM asset_collection_members "
                    "WHERE collection_id=? AND file_path=?",
                    (collection_id, path),
                )
                removed += cursor.rowcount
            if removed:
                self._conn.execute(
                    "UPDATE asset_collections SET updated_at=? WHERE id=?",
                    (time.time(), collection_id),
                )
            return removed

        if commit:
            with self._write_scope(
                "remove_members", require_clean_transaction=require_clean_transaction
            ):
                return remove()
        with db_write_lock(self._conn):
            return remove()
