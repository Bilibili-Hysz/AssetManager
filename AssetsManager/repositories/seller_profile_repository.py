"""Repository for the single seller profile owned by one library database."""
from __future__ import annotations

import time
from collections.abc import Mapping
from sqlite3 import Connection
from typing import Any

from AssetsManager.core.schema_defs import (
    SCHEMA_OBJECT_CONTRACT,
    SELLER_PROFILE_SCHEMA,
    validate_schema_object,
    validate_schema_objects,
)
from AssetsManager.repositories.shop_repository import (
    _CommerceRepository,
    _repository_operation,
    _transaction,
    locked_read,
)


_TABLE = "seller_profile"
_PROFILE_FIELDS = frozenset({
    "store_name",
    "contact_email",
    "description",
    "accept_orders",
})


def _ensure_seller_profile_schema(conn: Connection) -> None:
    """Ensure the v12 table is present for explicit raw-connection compatibility."""
    with _transaction(conn, "seller_profile_repository_init"):
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (_TABLE,),
        ).fetchone() is not None:
            contract = dict(SCHEMA_OBJECT_CONTRACT[_TABLE])
            contract.pop("indexes", None)
            validate_schema_object(conn, _TABLE, contract)  # type: ignore[arg-type]
        for statement in SELLER_PROFILE_SCHEMA.split(";"):
            if sql := statement.strip():
                conn.execute(sql)
        conn.execute(
            "INSERT OR IGNORE INTO seller_profile "
            "(id, store_name, contact_email, description, accept_orders) "
            "VALUES (1, '', '', '', 1)"
        )
        validate_schema_objects(conn, (_TABLE,))


class SellerProfileRepository(_CommerceRepository):
    """Persist the one seller profile row for the bound library."""

    def init_tables(self) -> None:
        """Compatibility ensure for raw connections; migration v12 owns the schema."""
        _ensure_seller_profile_schema(self._conn)

    @staticmethod
    def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "store_name": str(row[0]),
            "contact_email": str(row[1]),
            "description": str(row[2]),
            "accept_orders": bool(row[3]),
            "updated_at": float(row[4]),
        }

    def _ensure_profile_row(self) -> None:
        with _transaction(self._conn, "seller_profile_row_init"):
            self._conn.execute(
                "INSERT OR IGNORE INTO seller_profile "
                "(id, store_name, contact_email, description, accept_orders) "
                "VALUES (1, '', '', '', 1)"
            )

    @locked_read
    def _select_profile(self) -> tuple[Any, ...] | None:
        return self._conn.execute(
            "SELECT store_name, contact_email, description, accept_orders, updated_at "
            "FROM seller_profile WHERE id=1"
        ).fetchone()

    @_repository_operation
    def get_profile(self) -> dict[str, Any]:
        self._ensure_profile_row()
        row = self._select_profile()
        if row is None:  # pragma: no cover - protected by the table invariant
            raise RuntimeError("seller profile row could not be created")
        return self._row_to_dict(row)

    @_repository_operation
    def update_profile(self, fields: Mapping[str, Any]) -> dict[str, Any]:
        unknown = set(fields) - _PROFILE_FIELDS
        if unknown:
            names = ", ".join(sorted(str(name) for name in unknown))
            raise ValueError(f"unknown seller profile field(s): {names}")
        self._ensure_profile_row()
        if fields:
            assignments = []
            values: list[Any] = []
            for name in ("store_name", "contact_email", "description", "accept_orders"):
                if name in fields:
                    assignments.append(f"{name}=?")
                    values.append(fields[name])
            assignments.append("updated_at=?")
            values.append(time.time())
            values.append(1)
            with _transaction(self._conn, "seller_profile_update"):
                self._conn.execute(
                    f"UPDATE seller_profile SET {', '.join(assignments)} WHERE id=?",
                    tuple(values),
                )
        row = self._select_profile()
        if row is None:  # pragma: no cover - protected by the table invariant
            raise RuntimeError("seller profile row disappeared during update")
        return self._row_to_dict(row)


__all__ = ["SellerProfileRepository"]
