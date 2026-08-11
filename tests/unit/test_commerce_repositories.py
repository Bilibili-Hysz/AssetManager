import hashlib
import sqlite3

import pytest

from AssetsManager.domain.errors import DuplicateError
from AssetsManager.repositories.order_repository import OrderRepository
from AssetsManager.repositories.quota_repository import QuotaRepository
from AssetsManager.repositories.shop_repository import ShopRepository


def test_shop_order_and_delivery_round_trip(schema_db):
    shops = ShopRepository(schema_db)
    orders = OrderRepository(schema_db)
    quotas = QuotaRepository(schema_db)

    item = shops.create_item(
        path="projects/kit",
        title="Kit",
        description="A useful kit",
        price_cents=1299,
        currency="usd",
        cover_path="projects/kit/cover.png",
    )
    assert item["id"] > 0
    assert item["currency"] == "USD"
    updated = shops.update_item(
        item["id"], title="Kit v2", description="Updated", price_cents=1499
    )
    assert updated is not None
    assert shops.get_item(item["id"])["title"] == "Kit v2"
    assert shops.list_items() == [updated]

    order = orders.create_order(
        item_id=item["id"],
        buyer_name="Buyer",
        buyer_email="buyer@example.com",
        amount_cents=updated["price_cents"],
        currency=updated["currency"],
    )
    assert order["item_path"] == "projects/kit"
    assert order["item_title"] == "Kit v2"
    assert order["amount_cents"] == 1499
    assert order["status"] == "pending"
    assert orders.list_events(order["id"])[0]["event_type"] == "created"

    confirmed = orders.transition_status(
        order["id"], expected_status="pending", new_status="confirmed"
    )
    assert confirmed is not None and confirmed["status"] == "confirmed"
    assert orders.transition_status(
        order["id"], expected_status="pending", new_status="revoked"
    ) is None

    token_hash = hashlib.sha256(b"secret-token").hexdigest()
    fulfilled = orders.fulfill_order(
        order["id"],
        expected_status="confirmed",
        delivery_token_hash=token_hash,
        delivery_path="projects/kit",
        max_downloads=2,
        expires_at=4_000_000_000.0,
    )
    assert fulfilled is not None and fulfilled["status"] == "fulfilled"
    delivery = orders.get_delivery(token_hash)
    assert delivery is not None
    assert delivery["delivery_path"] == "projects/kit"
    assert orders.consume_download(
        order["id"], token_hash=token_hash, expected_download_count=0,
        consumed_at=2_000_000_000.0,
    ) is True
    assert orders.consume_download(
        order["id"], token_hash=token_hash, expected_download_count=0,
        consumed_at=2_000_000_001.0,
    ) is False
    assert quotas.get(token_hash)["remaining_downloads"] == 1
    assert quotas.consume(token_hash, now=2_000_000_002.0)["remaining_downloads"] == 0
    assert quotas.consume(token_hash, now=2_000_000_003.0) is None


def test_repository_contract_matches_commerce_services(schema_db):
    shops = ShopRepository(schema_db)
    orders = OrderRepository(schema_db)
    quotas = QuotaRepository(schema_db)

    item = shops.create_item(path="projects/one", title="One", price_cents=100)
    assert shops.get_item(item["id"])["path"] == "projects/one"
    assert shops.list_items(include_disabled=True)[0]["enabled"] is True
    assert shops.update_item(item["id"], enabled=False)["enabled"] is False
    assert shops.list_items() == []

    order = orders.create_order(
        item_id=item["id"], amount_cents=100, currency="CNY", status="pending"
    )
    assert orders.get_order(order["id"])["id"] == order["id"]
    assert orders.list_orders(status="pending")[0]["id"] == order["id"]
    assert orders.stats()["pending_orders"] == 1
    assert orders.export_orders()[0]["id"] == order["id"]
    assert quotas.get_quota() == {
        "delivery_tokens": 0,
        "download_limit": 0,
        "downloads_used": 0,
        "downloads_remaining": 0,
    }


def test_shop_repository_filters_by_status_and_rejects_invalid_status(schema_db):
    shops = ShopRepository(schema_db)
    active = shops.create_item(path="active", title="Active", price_cents=1)
    draft = shops.create_item(
        path="draft", title="Draft", price_cents=1, enabled=False, metadata={"status": "draft"}
    )
    archived = shops.create_item(path="archived", title="Archived", price_cents=1, enabled=False)

    assert [item["id"] for item in shops.list_items(status="active")] == [active["id"]]
    assert shops.list_items(status="draft", include_disabled=True)[0]["id"] == draft["id"]
    assert shops.list_items(status="archived", include_disabled=True)[0]["id"] == archived["id"]
    with pytest.raises(ValueError, match="status"):
        shops.list_items(status="unknown")


