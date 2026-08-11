from __future__ import annotations

import pytest

from AssetsManager.application.shop_buyer_service import ShopBuyerService, token_hash
from AssetsManager.domain.errors import IdempotencyKeyReusedError, NotFoundError, PriceChangedError, ValidationError
from AssetsManager.repositories.shop_repository import ShopRepository


def _setup(schema_db, tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    (root / "asset.txt").write_text("asset", encoding="utf-8")
    shop = ShopRepository(schema_db)
    item = shop.create_item(
        path="asset.txt",
        title="Asset",
        price_cents=100,
        currency="CNY",
    )
    schema_db.execute(
        "UPDATE seller_profile SET accept_orders=1 WHERE id=1"
    )
    schema_db.commit()
    service = ShopBuyerService(connection_provider=lambda _root: schema_db)
    return root, service, item


def test_guest_cart_checkout_is_atomic_idempotent_and_quantity_aware(schema_db, tmp_path):
    root, service, item = _setup(schema_db, tmp_path)
    guest = token_hash("guest-cart-token")

    cart = service.cart(root, owner_kind="anonymous", guest_token_hash=guest)
    assert cart["version"] == 1
    cart = service.add_cart_item(
        root,
        item["id"],
        2,
        owner_kind="anonymous",
        guest_token_hash=guest,
        expected_version=cart["version"],
    )
    assert cart["items"][0]["quantity"] == 2

    result = service.checkout(
        root,
        owner_kind="anonymous",
        guest_token_hash=guest,
        request_key="checkout-1",
        buyer_email="buyer@example.com",
    )
    assert result["idempotent"] is False
    assert result["checkout_group_id"]
    assert len(result["orders"]) == 1
    order = result["orders"][0]
    assert order["amount_cents"] == 200
    assert order["quantity"] == 2
    assert order["unit_price_cents"] == 100
    assert "item_path" not in order
    assert result["receipt_tokens"][str(order["id"])]
    assert result["cart"]["status"] == "converted"
    assert result["cart"]["items"] == []

    retry = service.checkout(
        root,
        owner_kind="anonymous",
        guest_token_hash=guest,
        request_key="checkout-1",
    )
    assert retry["idempotent"] is True
    assert retry["checkout_group_id"] == result["checkout_group_id"]
    assert [row["id"] for row in retry["orders"]] == [order["id"]]
    assert "receipt_tokens" not in retry
    assert schema_db.execute("SELECT COUNT(*) FROM shop_orders").fetchone()[0] == 1
    assert schema_db.execute("SELECT buyer_owner_type, buyer_owner_key FROM shop_orders WHERE id=?", (order["id"],)).fetchone() == ("anonymous", guest)


def test_checkout_group_is_scoped_to_buyer_and_is_buyer_safe(schema_db, tmp_path):
    root, service, item = _setup(schema_db, tmp_path)
    owner = token_hash("checkout-owner")
    other_owner = token_hash("checkout-other-owner")
    service.add_cart_item(
        root, item["id"], 1, owner_kind="anonymous", guest_token_hash=owner
    )
    created = service.checkout(
        root,
        owner_kind="anonymous",
        guest_token_hash=owner,
        request_key="group-query",
        buyer_name="Buyer",
        buyer_email="buyer@example.com",
    )

    loaded = service.checkout_group(
        root,
        created["checkout_group_id"],
        owner_kind="anonymous",
        guest_token_hash=owner,
    )
    assert loaded["checkout_group_id"] == created["checkout_group_id"]
    assert loaded["idempotent"] is True
    assert loaded["status"] == "pending"
    assert loaded["orders"][0]["id"] == created["orders"][0]["id"]
    assert loaded["orders"][0]["quantity"] == 1
    assert all(
        field not in loaded["orders"][0]
        for field in ("metadata", "item_path", "buyer_email")
    )
    assert "owner_key" not in loaded["cart"]
    assert all("path" not in item_row for item_row in loaded["cart"]["items"])

    with pytest.raises(NotFoundError):
        service.checkout_group(
            root,
            created["checkout_group_id"],
            owner_kind="anonymous",
            guest_token_hash=other_owner,
        )


def test_cart_rejects_stale_price_and_keeps_cart_usable(schema_db, tmp_path):
    root, service, item = _setup(schema_db, tmp_path)
    guest = token_hash("price-cart-token")
    service.add_cart_item(
        root, item["id"], 1, owner_kind="anonymous", guest_token_hash=guest
    )
    schema_db.execute(
        "UPDATE shop_items SET price_cents=250, updated_at=updated_at+1 WHERE id=?",
        (item["id"],),
    )
    schema_db.commit()

    with pytest.raises(PriceChangedError):
        service.checkout(
            root,
            owner_kind="anonymous",
            guest_token_hash=guest,
            request_key="price-check",
        )
    assert service.cart(root, owner_kind="anonymous", guest_token_hash=guest)["items"]


def test_wishlist_isolated_by_guest_token_and_marks_disabled_items_unavailable(
    schema_db, tmp_path
):
    root, service, item = _setup(schema_db, tmp_path)
    guest_a = token_hash("wishlist-a")
    guest_b = token_hash("wishlist-b")

    assert service.wishlist(
        root, owner_kind="anonymous", guest_token_hash=guest_a
    ) == []
    rows = service.wishlist_put(
        root, item["id"], owner_kind="anonymous", guest_token_hash=guest_a
    )
    assert rows[0]["item_id"] == item["id"]
    assert service.wishlist(
        root, owner_kind="anonymous", guest_token_hash=guest_b
    ) == []

    schema_db.execute("UPDATE shop_items SET enabled=0 WHERE id=?", (item["id"],))
    schema_db.commit()
    rows = service.wishlist(
        root, owner_kind="anonymous", guest_token_hash=guest_a
    )
    assert rows[0]["availability"] == "unavailable"


def test_cart_quantity_validation_is_explicit(schema_db, tmp_path):
    root, service, item = _setup(schema_db, tmp_path)
    guest = token_hash("quantity-cart-token")
    service.add_cart_item(
        root, item["id"], 999, owner_kind="anonymous", guest_token_hash=guest
    )
    with pytest.raises(ValidationError, match="quantity"):
        service.add_cart_item(
            root, item["id"], 1, owner_kind="anonymous", guest_token_hash=guest
        )



def test_checkout_group_status_is_derived_from_order_states():
    from AssetsManager.application.shop_buyer_service import ShopBuyerService

    assert ShopBuyerService._checkout_group_status([]) == "pending"
    assert ShopBuyerService._checkout_group_status([{"status": "confirmed"}, {"status": "fulfilled"}]) == "in_progress"
    assert ShopBuyerService._checkout_group_status([{"status": "pending"}, {"status": "confirmed"}]) == "in_progress"
    assert ShopBuyerService._checkout_group_status([{"status": "pending"}, {"status": "revoked"}]) == "mixed"


def test_buyer_order_history_is_owner_isolated_and_legacy_rows_are_hidden(schema_db, tmp_path):
    root, service, item = _setup(schema_db, tmp_path)
    owner = token_hash("history-owner")
    other = token_hash("history-other")
    service.add_cart_item(root, item["id"], 1, owner_kind="anonymous", guest_token_hash=owner)
    created = service.checkout(
        root, owner_kind="anonymous", guest_token_hash=owner,
        request_key="history-checkout", buyer_name="Private", buyer_email="private@example.com"
    )
    # A pre-owner order remains intentionally unlistable rather than being
    # guessed into an owner from buyer_email.
    schema_db.execute(
        "INSERT INTO shop_orders(item_id,item_path,item_title,buyer_name,buyer_email,amount_cents,currency,status,metadata) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (item["id"], "asset.txt", "Asset", "Legacy", "private@example.com", 100, "CNY", "pending", "{}"),
    )
    schema_db.commit()

    rows = service.buyer_orders(root, owner_kind="anonymous", guest_token_hash=owner)
    assert [row["id"] for row in rows] == [created["orders"][0]["id"]]
    assert all(field not in rows[0] for field in ("item_path", "buyer_name", "buyer_email", "metadata", "buyer_owner_key"))
    assert service.buyer_orders(root, owner_kind="anonymous", guest_token_hash=other) == []
    assert service.buyer_orders(root, owner_kind="anonymous", guest_token_hash=owner, status="fulfilled") == []


def test_guest_cart_and_wishlist_merge_is_atomic_idempotent_and_reprices(schema_db, tmp_path):
    root, service, item = _setup(schema_db, tmp_path)
    schema_db.execute(
        "INSERT INTO users(username,password,role,is_active) VALUES(?,?,?,1)",
        ("merge-user", "x", "viewer"),
    )
    user_id = int(schema_db.execute("SELECT id FROM users WHERE username=?", ("merge-user",)).fetchone()[0])
    guest_cart = token_hash("merge-cart")
    guest_wishlist = token_hash("merge-wishlist")

    service.add_cart_item(root, item["id"], 2, owner_kind="anonymous", guest_token_hash=guest_cart)
    service.add_cart_item(root, item["id"], 3, owner_kind="user", user_id=user_id)
    service.wishlist_put(root, item["id"], owner_kind="anonymous", guest_token_hash=guest_wishlist)
    service.wishlist_put(root, item["id"], owner_kind="user", user_id=user_id)
    schema_db.execute("UPDATE shop_items SET price_cents=125 WHERE id=?", (item["id"],))
    schema_db.commit()

    result = service.merge_guest_into_user(
        root,
        user_id=user_id,
        guest_cart_token_hash=guest_cart,
        guest_wishlist_token_hash=guest_wishlist,
    )
    assert result["merged"] is True
    assert result["cart"]["items"][0]["quantity"] == 5
    assert result["cart"]["items"][0]["unit_price_cents"] == 125
    assert [row["item_id"] for row in result["wishlist"]] == [item["id"]]
    assert "merge-cart" not in str(result)
    assert schema_db.execute(
        "SELECT status FROM shop_carts WHERE owner_type='anonymous' AND owner_key=?",
        (guest_cart,),
    ).fetchone()[0] == "merged"

    retry = service.merge_guest_into_user(
        root,
        user_id=user_id,
        guest_cart_token_hash=guest_cart,
        guest_wishlist_token_hash=guest_wishlist,
    )
    assert retry["merged"] is False
    assert retry["cart"]["items"][0]["quantity"] == 5
    assert len(retry["wishlist"]) == 1


def test_missing_cart_line_is_explicit_not_found(schema_db, tmp_path):
    root, service, item = _setup(schema_db, tmp_path)
    with pytest.raises(NotFoundError):
        service.update_cart_item(
            root, 999999, 1, owner_kind="anonymous", guest_token_hash=token_hash("missing-line")
        )

def test_checkout_idempotency_key_is_scoped_to_cart_generation(schema_db, tmp_path):
    root, service, item = _setup(schema_db, tmp_path)
    guest = token_hash("generation-cart-token")

    service.add_cart_item(root, item["id"], 1, owner_kind="anonymous", guest_token_hash=guest)
    first = service.checkout(
        root,
        owner_kind="anonymous",
        guest_token_hash=guest,
        request_key="reused-key",
        buyer_email="buyer@example.com",
    )
    first_id = first["orders"][0]["id"]

    # A converted cart starts a new lifecycle when the buyer adds another item.
    # Reusing the old idempotency key must not return the prior order.
    reopened = service.add_cart_item(
        root,
        item["id"],
        1,
        owner_kind="anonymous",
        guest_token_hash=guest,
    )
    assert reopened["status"] == "active"
    second = service.checkout(
        root,
        owner_kind="anonymous",
        guest_token_hash=guest,
        request_key="reused-key",
        buyer_email="buyer@example.com",
    )

    assert second["idempotent"] is False
    assert second["orders"][0]["id"] != first_id
    assert schema_db.execute("SELECT COUNT(*) FROM shop_orders").fetchone()[0] == 2

def test_checkout_same_generation_key_rejects_materially_different_payload(schema_db, tmp_path):
    root, service, item = _setup(schema_db, tmp_path)
    guest = token_hash("fingerprint-cart-token")
    service.add_cart_item(root, item["id"], 1, owner_kind="anonymous", guest_token_hash=guest)
    service.checkout(
        root,
        owner_kind="anonymous",
        guest_token_hash=guest,
        request_key="fingerprint-key",
        buyer_email="first@example.com",
    )

    with pytest.raises(IdempotencyKeyReusedError):
        service.checkout(
            root,
            owner_kind="anonymous",
            guest_token_hash=guest,
            request_key="fingerprint-key",
            buyer_email="second@example.com",
        )


def test_merge_guest_cart_with_disabled_item_does_not_block(schema_db, tmp_path):
    root, service, item = _setup(schema_db, tmp_path)
    shops = ShopRepository(schema_db)
    disabled = shops.create_item(
        path="disabled.txt", title="Disabled", price_cents=50, currency="CNY"
    )
    schema_db.execute(
        "INSERT INTO users(username,password,role,is_active) VALUES(?,?,?,1)",
        ("merge-disabled-user", "x", "viewer"),
    )
    user_id = int(
        schema_db.execute(
            "SELECT id FROM users WHERE username=?", ("merge-disabled-user",)
        ).fetchone()[0]
    )
    guest_cart = token_hash("merge-disabled-cart")
    guest_wishlist = token_hash("merge-disabled-wishlist")

    # Both items are added while enabled; the seller disables one before the
    # guest logs in and merges.
    service.add_cart_item(
        root, item["id"], 1, owner_kind="anonymous", guest_token_hash=guest_cart
    )
    service.add_cart_item(
        root, disabled["id"], 1, owner_kind="anonymous", guest_token_hash=guest_cart
    )
    service.wishlist_put(
        root, item["id"], owner_kind="anonymous", guest_token_hash=guest_wishlist
    )
    schema_db.execute("UPDATE shop_items SET enabled=0 WHERE id=?", (disabled["id"],))
    schema_db.commit()

    result = service.merge_guest_into_user(
        root,
        user_id=user_id,
        guest_cart_token_hash=guest_cart,
        guest_wishlist_token_hash=guest_wishlist,
    )
    assert result["merged"] is True
    lines = {int(row["item_id"]): row for row in result["cart"]["items"]}
    assert lines[item["id"]]["line_status"] == "active"
    assert lines[item["id"]]["quantity"] == 1
    assert lines[disabled["id"]]["line_status"] == "unavailable"
    assert [row["item_id"] for row in result["wishlist"]] == [item["id"]]
    # The guest cart was consumed despite the disabled line, and the wishlist
    # was merged alongside it.
    assert (
        schema_db.execute(
            "SELECT status FROM shop_carts WHERE owner_type='anonymous' AND owner_key=?",
            (guest_cart,),
        ).fetchone()[0]
        == "merged"
    )
    assert (
        schema_db.execute(
            "SELECT COUNT(*) FROM shop_wishlist_items w JOIN shop_wishlist_owners o ON o.id=w.owner_id WHERE o.owner_kind='anonymous'"
        ).fetchone()[0]
        == 0
    )


def test_checkout_amount_uses_validated_price_when_price_changes_are_accepted(
    schema_db, tmp_path
):
    root, service, item = _setup(schema_db, tmp_path)
    guest = token_hash("accept-price-token")
    service.add_cart_item(
        root, item["id"], 2, owner_kind="anonymous", guest_token_hash=guest
    )
    schema_db.execute(
        "UPDATE shop_items SET price_cents=250, updated_at=updated_at+1 WHERE id=?",
        (item["id"],),
    )
    schema_db.commit()

    result = service.checkout(
        root,
        owner_kind="anonymous",
        guest_token_hash=guest,
        request_key="accept-price",
        accept_price_changes=True,
        buyer_email="buyer@example.com",
    )
    assert result["idempotent"] is False
    assert result["orders"][0]["amount_cents"] == 500
    assert result["orders"][0]["quantity"] == 2
    assert result["orders"][0]["unit_price_cents"] == 250


def test_checkout_request_key_is_normalized_and_hashed(schema_db, tmp_path):
    root, service, item = _setup(schema_db, tmp_path)
    guest = token_hash("normalized-key-token")
    service.add_cart_item(
        root, item["id"], 1, owner_kind="anonymous", guest_token_hash=guest
    )

    first = service.checkout(
        root,
        owner_kind="anonymous",
        guest_token_hash=guest,
        request_key="  Checkout-Key ",
        buyer_email="buyer@example.com",
    )
    stored = schema_db.execute(
        "SELECT request_key FROM shop_cart_checkouts"
    ).fetchone()
    assert len(stored[0]) == 64
    assert all(char in "0123456789abcdef" for char in stored[0])
    assert stored[0] != "Checkout-Key"

    # A minimal retry with different casing and whitespace maps to the same
    # normalized key and hits the idempotent record.
    retry = service.checkout(
        root,
        owner_kind="anonymous",
        guest_token_hash=guest,
        request_key="checkout-key",
    )
    assert retry["idempotent"] is True
    assert retry["checkout_group_id"] == first["checkout_group_id"]
    assert schema_db.execute("SELECT COUNT(*) FROM shop_orders").fetchone()[0] == 1


def test_get_cart_and_wishlist_do_not_create_rows(schema_db, tmp_path):
    root, service, item = _setup(schema_db, tmp_path)
    guest = token_hash("readonly-guest")

    cart = service.cart(root, owner_kind="anonymous", guest_token_hash=guest)
    assert cart["items"] == []
    assert (
        schema_db.execute(
            "SELECT COUNT(*) FROM shop_carts WHERE owner_type='anonymous' AND owner_key=?",
            (guest,),
        ).fetchone()[0]
        == 0
    )

    assert service.wishlist(root, owner_kind="anonymous", guest_token_hash=guest) == []
    assert (
        schema_db.execute(
            "SELECT COUNT(*) FROM shop_wishlist_owners WHERE token_hash=?",
            (guest,),
        ).fetchone()[0]
        == 0
    )

    # User reads are equally side-effect free.
    schema_db.execute(
        "INSERT INTO users(username,password,role,is_active) VALUES(?,?,?,1)",
        ("readonly-user", "x", "viewer"),
    )
    user_id = int(
        schema_db.execute(
            "SELECT id FROM users WHERE username=?", ("readonly-user",)
        ).fetchone()[0]
    )
    assert service.cart(root, owner_kind="user", user_id=user_id)["items"] == []
    assert (
        schema_db.execute(
            "SELECT COUNT(*) FROM shop_carts WHERE owner_type='user' AND user_id=?",
            (user_id,),
        ).fetchone()[0]
        == 0
    )
    assert service.wishlist(root, owner_kind="user", user_id=user_id) == []
    assert (
        schema_db.execute(
            "SELECT COUNT(*) FROM shop_wishlist_owners WHERE owner_kind='user' AND user_id=?",
            (user_id,),
        ).fetchone()[0]
        == 0
    )

    # The first mutation still materializes the rows as before.
    service.add_cart_item(
        root, item["id"], 1, owner_kind="anonymous", guest_token_hash=guest
    )
    assert (
        schema_db.execute(
            "SELECT COUNT(*) FROM shop_carts WHERE owner_key=?", (guest,)
        ).fetchone()[0]
        == 1
    )
    service.wishlist_put(root, item["id"], owner_kind="anonymous", guest_token_hash=guest)
    assert (
        schema_db.execute(
            "SELECT COUNT(*) FROM shop_wishlist_owners WHERE token_hash=?",
            (guest,),
        ).fetchone()[0]
        == 1
    )
