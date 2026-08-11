"""Order lifecycle and guarded digital-delivery service."""
from __future__ import annotations

import csv
import hashlib
import io
import secrets
import sqlite3
import time
from contextlib import AbstractContextManager, nullcontext
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from AssetsManager.application.context import ConnectionProvider, LibrarySession, session_operation
from AssetsManager.application.shop_service import _record
from AssetsManager.application.shop_authorization import ensure_authorized_shop_path
from AssetsManager.repositories.order_repository import ALLOWED_TRANSITIONS, ORDER_STATUSES
from AssetsManager.repositories.shop_repository import _transaction
from AssetsManager.core.database import DatabaseManager
from AssetsManager.domain.asset import assert_under_root
from AssetsManager.domain.errors import NotFoundError, OperationNotPermitted, ValidationError
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import ActivityChanged, QuotaChanged, ShopOrderChanged

PENDING = "pending"
CONFIRMED = "confirmed"
FULFILLED = "fulfilled"
REVOKED = "revoked"
DEFAULT_MAX_DOWNLOADS = 3
MAX_DOWNLOADS_LIMIT = 100
DEFAULT_DELIVERY_TTL = 7 * 24 * 60 * 60
DEFAULT_RECEIPT_TTL = 30 * 24 * 60 * 60
MAX_DELIVERY_TTL = 365 * 24 * 60 * 60
_MIN_TOKEN_LENGTH = 20
_MAX_DELIVERY_REQUEST_KEY_LENGTH = 200

_BUYER_ORDER_FIELDS = (
    "id",
    "item_id",
    "item_title",
    "amount_cents",
    "currency",
    "status",
    "created_at",
    "updated_at",
)
_SELLER_ORDER_FIELDS = (
    "id",
    "item_id",
    "item_path",
    "item_title",
    "buyer_name",
    "buyer_email",
    "amount_cents",
    "currency",
    "status",
    "metadata",
    "created_at",
    "updated_at",
)
_DELIVERY_ORDER_FIELDS = (
    "item_id",
    "item_title",
    "status",
    "max_downloads",
    "download_count",
    "expires_at",
    "last_download_at",
)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_delivery_token(token: str) -> str:
    return _hash_token(token)


def hash_receipt_token(token: str) -> str:
    return _hash_token(token)


def hash_delivery_request_key(request_key: str) -> str:
    """Hash a caller-supplied download idempotency key without persisting plaintext."""
    normalized = str(request_key).strip()
    if not normalized or len(normalized) > _MAX_DELIVERY_REQUEST_KEY_LENGTH:
        raise ValidationError("idempotency_key", "must be 1-200 characters")
    return _hash_token(normalized)



def _decode_order_cursor(cursor: str | None) -> tuple[float, int] | None:
    """Decode an opaque keyset cursor (``created_at|id``, base64url)."""
    if not cursor:
        return None
    try:
        import base64
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii")
        created_at_s, id_s = raw.split("|", 1)
        return float(created_at_s), int(id_s)
    except (ValueError, TypeError, UnicodeError, base64.binascii.Error):
        raise ValidationError("cursor", "invalid pagination cursor")


def _encode_order_cursor(created_at: object, order_id: int) -> str:
    import base64
    raw = f"{float(created_at)}|{int(order_id)}"
    return base64.urlsafe_b64encode(raw.encode("ascii")).decode("ascii")


