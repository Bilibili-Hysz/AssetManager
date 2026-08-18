"""Session-bound repository for per-library Commerce catalog items."""
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from sqlite3 import Connection, IntegrityError, OperationalError
from typing import Any, Callable, Iterable, Iterator, TypeVar

from AssetsManager.core.database import DatabaseManager, db_write_lock, locked_read
from AssetsManager.core.path_resolver import RootIdentity, root_identity
from AssetsManager.core.schema_defs import (
    COMMERCE_SCHEMAS,
    SCHEMA_OBJECT_CONTRACT,
    validate_schema_object,
    validate_schema_objects,
)
from AssetsManager.domain.errors import DuplicateError

_R = TypeVar("_R")


def _repository_operation(method: Callable[..., _R]) -> Callable[..., _R]:
    @wraps(method)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> _R:
        with self._operation_scope():
            return method(self, *args, **kwargs)

    return wrapped


def _session_root(session: Any, repository_name: str) -> str | Path | RootIdentity:
    root = getattr(session, "root", None)
    if root is None:
        root = getattr(session, "root_str", None)
    if root is None:
        raise TypeError(f"{repository_name} canonical session requires root or root_str")
    return root


def _require_session_contract(
    session: Any, repository_name: str
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    operation = getattr(session, "operation", None)
    connection_for = getattr(session, "connection_for", None)
    if not callable(operation):
        raise TypeError(f"{repository_name} canonical session requires callable operation()")
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


class _CommerceRepository:
    """Shared strict LibrarySession/connection/root binding contract."""

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
        self._binding_lock = threading.RLock()
        if library_root is not None:
            identity = root_identity(library_root, strict=False)
            self._library_root_key = identity.map_key
            DatabaseManager.validate_connection_owner(identity, conn, allow_unmanaged=True)
        if session is not None:
            self._bind_session(session, library_root=library_root)

    @classmethod
    def for_session(cls, session: Any):
        repository_name = cls.__name__
        operation, connection_for = _require_session_contract(session, repository_name)
        with operation():
            root = _session_root(session, repository_name)
            conn = connection_for(root)
            conn = DatabaseManager.require_managed_connection_owner(root, conn)
            repository = cls(conn)
            repository._bind_session(session, library_root=root)
            return repository

    @contextmanager
    def _operation_scope(self) -> Iterator[None]:
        if self._session is None:
            yield
            return
        with self._session.operation():
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
        with self._binding_lock:
            if self._session is not None:
                if self._session is session:
                    return
                raise RuntimeError(
                    f"{repository_name} is already bound to another LibrarySession"
                )

            operation, connection_for = _require_session_contract(
                session, repository_name
            )
            session_root = _session_root(session, repository_name)
            session_identity = root_identity(session_root, strict=False)
            if library_root is not None:
                explicit_identity = root_identity(library_root, strict=False)
                if explicit_identity.map_key != session_identity.map_key:
                    raise ValueError(
                        f"{repository_name} library_root does not match the LibrarySession"
                    )
            if (
                self._library_root_key is not None
                and self._library_root_key != session_identity.map_key
            ):
                raise ValueError(f"{repository_name} belongs to a different library root")

            with operation():
                conn = connection_for(session_root)
                conn = DatabaseManager.require_managed_connection_owner(
                    session_identity, conn
                )
                if conn is not self._conn:
                    raise ValueError(
                        f"{repository_name} connection does not belong to the LibrarySession"
                    )

                def publish_binding() -> None:
                    self._library_root_key = session_identity.map_key
                    self._session = session

                publish_while_live = getattr(session, "_publish_while_live", None)
                if callable(publish_while_live):
                    publish_while_live(publish_binding)
                else:
                    publish_binding()

    @_repository_operation
    def init_tables(self) -> None:
        """Compatibility ensure for raw connections; migration v8 owns the schema."""
        _ensure_commerce_schema(self._conn)


class ShopRepository(_CommerceRepository):
    """CRUD for catalog items; paths are unique within one library database."""

    _STATUSES = frozenset({"active", "draft", "archived"})

    # SQLite JSON1 support is a property of the linked sqlite3 library, not of
    # any single connection, so the probe result is cached once per process.
    # Repository instances may be created per request (ShopService._repo) or
    # per session (for_session), which makes a class-level cache the only
    # lifecycle-safe place to store it.
    _JSON1_AVAILABLE: bool | None = None
    _JSON1_PROBE_LOCK = threading.Lock()

    @classmethod
    @locked_read
    def _json1_available(cls, conn: Connection) -> bool:
        """Return whether SQLite JSON1 functions are usable, probed once."""
        if cls._JSON1_AVAILABLE is not None:
            return cls._JSON1_AVAILABLE
        with cls._JSON1_PROBE_LOCK:
            if cls._JSON1_AVAILABLE is not None:
                return cls._JSON1_AVAILABLE
            try:
                conn.execute("SELECT json_valid(?)", ("{}",)).fetchone()
                cls._JSON1_AVAILABLE = True
            except OperationalError as exc:
                if "json" not in str(exc).lower() and "function" not in str(exc).lower():
                    raise
                cls._JSON1_AVAILABLE = False
            return cls._JSON1_AVAILABLE

    @staticmethod
    def _status_clause(status: str) -> str:
        """SQL predicate for one status, mirroring the legacy Python semantics.

        The legacy resolution is: metadata.status when it is one of the three
        known statuses, otherwise "active" when enabled else "archived".
        """
        status_expr = (
            "CASE WHEN json_valid(metadata) "
            "THEN json_extract(metadata, '$.status') ELSE NULL END"
        )
        if status == "active":
            return (
                f"({status_expr} = 'active' OR (enabled = 1 AND "
                f"({status_expr} IS NULL OR {status_expr} NOT IN "
                f"('active', 'draft', 'archived'))))"
            )
        if status == "draft":
            return f"{status_expr} = 'draft'"
        return (
            f"({status_expr} = 'archived' OR (enabled = 0 AND "
            f"({status_expr} IS NULL OR {status_expr} NOT IN "
            f"('active', 'draft', 'archived'))))"
        )

    @staticmethod
    def _catalog_path_is_allowed(path: object, authorized_roots: tuple[str, ...]) -> bool:
        """Apply the public catalog's relative-path/root boundary before paging."""
        if not isinstance(path, str):
            return False
        normalized = path.strip().replace("\\", "/")
        if (
            not normalized
            or normalized.startswith("/")
            or (len(normalized) >= 2 and normalized[1] == ":")
            or any(part in ("", ".", "..") for part in normalized.split("/"))
        ):
            return False
        if not authorized_roots:
            return True
        return any(
            normalized == root or normalized.startswith(root + "/")
            for root in authorized_roots
        )

    @staticmethod
    def _catalog_status(item: dict[str, Any]) -> str:
        metadata = item.get("metadata")
        stored_status = metadata.get("status") if isinstance(metadata, dict) else None
        return (
            stored_status
            if stored_status in ShopRepository._STATUSES
            else "active" if item.get("enabled") else "archived"
        )

    @staticmethod
    def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "id": int(row[0]),
            "path": str(row[1]),
            "title": str(row[2]),
            "description": str(row[3]),
            "price_cents": int(row[4]),
            "currency": str(row[5]),
            "cover_path": None if row[6] is None else str(row[6]),
            "enabled": bool(row[7]),
            "metadata": _json_load(row[8]),
            "created_at": float(row[9]),
            "updated_at": float(row[10]),
        }

    @staticmethod
    def _validate_fields(
        *, title: str, price_cents: int, currency: str
    ) -> tuple[str, int, str]:
        title = str(title).strip()
        currency = str(currency).strip().upper()
        if not title:
            raise ValueError("title must not be empty")
        if (
            not isinstance(price_cents, int)
            or isinstance(price_cents, bool)
            or price_cents < 0
        ):
            raise ValueError("price_cents must be a non-negative integer")
        if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
            raise ValueError("currency must be a three-letter code")
        return title, price_cents, currency

    @locked_read
    def _select_item(self, item_id: int) -> tuple[Any, ...] | None:
        return self._conn.execute(
            "SELECT id, path, title, description, price_cents, currency, cover_path, "
            "enabled, metadata, created_at, updated_at FROM shop_items WHERE id=?",
            (item_id,),
        ).fetchone()

    @_repository_operation
    def create_item(
        self,
        *,
        path: str,
        title: str,
        price_cents: int,
        description: str = "",
        currency: str = "CNY",
        cover_path: str | None = None,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
        created_at: float | None = None,
    ) -> dict[str, Any]:
        path = str(path).strip()
        if not path:
            raise ValueError("path must not be empty")
        title, price_cents, currency = self._validate_fields(
            title=title, price_cents=price_cents, currency=currency
        )
        timestamp = time.time() if created_at is None else float(created_at)
        with _transaction(self._conn, "shop_item_create"):
            try:
                cursor = self._conn.execute(
                    "INSERT INTO shop_items "
                    "(path, title, description, price_cents, currency, cover_path, enabled, "
                    "metadata, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        path,
                        title,
                        str(description),
                        price_cents,
                        currency,
                        cover_path,
                        int(bool(enabled)),
                        _json_dump(metadata),
                        timestamp,
                        timestamp,
                    ),
                )
            except IntegrityError as exc:
                # shop_items.path is UNIQUE; any constraint failure on insert is
                # a duplicate path, which must surface as a business error
                # instead of an unhandled 500.
                raise DuplicateError("shop item", path) from exc
            lastrowid = cursor.lastrowid
            if lastrowid is None:
                raise RuntimeError("shop item insert did not return a row id")
            row = self._select_item(int(lastrowid))
            assert row is not None
            return self._row_to_dict(row)

    @_repository_operation
    def get_item(self, item_id: int) -> dict[str, Any] | None:
        row = self._select_item(int(item_id))
        return None if row is None else self._row_to_dict(row)

    @_repository_operation
    @locked_read
    def get_by_path(self, path: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT id, path, title, description, price_cents, currency, cover_path, "
            "enabled, metadata, created_at, updated_at FROM shop_items WHERE path=?",
            (path,),
        ).fetchone()
        return None if row is None else self._row_to_dict(row)

    @_repository_operation
    @locked_read
    def list_items(
        self,
        *,
        include_disabled: bool = False,
        status: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if status is not None:
            status = str(status).strip().lower()
            if status not in self._STATUSES:
                raise ValueError("status must be active, archived, or draft")
        where = "" if include_disabled else " WHERE enabled=1"
        json1 = self._json1_available(self._conn)
        if status is not None and json1:
            # Filter by status in SQL so the LIMIT window applies to the full
            # matching set instead of truncating it first (see list_catalog).
            clause = self._status_clause(status)
            where = where + (" AND " if where else " WHERE ") + clause
        rows = self._conn.execute(
            "SELECT id, path, title, description, price_cents, currency, cover_path, "
            f"enabled, metadata, created_at, updated_at FROM shop_items{where} "
            "ORDER BY updated_at DESC, id LIMIT ?",
            (max(1, min(int(limit), 5000)),),
        ).fetchall()
        items = [self._row_to_dict(row) for row in rows]
        if status is None or json1:
            return items
        # Legacy compatibility fallback for SQLite builds without JSON1.
        return [
            item
            for item in items
            if self._catalog_status(item) == status
        ]

    @_repository_operation
    def list_catalog(
        self,
        *,
        q: str | None = None,
        page: int = 1,
        page_size: int = 24,
        authorized_roots: Iterable[str] = (),
    ) -> dict[str, Any]:
        """List the public active catalog without changing legacy list_items semantics.

        Root authorization and active-state filtering are applied to the full
        candidate set before the page slice is computed. Paths returned here
        are the stored library-relative paths only; no filesystem resolution
        or absolute path is ever introduced by the repository.
        """
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise ValueError("page must be a positive integer")
        if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 100:
            raise ValueError("page_size must be an integer between 1 and 100")
        roots = tuple(str(root).strip().replace("\\", "/").strip("/") for root in authorized_roots)
        roots = tuple(root for root in roots if root)
        query = None if q is None else str(q).strip()

        clauses = ["enabled=1"]
        params: list[Any] = []
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append("(LOWER(title) LIKE LOWER(?) ESCAPE '\\' OR LOWER(description) LIKE LOWER(?) ESCAPE '\\')")
            pattern = f"%{escaped}%"
            params.extend((pattern, pattern))
        # JSON1 is available in current SQLite builds, but it was not present
        # in some older Python/SQLite combinations. Keep the legacy Python
        # path as a compatibility fallback rather than making malformed or
        # old metadata rows disappear (or making the endpoint fail to open).
        # The probe result is cached per process (see _json1_available).
        if not self._json1_available(self._conn):
            return self._list_catalog_python(
                clauses=clauses,
                params=params,
                page=page,
                page_size=page_size,
                authorized_roots=roots,
            )

        # The expression mirrors _catalog_path_is_allowed for the relative
        # path forms used by the schema. Status and path authorization are
        # therefore applied by SQLite before COUNT/LIMIT/OFFSET. The service
        # still keeps its defensive public-DTO gate for adapter compatibility.
        normalized_path = "replace(trim(path), char(92), '/')"
        path_clauses = [
            f"{normalized_path} <> ''",
            f"substr({normalized_path}, 1, 1) <> '/'",
            f"(length({normalized_path}) < 2 OR substr({normalized_path}, 2, 1) <> ':')",
            f"instr({normalized_path}, '//') = 0",
            f"instr('/' || {normalized_path} || '/', '/./') = 0",
            f"instr('/' || {normalized_path} || '/', '/../') = 0",
        ]
        if roots:
            root_clauses: list[str] = []
            for root in roots:
                root_clauses.append(
                    f"({normalized_path} = ? OR "
                    f"substr({normalized_path}, 1, length(?) + 1) = ? || '/')"
                )
                params.extend((root, root, root))
            path_clauses.append("(" + " OR ".join(root_clauses) + ")")
        clauses.extend(path_clauses)

        # An absent/invalid/unrecognised status has always fallen back to the
        # enabled flag. Since this public query already requires enabled=1,
        # only explicit draft/archived statuses need to be excluded. CASE
        # protects json_extract from malformed legacy metadata.
        status_expr = (
            "CASE WHEN json_valid(metadata) "
            "THEN json_extract(metadata, '$.status') ELSE NULL END"
        )
        clauses.append(
            f"({status_expr} IS NULL OR {status_expr} NOT IN ('draft', 'archived'))"
        )
        where = " AND ".join(clauses)
        count_row = self._conn.execute(
            "SELECT COUNT(*) FROM shop_items WHERE " + where,
            tuple(params),
        ).fetchone()
        total = 0 if count_row is None else int(count_row[0])
        offset = (page - 1) * page_size
        rows = self._conn.execute(
            "SELECT id, path, title, description, price_cents, currency, cover_path, "
            "enabled, metadata, created_at, updated_at FROM shop_items WHERE "
            + where
            + " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            tuple(params) + (page_size, offset),
        ).fetchall()
        public_items = [self._row_to_dict(row) for row in rows]
        return {
            "items": public_items,
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    def _list_catalog_python(
        self,
        *,
        clauses: list[str],
        params: list[Any],
        page: int,
        page_size: int,
        authorized_roots: tuple[str, ...],
    ) -> dict[str, Any]:
        """Compatibility implementation for SQLite builds without JSON1."""
        rows = self._conn.execute(
            "SELECT id, path, title, description, price_cents, currency, cover_path, "
            "enabled, metadata, created_at, updated_at FROM shop_items WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at DESC, id DESC",
            tuple(params),
        ).fetchall()
        public_items = [
            item
            for row in rows
            for item in (self._row_to_dict(row),)
            if self._catalog_status(item) == "active"
            and self._catalog_path_is_allowed(item.get("path"), authorized_roots)
        ]
        offset = (page - 1) * page_size
        return {
            "items": public_items[offset : offset + page_size],
            "page": page,
            "page_size": page_size,
            "total": len(public_items),
        }

    @_repository_operation
    def update_item(self, item_id: int, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "path", "title", "description", "price_cents", "currency", "cover_path",
            "enabled", "metadata",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise TypeError(f"unsupported shop item fields: {', '.join(sorted(unknown))}")
        current_row = self._select_item(int(item_id))
        if current_row is None:
            return None
        current = self._row_to_dict(current_row)
        path = str(fields.get("path", current["path"])).strip()
        if not path:
            raise ValueError("path must not be empty")
        title, price_cents, currency = self._validate_fields(
            title=fields.get("title", current["title"]),
            price_cents=fields.get("price_cents", current["price_cents"]),
            currency=fields.get("currency", current["currency"]),
        )
        timestamp = time.time()
        with _transaction(self._conn, "shop_item_update"):
            try:
                self._conn.execute(
                    "UPDATE shop_items SET path=?, title=?, description=?, price_cents=?, "
                    "currency=?, cover_path=?, enabled=?, metadata=?, updated_at=? WHERE id=?",
                    (
                        path,
                        title,
                        str(fields.get("description", current["description"])),
                        price_cents,
                        currency,
                        fields.get("cover_path", current["cover_path"]),
                        int(bool(fields.get("enabled", current["enabled"]))),
                        _json_dump(fields.get("metadata", current["metadata"])),
                        timestamp,
                        int(item_id),
                    ),
                )
            except IntegrityError as exc:
                # Moving onto a path already claimed by another row violates
                # the UNIQUE constraint; surface it as a business error.
                raise DuplicateError("shop item", path) from exc
            row = self._select_item(int(item_id))
            return None if row is None else self._row_to_dict(row)

    @_repository_operation
    def delete_item(self, item_id: int) -> bool:
        """Delete an unreferenced item; SQLite rejects items retained by orders."""
        with _transaction(self._conn, "shop_item_delete"):
            cursor = self._conn.execute("DELETE FROM shop_items WHERE id=?", (int(item_id),))
            return cursor.rowcount > 0

    # Compatibility aliases for lower-level callers.
    get = get_item
    list_active = list_items
    delete = delete_item


__all__ = ["ShopRepository"]