def test_shop_repository_list_catalog_filters_before_paging_and_sorts_newest(schema_db):
    shops = ShopRepository(schema_db)
    shops.create_item(path="shop/old", title="Old", price_cents=1, created_at=1)
    newest = shops.create_item(
        path="shop/new", title="Newest", description="A searchable kit", price_cents=1, created_at=3
    )
    shops.create_item(path="outside/hidden", title="Newest outside", price_cents=1, created_at=4)
    shops.create_item(
        path="shop/draft", title="Draft", price_cents=1, created_at=5,
        enabled=False, metadata={"status": "draft"},
    )
    tied = shops.create_item(path="shop/tied", title="Tied", price_cents=1, created_at=3)

    result = shops.list_catalog(page=1, page_size=2, authorized_roots=("shop",))
    assert [item["id"] for item in result["items"]] == [tied["id"], newest["id"]]
    assert result["total"] == 3
    assert shops.list_catalog(q="SEARCHABLE", page_size=1, authorized_roots=("shop",))["items"][0]["id"] == newest["id"]


def test_shop_repository_duplicate_path_is_a_business_error(schema_db):
    shops = ShopRepository(schema_db)
    first = shops.create_item(path="projects/one", title="One", price_cents=100)
    with pytest.raises(DuplicateError, match="Duplicate shop item: projects/one"):
        shops.create_item(path="projects/one", title="Two", price_cents=200)
    # A failed insert must not poison the row or the transaction.
    assert shops.get_item(first["id"])["title"] == "One"

    second = shops.create_item(path="projects/two", title="Two", price_cents=200)
    with pytest.raises(DuplicateError, match="Duplicate shop item: projects/one"):
        shops.update_item(second["id"], path="projects/one")
    # A failed update must leave the original path intact.
    assert shops.get_item(second["id"])["path"] == "projects/two"
    # Updating an item onto its own path stays valid.
    assert shops.update_item(first["id"], path="projects/one") is not None


def test_shop_repository_list_items_filters_status_before_limit(schema_db):
    shops = ShopRepository(schema_db)
    active = [
        shops.create_item(
            path=f"a/{i}", title=f"Active {i}", price_cents=1, created_at=float(i)
        )
        for i in range(1, 6)
    ]
    archived = [
        shops.create_item(
            path=f"z/{i}", title=f"Archived {i}", price_cents=1,
            enabled=False, created_at=float(10 + i),
        )
        for i in range(1, 6)
    ]
    # All archived rows are newer, so the old post-LIMIT Python filter would
    # only ever see archived rows at limit=3 and return nothing for "active".
    # The fix filters in SQL first, so the window yields the newest active rows.
    result = shops.list_items(status="active", include_disabled=True, limit=3)
    assert [item["id"] for item in result] == [
        item["id"] for item in reversed(active)
    ][:3]
    assert result != []
    archived_result = shops.list_items(status="archived", include_disabled=True, limit=3)
    assert [item["id"] for item in archived_result] == [
        item["id"] for item in reversed(archived)
    ][:3]

    statements: list[str] = []
    schema_db.set_trace_callback(statements.append)
    try:
        shops.list_items(status="active", include_disabled=True, limit=3)
    finally:
        schema_db.set_trace_callback(None)
    assert any("json_valid" in sql and "LIMIT" in sql for sql in statements)


def test_shop_repository_list_catalog_uses_sql_filters_and_preserves_legacy_metadata(schema_db):
    shops = ShopRepository(schema_db)
    indexes = {row[1] for row in schema_db.execute("PRAGMA index_list(shop_items)")}
    assert "idx_shop_items_enabled_created" in indexes
    legacy_active = shops.create_item(
        path="shop/legacy-active", title="Legacy active", price_cents=1, created_at=3
    )
    shops.create_item(
        path="shop/draft", title="Draft", price_cents=1, created_at=4,
        metadata={"status": "draft"},
    )
    malformed = shops.create_item(
        path="shop/malformed", title="Malformed", price_cents=1, created_at=2
    )
    schema_db.execute(
        "UPDATE shop_items SET metadata=? WHERE id=?",
        ("{not-json", malformed["id"]),
    )
    schema_db.commit()

    statements: list[str] = []
    schema_db.set_trace_callback(statements.append)
    try:
        result = shops.list_catalog(page=1, page_size=1, authorized_roots=("shop",))
    finally:
        schema_db.set_trace_callback(None)

    assert result["total"] == 2
    assert result["items"][0]["id"] == legacy_active["id"]
    assert any("json_valid" in sql and "COUNT(*)" in sql for sql in statements)
    assert any("LIMIT 1 OFFSET 0" in sql for sql in statements)


