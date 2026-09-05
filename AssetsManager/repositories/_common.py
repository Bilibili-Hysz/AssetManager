"""Shared private plumbing for the session-bound repository family.

``shop_repository`` historically hosted the base class, decorators, JSON
helpers and the savepoint transaction used by its sibling repositories
(orders, carts/wishlists, delivery quotas, seller profile, storefront
analytics, free-download quotas) and by two application services. Those
symbols live here now; ``shop_repository`` re-exports them so existing
import paths keep working, and new code imports them from this module.

It also hosts the cross-repository write-safety mechanisms:

- :class:`_SessionBoundRepository` — the single canonical base for the
  repository family: real-session token check (``require_library_session``),
  captured ``RootIdentity`` binding, the raw-operation one-way door, the
  bind-session four-way guard, and the ``_write_scope`` savepoint contract.
  ``_CommerceRepository`` is retained as a legacy alias (pre-rename import
  paths and historical tests reference it).
- :func:`_guarded_commit` — commit a repository write only when the call
  owns its transaction, so a caller's outer transaction is never truncated.
- :func:`_with_sqlite_busy_retry` / :func:`_retry_sqlite_busy` — the shared
  bounded SQLITE_BUSY replay loop, opt-in per repository operation.
"""
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from sqlite3 import Connection
from typing import Any, Callable, Iterator, TypeVar

from AssetsManager.core.database import (
    SQLITE_BUSY_RETRY_ATTEMPTS,
    DatabaseManager,
    db_write_lock,
    is_sqlite_busy_error,
    sqlite_busy_retry_delay,
)
# ``locked_read`` originates in core.database; it is re-exported here because
# every repository of this family imports it alongside the plumbing below.
from AssetsManager.core.database import locked_read as locked_read
from AssetsManager.core.path_resolver import RootIdentity, root_identity
from AssetsManager.core.schema_defs import (
    COMMERCE_SCHEMAS,
    SCHEMA_OBJECT_CONTRACT,
    validate_schema_object,
    validate_schema_objects,
)
from AssetsManager.core.session_contract import require_library_session

_R = TypeVar("_R")


def _repository_operation(method: Callable[..., _R]) -> Callable[..., _R]:
    """Lease a canonical session for one complete repository operation."""
    @wraps(method)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> _R:
        with self._operation_scope():
            return method(self, *args, **kwargs)

    return wrapped


def _session_root(session: Any, repository_name: str) -> RootIdentity:
    """Resolve the session's captured root identity (the strict dialect).

    Unlike the legacy duck-typed ``session.root``/``root_str`` lookup, this
    requires the canonical ``LibrarySession`` shape: a ``context.root_identity``
    captured once at session construction. Sessions that only duck-type the
    old attributes are rejected — the identity must be captured, not derived
    per call, so binding and every later containment check agree.
    """
    identity = getattr(getattr(session, "context", None), "root_identity", None)
    if isinstance(identity, RootIdentity):
        return identity
    raise TypeError(
        f"{repository_name} canonical session must expose a captured root identity"
    )