class OrderService:
    """Enforce order state, receipt ownership, and delivery-token invariants."""

    def __init__(self, connection_provider: ConnectionProvider | None = None,
                 session: LibrarySession | None = None, *, repository: Any | None = None,
                 shop_repository: Any | None = None, clock=time.time) -> None:
        self._connection_provider = connection_provider
        self._session = session
        self._repository = repository
        self._shop_repository = shop_repository
        self._clock = clock

    def _connection(self, root: Path, db_conn: sqlite3.Connection | None) -> sqlite3.Connection:
        if db_conn is None:
            if self._connection_provider is None:
                raise RuntimeError("OrderService requires repositories, db_conn, or ConnectionProvider")
            db_conn = self._connection_provider(root)
        return DatabaseManager.validate_connection_owner(root, db_conn, allow_unmanaged=True)

    def _repos(self, root: Path, db_conn: sqlite3.Connection | None) -> tuple[Any, Any]:
        conn = None
        if self._repository is None or self._shop_repository is None:
            conn = self._connection(root, db_conn)
        order_repo = self._repository
        if order_repo is None:
            from AssetsManager.repositories.order_repository import OrderRepository
            assert conn is not None
            order_repo = OrderRepository(conn)
        shop_repo = self._shop_repository
        if shop_repo is None:
            from AssetsManager.repositories.shop_repository import ShopRepository
            assert conn is not None
            shop_repo = ShopRepository(conn)
        return order_repo, shop_repo

    def _publish(self, order_id: str | int | None = None) -> None:
        if self._session is None:
            return
        bus = get_event_bus()
        bus.publish(ActivityChanged(
            library_root=self._session.root_str,
            session_token=self._session.event_token,
        ))
        bus.publish(ShopOrderChanged(
            library_root=self._session.root_str,
            session_token=self._session.event_token,
            order_id="" if order_id is None else str(order_id),
        ))
        bus.publish(QuotaChanged(
            library_root=self._session.root_str,
            session_token=self._session.event_token,
            name="orders",
        ))

    @staticmethod
    def _buyer_order(order: Mapping[str, Any]) -> dict[str, Any]:
        result = {field: order.get(field) for field in _BUYER_ORDER_FIELDS}
        result["delivery_available"] = str(order.get("status")) == FULFILLED
        return result

    @classmethod
    def _buyer_history_order(cls, order: Mapping[str, Any]) -> dict[str, Any]:
        """Return the buyer DTO plus safe cart quantity details for history."""
        result = cls._buyer_order(order)
        metadata = order.get("metadata")
        if not isinstance(metadata, Mapping):
            metadata = {}
        try:
            quantity = int(metadata.get("quantity", 1))
        except (TypeError, ValueError):
            quantity = 1
        result["quantity"] = quantity if 1 <= quantity <= 999 else 1
        try:
            unit_price_cents = int(metadata["unit_price_cents"])
        except (KeyError, TypeError, ValueError):
            unit_price_cents = None
        if unit_price_cents is not None and unit_price_cents >= 0:
            result["unit_price_cents"] = unit_price_cents
        return result

    @staticmethod
    def _seller_order(order: Mapping[str, Any]) -> dict[str, Any]:
        return {field: order.get(field) for field in _SELLER_ORDER_FIELDS}

    @staticmethod
    def _delivery_order(order: Mapping[str, Any]) -> dict[str, Any]:
        result = {"order_id": order.get("id", order.get("order_id"))}
        result.update({field: order.get(field) for field in _DELIVERY_ORDER_FIELDS})
        return result

    @staticmethod
    def _positive_int(value: Any, field: str, *, maximum: int | None = None) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(field, "must be an integer") from exc
        if parsed <= 0 or (maximum is not None and parsed > maximum):
            suffix = f" and at most {maximum}" if maximum is not None else ""
            raise ValidationError(field, f"must be positive{suffix}")
        return parsed

    def _create_order(
        self,
        payload: Mapping[str, Any],
        order_repo: Any,
        shop_repo: Any,
        *,
        issue_receipt: bool,
        require_accepting_orders: bool = False,
        amount_cents: int | None = None,
        metadata: Mapping[str, Any] | None = None,
        buyer_owner_type: str | None = None,
        buyer_owner_key: str | None = None,
        publish: bool = True,
        item: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        item_id = self._positive_int(payload.get("item_id"), "item_id")
        if item is None:
            item = _record(shop_repo.get_item(item_id))
        else:
            # A caller that already loaded and validated the item (including
            # price and currency) may pass it in to avoid a second pricing
            # read inside the same checkout flow.
            item = _record(item)
        if item is None or not bool(item.get("enabled", True)):
            raise NotFoundError("shop item", str(item_id))
        ensure_authorized_shop_path(item.get("path", ""))
        buyer_name = str(payload.get("buyer_name") or "").strip()
        buyer_email = str(payload.get("buyer_email") or "").strip()
        if len(buyer_name) > 200:
            raise ValidationError("buyer_name", "must be at most 200 characters")
        if len(buyer_email) > 320 or (buyer_email and "@" not in buyer_email):
            raise ValidationError("buyer_email", "must be a valid email address")
        if amount_cents is not None and (
            isinstance(amount_cents, bool)
            or not isinstance(amount_cents, int)
            or amount_cents < 0
        ):
            raise ValidationError("amount_cents", "must be a non-negative integer")

        now = float(self._clock())
        receipt = secrets.token_urlsafe(32) if issue_receipt else None
        created = order_repo.create_order(
            item_id=item_id,
            buyer_name=buyer_name or None,
            buyer_email=buyer_email or None,
            buyer_owner_type=buyer_owner_type,
            buyer_owner_key=buyer_owner_key,
            amount_cents=(
                int(item.get("price_cents", 0))
                if amount_cents is None
                else amount_cents
            ),
            currency=str(item.get("currency", "CNY")),
            status=PENDING,
            created_at=now,
            metadata=None if metadata is None else dict(metadata),
            receipt_token_hash=None if receipt is None else hash_receipt_token(receipt),
            receipt_expires_at=None if receipt is None else now + DEFAULT_RECEIPT_TTL,
            require_accepting_orders=require_accepting_orders,
        )
        order = _record(created)
        if order is None:
            order = _record(order_repo.get_order(created))
        if order is None:
            raise RuntimeError("OrderRepository.create_order did not return a record or id")
        if publish:
            self._publish(order.get("id") if isinstance(order, Mapping) else None)
        return self._buyer_order(order), receipt

    @session_operation
    def create_order(self, library_root: str | Path, payload: Mapping[str, Any], *,
                     db_conn: sqlite3.Connection | None = None) -> dict[str, Any]:
        """Compatibility creation API; it deliberately does not fabricate a receipt."""
        root = Path(library_root).resolve()
        order_repo, shop_repo = self._repos(root, db_conn)
        order, _receipt = self._create_order(
            payload, order_repo, shop_repo, issue_receipt=False
        )
        return order

    @session_operation
    def create_order_with_receipt(
        self,
        library_root: str | Path,
        payload: Mapping[str, Any],
        *,
        db_conn: sqlite3.Connection | None = None,
        require_accepting_orders: bool = False,
        amount_cents: int | None = None,
        metadata: Mapping[str, Any] | None = None,
        buyer_owner_type: str | None = None,
        buyer_owner_key: str | None = None,
        publish: bool = True,
        item: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Create a buyer order and return its one-time plaintext cookie credential."""
        root = Path(library_root).resolve()
        order_repo, shop_repo = self._repos(root, db_conn)
        order, receipt = self._create_order(
            payload,
            order_repo,
            shop_repo,
            issue_receipt=True,
            require_accepting_orders=require_accepting_orders,
            amount_cents=amount_cents,
            metadata=metadata,
            buyer_owner_type=buyer_owner_type,
            buyer_owner_key=buyer_owner_key,
            publish=publish,
            item=item,
        )
        assert receipt is not None
        return order, receipt

    def publish_order_events(self, order_ids: list[int]) -> None:
        """Publish already-committed order changes after an outer transaction."""
        for order_id in order_ids:
            self._publish(order_id)

    @staticmethod
    def _require_token(token: str, resource: str) -> str:
        if not isinstance(token, str) or len(token) < _MIN_TOKEN_LENGTH:
            raise NotFoundError(resource, "token")
        return token

    def _receipt_order(
        self,
        order_repo: Any,
        order_id: str | int,
        receipt: str,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        self._require_token(receipt, "order receipt")
        order = _record(order_repo.get_order_with_receipt(order_id, hash_receipt_token(receipt)))
        if order is None:
            raise NotFoundError("order receipt", str(order_id))
        if order.get("receipt_revoked_at") is not None:
            raise OperationNotPermitted("Order receipt has been revoked")
        checked_at = float(self._clock()) if now is None else float(now)
        if float(order.get("receipt_expires_at", 0)) <= checked_at:
            raise OperationNotPermitted("Order receipt has expired")
        return order

    @session_operation
    def get_order(self, library_root: str | Path, order_id: str | int, *,
                  db_conn: sqlite3.Connection | None = None) -> dict[str, Any]:
        """Legacy lookup returning only the non-sensitive buyer projection."""
        root = Path(library_root).resolve()
        order_repo, _ = self._repos(root, db_conn)
        order = _record(order_repo.get_order(order_id))
        if order is None:
            raise NotFoundError("order", str(order_id))
        return self._buyer_order(order)

    @session_operation
    def recover_receipt_for_owner(
        self,
        library_root: str | Path,
        order_id: str | int,
        *,
        owner_type: str,
        owner_key: str,
        db_conn: sqlite3.Connection | None = None,
    ) -> str:
        """Issue an additional HttpOnly receipt credential for the order owner."""
        if owner_type not in {"user", "anonymous"} or not str(owner_key).strip():
            raise ValidationError("owner", "invalid buyer owner")
        root = Path(library_root).resolve()
        order_repo, _ = self._repos(root, db_conn)
        conn = db_conn or getattr(order_repo, "_conn", None)
        if conn is None:
            conn = self._connection(root, db_conn)
        with _transaction(conn, "shop_receipt_recover"):
            order = _record(order_repo.get_order(order_id))
            if order is None or (
                str(order.get("buyer_owner_type")) != owner_type
                or str(order.get("buyer_owner_key")) != str(owner_key)
            ):
                # Do not reveal whether another buyer's numeric order exists.
                raise NotFoundError("order receipt", str(order_id))
            state = _record(order_repo.get_receipt_state(order_id))
            if state is None:
                raise NotFoundError("order receipt", str(order_id))
            if state.get("revoked_at") is not None:
                raise OperationNotPermitted("Order receipt has been revoked")
            now = float(self._clock())
            expires_at = float(state.get("expires_at", 0))
            if expires_at <= now:
                raise OperationNotPermitted("Order receipt has expired")
            token = secrets.token_urlsafe(32)
            order_repo.create_receipt_recovery(
                int(order_id),
                token_hash=hash_receipt_token(token),
                created_at=now,
                expires_at=expires_at,
            )
        return token

    @session_operation
    def get_order_by_receipt(
        self,
        library_root: str | Path,
        order_id: str | int,
        receipt: str,
        *,
        db_conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        root = Path(library_root).resolve()
        order_repo, _ = self._repos(root, db_conn)
        return self._buyer_order(self._receipt_order(order_repo, order_id, receipt))

    @session_operation
    def get_seller_order(self, library_root: str | Path, order_id: str | int, *,
                         db_conn: sqlite3.Connection | None = None) -> dict[str, Any]:
        root = Path(library_root).resolve()
        order_repo, _ = self._repos(root, db_conn)
        order = _record(order_repo.get_order(order_id))
        if order is None:
            raise NotFoundError("order", str(order_id))
        return self._seller_order(order)

    @session_operation
    def list_seller_orders(self, library_root: str | Path, *, status: str | None = None,
                           limit: int = 200,
                           db_conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
        root = Path(library_root).resolve()
        order_repo, _ = self._repos(root, db_conn)
        if status is not None and status not in ORDER_STATUSES:
            raise ValidationError("status", "unknown order status")
        rows = order_repo.list_orders(status=status, limit=min(max(int(limit), 1), 1000))
        return [self._seller_order(row) for raw in rows if (row := _record(raw)) is not None]

    @session_operation
    def list_buyer_orders(
        self, library_root: str | Path, *, owner_type: str, owner_key: str,
        status: str | None = None, limit: int = 200, cursor: str | None = None,
        db_conn: sqlite3.Connection | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """List orders bound to the current buyer owner with keyset pagination.

        Returns ``(orders, next_cursor)``; ``next_cursor`` is the opaque
        base64url ``created_at|id`` marker of the last returned row when more
        rows may exist (requested limit was reached).
        """
        if owner_type not in {"user", "anonymous"} or not str(owner_key).strip():
            raise ValidationError("owner", "invalid buyer owner")
        if status is not None and status not in ORDER_STATUSES:
            raise ValidationError("status", "unknown order status")
        requested_limit = min(max(int(limit), 1), 1000)
        cursor_tuple = _decode_order_cursor(cursor)
        root = Path(library_root).resolve()
        order_repo, _ = self._repos(root, db_conn)
        rows = order_repo.list_orders_by_owner(
            owner_type=owner_type, owner_key=str(owner_key), status=status,
            limit=requested_limit + 1, cursor=cursor_tuple,
        )
        has_more = len(rows) > requested_limit
        page = rows[:requested_limit]
        orders = [self._buyer_history_order(row) for raw in page if (row := _record(raw)) is not None]
        next_cursor = None
        if has_more and page:
            last = page[-1]
            next_cursor = _encode_order_cursor(last.get("created_at"), int(last.get("id", 0)))
        return orders, next_cursor

    def list_orders(self, library_root: str | Path, *, status: str | None = None,
                    limit: int = 200, db_conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
        """Compatibility alias for the established seller-only listing contract."""
        return self.list_seller_orders(
            library_root, status=status, limit=limit, db_conn=db_conn
        )

    def _transition(self, root: Path, order_repo: Any, order_id: str | int,
                    target: str) -> dict[str, Any]:
        current = _record(order_repo.get_order(order_id))
        if current is None:
            raise NotFoundError("order", str(order_id))
        source = str(current.get("status", ""))
        if target not in ALLOWED_TRANSITIONS.get(source, frozenset()):
            raise OperationNotPermitted(f"Order cannot transition from {source} to {target}")
        updated = order_repo.transition_status(order_id, expected_status=source, new_status=target)
        order = _record(updated)
        if order is None and updated:
            order = _record(order_repo.get_order(order_id))
        if order is None:
            raise OperationNotPermitted("Order status changed concurrently")
        self._publish(order.get("id") if isinstance(order, Mapping) else None)
        return order

    @session_operation
    def confirm(self, library_root: str | Path, order_id: str | int, *,
                db_conn: sqlite3.Connection | None = None) -> dict[str, Any]:
        root = Path(library_root).resolve()
        order_repo, _ = self._repos(root, db_conn)
        return self._buyer_order(self._transition(root, order_repo, order_id, CONFIRMED))

    @session_operation
    def confirm_by_receipt(
        self,
        library_root: str | Path,
        order_id: str | int,
        receipt: str,
        *,
        db_conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        """Confirm a pending order with receipt authorization checked atomically."""
        root = Path(library_root).resolve()
        order_repo, _ = self._repos(root, db_conn)
        now = float(self._clock())
        current = self._receipt_order(order_repo, order_id, receipt, now=now)
        source = str(current.get("status", ""))
        # Confirmation is a replay-safe buyer action. If the first request
        # committed but its response was lost, returning the current terminal
        # projection is safer than turning a successful confirmation into a
        # misleading 409 on retry. Revoked orders remain errors below.
        if source in {CONFIRMED, FULFILLED}:
            return self._buyer_order(current)
        if CONFIRMED not in ALLOWED_TRANSITIONS.get(source, frozenset()):
            raise OperationNotPermitted(
                f"Order cannot transition from {source} to {CONFIRMED}"
            )
        updated = order_repo.transition_status_by_receipt(
            order_id,
            receipt_token_hash=hash_receipt_token(receipt),
            expected_status=source,
            new_status=CONFIRMED,
            updated_at=now,
        )
        order = _record(updated)
        if order is None:
            self._receipt_order(order_repo, order_id, receipt)
            raise OperationNotPermitted("Order status changed concurrently")
        self._publish(order.get("id"))
        return self._buyer_order(order)

    @session_operation
    def revoke(self, library_root: str | Path, order_id: str | int, *,
               db_conn: sqlite3.Connection | None = None) -> dict[str, Any]:
        root = Path(library_root).resolve()
        order_repo, _ = self._repos(root, db_conn)
        return self._seller_order(self._transition(root, order_repo, order_id, REVOKED))

    @session_operation
    def fulfill(self, library_root: str | Path, order_id: str | int, *,
                max_downloads: int = DEFAULT_MAX_DOWNLOADS,
                expires_in: int = DEFAULT_DELIVERY_TTL,
                db_conn: sqlite3.Connection | None = None) -> tuple[dict[str, Any], str]:
        root = Path(library_root).resolve()
        order_repo, shop_repo = self._repos(root, db_conn)
        current = _record(order_repo.get_order(order_id))
        if current is None:
            raise NotFoundError("order", str(order_id))
        if str(current.get("status")) != CONFIRMED:
            raise OperationNotPermitted("Only confirmed orders can be fulfilled")
        item = _record(shop_repo.get_item(int(current["item_id"])))
        if item is None:
            raise NotFoundError("shop item", str(current.get("item_id")))
        raw_path = ensure_authorized_shop_path(item.get("path", ""))
        target = assert_under_root(root / raw_path, root)
        if target == root or not target.exists():
            raise NotFoundError("delivery path", raw_path)
        maximum = self._positive_int(max_downloads, "max_downloads", maximum=MAX_DOWNLOADS_LIMIT)
        ttl = self._positive_int(expires_in, "expires_in", maximum=MAX_DELIVERY_TTL)
        token = secrets.token_urlsafe(32)
        token_hash = hash_delivery_token(token)
        updated = order_repo.fulfill_order(
            order_id,
            expected_status=CONFIRMED,
            delivery_token_hash=token_hash,
            delivery_path=target.relative_to(root).as_posix(),
            max_downloads=maximum,
            expires_at=float(self._clock()) + ttl,
        )
        order = _record(updated)
        if order is None and updated:
            order = _record(order_repo.get_order(order_id))
        if order is None:
            raise OperationNotPermitted("Order status changed concurrently")
        self._publish(order.get("id") if isinstance(order, Mapping) else None)
        return self._seller_order(order), token

    @session_operation
    def rotate_delivery(
        self,
        library_root: str | Path,
        order_id: str | int,
        *,
        max_downloads: int | None = None,
        expires_in: int | None = None,
        db_conn: sqlite3.Connection | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Issue a replacement seller delivery link, revoking the previous one.

        The replacement token inherits only the order's remaining quota, so
        repeated rotation can never inflate the total downloadable count and
        a leaked delivery link stops working as soon as it is rotated.
        """
        root = Path(library_root).resolve()
        order_repo, shop_repo = self._repos(root, db_conn)
        current = _record(order_repo.get_order(order_id))
        if current is None:
            raise NotFoundError("order", str(order_id))
        if str(current.get("status")) != FULFILLED:
            raise OperationNotPermitted("Only fulfilled orders can rotate delivery")

        existing = _record(order_repo.get_delivery_by_order_id(order_id))
        item = _record(shop_repo.get_item(int(current["item_id"])))
        if item is None:
            raise NotFoundError("shop item", str(current.get("item_id")))
        raw_path = (existing or {}).get("delivery_path") or item.get("path", "")
        delivery_path = ensure_authorized_shop_path(raw_path)
        target = assert_under_root(root / delivery_path, root)
        if target == root or not target.exists():
            raise NotFoundError("delivery path", delivery_path)

        now = float(self._clock())
        # The repository inherits the newest token's remaining quota
        # (max_downloads - download_count) and rejects rotation once it is
        # exhausted; an explicit max_downloads only caps that inheritance.
        maximum = None
        if max_downloads is not None:
            maximum = self._positive_int(
                max_downloads, "max_downloads", maximum=MAX_DOWNLOADS_LIMIT
            )
        if expires_in is None and existing is not None:
            previous_expiry = existing.get("expires_at")
            if previous_expiry is not None and float(previous_expiry) > now:
                expires_at = float(previous_expiry)
            else:
                expires_at = now + DEFAULT_DELIVERY_TTL
        else:
            ttl = self._positive_int(
                DEFAULT_DELIVERY_TTL if expires_in is None else expires_in,
                "expires_in",
                maximum=MAX_DELIVERY_TTL,
            )
            expires_at = now + ttl

        token = secrets.token_urlsafe(32)
        updated = order_repo.rotate_fulfilled_delivery(
            order_id,
            delivery_token_hash=hash_delivery_token(token),
            delivery_path=Path(delivery_path).as_posix(),
            max_downloads=maximum,
            expires_at=expires_at,
            rotated_at=now,
        )
        if updated is None:
            raise OperationNotPermitted("Order status changed concurrently")
        self._publish(updated.get("id") if isinstance(updated, Mapping) else None)
        return self._seller_order(updated), token

    @session_operation
    def revoke_delivery(
        self,
        library_root: str | Path,
        order_id: str | int,
        *,
        seller: Mapping[str, Any] | None = None,
        db_conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        """Revoke every delivery token of a fulfilled order.

        All previously issued bearer links become unusable immediately while
        the order itself stays ``fulfilled``. Seller authorization follows the
        order seller-route pattern: the route rejects unauthenticated callers
        before this method runs, and this check is defense in depth.
        """
        if seller is None:
            raise OperationNotPermitted("Seller authentication required")
        root = Path(library_root).resolve()
        order_repo, _ = self._repos(root, db_conn)
        order = _record(order_repo.get_order(order_id))
        if order is None:
            raise NotFoundError("order", str(order_id))
        if str(order.get("status")) != FULFILLED:
            raise OperationNotPermitted("Only fulfilled orders can revoke delivery")
        order_repo.revoke_delivery_tokens(order_id, revoked_at=float(self._clock()))
        order = _record(order_repo.get_order(order_id))
        if order is None:
            raise NotFoundError("order", str(order_id))
        self._publish(order.get("id") if isinstance(order, Mapping) else None)
        return self._seller_order(order)

    def _validate_delivery(
        self, order: Mapping[str, Any], *, allow_replay: bool = False
    ) -> None:
        if str(order.get("status")) != FULFILLED:
            raise NotFoundError("delivery", "token")
        if order.get("revoked_at") is not None:
            raise OperationNotPermitted("Delivery token has been revoked")
        expires_at = order.get("expires_at")
        if expires_at is not None and float(expires_at) <= float(self._clock()):
            raise OperationNotPermitted("Delivery token has expired")
        count = int(order.get("download_count", 0))
        maximum = int(order.get("max_downloads", 0))
        if maximum <= 0 or (count >= maximum and not allow_replay):
            raise OperationNotPermitted("Download limit reached")

    @staticmethod
    def _delivery_target(root: Path, order: Mapping[str, Any]) -> Path:
        delivery_path = ensure_authorized_shop_path(order.get("delivery_path", ""))
        target = assert_under_root(root / delivery_path, root)
        if target == root or not target.exists():
            raise NotFoundError("delivery path", delivery_path)
        return target

    @staticmethod
    def _serialized_repository_operation(repository: Any) -> AbstractContextManager[None]:
        serializer = getattr(repository, "serialized_operation", None)
        if callable(serializer):
            return cast(AbstractContextManager[None], serializer())
        return nullcontext()

    @session_operation
    def resolve_delivery(
        self,
        library_root: str | Path,
        token: str,
        *,
        consume: bool = False,
        request_key: str | None = None,
        db_conn: sqlite3.Connection | None = None,
    ) -> tuple[dict[str, Any], Path]:
        self._require_token(token, "delivery")
        request_hash = None if request_key is None else hash_delivery_request_key(request_key)
        root = Path(library_root).resolve()
        order_repo, _ = self._repos(root, db_conn)
        with self._serialized_repository_operation(order_repo):
            token_hash = hash_delivery_token(token)
            order = _record(order_repo.get_delivery(token_hash))
            if order is None:
                raise NotFoundError("delivery", "token")
            attempt = None
            if request_hash is not None:
                attempt = _record(
                    order_repo.get_delivery_attempt(
                        credential_kind="bearer",
                        credential_hash=token_hash,
                        request_key_hash=request_hash,
                    )
                )
            self._validate_delivery(
                order,
                allow_replay=attempt is not None and attempt.get("state") == "consumed",
            )
            target = self._delivery_target(root, order)
            if request_hash is not None:
                attempt_state = order_repo.reserve_delivery_attempt(
                    order.get("id", order.get("order_id")),
                    credential_kind="bearer",
                    credential_hash=token_hash,
                    request_key_hash=request_hash,
                    delivery_token_hash=token_hash,
                    reserved_at=float(self._clock()),
                )
                if attempt_state == "failed":
                    raise OperationNotPermitted("Download limit reached")
            if consume:
                if request_hash is not None:
                    outcome = order_repo.complete_delivery_attempt(
                        order.get("id", order.get("order_id")),
                        credential_kind="bearer",
                        credential_hash=token_hash,
                        request_key_hash=request_hash,
                        delivery_token_hash=token_hash,
                        expected_download_count=int(order.get("download_count", 0)),
                        consumed_at=float(self._clock()),
                    )
                    if outcome == "failed":
                        refreshed = _record(order_repo.get_delivery(token_hash))
                        if refreshed is not None:
                            self._validate_delivery(refreshed)
                        raise OperationNotPermitted("Download limit reached")
                    if outcome == "consumed":
                        order["download_count"] = int(order.get("download_count", 0)) + 1
                        order["last_download_at"] = float(self._clock())
                    else:
                        refreshed = _record(order_repo.get_delivery(token_hash))
                        if refreshed is not None:
                            order = refreshed
                else:
                    consumed = order_repo.consume_download(
                        order.get("id", order.get("order_id")),
                        token_hash=token_hash,
                        expected_download_count=int(order.get("download_count", 0)),
                        consumed_at=float(self._clock()),
                    )
                    if not consumed:
                        raise OperationNotPermitted("Download limit reached")
                    order["download_count"] = int(order.get("download_count", 0)) + 1
                    order["last_download_at"] = float(self._clock())
            return self._delivery_order(order), target

    @session_operation
    def fail_delivery_attempt(
        self,
        library_root: str | Path,
        token: str,
        *,
        request_key: str,
        db_conn: sqlite3.Connection | None = None,
    ) -> bool:
        """Mark a reserved bearer download attempt failed without consuming quota."""
        self._require_token(token, "delivery")
        request_hash = hash_delivery_request_key(request_key)
        root = Path(library_root).resolve()
        order_repo, _ = self._repos(root, db_conn)
        with self._serialized_repository_operation(order_repo):
            token_hash = hash_delivery_token(token)
            order = _record(order_repo.get_delivery(token_hash))
            if order is None:
                return False
            return order_repo.fail_delivery_attempt(
                order.get("id", order.get("order_id")),
                credential_kind="bearer",
                credential_hash=token_hash,
                request_key_hash=request_hash,
                delivery_token_hash=token_hash,
                failed_at=float(self._clock()),
            )

    @session_operation
    def resolve_delivery_by_receipt(
        self,
        library_root: str | Path,
        order_id: str | int,
        receipt: str,
        *,
        consume: bool = False,
        request_key: str | None = None,
        db_conn: sqlite3.Connection | None = None,
    ) -> tuple[dict[str, Any], Path]:
        """Resolve automatic delivery using the order id and HttpOnly receipt cookie."""
        request_hash = None if request_key is None else hash_delivery_request_key(request_key)
        root = Path(library_root).resolve()
        order_repo, _ = self._repos(root, db_conn)
        with self._serialized_repository_operation(order_repo):
            self._receipt_order(order_repo, order_id, receipt)
            order = _record(order_repo.get_delivery_by_order_id(order_id))
            if order is None:
                raise NotFoundError("delivery", str(order_id))
            receipt_hash = hash_receipt_token(receipt)
            delivery_hash = str(order.get("delivery_token_hash", ""))
            attempt = None
            if request_hash is not None:
                attempt = _record(
                    order_repo.get_delivery_attempt(
                        credential_kind="receipt",
                        credential_hash=receipt_hash,
                        request_key_hash=request_hash,
                    )
                )
            self._validate_delivery(
                order,
                allow_replay=attempt is not None and attempt.get("state") == "consumed",
            )
            target = self._delivery_target(root, order)
            if request_hash is not None:
                attempt_state = order_repo.reserve_delivery_attempt(
                    order_id,
                    credential_kind="receipt",
                    credential_hash=receipt_hash,
                    request_key_hash=request_hash,
                    delivery_token_hash=delivery_hash,
                    reserved_at=float(self._clock()),
                )
                if attempt_state == "failed":
                    raise OperationNotPermitted("Download limit reached")
            if consume:
                consumed_at = float(self._clock())
                if request_hash is not None:
                    outcome = order_repo.complete_delivery_attempt_by_receipt(
                        order_id,
                        credential_kind="receipt",
                        credential_hash=receipt_hash,
                        request_key_hash=request_hash,
                        receipt_token_hash=receipt_hash,
                        delivery_token_hash=delivery_hash,
                        expected_download_count=int(order.get("download_count", 0)),
                        consumed_at=consumed_at,
                    )
                    if outcome == "failed":
                        self._receipt_order(order_repo, order_id, receipt)
                        refreshed = _record(order_repo.get_delivery_by_order_id(order_id))
                        if refreshed is not None:
                            self._validate_delivery(refreshed)
                        raise OperationNotPermitted("Download limit reached")
                    if outcome == "consumed":
                        order["download_count"] = int(order.get("download_count", 0)) + 1
                        order["last_download_at"] = consumed_at
                    else:
                        refreshed = _record(order_repo.get_delivery_by_order_id(order_id))
                        if refreshed is not None:
                            order = refreshed
                else:
                    consumed = order_repo.consume_download_by_receipt(
                        order_id,
                        receipt_token_hash=receipt_hash,
                        delivery_token_hash=delivery_hash,
                        expected_download_count=int(order.get("download_count", 0)),
                        consumed_at=consumed_at,
                    )
                    if not consumed:
                        self._receipt_order(order_repo, order_id, receipt)
                        raise OperationNotPermitted("Download limit reached")
                    order["download_count"] = int(order.get("download_count", 0)) + 1
                    order["last_download_at"] = consumed_at
            return self._delivery_order(order), target

    @session_operation
    def fail_delivery_attempt_by_receipt(
        self,
        library_root: str | Path,
        order_id: str | int,
        receipt: str,
        *,
        request_key: str,
        db_conn: sqlite3.Connection | None = None,
    ) -> bool:
        """Mark a reserved receipt-authorized attempt failed without consuming quota."""
        request_hash = hash_delivery_request_key(request_key)
        root = Path(library_root).resolve()
        order_repo, _ = self._repos(root, db_conn)
        with self._serialized_repository_operation(order_repo):
            self._receipt_order(order_repo, order_id, receipt)
            order = _record(order_repo.get_delivery_by_order_id(order_id))
            if order is None:
                return False
            return order_repo.fail_delivery_attempt(
                order_id,
                credential_kind="receipt",
                credential_hash=hash_receipt_token(receipt),
                request_key_hash=request_hash,
                delivery_token_hash=str(order.get("delivery_token_hash", "")),
                failed_at=float(self._clock()),
            )

    @session_operation
    def stats(self, library_root: str | Path, *,
              db_conn: sqlite3.Connection | None = None) -> dict[str, Any]:
        root = Path(library_root).resolve()
        order_repo, _ = self._repos(root, db_conn)
        return dict(order_repo.stats())

    @session_operation
    def export_csv(self, library_root: str | Path, *,
                   db_conn: sqlite3.Connection | None = None) -> str:
        root = Path(library_root).resolve()
        order_repo, _ = self._repos(root, db_conn)
        rows = [row for raw in order_repo.export_orders() if (row := _record(raw)) is not None]
        if not rows:
            return ""
        blocked = {"delivery_token_hash", "token_hash", "delivery_path"}
        fields = [key for key in rows[0] if key not in blocked]
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fields})
        return stream.getvalue()


__all__ = [
    "DEFAULT_DELIVERY_TTL",
    "DEFAULT_MAX_DOWNLOADS",
    "DEFAULT_RECEIPT_TTL",
    "MAX_DOWNLOADS_LIMIT",
    "ORDER_STATUSES",
    "OrderService",
    "hash_delivery_request_key",
    "hash_delivery_token",
    "hash_receipt_token",
]



