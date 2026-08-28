"""Session-bound repository for per-library Commerce catalog items."""
from __future__ import annotations

import threading
import time
from sqlite3 import Connection, IntegrityError, OperationalError
from typing import Any, Iterable

from AssetsManager.core.database import locked_read
from AssetsManager.domain.errors import (
    DuplicateError,
    OperationNotPermitted,
)
from AssetsManager.repositories._common import (
    _CommerceRepository,
    _json_dump,
    _json_load,
    _repository_operation,
    _transaction,
)
# Backwards-compatible re-exports: the shared session/transaction plumbing
# moved to ``repositories/_common.py``.  Existing ``shop_repository`` import
# paths keep working; new code imports these from ``_common`` directly.
from AssetsManager.repositories._common import (  # noqa: F401
    _ensure_commerce_schema as _ensure_commerce_schema,
    _require_session_contract as _require_session_contract,
    _session_root as _session_root,
)


class ShopItemVersionConflictError(OperationNotPermitted):
    """Optimistic-concurrency rejection for shop item updates (HTTP 409)."""

    code = "shop_item_version_conflict"

    def __init__(self) -> None:
        super().__init__("Shop item was updated concurrently")


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
            "total": len(public_items),
        }

    @_repository_operation
    def update_item(
        self,
        item_id: int,
        *,
        expected_updated_at: float | None = None,
        **fields: Any,
    ) -> dict[str, Any] | None:
        allowed = {
            "path", "title", "description", "price_cents", "currency", "cover_path",
            "enabled", "metadata",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise TypeError(f"unsupported shop item fields: {', '.join(sorted(unknown))}")
        # The baseline row must be read under the same db_write_lock window as
        # the UPDATE below. Reading it before entering the transaction left a
        # TOCTOU gap in which another thread sharing this connection could run
        # a full update_item; replaying this stale baseline afterwards silently
        # dropped that writer's columns (lost update).
        with _transaction(self._conn, "shop_item_update"):
            current_row = self._select_item(int(item_id))
            if current_row is None:
                return None
            current = self._row_to_dict(current_row)
            if (
                expected_updated_at is not None
                and float(current["updated_at"]) != float(expected_updated_at)
            ):
                # Optimistic guard: the caller pinned its baseline timestamp and
                # another writer committed first. Cheap version column (schema
                # v35) stays unnecessary for this check.
                raise ShopItemVersionConflictError()
            path = str(fields.get("path", current["path"])).strip()
            if not path:
                raise ValueError("path must not be empty")
            title, price_cents, currency = self._validate_fields(
                title=fields.get("title", current["title"]),
                price_cents=fields.get("price_cents", current["price_cents"]),
                currency=fields.get("currency", current["currency"]),
            )
            timestamp = time.time()
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