def _require_session_contract(
    session: Any, repository_name: str
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    """Validate the real-session marker and the lifecycle/provider surface."""
    require_library_session(session)
    operation = getattr(session, "operation", None)
    if not callable(operation):
        raise TypeError(
            f"{repository_name} canonical session requires callable operation()"
        )
    connection_for = getattr(session, "connection_for", None)
    if not callable(connection_for):
        raise TypeError(
            f"{repository_name} canonical session requires callable connection_for()"
        )
    return operation, connection_for


@contextmanager
def _transaction(conn: Connection, prefix: str) -> Iterator[None]:
    """Run one repository write atomically without committing a caller transaction."""
    with db_write_lock(conn):
        outer_transaction = conn.in_transaction
        savepoint = f"{prefix}_{time.monotonic_ns():x}"
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            yield
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            if not outer_transaction:
                conn.commit()
        except BaseException:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise


def _json_dump(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _json_load(value: object) -> dict[str, Any]:
    if not value:
        return {}
    text = str(value)
    # Fast path: the common empty-metadata row skips a JSON parse entirely.
    if text == "{}":
        return {}
    try:
        decoded = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _ensure_commerce_schema(conn: Connection) -> None:
    tables = tuple(table for table, _schema in COMMERCE_SCHEMAS)
    with _transaction(conn, "commerce_repository_init"):
        for table in tables:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if exists is None:
                continue
            contract = dict(SCHEMA_OBJECT_CONTRACT[table])
            contract.pop("indexes", None)
            validate_schema_object(conn, table, contract)  # type: ignore[arg-type]
        for _table, schema in COMMERCE_SCHEMAS:
            for statement in schema.split(";"):
                if sql := statement.strip():
                    conn.execute(sql)
        validate_schema_objects(conn, tables)


class _SessionBoundRepository:
    """The canonical strict LibrarySession/connection/root binding contract.

    One implementation of the scaffolding every repository in this family
    used to copy verbatim (D1/W-3 dialect unification, 2026-09-04):

    - ``for_session`` — require the real-session token, resolve the captured
      ``RootIdentity``, take the connection through
      ``require_managed_connection_owner``, then bind.
    - ``_operation_scope`` — the raw-operation one-way door: the first raw
      (sessionless) operation permanently closes the session-binding channel,
      so a published session binding can never coexist with unleased raw
      writes on the same instance.
    - ``_bind_session`` — the four-way guard: no rebind to a different
      session, no bind after raw operations, explicit ``library_root`` must
      match the session identity, and the connection must be the session's
      managed connection. Publication runs under
      ``session._publish_while_live`` when available so a closing session
      rejects the binding atomically.
    - ``_write_scope`` — raw mode commits directly; bound mode opens a
      per-operation SAVEPOINT so caller transactions are never truncated,
      with failed-cleanup diagnostics attached via ``add_note``.
    - ``_path_key`` — bound-root containment; unbound repositories must
      override with an explicit policy (the base raises rather than
      silently passing raw paths through, closing the old no-op hole).
    """

    def __init__(
        self,
        conn: Connection,
        *,
        library_root: str | Path | RootIdentity | None = None,
        session: Any | None = None,
    ) -> None:
        self._conn = conn
        self._session: Any | None = None
        self._library_root_key: str | None = None
        self._library_root: Path | None = None
        self._binding_lock = threading.RLock()
        self._raw_operation_started = False
        if library_root is not None:
            identity = root_identity(library_root, strict=False)
            self._apply_root_identity(identity)
            DatabaseManager.validate_connection_owner(identity, conn, allow_unmanaged=True)
        if session is not None:
            self._bind_session(session, library_root=library_root)

    def _apply_root_identity(self, identity: RootIdentity) -> None:
        """Record the bound root identity (subclass override point).

        Subclasses that keep extra root-derived state (e.g. the asset index
        ``_root_identity``) override this instead of re-deriving after
        ``super().__init__``; every binding path (constructor ``library_root``,
        ``_bind_session`` publication) funnels through here so the extra state
        can never lag the base fields.
        """
        self._library_root_key = identity.map_key
        self._library_root = identity.display_path

    @classmethod
    def for_session(
        cls,
        session: Any,
        *,
        library_root: str | Path | RootIdentity | None = None,
    ):
        """Build a strictly session/root-bound repository for a canonical session."""
        repository_name = cls.__name__
        operation, connection_for = _require_session_contract(session, repository_name)
        with operation():
            session_root = _session_root(session, repository_name)
            conn = connection_for(session_root)
            conn = DatabaseManager.require_managed_connection_owner(session_root, conn)
            repository = cls(conn)
            repository._bind_session(session, library_root=library_root)
            return repository

    @contextmanager
    def _operation_scope(self) -> Iterator[None]:
        with self._binding_lock:
            session = self._session
            if session is None:
                self._raw_operation_started = True
        if session is None:
            yield
            return
        with session.operation():
            yield

    @contextmanager
    def serialized_operation(self) -> Iterator[None]:
        """Serialize a compound read/validate/write operation on this connection."""
        with db_write_lock(self._conn):
            yield

    def _bind_session(
        self,
        session: Any,
        *,
        library_root: str | Path | RootIdentity | None = None,
    ) -> None:
        repository_name = type(self).__name__
        operation, connection_for = _require_session_contract(session, repository_name)
        session_identity = _session_root(session, repository_name)
        if library_root is not None:
            explicit_identity = root_identity(library_root, strict=False)
            if explicit_identity.map_key != session_identity.map_key:
                raise ValueError(
                    f"{repository_name} library_root does not match the LibrarySession"
                )

        with self._binding_lock:
            if self._session is not None:
                if self._session is session:
                    return
                raise RuntimeError(
                    f"{repository_name} is already bound to another LibrarySession"
                )
            if self._raw_operation_started:
                raise RuntimeError(
                    f"{repository_name} cannot bind after raw operations have started"
                )
            if (
                self._library_root_key is not None
                and self._library_root_key != session_identity.map_key
            ):
                raise ValueError(
                    f"{repository_name} belongs to a different library root"
                )

            with operation():
                conn = connection_for(session_identity)
                conn = DatabaseManager.require_managed_connection_owner(
                    session_identity, conn
                )
                if conn is not self._conn:
                    raise ValueError(
                        f"{repository_name} connection does not belong to the LibrarySession"
                    )

                def publish_binding() -> None:
                    self._apply_root_identity(session_identity)
                    self._session = session

                publish_while_live = getattr(session, "_publish_while_live", None)
                if callable(publish_while_live):
                    publish_while_live(publish_binding)
                else:
                    publish_binding()

    def _path_key(self, file_path: str | Path) -> str:
        """Return a canonical path and enforce bound-root containment.

        The base contract refuses unbound repositories outright: a sessionless
        ``_path_key`` historically returned the raw string (a containment
        no-op — the W-5 dialect hole), so subclasses that genuinely support
        the raw path must override this with an explicit policy.
        """
        if self._library_root is None:
            raise ValueError(
                f"{type(self).__name__} path containment requires a bound library root"
            )
        target = Path(file_path).resolve()
        if not target.is_relative_to(self._library_root):
            raise ValueError(
                f"{type(self).__name__} path must be under library_root: {target} "
                f"(root {self._library_root})"
            )
        return str(target)

    @contextmanager
    def _write_scope(
        self,
        operation_name: str,
        *,
        require_clean_transaction: bool = False,
    ) -> Iterator[None]:
        """Commit raw writes, but preserve caller transactions when bound."""
        with db_write_lock(self._conn):
            if self._session is None:
                yield
                self._conn.commit()
                return

            if require_clean_transaction and self._conn.in_transaction:
                raise RuntimeError(
                    f"{type(self).__name__} mutation requires a clean transaction boundary"
                )
            outer_transaction = self._conn.in_transaction
            savepoint = (
                f"{type(self).__name__.lower()}_{operation_name}_"
                f"{id(self):x}_{time.monotonic_ns():x}"
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
                        f"{type(self).__name__} transaction cleanup also failed: "
                        + "; ".join(str(error) for error in cleanup_errors)
                    )
                raise

    @_repository_operation
    def init_tables(self) -> None:
        """Compatibility ensure for raw connections; migration v8 owns the schema."""
        _ensure_commerce_schema(self._conn)


# Legacy alias: the base predates the family-wide rename (2026-09-04) and the
# commerce-era name still appears in historical import paths and tests.
_CommerceRepository = _SessionBoundRepository


def _guarded_commit(conn: Connection, *, outer_transaction: bool) -> bool:
    """Commit ``conn`` only when the repository owns the transaction.

    Returns True when the commit was performed and False when the caller had
    already opened an outer transaction that this write must not truncate.

    Callers must sample ``conn.in_transaction`` BEFORE their own statements and
    pass it as ``outer_transaction``: managed connections use Python's default
    (deferred) transaction control, so the first DML of the method itself opens
    an implicit transaction and ``in_transaction`` sampled after the writes can
    no longer distinguish "caller owns the transaction" from "this method just
    opened one".
    """
    if outer_transaction:
        return False
    conn.commit()
    return True


def _retry_sqlite_busy(
    run: Callable[[], _R],
    *,
    outer_transaction: bool,
    attempts: int,
    rollback: Callable[[], None] | None = None,
) -> _R:
    """Run ``run`` under the shared bounded SQLITE_BUSY retry policy.

    Only ``sqlite3.OperationalError`` messages reporting a locked/busy
    database are retried, and never inside a caller-owned outer transaction
    (a caller transaction must not be rolled back or replayed underneath
    itself).  ``attempts`` counts the first try; callers pass ``1`` to
    disable replaying outright.  ``rollback`` is a best-effort hook that
    clears the failed attempt's partial transaction before the backoff.
    """
    for attempt in range(attempts):
        try:
            return run()
        except Exception as error:
            if (
                not is_sqlite_busy_error(error)
                or outer_transaction
                or attempt + 1 >= attempts
            ):
                raise
            if rollback is not None:
                try:
                    rollback()
                except Exception:
                    pass
            time.sleep(sqlite_busy_retry_delay(attempt))
    raise AssertionError("unreachable sqlite busy retry state")


def _with_sqlite_busy_retry(method: Callable[..., _R]) -> Callable[..., _R]:
    """Opt-in decorator: replay one repository operation on transient SQLITE_BUSY.

    The whole decorated call is retried from a clean transaction using the
    shared bounded policy (``SQLITE_BUSY_RETRY_ATTEMPTS`` total tries with the
    core backoff).  The replay is disabled entirely when the connection is
    already inside a caller-owned transaction.  Decorated repositories must
    expose their connection as ``self._conn``.
    """

    @wraps(method)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> _R:
        conn = getattr(self, "_conn", None)
        outer_transaction = bool(getattr(conn, "in_transaction", False))
        attempts = 1 if outer_transaction else SQLITE_BUSY_RETRY_ATTEMPTS
        return _retry_sqlite_busy(
            lambda: method(self, *args, **kwargs),
            outer_transaction=outer_transaction,
            attempts=attempts,
            rollback=None if conn is None else conn.rollback,
        )

    return wrapped


__all__ = [
    "_CommerceRepository",
    "_SessionBoundRepository",
    "_ensure_commerce_schema",
    "_guarded_commit",
    "_json_dump",
    "_json_load",
    "_repository_operation",
    "_require_session_contract",
    "_retry_sqlite_busy",
    "_session_root",
    "_transaction",
    "_with_sqlite_busy_retry",
    "locked_read",
]
