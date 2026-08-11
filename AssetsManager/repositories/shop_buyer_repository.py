"""Session-bound repositories for buyer carts and wishlists."""

from __future__ import annotations
import hashlib
import json
import time
from typing import Any

from AssetsManager.domain.errors import (
    OperationNotPermitted,
    NotFoundError,
    ValidationError,
    VersionConflictError,
    WishlistLimitError,
)
from AssetsManager.repositories.shop_repository import (
    _CommerceRepository,
    _repository_operation,
    _transaction,
)


CART_TTL_SECONDS = 30 * 24 * 60 * 60
WISHLIST_LIMIT = 500


class CartRepository(_CommerceRepository):
    def _cart(self, owner_type: str, owner_key: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT id,owner_type,owner_key,user_id,status,version,checkout_generation,expires_at,created_at,updated_at FROM shop_carts WHERE owner_type=? AND owner_key=?",
            (owner_type, owner_key),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": int(row[0]),
            "owner_type": str(row[1]),
            "owner_key": str(row[2]),
            "user_id": None if row[3] is None else int(row[3]),
            "status": str(row[4]),
            "version": int(row[5]),
            "checkout_generation": int(row[6]),
            "expires_at": row[7],
            "created_at": float(row[8]),
            "updated_at": float(row[9]),
        }

    def _ensure_cart(
        self, owner_type: str, owner_key: str, user_id: int | None
    ) -> dict[str, Any]:
        cart = self._cart(owner_type, owner_key)
        if cart:
            return cart
        now = time.time()
        self._conn.execute(
            "INSERT INTO shop_carts(owner_type,owner_key,user_id,expires_at,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (owner_type, owner_key, user_id, now + CART_TTL_SECONDS, now, now),
        )
        return self._cart(owner_type, owner_key) or {}

    def _expire_cart_if_needed(self, cart: dict[str, Any]) -> dict[str, Any]:
        expires_at = cart.get("expires_at")
        if (
            cart.get("status") == "active"
            and expires_at is not None
            and float(expires_at) <= time.time()
        ):
            now = time.time()
            self._conn.execute(
                "UPDATE shop_carts SET status='expired',version=version+1,updated_at=? WHERE id=? AND status='active'",
                (now, int(cart["id"])),
            )
            cart["status"] = "expired"
            cart["version"] = int(cart["version"]) + 1
            cart["updated_at"] = now
        return cart

    def _prepare_cart_mutation(self, cart: dict[str, Any]) -> dict[str, Any]:
        cart = self._expire_cart_if_needed(cart)
        status = str(cart.get("status", ""))
        if status == "active":
            return cart
        if status in {"converted", "expired"}:
            # A converted/expired cart can be reused for a new checkout.  The
            # old line snapshots must not silently become a second purchase.
            now = time.time()
            self._conn.execute(
                "DELETE FROM shop_cart_items WHERE cart_id=?", (int(cart["id"]),)
            )
            self._conn.execute(
                "UPDATE shop_carts SET status='active',version=version+1,checkout_generation=checkout_generation+1,expires_at=?,updated_at=? WHERE id=?",
                (now + CART_TTL_SECONDS, now, int(cart["id"])),
            )
            cart["status"] = "active"
            cart["version"] = int(cart["version"]) + 1
            cart["checkout_generation"] = int(cart["checkout_generation"]) + 1
            cart["expires_at"] = now + CART_TTL_SECONDS
            cart["updated_at"] = now
            return cart
        raise OperationNotPermitted(f"Cart cannot be modified in status {status}")

    @staticmethod
    def _line(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "id": int(row[0]),
            "item_id": int(row[1]),
            "quantity": int(row[2]),
            "unit_price_cents": int(row[3]),
            "currency": str(row[4]),
            "path": str(row[5]),
            "title": str(row[6]),
            "line_status": str(row[7]),
            "created_at": float(row[8]),
            "updated_at": float(row[9]),
        }

    def _lines(self, cart_id: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id,item_id,quantity,unit_price_cents,currency,item_path,item_title,line_status,created_at,updated_at FROM shop_cart_items WHERE cart_id=? ORDER BY id",
            (cart_id,),
        ).fetchall()
        return [self._line(r) for r in rows]

    @_repository_operation
    def get(
        self, *, owner_type: str, owner_key: str, user_id: int | None = None
    ) -> dict[str, Any]:
        with _transaction(self._conn, "cart_get"):
            cart = self._ensure_cart(owner_type, owner_key, user_id)
            cart = self._expire_cart_if_needed(cart)
        cart["items"] = self._lines(int(cart["id"]))
        return cart

    @_repository_operation
    def existing(
        self, *, owner_type: str, owner_key: str
    ) -> dict[str, Any] | None:
        """Return an existing cart without creating one for a guest owner."""
        with _transaction(self._conn, "cart_existing"):
            cart = self._cart(owner_type, owner_key)
            if cart is None:
                return None
            cart = self._expire_cart_if_needed(cart)
            cart["items"] = self._lines(int(cart["id"]))
            return cart

    @_repository_operation
    def merge_guest_into_user(
        self,
        *,
        guest_key: str,
        user_id: int,
        current_items: dict[int, dict[str, Any]],
    ) -> tuple[bool, dict[str, Any]]:
        """Merge one anonymous cart into the authenticated user's cart.

        The caller owns the surrounding transaction when Cart and Wishlist are
        merged together.  This method therefore uses savepoints only and marks
        the source cart as ``merged`` after all lines have been applied.
        """
        with _transaction(self._conn, "cart_merge"):
            guest = self._cart("anonymous", guest_key)
            target = self._ensure_cart("user", str(user_id), user_id)
            if guest is None or guest.get("status") == "merged":
                target["items"] = self._lines(int(target["id"]))
                return False, target
            guest = self._expire_cart_if_needed(guest)
            if guest.get("status") != "active":
                target["items"] = self._lines(int(target["id"]))
                return False, target

            target = self._prepare_cart_mutation(target)
            target_id = int(target["id"])
            target_lines = {
                int(row[0]): {"id": int(row[1]), "quantity": int(row[2])}
                for row in self._conn.execute(
                    "SELECT item_id,id,quantity FROM shop_cart_items WHERE cart_id=?",
                    (target_id,),
                ).fetchall()
            }
            now = time.time()
            for line in self._lines(int(guest["id"])):
                item_id = int(line["item_id"])
                item = current_items.get(item_id)
                quantity = int(line["quantity"])
                existing = target_lines.get(item_id)
                if item is None:
                    # The item was disabled or removed since the guest added
                    # it.  Carry the guest line snapshot over as an
                    # unavailable line instead of failing the whole
                    # cart/wishlist merge.
                    if existing is not None:
                        self._conn.execute(
                            "UPDATE shop_cart_items SET line_status='unavailable',updated_at=? WHERE id=?",
                            (now, existing["id"]),
                        )
                    else:
                        self._conn.execute(
                            "INSERT INTO shop_cart_items(cart_id,item_id,quantity,unit_price_cents,currency,item_path,item_title,line_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (target_id, item_id, quantity, int(line["unit_price_cents"]), str(line["currency"]), str(line["path"]), str(line["title"]), "unavailable", now, now),
                        )
                    continue
                if existing is not None:
                    quantity += int(existing["quantity"])
                    if quantity > 999:
                        raise ValidationError("quantity", "must not exceed 999 per cart item")
                    self._conn.execute(
                        "UPDATE shop_cart_items SET quantity=?,unit_price_cents=?,currency=?,item_path=?,item_title=?,line_status='active',updated_at=? WHERE id=?",
                        (quantity, int(item["price_cents"]), str(item["currency"]), str(item["path"]), str(item["title"]), now, existing["id"]),
                    )
                else:
                    self._conn.execute(
                        "INSERT INTO shop_cart_items(cart_id,item_id,quantity,unit_price_cents,currency,item_path,item_title,line_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (target_id, item_id, quantity, int(item["price_cents"]), str(item["currency"]), str(item["path"]), str(item["title"]), "active", now, now),
                    )
            self._conn.execute(
                "UPDATE shop_carts SET status='active',version=version+1,expires_at=?,updated_at=? WHERE id=?",
                (now + CART_TTL_SECONDS, now, target_id),
            )
            self._conn.execute(
                "UPDATE shop_carts SET status='merged',version=version+1,updated_at=? WHERE id=? AND status='active'",
                (now, int(guest["id"])),
            )
            target = self._cart("user", str(user_id)) or target
            target["items"] = self._lines(target_id)
            return True, target

    @_repository_operation
    def add_item(
        self,
        *,
        owner_type: str,
        owner_key: str,
        user_id: int | None,
        item: dict[str, Any],
        quantity: int,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        with _transaction(self._conn, "cart_add"):
            cart = self._ensure_cart(owner_type, owner_key, user_id)
            cart = self._prepare_cart_mutation(cart)
            cid = int(cart["id"])
            if expected_version is not None and int(cart["version"]) != int(
                expected_version
            ):
                raise VersionConflictError()
            now = time.time()
            existing = self._conn.execute(
                "SELECT id,quantity FROM shop_cart_items WHERE cart_id=? AND item_id=?",
                (cid, int(item["id"])),
            ).fetchone()
            if existing:
                next_quantity = int(existing[1]) + quantity
                if next_quantity > 999:
                    raise ValidationError("quantity", "must not exceed 999 per cart item")
                self._conn.execute(
                    "UPDATE shop_cart_items SET quantity=?,unit_price_cents=?,currency=?,item_path=?,item_title=?,line_status='active',updated_at=? WHERE id=?",
                    (
                        next_quantity,
                        item["price_cents"],
                        item["currency"],
                        item["path"],
                        item["title"],
                        now,
                        existing[0],
                    ),
                )
            else:
                self._conn.execute(
                    "INSERT INTO shop_cart_items(cart_id,item_id,quantity,unit_price_cents,currency,item_path,item_title,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        cid,
                        int(item["id"]),
                        quantity,
                        item["price_cents"],
                        item["currency"],
                        item["path"],
                        item["title"],
                        now,
                    ),
                )
            self._conn.execute(
                "UPDATE shop_carts SET version=version+1,expires_at=?,updated_at=?,status='active' WHERE id=?",
                (now + CART_TTL_SECONDS, now, cid),
            )
        return self.get(owner_type=owner_type, owner_key=owner_key, user_id=user_id)

    @_repository_operation
    def update_item(
        self,
        *,
        owner_type: str,
        owner_key: str,
        user_id: int | None,
        line_id: int,
        quantity: int,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        with _transaction(self._conn, "cart_update"):
            cart = self._ensure_cart(owner_type, owner_key, user_id)
            cart = self._prepare_cart_mutation(cart)
            if expected_version is not None and cart["version"] != expected_version:
                raise VersionConflictError()
            cur = self._conn.execute(
                "UPDATE shop_cart_items SET quantity=?,updated_at=? WHERE id=? AND cart_id=?",
                (quantity, time.time(), line_id, cart["id"]),
            )
            if cur.rowcount == 0:
                raise NotFoundError("cart line", str(line_id))
            self._conn.execute(
                "UPDATE shop_carts SET version=version+1,expires_at=?,updated_at=? WHERE id=?",
                (time.time() + CART_TTL_SECONDS, time.time(), cart["id"]),
            )
        return self.get(owner_type=owner_type, owner_key=owner_key, user_id=user_id)

    @_repository_operation
    def remove_item(
        self,
        *,
        owner_type: str,
        owner_key: str,
        user_id: int | None = None,
        line_id: int | None = None,
        item_id: int | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        with _transaction(self._conn, "cart_remove"):
            cart = self._ensure_cart(owner_type, owner_key, user_id)
            cart = self._prepare_cart_mutation(cart)
            if expected_version is not None and cart["version"] != expected_version:
                raise VersionConflictError()
            if line_id is None and item_id is None:
                self._conn.execute(
                    "DELETE FROM shop_cart_items WHERE cart_id=?", (cart["id"],)
                )
            elif line_id is not None:
                self._conn.execute(
                    "DELETE FROM shop_cart_items WHERE cart_id=? AND id=?",
                    (cart["id"], line_id),
                )
            else:
                self._conn.execute(
                    "DELETE FROM shop_cart_items WHERE cart_id=? AND item_id=?",
                    (cart["id"], item_id),
                )
            self._conn.execute(
                "UPDATE shop_carts SET version=version+1,expires_at=?,updated_at=? WHERE id=?",
                (time.time() + CART_TTL_SECONDS, time.time(), cart["id"]),
            )
        return self.get(owner_type=owner_type, owner_key=owner_key, user_id=user_id)

    @_repository_operation
    def checkout_record(
        self,
        cart_id: int,
        checkout_generation: int,
        request_fingerprint: str | None,
        request_key: str,
        group_id: str,
        order_ids: list[int],
    ) -> None:
        # Only the SHA-256 digest of the idempotency key is persisted; the
        # caller is responsible for normalizing the key before this point.
        request_key_hash = hashlib.sha256(request_key.encode("utf-8")).hexdigest()
        with _transaction(self._conn, "cart_checkout_record"):
            self._conn.execute(
                "INSERT INTO shop_cart_checkouts(cart_id,checkout_generation,request_fingerprint,request_key,checkout_group_id,order_ids) VALUES(?,?,?,?,?,?)",
                (
                    cart_id,
                    checkout_generation,
                    request_fingerprint,
                    request_key_hash,
                    group_id,
                    json.dumps(order_ids, separators=(",", ":")),
                ),
            )

    @_repository_operation
    def find_checkout(
        self, cart_id: int, checkout_generation: int, request_key: str
    ) -> dict[str, Any] | None:
        request_key_hash = hashlib.sha256(request_key.encode("utf-8")).hexdigest()
        row = self._conn.execute(
            "SELECT order_ids,request_fingerprint FROM shop_cart_checkouts WHERE cart_id=? AND checkout_generation=? AND request_key=?",
            (cart_id, checkout_generation, request_key_hash),
        ).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(row[0])
            order_ids = [int(x) for x in value]
        except Exception:
            order_ids = []
        group = self._conn.execute(
            "SELECT checkout_group_id,created_at FROM shop_cart_checkouts WHERE cart_id=? AND checkout_generation=? AND request_key=?",
            (cart_id, checkout_generation, request_key_hash),
        ).fetchone()
        if group is None:
            return None
        return {
            "checkout_group_id": str(group[0]),
            "order_ids": order_ids,
            "request_fingerprint": None if row[1] is None else str(row[1]),
            "created_at": float(group[1]),
        }

    @_repository_operation
    def get_checkout(
        self,
        *,
        checkout_group_id: str,
        owner_type: str,
        owner_key: str,
    ) -> dict[str, Any] | None:
        """Return a checkout group only when it belongs to the supplied buyer."""
        row = self._conn.execute(
            """
            SELECT cc.cart_id,cc.checkout_group_id,cc.order_ids,cc.created_at
            FROM shop_cart_checkouts AS cc
            INNER JOIN shop_carts AS c ON c.id=cc.cart_id
            WHERE cc.checkout_group_id=? AND c.owner_type=? AND c.owner_key=?
            """,
            (checkout_group_id, owner_type, owner_key),
        ).fetchone()
        if row is None:
            return None
        try:
            order_ids = [int(value) for value in json.loads(row[2])]
        except Exception:
            order_ids = []
        return {
            "cart_id": int(row[0]),
            "checkout_group_id": str(row[1]),
            "order_ids": order_ids,
            "created_at": float(row[3]),
        }


class WishlistRepository(_CommerceRepository):
    def _owner_existing(
        self, kind: str, *, user_id: int | None = None, token_hash: str | None = None
    ) -> int | None:
        """Return the owner row id without creating one (read-only paths)."""
        if kind == "user":
            row = self._conn.execute(
                "SELECT id FROM shop_wishlist_owners WHERE owner_kind='user' AND user_id=?",
                (user_id,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT id FROM shop_wishlist_owners WHERE owner_kind='anonymous' AND token_hash=?",
                (token_hash,),
            ).fetchone()
        return None if row is None else int(row[0])

    def _owner(
        self, kind: str, *, user_id: int | None = None, token_hash: str | None = None
    ) -> int:
        if kind == "user":
            row = self._conn.execute(
                "SELECT id FROM shop_wishlist_owners WHERE owner_kind='user' AND user_id=?",
                (user_id,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT id FROM shop_wishlist_owners WHERE owner_kind='anonymous' AND token_hash=?",
                (token_hash,),
            ).fetchone()
        if row:
            return int(row[0])
        now = time.time()
        self._conn.execute(
            "INSERT OR IGNORE INTO shop_wishlist_owners(owner_kind,user_id,token_hash,created_at,updated_at) VALUES(?,?,?,?,?)",
            (kind, user_id, token_hash, now, now),
        )
        if kind == "user":
            row = self._conn.execute(
                "SELECT id FROM shop_wishlist_owners WHERE owner_kind='user' AND user_id=?",
                (user_id,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT id FROM shop_wishlist_owners WHERE owner_kind='anonymous' AND token_hash=?",
                (token_hash,),
            ).fetchone()
        if row is None:
            raise RuntimeError("wishlist owner could not be created")
        return int(row[0])

    @_repository_operation
    def merge_guest_into_user(
        self, *, guest_key: str, user_id: int
    ) -> bool:
        """Move guest wishlist rows into the user owner, deleting the source."""
        with _transaction(self._conn, "wishlist_merge"):
            source = self._conn.execute(
                "SELECT id FROM shop_wishlist_owners WHERE owner_kind='anonymous' AND token_hash=?",
                (guest_key,),
            ).fetchone()
            if source is None:
                return False
            target_id = self._owner("user", user_id=user_id)
            source_id = int(source[0])
            source_count = int(self._conn.execute(
                "SELECT count(*) FROM shop_wishlist_items WHERE owner_id=?", (source_id,)
            ).fetchone()[0])
            if source_count == 0:
                return False
            incoming = self._conn.execute(
                "SELECT item_id FROM shop_wishlist_items WHERE owner_id=? AND item_id NOT IN (SELECT item_id FROM shop_wishlist_items WHERE owner_id=?)",
                (source_id, target_id),
            ).fetchall()
            count = int(self._conn.execute(
                "SELECT count(*) FROM shop_wishlist_items WHERE owner_id=?", (target_id,)
            ).fetchone()[0])
            if count + len(incoming) > WISHLIST_LIMIT:
                raise WishlistLimitError(WISHLIST_LIMIT)
            now = time.time()
            for row in incoming:
                self._conn.execute(
                    "INSERT OR IGNORE INTO shop_wishlist_items(owner_id,item_id,added_at) VALUES(?,?,?)",
                    (target_id, int(row[0]), now),
                )
            self._conn.execute(
                "UPDATE shop_wishlist_owners SET updated_at=? WHERE id=?", (now, target_id)
            )
            self._conn.execute(
                "DELETE FROM shop_wishlist_items WHERE owner_id=?", (source_id,)
            )
            return True

    @_repository_operation
    def list(
        self, *, kind: str, user_id: int | None = None, token_hash: str | None = None
    ) -> list[dict[str, Any]]:
        with _transaction(self._conn, "wishlist_list"):
            oid = self._owner_existing(kind, user_id=user_id, token_hash=token_hash)
            if oid is None:
                # A read of a wishlist with no owner row is an empty list and
                # must not create an owner row as a side effect.
                return []
            rows = self._conn.execute(
                "SELECT w.item_id,w.added_at,s.path,s.title,s.price_cents,s.currency,s.enabled,s.metadata FROM shop_wishlist_items w LEFT JOIN shop_items s ON s.id=w.item_id WHERE w.owner_id=? ORDER BY w.added_at DESC,w.item_id DESC",
                (oid,),
            ).fetchall()
        result = []
        for r in rows:
            result.append(
                {
                    "item_id": int(r[0]),
                    "added_at": float(r[1]),
                    "path": None if r[2] is None else str(r[2]),
                    "title": None if r[3] is None else str(r[3]),
                    "price_cents": None if r[4] is None else int(r[4]),
                    "currency": None if r[5] is None else str(r[5]),
                    "availability": "available" if r[2] is not None and bool(r[6]) else "unavailable",
                }
            )
        return result

    @_repository_operation
    def put(
        self,
        *,
        kind: str,
        user_id: int | None = None,
        token_hash: str | None = None,
        item_id: int,
    ) -> list[dict[str, Any]]:
        with _transaction(self._conn, "wishlist_put"):
            oid = self._owner(kind, user_id=user_id, token_hash=token_hash)
            count = self._conn.execute(
                "SELECT count(*) FROM shop_wishlist_items WHERE owner_id=?", (oid,)
            ).fetchone()[0]
            if (
                count >= WISHLIST_LIMIT
                and self._conn.execute(
                    "SELECT 1 FROM shop_wishlist_items WHERE owner_id=? AND item_id=?",
                    (oid, item_id),
                ).fetchone()
                is None
            ):
                raise WishlistLimitError(WISHLIST_LIMIT)
            self._conn.execute(
                "INSERT OR IGNORE INTO shop_wishlist_items(owner_id,item_id) VALUES(?,?)",
                (oid, item_id),
            )
            self._conn.execute(
                "UPDATE shop_wishlist_owners SET updated_at=? WHERE id=?",
                (time.time(), oid),
            )
        return self.list(kind=kind, user_id=user_id, token_hash=token_hash)

    @_repository_operation
    def delete(
        self,
        *,
        kind: str,
        user_id: int | None = None,
        token_hash: str | None = None,
        item_id: int | None = None,
    ) -> list[dict[str, Any]]:
        with _transaction(self._conn, "wishlist_delete"):
            oid = self._owner(kind, user_id=user_id, token_hash=token_hash)
            if item_id is None:
                self._conn.execute(
                    "DELETE FROM shop_wishlist_items WHERE owner_id=?", (oid,)
                )
            else:
                self._conn.execute(
                    "DELETE FROM shop_wishlist_items WHERE owner_id=? AND item_id=?",
                    (oid, item_id),
                )
            self._conn.execute(
                "UPDATE shop_wishlist_owners SET updated_at=? WHERE id=?",
                (time.time(), oid),
            )
        return self.list(kind=kind, user_id=user_id, token_hash=token_hash)
