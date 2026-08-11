"""Atomic download-quota repository for Commerce delivery tokens."""
from __future__ import annotations

import time
from typing import Any

from AssetsManager.repositories.shop_repository import (
    _CommerceRepository,
    _repository_operation,
    _transaction,
)


class QuotaRepository(_CommerceRepository):
    """Issue, inspect, revoke, and atomically consume hashed delivery tokens."""

    @staticmethod
    def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        max_downloads = int(row[4])
        download_count = int(row[5])
        return {
            "token_hash": str(row[0]),
            "order_id": int(row[1]),
            "share_id": None if row[2] is None else str(row[2]),
            "delivery_path": str(row[3]),
            "max_downloads": max_downloads,
            "download_count": download_count,
            "remaining_downloads": max(0, max_downloads - download_count),
            "expires_at": None if row[6] is None else float(row[6]),
            "revoked_at": None if row[7] is None else float(row[7]),
            "created_at": float(row[8]),
            "last_download_at": None if row[9] is None else float(row[9]),
        }

    def _select_token(self, token_hash: str) -> tuple[Any, ...] | None:
        return self._conn.execute(
            "SELECT token_hash, order_id, share_id, delivery_path, max_downloads, "
            "download_count, expires_at, revoked_at, created_at, last_download_at "
            "FROM shop_delivery_tokens WHERE token_hash=?",
            (token_hash,),
        ).fetchone()

    @_repository_operation
    def issue(
        self,
        token_hash: str,
        order_id: int,
        *,
        max_downloads: int,
        delivery_path: str | None = None,
        expires_at: float | None = None,
        share_id: str | None = None,
        created_at: float | None = None,
    ) -> dict[str, Any]:
        """Persist only the token hash; raw bearer tokens are never stored."""
        token_hash = str(token_hash).strip()
        if not token_hash:
            raise ValueError("token_hash must not be empty")
        if not isinstance(order_id, int) or isinstance(order_id, bool) or order_id <= 0:
            raise ValueError("order_id must be a positive integer")
        if (
            not isinstance(max_downloads, int)
            or isinstance(max_downloads, bool)
            or max_downloads <= 0
        ):
            raise ValueError("max_downloads must be a positive integer")
        timestamp = time.time() if created_at is None else float(created_at)
        with _transaction(self._conn, "shop_delivery_issue"):
            if delivery_path is None:
                order = self._conn.execute(
                    "SELECT item_path FROM shop_orders WHERE id=?", (order_id,)
                ).fetchone()
                if order is None:
                    raise LookupError(f"shop order does not exist: {order_id}")
                delivery_path = str(order[0])
            delivery_path = str(delivery_path).strip()
            if not delivery_path:
                raise ValueError("delivery_path must not be empty")
            self._conn.execute(
                "INSERT INTO shop_delivery_tokens "
                "(token_hash, order_id, share_id, delivery_path, max_downloads, "
                "download_count, expires_at, revoked_at, created_at, last_download_at) "
                "VALUES (?, ?, ?, ?, ?, 0, ?, NULL, ?, NULL)",
                (
                    token_hash,
                    order_id,
                    share_id,
                    delivery_path,
                    max_downloads,
                    expires_at,
                    timestamp,
                ),
            )
            row = self._select_token(token_hash)
            assert row is not None
            return self._row_to_dict(row)

    @_repository_operation
    def get(self, token_hash: str) -> dict[str, Any] | None:
        row = self._select_token(token_hash)
        return None if row is None else self._row_to_dict(row)

    @_repository_operation
    def consume(
        self, token_hash: str, amount: int = 1, *, now: float | None = None
    ) -> dict[str, Any] | None:
        """Atomically consume units if the token is live and remains within quota."""
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ValueError("amount must be a positive integer")
        timestamp = time.time() if now is None else float(now)
        with _transaction(self._conn, "shop_delivery_consume"):
            row = self._conn.execute(
                "UPDATE shop_delivery_tokens "
                "SET download_count=download_count+?, last_download_at=? "
                "WHERE token_hash=? AND revoked_at IS NULL "
                "AND (expires_at IS NULL OR expires_at>?) "
                "AND download_count+?<=max_downloads "
                "RETURNING token_hash, order_id, share_id, delivery_path, max_downloads, "
                "download_count, expires_at, revoked_at, created_at, last_download_at",
                (amount, timestamp, token_hash, timestamp, amount),
            ).fetchone()
            return None if row is None else self._row_to_dict(row)

    @_repository_operation
    def revoke(self, token_hash: str, *, revoked_at: float | None = None) -> bool:
        timestamp = time.time() if revoked_at is None else float(revoked_at)
        with _transaction(self._conn, "shop_delivery_revoke"):
            cursor = self._conn.execute(
                "UPDATE shop_delivery_tokens SET revoked_at=? "
                "WHERE token_hash=? AND revoked_at IS NULL",
                (timestamp, token_hash),
            )
            return cursor.rowcount > 0

    @_repository_operation
    def get_quota(self) -> dict[str, int]:
        row = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(max_downloads), 0), "
            "COALESCE(SUM(download_count), 0) FROM shop_delivery_tokens "
            "WHERE revoked_at IS NULL"
        ).fetchone()
        assert row is not None
        return {
            "delivery_tokens": int(row[0]),
            "download_limit": int(row[1]),
            "downloads_used": int(row[2]),
            "downloads_remaining": max(0, int(row[1]) - int(row[2])),
        }

    get_usage = get_quota

    @_repository_operation
    def delete_for_order(self, order_id: int | str) -> int:
        with _transaction(self._conn, "shop_delivery_delete"):
            cursor = self._conn.execute(
                "DELETE FROM shop_delivery_tokens WHERE order_id=?", (order_id,)
            )
            return cursor.rowcount


__all__ = ["QuotaRepository"]
