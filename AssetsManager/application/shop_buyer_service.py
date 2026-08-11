"""Cart and wishlist application services; owner identity is supplied by LAN auth/cookie adapters."""

from __future__ import annotations
import hashlib
import json
import secrets
import time
import uuid
from pathlib import Path
from typing import Any, cast
import sqlite3
from AssetsManager.core.database import DatabaseManager
from AssetsManager.domain.errors import (
    ValidationError,
    NotFoundError,
    OperationNotPermitted,
    IdempotencyKeyReusedError,
    PriceChangedError,
)
from AssetsManager.application.order_service import OrderService
from AssetsManager.repositories.shop_buyer_repository import (
    CartRepository,
    WishlistRepository,
)
from AssetsManager.repositories.order_repository import OrderRepository
from AssetsManager.repositories.shop_repository import ShopRepository, _transaction


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_guest_token() -> str:
    return secrets.token_urlsafe(32)


class ShopBuyerService:
    def __init__(self, connection_provider: Any = None, session: Any = None) -> None:
        self._connection_provider = connection_provider
        self._session = session

    def _conn(
        self, root: Path, db_conn: sqlite3.Connection | None
    ) -> sqlite3.Connection:
        if db_conn is not None:
            return db_conn
        if self._session is not None:
            connection = cast(sqlite3.Connection, self._session.connection_for(root))
            return DatabaseManager.require_managed_connection_owner(root, connection)
        if not callable(self._connection_provider):
            raise RuntimeError("connection provider required")
        connection = cast(sqlite3.Connection, self._connection_provider(root))
        return DatabaseManager.validate_connection_owner(
            root, connection, allow_unmanaged=True
        )

    def _repos(self, root: Path, db_conn: sqlite3.Connection | None):
        conn = self._conn(root, db_conn)
        return (
            conn,
            CartRepository(conn),
            WishlistRepository(conn),
            ShopRepository(conn),
            OrderRepository(conn),
        )

    @staticmethod
    def _owner(
        kind: str, *, user_id: int | None, guest_token_hash: str | None
    ) -> tuple[str, str, int | None]:
        if kind == "user":
            if not isinstance(user_id, int) or user_id <= 0:
                raise OperationNotPermitted("authenticated user required")
            return "user", str(user_id), user_id
        if kind != "anonymous" or not guest_token_hash or len(guest_token_hash) != 64:
            raise ValidationError("owner", "invalid anonymous owner")
        return "anonymous", guest_token_hash, None

    @classmethod
    def _resolved_owner(
        cls,
        owner_kind: str,
        *,
        user_id: int | None,
        guest_token_hash: str | None,
    ) -> tuple[str, str, int | None, str | None]:
        kind, key, uid = cls._owner(
            owner_kind, user_id=user_id, guest_token_hash=guest_token_hash
        )
        return kind, key, uid, key if kind == "anonymous" else None

    @staticmethod
    def _expected_version(value: Any) -> int | None:
        if value is None:
            return None
        try:
            version = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError("version", "must be an integer") from exc
        if version < 1:
            raise ValidationError("version", "must be positive")
        return version

    @staticmethod
    def _buyer_order(order: Any) -> dict[str, Any]:
        if not isinstance(order, dict):
            order = dict(order)
        metadata = order.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        try:
            quantity = int(metadata.get("quantity", 1))
        except (TypeError, ValueError):
            quantity = 1
        if quantity < 1 or quantity > 999:
            quantity = 1

        result = {
            "id": order.get("id"),
            "item_id": order.get("item_id"),
            "item_title": order.get("item_title"),
            "amount_cents": order.get("amount_cents"),
            "currency": order.get("currency"),
            "status": order.get("status"),
            "delivery_available": str(order.get("status")) == "fulfilled",
            # Quantity is a safe, buyer-facing projection of the cart order
            # snapshot.  Do not expose the full order metadata object.
            "quantity": quantity,
            "created_at": order.get("created_at"),
            "updated_at": order.get("updated_at"),
        }
        try:
            unit_price_cents = int(metadata["unit_price_cents"])
        except (KeyError, TypeError, ValueError):
            unit_price_cents = None
        if unit_price_cents is not None and unit_price_cents >= 0:
            result["unit_price_cents"] = unit_price_cents
        return result

    @staticmethod
    def _buyer_cart(cart: Any) -> dict[str, Any]:
        """Project cart data to fields safe for a buyer-facing checkout response."""
        if not isinstance(cart, dict):
            cart = dict(cart)
        safe = {
            key: cart.get(key)
            for key in (
                "id",
                # Keep the existing public Cart DTO shape without exposing
                # the stable owner key or authenticated user id.
                "owner_type",
                "status",
                "version",
                "expires_at",
                "created_at",
                "updated_at",
            )
        }
        safe["items"] = []
        for item in cart.get("items", []):
            if not isinstance(item, dict):
                item = dict(item)
            safe["items"].append(
                {
                    key: item.get(key)
                    for key in (
                        "id",
                        "item_id",
                        "quantity",
                        "unit_price_cents",
                        "currency",
                        "title",
                        "line_status",
                        "created_at",
                        "updated_at",
                    )
                }
            )
        return safe

    @staticmethod
    def _checkout_fingerprint(
        cart: dict[str, Any],
        *,
        buyer_name: str | None,
        buyer_email: str | None,
        accept_price_changes: bool,
    ) -> str:
        snapshot = {
            "cart_id": int(cart["id"]),
            "checkout_generation": int(cart.get("checkout_generation", 1)),
            "items": [
                {
                    "line_id": int(item["id"]),
                    "item_id": int(item["item_id"]),
                    "quantity": int(item["quantity"]),
                    "unit_price_cents": int(item["unit_price_cents"]),
                    "currency": str(item["currency"]),
                }
                for item in cart.get("items", [])
            ],
            "buyer_name": str(buyer_name or "").strip() or None,
            "buyer_email": str(buyer_email or "").strip() or None,
            "accept_price_changes": bool(accept_price_changes),
        }
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _item_id(value: Any, field: str = "item_id") -> int:
        try:
            item_id = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(field, "must be a positive integer") from exc
        if item_id <= 0:
            raise ValidationError(field, "must be a positive integer")
        return item_id

    @staticmethod
    def _quantity(value: Any) -> int:
        try:
            q = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError("quantity", "must be an integer") from exc
        if q <= 0 or q > 999:
            raise ValidationError("quantity", "must be between 1 and 999")
        return q

    def cart(
        self,
        root: str | Path,
        *,
        owner_kind: str,
        user_id: int | None = None,
        guest_token_hash: str | None = None,
        db_conn=None,
    ):
        """Read a cart without side effects.

        A missing cart yields an empty structure and never creates a row;
        cart rows are only materialized by the first mutation.
        """
        path = Path(root).resolve()
        kind, key, uid = self._owner(
            owner_kind, user_id=user_id, guest_token_hash=guest_token_hash
        )
        cart = self._repos(path, db_conn)[1].existing(owner_type=kind, owner_key=key)
        if cart is None:
            return {
                "id": None,
                "owner_type": kind,
                "owner_key": key,
                "user_id": uid,
                "status": "active",
                # The version a fresh cart will start at, so a
                # read-then-add-with-version client flow keeps working.
                "version": 1,
                "checkout_generation": 1,
                "expires_at": None,
                "created_at": None,
                "updated_at": None,
                "items": [],
            }
        return cart

    def merge_guest_into_user(
        self,
        root: str | Path,
        *,
        user_id: int,
        guest_cart_token_hash: str | None = None,
        guest_wishlist_token_hash: str | None = None,
        db_conn=None,
    ) -> dict[str, Any]:
        """Atomically merge guest cart/wishlist state into one user owner.

        Guest identifiers are hashes supplied by the HTTP cookie adapter; raw
        tokens never enter this service result or any JSON response. Repeating
        the operation is a no-op after the cart is marked ``merged`` and guest
        wishlist rows are removed.
        """
        if not isinstance(user_id, int) or user_id <= 0:
            raise OperationNotPermitted("authenticated user required")
        for field, value in (("guest_cart_token_hash", guest_cart_token_hash), ("guest_wishlist_token_hash", guest_wishlist_token_hash)):
            if value is not None and (not isinstance(value, str) or len(value) != 64):
                raise ValidationError(field, "invalid guest owner")

        path = Path(root).resolve()
        conn, cart_repo, wishlist_repo, shop, _ = self._repos(path, db_conn)
        merged_cart = False
        merged_wishlist = False
        with _transaction(conn, "buyer_merge"):
            current_items: dict[int, dict[str, Any]] = {}
            guest_cart = None
            if guest_cart_token_hash:
                guest_cart = cart_repo.existing(
                    owner_type="anonymous", owner_key=guest_cart_token_hash
                )
                if guest_cart is not None and guest_cart.get("status") == "active":
                    for line in guest_cart.get("items", []):
                        item_id = int(line["item_id"])
                        item = shop.get_item(item_id)
                        if item is None or not bool(item.get("enabled")):
                            # A disabled or deleted item must not block the
                            # whole cart/wishlist merge; the repository
                            # carries the guest line over as an unavailable
                            # line instead of failing atomically.
                            continue
                        current_items[item_id] = item

            if guest_cart_token_hash:
                merged_cart, cart = cart_repo.merge_guest_into_user(
                    guest_key=guest_cart_token_hash,
                    user_id=user_id,
                    current_items=current_items,
                )
            else:
                cart = cart_repo.get(
                    owner_type="user", owner_key=str(user_id), user_id=user_id
                )

            if guest_wishlist_token_hash:
                merged_wishlist = wishlist_repo.merge_guest_into_user(
                    guest_key=guest_wishlist_token_hash, user_id=user_id
                )
            wishlist = wishlist_repo.list(kind="user", user_id=user_id)

        return {
            "merged": bool(merged_cart or merged_wishlist),
            "cart": self._buyer_cart(cart),
            "wishlist": wishlist,
            "items": wishlist,
            "source": {"cart": bool(guest_cart_token_hash), "wishlist": bool(guest_wishlist_token_hash)},
            "limits": {"cart_item_quantity": 999, "wishlist_items": 500},
        }

    def add_cart_item(
        self,
        root: str | Path,
        item_id: Any,
        quantity: Any,
        *,
        owner_kind: str,
        user_id: int | None = None,
        guest_token_hash: str | None = None,
        expected_version: int | None = None,
        db_conn=None,
    ):
        path = Path(root).resolve()
        kind, key, uid = self._owner(
            owner_kind, user_id=user_id, guest_token_hash=guest_token_hash
        )
        conn, cart, _, shop, _ = self._repos(path, db_conn)
        item = shop.get_item(self._item_id(item_id))
        if item is None or not bool(item.get("enabled")):
            raise NotFoundError("shop item", str(item_id))
        return cart.add_item(
            owner_type=kind,
            owner_key=key,
            user_id=uid,
            item=item,
            quantity=self._quantity(quantity),
            expected_version=self._expected_version(expected_version),
        )

    def update_cart_item(self, root: str | Path, line_id: Any, quantity: Any, **kwargs):
        path = Path(root).resolve()
        kind, key, uid = self._owner(
            kwargs.pop("owner_kind"),
            user_id=kwargs.pop("user_id", None),
            guest_token_hash=kwargs.pop("guest_token_hash", None),
        )
        return self._repos(path, kwargs.pop("db_conn", None))[1].update_item(
            owner_type=kind,
            owner_key=key,
            user_id=uid,
            line_id=self._item_id(line_id, "line_id"),
            quantity=self._quantity(quantity),
            expected_version=self._expected_version(kwargs.pop("expected_version", None)),
        )

    def remove_cart_item(self, root: str | Path, **kwargs):
        path = Path(root).resolve()
        kind, key, uid = self._owner(
            kwargs.pop("owner_kind"),
            user_id=kwargs.pop("user_id", None),
            guest_token_hash=kwargs.pop("guest_token_hash", None),
        )
        return self._repos(path, kwargs.pop("db_conn", None))[1].remove_item(
            owner_type=kind,
            owner_key=key,
            user_id=uid,
            line_id=kwargs.pop("line_id", None),
            item_id=kwargs.pop("item_id", None),
            expected_version=self._expected_version(kwargs.pop("expected_version", None)),
        )

    @staticmethod
    def _checkout_group_status(orders: list[dict[str, Any]]) -> str:
        statuses = {str(order.get("status", "pending")) for order in orders}
        if not statuses:
            return "pending"
        if len(statuses) == 1:
            only = next(iter(statuses))
            return only if only in {"pending", "confirmed", "fulfilled", "revoked"} else "mixed"
        # A group with any non-pending, non-revoked work is actively
        # progressing. Revoked orders mixed with live orders remain explicit
        # ``mixed`` so a partial cancellation is not mistaken for success.
        if statuses <= {"pending", "confirmed", "fulfilled"} and statuses & {"confirmed", "fulfilled"}:
            return "in_progress"
        return "mixed"

    def buyer_orders(
        self, root: str | Path, *, owner_kind: str, user_id: int | None = None,
        guest_token_hash: str | None = None, status: str | None = None,
        limit: int = 200, db_conn=None,
    ) -> list[dict[str, Any]]:
        path = Path(root).resolve()
        kind, key, _uid = self._owner(owner_kind, user_id=user_id, guest_token_hash=guest_token_hash)
        orders = self._repos(path, db_conn)[4]
        if status is not None and status not in {"pending", "confirmed", "fulfilled", "revoked"}:
            raise ValidationError("status", "unknown order status")
        return [self._buyer_order(order) for order in orders.list_orders_by_owner(
            owner_type=kind, owner_key=key, status=status, limit=min(max(int(limit), 1), 1000)
        )]

    def checkout(
        self,
        root: str | Path,
        *,
        owner_kind: str,
        user_id: int | None = None,
        guest_token_hash: str | None = None,
        request_key: str,
        accept_price_changes: bool = False,
        buyer_name: str | None = None,
        buyer_email: str | None = None,
        db_conn=None,
    ):
        # Normalize the idempotency key so retries with different casing or
        # whitespace spacing hit the same checkout record, then validate the
        # normalized form.
        request_key = " ".join(str(request_key).split()).casefold()
        if not request_key or len(request_key) > 200:
            raise ValidationError("idempotency_key", "must be 1-200 characters")
        path = Path(root).resolve()
        kind, key, uid = self._owner(
            owner_kind, user_id=user_id, guest_token_hash=guest_token_hash
        )
        conn, cart_repo, _, shop, orders = self._repos(path, db_conn)
        order_service = OrderService(self._connection_provider, self._session)
        receipt_tokens: dict[str, str] = {}
        with _transaction(conn, "cart_checkout"):
            cart = cart_repo.get(owner_type=kind, owner_key=key, user_id=uid)
            request_fingerprint = self._checkout_fingerprint(
                cart,
                buyer_name=buyer_name,
                buyer_email=buyer_email,
                accept_price_changes=accept_price_changes,
            )
            found = cart_repo.find_checkout(
                int(cart["id"]), int(cart["checkout_generation"]), request_key
            )
            if found is not None:
                stored_fingerprint = found.get("request_fingerprint")
                # Older clients commonly retry with only the idempotency key
                # after a response loss. Treat that empty optional-body replay
                # as compatible, while still rejecting a materially different
                # buyer payload or price-change choice.
                minimal_replay = (
                    buyer_name is None
                    and buyer_email is None
                    and accept_price_changes is False
                )
                if stored_fingerprint and stored_fingerprint != request_fingerprint and not minimal_replay:
                    raise IdempotencyKeyReusedError()
                resolved = []
                for order_id in found["order_ids"]:
                    order = orders.get_order(order_id)
                    if order is not None:
                        resolved.append(self._buyer_order(order))
                return {
                    "checkout_group_id": found["checkout_group_id"],
                    "orders": resolved,
                    "idempotent": True,
                    "status": self._checkout_group_status(resolved),
                    "cart": self._buyer_cart(cart),
                }
            if cart.get("status") != "active":
                raise OperationNotPermitted("Cart has expired or is no longer active")
            fresh = []
            for line in cart["items"]:
                item = shop.get_item(line["item_id"])
                if item is None or not bool(item.get("enabled")):
                    raise NotFoundError("shop item", str(line["item_id"]))
                if (
                    int(item["price_cents"]) != line["unit_price_cents"]
                    or str(item["currency"]) != line["currency"]
                ):
                    if not accept_price_changes:
                        raise PriceChangedError(line["item_id"])
                fresh.append((line, item))
            if not fresh:
                raise ValidationError("cart", "cannot checkout an empty cart")
            group = str(uuid.uuid4())
            order_ids = []
            for line, item in fresh:
                quantity = int(line["quantity"])
                order, receipt = order_service.create_order_with_receipt(
                    path,
                    {
                        "item_id": int(item["id"]),
                        "buyer_name": buyer_name,
                        "buyer_email": buyer_email,
                    },
                    db_conn=conn,
                    require_accepting_orders=True,
                    amount_cents=int(item["price_cents"]) * quantity,
                    buyer_owner_type=kind,
                    buyer_owner_key=key,
                    publish=False,
                    metadata={
                        "source": "cart",
                        "cart_id": cart["id"],
                        "cart_line_id": line["id"],
                        "checkout_group_id": group,
                        "quantity": quantity,
                        "unit_price_cents": int(item["price_cents"]),
                    },
                    # The item was already loaded and validated (price,
                    # currency, enabled) in the fresh loop above; passing it
                    # avoids a second implicit pricing read inside the order
                    # service (TOCTOU).
                    item=item,
                )
                order_ids.append(int(order["id"]))
                receipt_tokens[str(order["id"])] = receipt
            cart_repo.checkout_record(
                int(cart["id"]),
                int(cart["checkout_generation"]),
                request_fingerprint,
                request_key,
                group,
                order_ids,
            )
            conn.execute("DELETE FROM shop_cart_items WHERE cart_id=?", (cart["id"],))
            conn.execute(
                "UPDATE shop_carts SET status='converted',version=version+1,updated_at=? WHERE id=?",
                (time.time(), cart["id"]),
            )
        # Only publish after the enclosing cart transaction has committed;
        # otherwise a later line failure could expose a rolled-back order.
        order_service.publish_order_events(order_ids)
        cart_after = cart_repo.get(owner_type=kind, owner_key=key, user_id=uid)
        return {
            "orders": [
                self._buyer_order(order)
                for order_id in order_ids
                if (order := orders.get_order(order_id)) is not None
            ],
            "idempotent": False,
            "checkout_group_id": group,
            "status": self._checkout_group_status([
                self._buyer_order(order)
                for order_id in order_ids
                if (order := orders.get_order(order_id)) is not None
            ]),
            "cart": self._buyer_cart(cart_after),
            "receipt_tokens": receipt_tokens,
        }

    def checkout_group(
        self,
        root: str | Path,
        checkout_group_id: Any,
        *,
        owner_kind: str,
        user_id: int | None = None,
        guest_token_hash: str | None = None,
        db_conn=None,
    ) -> dict[str, Any]:
        """Load a checkout group scoped to the current buyer/cart owner."""
        group_id = str(checkout_group_id).strip()
        if not group_id or len(group_id) > 200:
            raise ValidationError("checkout_group_id", "must be 1-200 characters")
        path = Path(root).resolve()
        kind, key, uid = self._owner(
            owner_kind, user_id=user_id, guest_token_hash=guest_token_hash
        )
        conn, cart_repo, _, _, orders = self._repos(path, db_conn)
        checkout = cart_repo.get_checkout(
            checkout_group_id=group_id,
            owner_type=kind,
            owner_key=key,
        )
        if checkout is None:
            raise NotFoundError("checkout group", group_id)
        cart = cart_repo.get(owner_type=kind, owner_key=key, user_id=uid)
        resolved = []
        for order_id in checkout["order_ids"]:
            order = orders.get_order(order_id)
            if order is not None:
                resolved.append(self._buyer_order(order))
        return {
            "checkout_group_id": checkout["checkout_group_id"],
            "orders": resolved,
            "idempotent": True,
            "status": self._checkout_group_status(resolved),
            "created_at": checkout["created_at"],
            "cart": self._buyer_cart(cart),
        }

    def wishlist(self, root: str | Path, **owner):
        path = Path(root).resolve()
        kind, _key, uid, token = self._resolved_owner(
            owner.pop("owner_kind"),
            user_id=owner.pop("user_id", None),
            guest_token_hash=owner.pop("guest_token_hash", None),
        )
        return self._repos(path, owner.pop("db_conn", None))[2].list(
            kind=kind, user_id=uid, token_hash=token
        )

    def wishlist_put(self, root: str | Path, item_id: Any, **owner):
        path = Path(root).resolve()
        kind, _key, uid, token = self._resolved_owner(
            owner.pop("owner_kind"),
            user_id=owner.pop("user_id", None),
            guest_token_hash=owner.pop("guest_token_hash", None),
        )
        _, _, repo, shop, _ = self._repos(path, owner.pop("db_conn", None))
        item = shop.get_item(self._item_id(item_id))
        if item is None or not bool(item.get("enabled")):
            raise NotFoundError("shop item", str(item_id))
        return repo.put(kind=kind, user_id=uid, token_hash=token, item_id=int(item_id))

    def wishlist_delete(self, root: str | Path, item_id: Any | None = None, **owner):
        path = Path(root).resolve()
        kind, _key, uid, token = self._resolved_owner(
            owner.pop("owner_kind"),
            user_id=owner.pop("user_id", None),
            guest_token_hash=owner.pop("guest_token_hash", None),
        )
        return self._repos(path, owner.pop("db_conn", None))[2].delete(
            kind=kind,
            user_id=uid,
            token_hash=token,
            item_id=None if item_id is None else self._item_id(item_id),
        )

