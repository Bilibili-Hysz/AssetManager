"""Session-bound repository for Commerce orders and their audit events."""
from __future__ import annotations

import logging
import time
from typing import Any

from AssetsManager.domain.errors import (
    NotFoundError,
    OperationNotPermitted,
    StoreNotAcceptingOrdersError,
)
from AssetsManager.repositories.shop_repository import (
    _CommerceRepository,
    _json_dump,
    _json_load,
    _repository_operation,
    _transaction,
)

_log = logging.getLogger(__name__)

# Canonical order-status whitelist shared with the application layer
# (AssetsManager/application/order_service.py imports these constants so the
# repository CAS and the service state machine can never diverge).
ORDER_STATUSES = frozenset({"pending", "confirmed", "fulfilled", "revoked"})
ALLOWED_TRANSITIONS = {
    "pending": frozenset({"confirmed", "revoked"}),
    "confirmed": frozenset({"fulfilled", "revoked"}),
    "fulfilled": frozenset(),
    "revoked": frozenset(),
}


class OrderRepository(_CommerceRepository):
    """Persist order snapshots, status events, and guarded delivery state."""

    @staticmethod
    def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "id": int(row[0]),
            "item_id": int(row[1]),
            "item_path": str(row[2]),
            "item_title": str(row[3]),
            "buyer_name": None if row[4] is None else str(row[4]),
            "buyer_email": None if row[5] is None else str(row[5]),
            "buyer_owner_type": None if row[6] is None else str(row[6]),
            "buyer_owner_key": None if row[7] is None else str(row[7]),
            "amount_cents": int(row[8]),
            "currency": str(row[9]),
            "status": str(row[10]),
            "metadata": _json_load(row[11]),
            "created_at": float(row[12]),
            "updated_at": float(row[13]),
        }

    @staticmethod
    def _delivery_row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        result = OrderRepository._row_to_dict(row[:14])
        result.update(
            {
                "delivery_token_hash": str(row[14]),
                "share_id": None if row[15] is None else str(row[15]),
                "delivery_path": str(row[16]),
                "max_downloads": int(row[17]),
                "download_count": int(row[18]),
                "expires_at": None if row[19] is None else float(row[19]),
                "revoked_at": None if row[20] is None else float(row[20]),
                "last_download_at": None if row[21] is None else float(row[21]),
            }
        )
        return result

    @staticmethod
    def _event_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "id": int(row[0]),
            "order_id": int(row[1]),
            "event_type": str(row[2]),
            "from_status": None if row[3] is None else str(row[3]),
            "to_status": None if row[4] is None else str(row[4]),
            "actor_key": None if row[5] is None else str(row[5]),
            "payload": _json_load(row[6]),
            "created_at": float(row[7]),
        }

    def _select_order(self, order_id: int | str) -> tuple[Any, ...] | None:
        return self._conn.execute(
            "SELECT id, item_id, item_path, item_title, buyer_name, buyer_email, "
            "buyer_owner_type, buyer_owner_key, amount_cents, currency, status, metadata, created_at, updated_at "
            "FROM shop_orders WHERE id=?",
            (order_id,),
        ).fetchone()

    def _insert_event(
        self,
        order_id: int,
        event_type: str,
        *,
        from_status: str | None = None,
        to_status: str | None = None,
        actor_key: str | None = None,
        payload: dict[str, Any] | None = None,
        created_at: float,
    ) -> int:
        event_type = str(event_type).strip()
        if not event_type:
            raise ValueError("event_type must not be empty")
        cursor = self._conn.execute(
            "INSERT INTO shop_order_events "
            "(order_id, event_type, from_status, to_status, actor_key, payload, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                order_id,
                event_type,
                from_status,
                to_status,
                actor_key,
                _json_dump(payload),
                created_at,
            ),
        )
        lastrowid = cursor.lastrowid
        if lastrowid is None:
            raise RuntimeError("order event insert did not return a row id")
        return int(lastrowid)

    @_repository_operation
    def create_order(
        self,
        *,
        item_id: int,
        buyer_name: str | None = None,
        buyer_email: str | None = None,
        buyer_owner_type: str | None = None,
        buyer_owner_key: str | None = None,
        amount_cents: int,
        currency: str,
        status: str = "pending",
        metadata: dict[str, Any] | None = None,
        actor_key: str | None = None,
        created_at: float | None = None,
        receipt_token_hash: str | None = None,
        receipt_expires_at: float | None = None,
        require_accepting_orders: bool = False,
    ) -> dict[str, Any]:
        status = str(status).strip()
        if (buyer_owner_type is None) != (buyer_owner_key is None):
            raise ValueError("buyer_owner_type and buyer_owner_key must be supplied together")
        if buyer_owner_type is not None:
            buyer_owner_type = str(buyer_owner_type).strip()
            buyer_owner_key = str(buyer_owner_key).strip()
            if buyer_owner_type not in {"user", "anonymous"} or not buyer_owner_key:
                raise ValueError("invalid buyer owner")
        currency = str(currency).strip().upper()
        if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
            raise ValueError("item_id must be a positive integer")
        if (
            not isinstance(amount_cents, int)
            or isinstance(amount_cents, bool)
            or amount_cents < 0
        ):
            raise ValueError("amount_cents must be a non-negative integer")
        if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
            raise ValueError("currency must be a three-letter code")
        if not status:
            raise ValueError("status must not be empty")
        timestamp = time.time() if created_at is None else float(created_at)
        receipt_hash = None if receipt_token_hash is None else str(receipt_token_hash).strip()
        receipt_expiry: float | None = None
        if receipt_hash is not None:
            if not receipt_hash:
                raise ValueError("receipt_token_hash must not be empty")
            if receipt_expires_at is None:
                raise ValueError("receipt_expires_at must be later than created_at")
            receipt_expiry = float(receipt_expires_at)
            if receipt_expiry <= timestamp:
                raise ValueError("receipt_expires_at must be later than created_at")
        elif receipt_expires_at is not None:
            raise ValueError("receipt_token_hash is required with receipt_expires_at")

        with _transaction(self._conn, "shop_order_create"):
            if require_accepting_orders:
                profile = self._conn.execute(
                    "SELECT accept_orders FROM seller_profile WHERE id=1"
                ).fetchone()
                if profile is None or not bool(profile[0]):
                    raise StoreNotAcceptingOrdersError()
            item = self._conn.execute(
                "SELECT path, title FROM shop_items WHERE id=?", (item_id,)
            ).fetchone()
            if item is None:
                raise LookupError(f"shop item does not exist: {item_id}")
            cursor = self._conn.execute(
                "INSERT INTO shop_orders "
                "(item_id, item_path, item_title, buyer_name, buyer_email, buyer_owner_type, "
                "buyer_owner_key, amount_cents, currency, status, metadata, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item_id,
                    item[0],
                    item[1],
                    buyer_name,
                    buyer_email,
                    buyer_owner_type,
                    buyer_owner_key,
                    amount_cents,
                    currency,
                    status,
                    _json_dump(metadata),
                    timestamp,
                    timestamp,
                ),
            )
            lastrowid = cursor.lastrowid
            if lastrowid is None:
                raise RuntimeError("order insert did not return a row id")
            order_id = int(lastrowid)
            if receipt_hash is not None:
                self._conn.execute(
                    "INSERT INTO shop_order_receipts "
                    "(token_hash, order_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                    (receipt_hash, order_id, timestamp, receipt_expiry),
                )
            self._insert_event(
                order_id,
                "created",
                to_status=status,
                actor_key=actor_key,
                payload={"item_id": item_id},
                created_at=timestamp,
            )
            row = self._select_order(order_id)
            assert row is not None
            return self._row_to_dict(row)

    @_repository_operation
    def get_order(self, order_id: int | str) -> dict[str, Any] | None:
        row = self._select_order(order_id)
        return None if row is None else self._row_to_dict(row)

    @_repository_operation
    def list_orders(
        self, *, status: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        where = " WHERE status=?" if status is not None else ""
        parameters: tuple[object, ...] = (
            (status, max(1, min(int(limit), 5000)))
            if status is not None
            else (max(1, min(int(limit), 5000)),)
        )
        rows = self._conn.execute(
            "SELECT id, item_id, item_path, item_title, buyer_name, buyer_email, "
            "buyer_owner_type, buyer_owner_key, amount_cents, currency, status, metadata, created_at, updated_at "
            f"FROM shop_orders{where} ORDER BY created_at DESC, id DESC LIMIT ?",
            parameters,
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    @_repository_operation
    def list_orders_by_owner(
        self, *, owner_type: str, owner_key: str, status: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        where = "buyer_owner_type=? AND buyer_owner_key=?"
        parameters: list[object] = [owner_type, owner_key]
        if status is not None:
            where += " AND status=?"
            parameters.append(status)
        parameters.append(max(1, min(int(limit), 1000)))
        rows = self._conn.execute(
            "SELECT id, item_id, item_path, item_title, buyer_name, buyer_email, "
            "buyer_owner_type, buyer_owner_key, amount_cents, currency, status, metadata, created_at, updated_at "
            f"FROM shop_orders WHERE {where} ORDER BY created_at DESC, id DESC LIMIT ?",
            tuple(parameters),
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    @_repository_operation
    def transition_status(
        self,
        order_id: int | str,
        *,
        expected_status: str,
        new_status: str,
        actor_key: str | None = None,
        payload: dict[str, Any] | None = None,
        updated_at: float | None = None,
    ) -> dict[str, Any] | None:
        new_status = str(new_status).strip()
        if not new_status:
            raise ValueError("new_status must not be empty")
        if new_status not in ORDER_STATUSES:
            raise ValueError(f"new_status must be one of {sorted(ORDER_STATUSES)}")
        timestamp = time.time() if updated_at is None else float(updated_at)
        with _transaction(self._conn, "shop_order_status"):
            cursor = self._conn.execute(
                "UPDATE shop_orders SET status=?, updated_at=? WHERE id=? AND status=?",
                (new_status, timestamp, order_id, expected_status),
            )
            if cursor.rowcount <= 0:
                return None
            resolved_id = int(order_id)
            if new_status == "revoked":
                self._conn.execute(
                    "UPDATE shop_order_receipts SET revoked_at=? "
                    "WHERE order_id=? AND revoked_at IS NULL",
                    (timestamp, resolved_id),
                )
                self._conn.execute(
                    "UPDATE shop_order_receipt_recoveries SET revoked_at=? "
                    "WHERE order_id=? AND revoked_at IS NULL",
                    (timestamp, resolved_id),
                )
            self._insert_event(
                resolved_id,
                "status_changed",
                from_status=expected_status,
                to_status=new_status,
                actor_key=actor_key,
                payload=payload,
                created_at=timestamp,
            )
            row = self._select_order(resolved_id)
            return None if row is None else self._row_to_dict(row)

    @_repository_operation
    def transition_status_by_receipt(
        self,
        order_id: int | str,
        *,
        receipt_token_hash: str,
        expected_status: str,
        new_status: str,
        updated_at: float | None = None,
    ) -> dict[str, Any] | None:
        timestamp = time.time() if updated_at is None else float(updated_at)
        with _transaction(self._conn, "shop_order_receipt_status"):
            cursor = self._conn.execute(
                "UPDATE shop_orders SET status=?, updated_at=? WHERE id=? AND status=? "
                "AND (EXISTS (SELECT 1 FROM shop_order_receipts r "
                "WHERE r.order_id=shop_orders.id AND r.token_hash=? "
                "AND r.revoked_at IS NULL AND r.expires_at>?) "
                "OR EXISTS (SELECT 1 FROM shop_order_receipt_recoveries rr "
                "WHERE rr.order_id=shop_orders.id AND rr.token_hash=? "
                "AND rr.revoked_at IS NULL AND rr.expires_at>?))",
                (
                    new_status,
                    timestamp,
                    order_id,
                    expected_status,
                    receipt_token_hash,
                    timestamp,
                    receipt_token_hash,
                    timestamp,
                ),
            )
            if cursor.rowcount != 1:
                return None
            resolved_id = int(order_id)
            self._insert_event(
                resolved_id,
                "status_changed",
                from_status=expected_status,
                to_status=new_status,
                created_at=timestamp,
            )
            row = self._select_order(resolved_id)
            return None if row is None else self._row_to_dict(row)

    @_repository_operation
    def fulfill_order(
        self,
        order_id: int | str,
        *,
        expected_status: str,
        delivery_token_hash: str,
        delivery_path: str,
        max_downloads: int,
        expires_at: float | None,
        share_id: str | None = None,
        fulfilled_at: float | None = None,
    ) -> dict[str, Any] | None:
        token_hash = str(delivery_token_hash).strip()
        delivery_path = str(delivery_path).strip()
        if not token_hash:
            raise ValueError("delivery_token_hash must not be empty")
        if not delivery_path:
            raise ValueError("delivery_path must not be empty")
        if (
            not isinstance(max_downloads, int)
            or isinstance(max_downloads, bool)
            or max_downloads <= 0
        ):
            raise ValueError("max_downloads must be a positive integer")
        timestamp = time.time() if fulfilled_at is None else float(fulfilled_at)
        with _transaction(self._conn, "shop_order_fulfill"):
            cursor = self._conn.execute(
                "UPDATE shop_orders SET status='fulfilled', updated_at=? "
                "WHERE id=? AND status=?",
                (timestamp, order_id, expected_status),
            )
            if cursor.rowcount <= 0:
                return None
            resolved_id = int(order_id)
            self._conn.execute(
                "INSERT INTO shop_delivery_tokens "
                "(token_hash, order_id, share_id, delivery_path, max_downloads, "
                "download_count, expires_at, created_at) VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
                (
                    token_hash,
                    resolved_id,
                    share_id,
                    delivery_path,
                    max_downloads,
                    expires_at,
                    timestamp,
                ),
            )
            self._insert_event(
                resolved_id,
                "fulfilled",
                from_status=expected_status,
                to_status="fulfilled",
                payload={"max_downloads": max_downloads, "expires_at": expires_at},
                created_at=timestamp,
            )
            row = self._select_order(resolved_id)
            return None if row is None else self._row_to_dict(row)

    @_repository_operation
    def rotate_fulfilled_delivery(
        self,
        order_id: int | str,
        *,
        delivery_token_hash: str,
        delivery_path: str,
        max_downloads: int | None = None,
        expires_at: float | None = None,
        rotated_at: float | None = None,
    ) -> dict[str, Any] | None:
        """Issue a replacement bearer token, revoking the previous live one.

        The new token inherits only the remaining quota of the newest live
        token (``max_downloads - download_count``) so repeated rotation can
        never mint fresh full-quota tokens; the source token is revoked in
        the same transaction so the order's total download quota is
        conserved and a leaked delivery link stops working on rotation.
        ``max_downloads`` is an optional seller-supplied cap; the effective
        quota is ``min(remaining, cap)``. Rotation is rejected once no quota
        remains.
        """
        token_hash = str(delivery_token_hash).strip()
        path = str(delivery_path).strip()
        if not token_hash:
            raise ValueError("delivery_token_hash must not be empty")
        if not path:
            raise ValueError("delivery_path must not be empty")
        if max_downloads is not None and (
            not isinstance(max_downloads, int)
            or isinstance(max_downloads, bool)
            or max_downloads <= 0
        ):
            raise ValueError("max_downloads must be a positive integer")
        timestamp = time.time() if rotated_at is None else float(rotated_at)
        with _transaction(self._conn, "shop_order_delivery_rotate"):
            current = self._select_order(order_id)
            if current is None:
                raise NotFoundError("order", str(order_id))
            if str(current[10]) != "fulfilled":
                raise OperationNotPermitted("Only fulfilled orders can rotate delivery")
            resolved_id = int(order_id)
            previous = self._conn.execute(
                "SELECT token_hash, max_downloads, download_count FROM shop_delivery_tokens "
                "WHERE order_id=? AND revoked_at IS NULL "
                "AND (expires_at IS NULL OR expires_at > ?) "
                "ORDER BY rowid DESC LIMIT 1",
                (resolved_id, timestamp),
            ).fetchone()
            if previous is None:
                raise OperationNotPermitted("No delivery token exists to rotate")
            remaining = int(previous[1]) - int(previous[2])
            if remaining <= 0:
                raise OperationNotPermitted("No download quota remains to rotate")
            if max_downloads is not None:
                remaining = min(remaining, max_downloads)
            self._conn.execute(
                "INSERT INTO shop_delivery_tokens "
                "(token_hash, order_id, share_id, delivery_path, max_downloads, "
                "download_count, expires_at, revoked_at, created_at, last_download_at) "
                "VALUES (?, ?, NULL, ?, ?, 0, ?, NULL, ?, NULL)",
                (token_hash, resolved_id, path, remaining, expires_at, timestamp),
            )
            # Revoke the source token so the order's total quota stays
            # conserved and a leaked link stops working on rotation.
            self._conn.execute(
                "UPDATE shop_delivery_tokens SET revoked_at=? WHERE token_hash=?",
                (timestamp, str(previous[0])),
            )
            self._insert_event(
                resolved_id,
                "delivery_rotated",
                from_status="fulfilled",
                to_status="fulfilled",
                payload={"max_downloads": remaining, "expires_at": expires_at},
                created_at=timestamp,
            )
            row = self._select_order(resolved_id)
            return None if row is None else self._row_to_dict(row)

    @_repository_operation
    def get_receipt_state(self, order_id: int | str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT created_at,expires_at,revoked_at FROM shop_order_receipts WHERE order_id=?",
            (order_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "created_at": float(row[0]),
            "expires_at": float(row[1]),
            "revoked_at": None if row[2] is None else float(row[2]),
        }

    @_repository_operation
    def create_receipt_recovery(
        self,
        order_id: int | str,
        *,
        token_hash: str,
        created_at: float,
        expires_at: float,
    ) -> None:
        token_hash = str(token_hash).strip()
        if not token_hash:
            raise ValueError("token_hash must not be empty")
        if expires_at <= created_at:
            raise ValueError("expires_at must be later than created_at")
        with _transaction(self._conn, "shop_order_receipt_recovery"):
            self._conn.execute(
                "DELETE FROM shop_order_receipt_recoveries "
                "WHERE order_id=? AND (revoked_at IS NOT NULL OR expires_at<=?)",
                (order_id, created_at),
            )
            self._conn.execute(
                "INSERT INTO shop_order_receipt_recoveries "
                "(token_hash,order_id,created_at,expires_at,revoked_at) "
                "VALUES(?,?,?,?,NULL)",
                (token_hash, order_id, created_at, expires_at),
            )

    @_repository_operation
    def get_order_with_receipt(
        self, order_id: int | str, token_hash: str
    ) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT o.id, o.item_id, o.item_path, o.item_title, o.buyer_name, "
            "o.buyer_email, o.buyer_owner_type, o.buyer_owner_key, o.amount_cents, o.currency, o.status, o.metadata, "
            "o.created_at, o.updated_at, r.created_at, r.expires_at, r.revoked_at "
            "FROM shop_orders o JOIN shop_order_receipts r ON r.order_id=o.id "
            "WHERE o.id=? AND r.token_hash=? "
            "UNION ALL "
            "SELECT o.id, o.item_id, o.item_path, o.item_title, o.buyer_name, "
            "o.buyer_email, o.buyer_owner_type, o.buyer_owner_key, o.amount_cents, o.currency, o.status, o.metadata, "
            "o.created_at, o.updated_at, rr.created_at, rr.expires_at, rr.revoked_at "
            "FROM shop_orders o JOIN shop_order_receipt_recoveries rr ON rr.order_id=o.id "
            "WHERE o.id=? AND rr.token_hash=? LIMIT 1",
            (order_id, token_hash, order_id, token_hash),
        ).fetchone()
        if row is None:
            return None
        result = self._row_to_dict(row[:14])
        result.update(
            {
                "receipt_created_at": float(row[14]),
                "receipt_expires_at": float(row[15]),
                "receipt_revoked_at": None if row[16] is None else float(row[16]),
            }
        )
        return result

    @staticmethod
    def _delivery_select(where: str) -> str:
        return (
            "SELECT o.id, o.item_id, o.item_path, o.item_title, o.buyer_name, "
            "o.buyer_email, o.buyer_owner_type, o.buyer_owner_key, o.amount_cents, o.currency, o.status, o.metadata, "
            "o.created_at, o.updated_at, t.token_hash, t.share_id, t.delivery_path, "
            "t.max_downloads, t.download_count, t.expires_at, t.revoked_at, "
            "t.last_download_at FROM shop_orders o JOIN shop_delivery_tokens t "
            f"ON t.order_id=o.id WHERE {where}"
        )

    @_repository_operation
    def get_delivery(self, token_hash: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            self._delivery_select("t.token_hash=?"), (token_hash,)
        ).fetchone()
        return None if row is None else self._delivery_row_to_dict(row)

    @_repository_operation
    def get_delivery_by_order_id(self, order_id: int | str) -> dict[str, Any] | None:
        # "Newest" is the insertion order (rowid), which is immune to clock
        # skew between token issuance paths.
        row = self._conn.execute(
            self._delivery_select("o.id=? ORDER BY t.rowid DESC LIMIT 1"),
            (order_id,),
        ).fetchone()
        return None if row is None else self._delivery_row_to_dict(row)

    @_repository_operation
    def revoke_delivery_tokens(
        self, order_id: int | str, *, revoked_at: float | None = None
    ) -> int:
        """Revoke every outstanding delivery token of an order; returns the count."""
        timestamp = time.time() if revoked_at is None else float(revoked_at)
        with _transaction(self._conn, "shop_delivery_revoke"):
            cursor = self._conn.execute(
                "UPDATE shop_delivery_tokens SET revoked_at=? "
                "WHERE order_id=? AND revoked_at IS NULL",
                (timestamp, order_id),
            )
            return cursor.rowcount

    @staticmethod
    def _delivery_attempt_row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "id": int(row[0]),
            "credential_kind": str(row[1]),
            "credential_hash": str(row[2]),
            "request_key_hash": str(row[3]),
            "order_id": int(row[4]),
            "delivery_token_hash": str(row[5]),
            "state": str(row[6]),
            "reserved_at": float(row[7]),
            "consumed_at": None if row[8] is None else float(row[8]),
            "failed_at": None if row[9] is None else float(row[9]),
            "failure_code": None if row[10] is None else str(row[10]),
        }

    def _select_delivery_attempt(
        self,
        credential_kind: str,
        credential_hash: str,
        request_key_hash: str,
    ) -> tuple[Any, ...] | None:
        return self._conn.execute(
            "SELECT id, credential_kind, credential_hash, request_key_hash, order_id, "
            "delivery_token_hash, state, reserved_at, consumed_at, failed_at, failure_code "
            "FROM shop_delivery_attempts WHERE credential_kind=? AND credential_hash=? "
            "AND request_key_hash=?",
            (credential_kind, credential_hash, request_key_hash),
        ).fetchone()

    @staticmethod
    def _validate_delivery_attempt_args(
        credential_kind: str,
        credential_hash: str,
        request_key_hash: str,
        delivery_token_hash: str,
    ) -> tuple[str, str, str, str]:
        kind = str(credential_kind).strip()
        credential = str(credential_hash).strip()
        request = str(request_key_hash).strip()
        delivery = str(delivery_token_hash).strip()
        if kind not in {"bearer", "receipt"}:
            raise ValueError("credential_kind must be bearer or receipt")
        for field, value in (
            ("credential_hash", credential),
            ("request_key_hash", request),
            ("delivery_token_hash", delivery),
        ):
            if len(value) != 64:
                raise ValueError(f"{field} must be a 64-character hash")
        return kind, credential, request, delivery

    @staticmethod
    def _assert_delivery_attempt_binding(
        row: tuple[Any, ...], order_id: int | str, delivery_token_hash: str
    ) -> None:
        # A receipt remains scoped to the order while seller delivery rotation may
        # issue a newer bearer token between two client retries. Bearer keys remain
        # bound to their exact token so a key cannot cross delivery credentials.
        if int(row[4]) != int(order_id):
            raise OperationNotPermitted("Delivery idempotency key is bound to another delivery")
        if str(row[1]) != "receipt" and str(row[5]) != str(delivery_token_hash):
            raise OperationNotPermitted("Delivery idempotency key is bound to another delivery")

    @_repository_operation
    def get_delivery_attempt(
        self,
        *,
        credential_kind: str,
        credential_hash: str,
        request_key_hash: str,
    ) -> dict[str, Any] | None:
        kind, credential, request, _ = self._validate_delivery_attempt_args(
            credential_kind, credential_hash, request_key_hash, "0" * 64
        )
        row = self._select_delivery_attempt(kind, credential, request)
        return None if row is None else self._delivery_attempt_row_to_dict(row)

    @_repository_operation
    def reserve_delivery_attempt(
        self,
        order_id: int | str,
        *,
        credential_kind: str,
        credential_hash: str,
        request_key_hash: str,
        delivery_token_hash: str,
        reserved_at: float | None = None,
    ) -> str:
        kind, credential, request, delivery = self._validate_delivery_attempt_args(
            credential_kind, credential_hash, request_key_hash, delivery_token_hash
        )
        timestamp = time.time() if reserved_at is None else float(reserved_at)
        with _transaction(self._conn, "shop_delivery_attempt_reserve"):
            row = self._select_delivery_attempt(kind, credential, request)
            if row is None:
                self._conn.execute(
                    "INSERT OR IGNORE INTO shop_delivery_attempts "
                    "(credential_kind, credential_hash, request_key_hash, order_id, "
                    "delivery_token_hash, state, reserved_at) VALUES (?, ?, ?, ?, ?, 'reserved', ?)",
                    (kind, credential, request, int(order_id), delivery, timestamp),
                )
                row = self._select_delivery_attempt(kind, credential, request)
                if row is None:
                    raise RuntimeError("delivery attempt reservation was not persisted")
            self._assert_delivery_attempt_binding(row, order_id, delivery)
            state = str(row[6])
            if state == "failed" and row[10] == "delivery_prepare_failed":
                self._conn.execute(
                    "UPDATE shop_delivery_attempts SET state='reserved', reserved_at=?, "
                    "consumed_at=NULL, failed_at=NULL, failure_code=NULL WHERE id=? AND state='failed'",
                    (timestamp, int(row[0])),
                )
                return "reserved"
            return state

    @_repository_operation
    def fail_delivery_attempt(
        self,
        order_id: int | str,
        *,
        credential_kind: str,
        credential_hash: str,
        request_key_hash: str,
        delivery_token_hash: str,
        failed_at: float | None = None,
        failure_code: str = "delivery_prepare_failed",
    ) -> bool:
        kind, credential, request, delivery = self._validate_delivery_attempt_args(
            credential_kind, credential_hash, request_key_hash, delivery_token_hash
        )
        timestamp = time.time() if failed_at is None else float(failed_at)
        with _transaction(self._conn, "shop_delivery_attempt_fail"):
            row = self._select_delivery_attempt(kind, credential, request)
            if row is None:
                return False
            self._assert_delivery_attempt_binding(row, order_id, delivery)
            cursor = self._conn.execute(
                "UPDATE shop_delivery_attempts SET state='failed', failed_at=?, "
                "failure_code=? WHERE id=? AND state='reserved'",
                (timestamp, str(failure_code), int(row[0])),
            )
            return cursor.rowcount == 1

    @_repository_operation
    def complete_delivery_attempt(
        self,
        order_id: int | str,
        *,
        credential_kind: str,
        credential_hash: str,
        request_key_hash: str,
        delivery_token_hash: str,
        expected_download_count: int,
        consumed_at: float | None = None,
    ) -> str:
        """Consume a bearer delivery slot once for one credential/request key."""
        kind, credential, request, delivery = self._validate_delivery_attempt_args(
            credential_kind, credential_hash, request_key_hash, delivery_token_hash
        )
        if kind != "bearer":
            raise ValueError("complete_delivery_attempt requires a bearer credential")
        timestamp = time.time() if consumed_at is None else float(consumed_at)
        with _transaction(self._conn, "shop_delivery_attempt_complete"):
            row = self._select_delivery_attempt(kind, credential, request)
            if row is None:
                self._conn.execute(
                    "INSERT OR IGNORE INTO shop_delivery_attempts "
                    "(credential_kind, credential_hash, request_key_hash, order_id, "
                    "delivery_token_hash, state, reserved_at) VALUES (?, ?, ?, ?, ?, 'reserved', ?)",
                    (kind, credential, request, int(order_id), delivery, timestamp),
                )
                row = self._select_delivery_attempt(kind, credential, request)
                if row is None:
                    raise RuntimeError("delivery attempt was not persisted")
            self._assert_delivery_attempt_binding(row, order_id, delivery)
            state = str(row[6])
            if state == "consumed":
                return "replayed"
            if state == "failed":
                if row[10] != "delivery_prepare_failed":
                    return "failed"
                self._conn.execute(
                    "UPDATE shop_delivery_attempts SET state='reserved', reserved_at=?, "
                    "consumed_at=NULL, failed_at=NULL, failure_code=NULL WHERE id=? AND state='failed'",
                    (timestamp, int(row[0])),
                )
            cursor = self._conn.execute(
                "UPDATE shop_delivery_tokens SET download_count=download_count+1, "
                "last_download_at=? WHERE order_id=? AND token_hash=? "
                "AND download_count=? AND download_count<max_downloads "
                "AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>?)",
                (
                    timestamp,
                    order_id,
                    delivery,
                    int(expected_download_count),
                    timestamp,
                ),
            )
            if cursor.rowcount != 1:
                self._conn.execute(
                    "UPDATE shop_delivery_attempts SET state='failed', failed_at=?, "
                    "failure_code='delivery_quota_exhausted' WHERE id=? AND state='reserved'",
                    (timestamp, int(row[0])),
                )
                return "failed"
            consumed = self._conn.execute(
                "UPDATE shop_delivery_attempts SET state='consumed', consumed_at=?, "
                "failed_at=NULL, failure_code=NULL WHERE id=? AND state='reserved'",
                (timestamp, int(row[0])),
            )
            if consumed.rowcount != 1:
                # A concurrent connection transitioned the attempt while the
                # token slot was being consumed; report the actual audit state
                # instead of a stale 'consumed' so callers never overcount.
                _log.warning(
                    "Delivery attempt %s changed state while consuming token %s; "
                    "re-reading actual state",
                    row[0],
                    delivery,
                )
                current = self._select_delivery_attempt(kind, credential, request)
                if current is not None and str(current[6]) in {"consumed", "failed"}:
                    return str(current[6])
            return "consumed"

    @_repository_operation
    def complete_delivery_attempt_by_receipt(
        self,
        order_id: int | str,
        *,
        credential_kind: str,
        credential_hash: str,
        request_key_hash: str,
        receipt_token_hash: str,
        delivery_token_hash: str,
        expected_download_count: int,
        consumed_at: float | None = None,
    ) -> str:
        """Consume one receipt-authorized delivery slot once for a request key."""
        kind, credential, request, delivery = self._validate_delivery_attempt_args(
            credential_kind, credential_hash, request_key_hash, delivery_token_hash
        )
        if kind != "receipt":
            raise ValueError("complete_delivery_attempt_by_receipt requires a receipt credential")
        receipt = str(receipt_token_hash).strip()
        if len(receipt) != 64:
            raise ValueError("receipt_token_hash must be a 64-character hash")
        timestamp = time.time() if consumed_at is None else float(consumed_at)
        with _transaction(self._conn, "shop_delivery_attempt_receipt_complete"):
            row = self._select_delivery_attempt(kind, credential, request)
            if row is None:
                self._conn.execute(
                    "INSERT OR IGNORE INTO shop_delivery_attempts "
                    "(credential_kind, credential_hash, request_key_hash, order_id, "
                    "delivery_token_hash, state, reserved_at) VALUES (?, ?, ?, ?, ?, 'reserved', ?)",
                    (kind, credential, request, int(order_id), delivery, timestamp),
                )
                row = self._select_delivery_attempt(kind, credential, request)
                if row is None:
                    raise RuntimeError("delivery attempt was not persisted")
            self._assert_delivery_attempt_binding(row, order_id, delivery)
            state = str(row[6])
            if state == "consumed":
                return "replayed"
            if state == "failed":
                if row[10] != "delivery_prepare_failed":
                    return "failed"
                self._conn.execute(
                    "UPDATE shop_delivery_attempts SET state='reserved', reserved_at=?, "
                    "consumed_at=NULL, failed_at=NULL, failure_code=NULL WHERE id=? AND state='failed'",
                    (timestamp, int(row[0])),
                )
            cursor = self._conn.execute(
                "UPDATE shop_delivery_tokens SET download_count=download_count+1, "
                "last_download_at=? WHERE order_id=? AND token_hash=? "
                "AND download_count=? AND download_count<max_downloads AND revoked_at IS NULL "
                "AND (expires_at IS NULL OR expires_at>?) AND (EXISTS ("
                "SELECT 1 FROM shop_order_receipts r WHERE r.order_id=? "
                "AND r.token_hash=? AND r.revoked_at IS NULL AND r.expires_at>?) "
                "OR EXISTS (SELECT 1 FROM shop_order_receipt_recoveries rr "
                "WHERE rr.order_id=? AND rr.token_hash=? "
                "AND rr.revoked_at IS NULL AND rr.expires_at>?))",
                (
                    timestamp,
                    order_id,
                    delivery,
                    int(expected_download_count),
                    timestamp,
                    order_id,
                    receipt,
                    timestamp,
                    order_id,
                    receipt,
                    timestamp,
                ),
            )
            if cursor.rowcount != 1:
                self._conn.execute(
                    "UPDATE shop_delivery_attempts SET state='failed', failed_at=?, "
                    "failure_code='delivery_quota_exhausted' WHERE id=? AND state='reserved'",
                    (timestamp, int(row[0])),
                )
                return "failed"
            consumed = self._conn.execute(
                "UPDATE shop_delivery_attempts SET state='consumed', consumed_at=?, "
                "failed_at=NULL, failure_code=NULL WHERE id=? AND state='reserved'",
                (timestamp, int(row[0])),
            )
            if consumed.rowcount != 1:
                # A concurrent connection transitioned the attempt while the
                # token slot was being consumed; report the actual audit state
                # instead of a stale 'consumed' so callers never overcount.
                _log.warning(
                    "Delivery attempt %s changed state while consuming receipt "
                    "token %s; re-reading actual state",
                    row[0],
                    delivery,
                )
                current = self._select_delivery_attempt(kind, credential, request)
                if current is not None and str(current[6]) in {"consumed", "failed"}:
                    return str(current[6])
            return "consumed"

    @_repository_operation
    def consume_download(
        self,
        order_id: int | str,
        *,
        token_hash: str,
        expected_download_count: int,
        consumed_at: float | None = None,
    ) -> bool:
        timestamp = time.time() if consumed_at is None else float(consumed_at)
        with _transaction(self._conn, "shop_order_download"):
            cursor = self._conn.execute(
                "UPDATE shop_delivery_tokens SET download_count=download_count+1, "
                "last_download_at=? WHERE order_id=? AND token_hash=? "
                "AND download_count=? AND download_count<max_downloads "
                "AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>?)",
                (
                    timestamp,
                    order_id,
                    token_hash,
                    int(expected_download_count),
                    timestamp,
                ),
            )
            return cursor.rowcount > 0

    @_repository_operation
    def consume_download_by_receipt(
        self,
        order_id: int | str,
        *,
        receipt_token_hash: str,
        delivery_token_hash: str,
        expected_download_count: int,
        consumed_at: float | None = None,
    ) -> bool:
        timestamp = time.time() if consumed_at is None else float(consumed_at)
        with _transaction(self._conn, "shop_order_receipt_download"):
            cursor = self._conn.execute(
                "UPDATE shop_delivery_tokens SET download_count=download_count+1, "
                "last_download_at=? WHERE order_id=? AND token_hash=? AND download_count=? "
                "AND download_count<max_downloads AND revoked_at IS NULL "
                "AND (expires_at IS NULL OR expires_at>?) AND (EXISTS ("
                "SELECT 1 FROM shop_order_receipts r WHERE r.order_id=? "
                "AND r.token_hash=? AND r.revoked_at IS NULL AND r.expires_at>?) "
                "OR EXISTS (SELECT 1 FROM shop_order_receipt_recoveries rr "
                "WHERE rr.order_id=? AND rr.token_hash=? "
                "AND rr.revoked_at IS NULL AND rr.expires_at>?))",
                (
                    timestamp,
                    order_id,
                    delivery_token_hash,
                    int(expected_download_count),
                    timestamp,
                    order_id,
                    receipt_token_hash,
                    timestamp,
                    order_id,
                    receipt_token_hash,
                    timestamp,
                ),
            )
            return cursor.rowcount == 1

    @_repository_operation
    def append_event(
        self,
        order_id: int | str,
        event_type: str,
        *,
        actor_key: str | None = None,
        payload: dict[str, Any] | None = None,
        created_at: float | None = None,
    ) -> int:
        timestamp = time.time() if created_at is None else float(created_at)
        with _transaction(self._conn, "shop_order_event"):
            if self._select_order(order_id) is None:
                raise LookupError(f"shop order does not exist: {order_id}")
            return self._insert_event(
                int(order_id),
                event_type,
                actor_key=actor_key,
                payload=payload,
                created_at=timestamp,
            )

    @_repository_operation
    def list_events(
        self, order_id: int | str, *, limit: int = 1000
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, order_id, event_type, from_status, to_status, actor_key, "
            "payload, created_at FROM shop_order_events WHERE order_id=? "
            "ORDER BY created_at, id LIMIT ?",
            (order_id, max(1, min(int(limit), 5000))),
        ).fetchall()
        return [self._event_to_dict(row) for row in rows]

    @_repository_operation
    def stats(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*), COALESCE(SUM(amount_cents), 0) "
            "FROM shop_orders GROUP BY status"
        ).fetchall()
        result = {"total_orders": 0, "gross_cents": 0}
        for status, count, amount in rows:
            result[f"{status}_orders"] = int(count)
            result["total_orders"] += int(count)
            if str(status) in {"confirmed", "fulfilled"}:
                result["gross_cents"] += int(amount)
        return result

    @_repository_operation
    def export_orders(self) -> list[dict[str, Any]]:
        rows = self.list_orders(limit=5000)
        token_rows = self._conn.execute(
            "SELECT order_id, token_hash, delivery_path, max_downloads, download_count, "
            "expires_at, revoked_at FROM shop_delivery_tokens"
        ).fetchall()
        tokens = {int(row[0]): row[1:] for row in token_rows}
        for order in rows:
            token = tokens.get(int(order["id"]))
            if token is not None:
                order.update(
                    {
                        "delivery_token_hash": str(token[0]),
                        "delivery_path": str(token[1]),
                        "max_downloads": int(token[2]),
                        "download_count": int(token[3]),
                        "expires_at": None if token[4] is None else float(token[4]),
                        "revoked_at": None if token[5] is None else float(token[5]),
                    }
                )
        return rows

    # Lower-level compatibility aliases.
    get = get_order


__all__ = ["OrderRepository"]