def test_shop_repository_json1_probe_is_cached_per_process(schema_db):
    shops = ShopRepository(schema_db)
    # Force a fresh probe regardless of prior tests in this process.
    ShopRepository._JSON1_AVAILABLE = None
    statements: list[str] = []
    schema_db.set_trace_callback(statements.append)
    try:
        first = shops.list_catalog(page=1, page_size=1, authorized_roots=("shop",))
        second = shops.list_catalog(page=1, page_size=1, authorized_roots=("shop",))
    finally:
        schema_db.set_trace_callback(None)
        # Restore the pristine cache state for any later tests.
        ShopRepository._JSON1_AVAILABLE = None
    # Both requests must behave identically and only the first one may run
    # the JSON1 capability probe (M9-Bug15-3: probe once per process).
    assert first == second
    probes = [sql for sql in statements if sql.strip().startswith("SELECT json_valid")]
    assert len(probes) == 1


def test_shop_repository_list_catalog_validates_paging(schema_db):
    shops = ShopRepository(schema_db)
    with pytest.raises(ValueError, match="page"):
        shops.list_catalog(page=0)
    with pytest.raises(ValueError, match="page_size"):
        shops.list_catalog(page_size=101)


def test_commerce_constraints_and_foreign_keys(schema_db):
    shops = ShopRepository(schema_db)
    orders = OrderRepository(schema_db)
    quotas = QuotaRepository(schema_db)

    with pytest.raises(ValueError, match="price_cents"):
        shops.create_item(path="projects/bad", title="Bad", price_cents=-1)
    with pytest.raises(ValueError, match="currency"):
        shops.create_item(path="projects/bad", title="Bad", price_cents=1, currency="US")
    with pytest.raises(LookupError, match="shop item"):
        orders.create_order(item_id=999, amount_cents=1, currency="CNY")

    item = shops.create_item(path="projects/one", title="One", price_cents=100)
    order = orders.create_order(item_id=item["id"], amount_cents=100, currency="CNY")
    with pytest.raises(ValueError, match="max_downloads"):
        quotas.issue("hash", order["id"], max_downloads=0)

    with pytest.raises(sqlite3.IntegrityError):
        schema_db.execute("DELETE FROM shop_items WHERE id=?", (item["id"],))


def test_expired_or_revoked_delivery_token_is_not_consumed(schema_db):
    shops = ShopRepository(schema_db)
    orders = OrderRepository(schema_db)
    quotas = QuotaRepository(schema_db)
    item = shops.create_item(path="projects/one", title="One", price_cents=100)
    order = orders.create_order(item_id=item["id"], amount_cents=100, currency="CNY")

    quotas.issue("expired", order["id"], max_downloads=1, expires_at=10.0)
    assert quotas.consume("expired", now=10.0) is None
    assert quotas.get("expired")["download_count"] == 0

    quotas.issue("revoked", order["id"], max_downloads=1)
    assert quotas.revoke("revoked", revoked_at=5.0) is True
    assert quotas.consume("revoked", now=6.0) is None
    assert quotas.get("revoked")["download_count"] == 0


def _fulfilled_bearer_token(orders, item, *, max_downloads=3):
    token = hashlib.sha256(b"bearer-cas-token").hexdigest()
    order = orders.create_order(
        item_id=item["id"], amount_cents=100, currency="CNY", status="confirmed"
    )
    orders.fulfill_order(
        order["id"],
        expected_status="confirmed",
        delivery_token_hash=token,
        delivery_path="projects/one",
        max_downloads=max_downloads,
        expires_at=4_000_000_000.0,
    )
    return order, token


def test_complete_delivery_attempt_rejects_stale_expected_download_count(schema_db):
    shops = ShopRepository(schema_db)
    orders = OrderRepository(schema_db)
    item = shops.create_item(path="projects/one", title="One", price_cents=100)
    order, token = _fulfilled_bearer_token(orders, item)

    def attempt(key):
        return dict(
            credential_kind="bearer",
            credential_hash=token,
            request_key_hash=hashlib.sha256(key.encode()).hexdigest(),
            delivery_token_hash=token,
            consumed_at=2_000_000_000.0,
        )

    # A stale expected count must fail without consuming the slot.
    assert orders.complete_delivery_attempt(
        order["id"], expected_download_count=5, **attempt("key-stale")
    ) == "failed"
    assert orders.get_delivery(token)["download_count"] == 0

    # The fresh count succeeds on a different request key.
    assert orders.complete_delivery_attempt(
        order["id"], expected_download_count=0, **attempt("key-fresh")
    ) == "consumed"
    assert orders.get_delivery(token)["download_count"] == 1

    # Replays stay idempotent even with a stale count.
    assert orders.complete_delivery_attempt(
        order["id"], expected_download_count=0, **attempt("key-fresh")
    ) == "replayed"


def test_complete_delivery_attempt_by_receipt_rejects_stale_expected_download_count(
    schema_db,
):
    shops = ShopRepository(schema_db)
    orders = OrderRepository(schema_db)
    item = shops.create_item(path="projects/one", title="One", price_cents=100)
    receipt = hashlib.sha256(b"receipt-cas-token").hexdigest()
    token = hashlib.sha256(b"receipt-delivery-token").hexdigest()
    order = orders.create_order(
        item_id=item["id"],
        amount_cents=100,
        currency="CNY",
        status="confirmed",
        receipt_token_hash=receipt,
        receipt_expires_at=5_000_000_000.0,
    )
    orders.fulfill_order(
        order["id"],
        expected_status="confirmed",
        delivery_token_hash=token,
        delivery_path="projects/one",
        max_downloads=3,
        expires_at=4_000_000_000.0,
    )

    def attempt(key):
        return dict(
            credential_kind="receipt",
            credential_hash=receipt,
            request_key_hash=hashlib.sha256(key.encode()).hexdigest(),
            receipt_token_hash=receipt,
            delivery_token_hash=token,
            consumed_at=2_000_000_000.0,
        )

    assert orders.complete_delivery_attempt_by_receipt(
        order["id"], expected_download_count=9, **attempt("key-stale")
    ) == "failed"
    assert orders.get_delivery(token)["download_count"] == 0
    assert orders.complete_delivery_attempt_by_receipt(
        order["id"], expected_download_count=0, **attempt("key-fresh")
    ) == "consumed"
    assert orders.get_delivery(token)["download_count"] == 1


def test_transition_status_rejects_unknown_new_status(schema_db):
    shops = ShopRepository(schema_db)
    orders = OrderRepository(schema_db)
    item = shops.create_item(path="projects/one", title="One", price_cents=100)
    order = orders.create_order(item_id=item["id"], amount_cents=100, currency="CNY")

    with pytest.raises(ValueError, match="new_status"):
        orders.transition_status(
            order["id"], expected_status="pending", new_status="shipped"
        )


def test_revoke_delivery_tokens_marks_all_order_tokens_with_server_timestamp(schema_db):
    shops = ShopRepository(schema_db)
    orders = OrderRepository(schema_db)
    item = shops.create_item(path="projects/one", title="One", price_cents=100)
    order, token = _fulfilled_bearer_token(orders, item)
    second = hashlib.sha256(b"second-rotated-token").hexdigest()
    orders.rotate_fulfilled_delivery(
        order["id"],
        delivery_token_hash=second,
        delivery_path="projects/one",
        expires_at=4_000_000_000.0,
        rotated_at=1_000.0,
    )

    # Rotation already revoked the source token (rotated_at=1000); the
    # explicit revocation only touches the remaining live (rotated) token.
    revoked = orders.revoke_delivery_tokens(order["id"], revoked_at=1_500.0)
    assert revoked == 1
    rows = schema_db.execute(
        "SELECT revoked_at FROM shop_delivery_tokens WHERE order_id=?",
        (order["id"],),
    ).fetchall()
    assert rows == [(1_000.0,), (1_500.0,)]

    # Idempotent: a second revocation touches nothing.
    assert orders.revoke_delivery_tokens(order["id"], revoked_at=1_600.0) == 0
    assert orders.get_delivery(token)["revoked_at"] == 1_000.0


def test_repository_writes_preserve_caller_transaction(schema_db):
    shops = ShopRepository(schema_db)
    schema_db.execute("CREATE TABLE commerce_probe (value TEXT NOT NULL)")
    schema_db.commit()
    schema_db.execute("INSERT INTO commerce_probe VALUES ('rollback-me')")

    item = shops.create_item(path="projects/one", title="One", price_cents=100)
    assert shops.get_item(item["id"]) is not None
    schema_db.rollback()

    assert schema_db.execute("SELECT * FROM commerce_probe").fetchall() == []
    assert shops.get_item(item["id"]) is None
