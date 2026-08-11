"""One-time share-claim delivery: issuance, redemption, and invalidation."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from AssetsManager.application.order_service import (
    DEFAULT_RECEIPT_TTL,
    DEFAULT_SHARE_CLAIM_TTL,
    OrderService,
    hash_receipt_token,
    hash_share_claim,
)
from AssetsManager.repositories.order_repository import OrderRepository
from AssetsManager.repositories.shop_repository import ShopRepository


def _services(schema_db, tmp_path, *, now=1_000.0):
    root = tmp_path / "library"
    root.mkdir()
    (root / "asset.txt").write_text("asset", encoding="utf-8")
    shops = ShopRepository(schema_db)
    orders = OrderRepository(schema_db)
    item = shops.create_item(path="asset.txt", title="Asset", price_cents=100)
    service = OrderService(
        repository=orders,
        shop_repository=shops,
        clock=lambda: now,
    )
    return root, item, orders, service


def _fulfilled_order(schema_db, tmp_path, *, now=1_000.0, max_downloads=3):
    root, item, orders, service = _services(schema_db, tmp_path, now=now)
    order = service.create_order(root, {"item_id": item["id"]})
    service.confirm(root, order["id"])
    fulfilled, token, claim = service.fulfill(
        root, order["id"], max_downloads=max_downloads, expires_in=60
    )
    assert fulfilled["status"] == "fulfilled"
    return root, order, token, claim, orders, service


def test_fulfill_issues_share_claim_and_persists_only_hash(schema_db, tmp_path):
    root, order, _token, claim, _orders, service = _fulfilled_order(
        schema_db, tmp_path
    )
    assert len(claim) >= 20

    stored = schema_db.execute(
        "SELECT claim_hash, order_id, expires_at, claimed_at, revoked_at, created_at "
        "FROM shop_share_claims"
    ).fetchall()
    assert len(stored) == 1
    row = stored[0]
    # Only the SHA-256 hex hash is stored; the plaintext claim never is.
    assert row[0] == hash_share_claim(claim)
    assert claim not in {entry[0] for entry in stored}
    assert len(row[0]) == 64
    assert row[1] == order["id"]
    assert row[2] == 1_000.0 + DEFAULT_SHARE_CLAIM_TTL
    assert row[3] is None
    assert row[4] is None
    assert row[5] == 1_000.0


def test_share_claim_redeems_once_into_receipt_credential(schema_db, tmp_path):
    root, order, _token, claim, _orders, service = _fulfilled_order(
        schema_db, tmp_path, max_downloads=1
    )

    result = service.claim_share_delivery(root, order["id"], claim)
    assert result is not None
    claimant_order, receipt = result
    assert claimant_order["id"] == order["id"]
    assert claimant_order["delivery_available"] is True
    assert len(receipt) >= 40
    # The claim-issued credential works like a regular receipt: cookie-based
    # lookup and download consumption.
    assert service.get_order_by_receipt(root, order["id"], receipt)["id"] == order["id"]
    delivery, target = service.resolve_delivery_by_receipt(
        root, order["id"], receipt, consume=True
    )
    assert target == root / "asset.txt"
    assert delivery["download_count"] == 1
    # The claim row is now marked claimed at the redemption time.
    claimed = schema_db.execute(
        "SELECT claimed_at FROM shop_share_claims WHERE claim_hash=?",
        (hash_share_claim(claim),),
    ).fetchone()
    assert claimed is not None
    assert claimed[0] == 1_000.0

    # Second redemption of the same claim fails (single use).
    assert service.claim_share_delivery(root, order["id"], claim) is None
    # An unknown code fails identically.
    assert service.claim_share_delivery(root, order["id"], "x" * 32) is None
    # A truncated code fails without touching the database.
    assert service.claim_share_delivery(root, order["id"], "short") is None


def test_share_claim_redemption_aligns_receipt_expiry(schema_db, tmp_path):
    root, item, _orders, service = _services(schema_db, tmp_path)
    # A primary receipt row exists only for receipt-issued orders.
    order, _receipt = service.create_order_with_receipt(root, {"item_id": item["id"]})
    service.confirm(root, order["id"])
    _fulfilled, _token, claim = service.fulfill(
        root, order["id"], max_downloads=3, expires_in=60
    )
    updated = schema_db.execute(
        "UPDATE shop_order_receipts SET expires_at=?"
        "WHERE order_id=? AND revoked_at IS NULL",
        (1_000.0 + 12345.0, order["id"]),
    )
    assert updated.rowcount == 1
    _claimant_order, receipt = service.claim_share_delivery(root, order["id"], claim)
    row = schema_db.execute(
        "SELECT expires_at FROM shop_order_receipt_recoveries WHERE token_hash=?",
        (hash_receipt_token(receipt),),
    ).fetchone()
    assert row is not None
    assert row[0] == 1_000.0 + 12345.0


def test_share_claim_expiry_blocks_redemption(schema_db, tmp_path):
    now = [1_000.0]
    root, order, _token, claim, _orders, service = _fulfilled_order(
        schema_db, tmp_path, now=now[0]
    )
    service._clock = lambda: now[0]

    now[0] = 1_000.0 + DEFAULT_SHARE_CLAIM_TTL
    assert service.claim_share_delivery(root, order["id"], claim) is None
    # The claim row is untouched (still unclaimed) but permanently unusable.
    row = schema_db.execute(
        "SELECT claimed_at FROM shop_share_claims WHERE claim_hash=?",
        (hash_share_claim(claim),),
    ).fetchone()
    assert row == (None,)


def test_share_claim_is_revoked_by_delivery_revoke(schema_db, tmp_path):
    root, order, _token, claim, _orders, service = _fulfilled_order(
        schema_db, tmp_path
    )

    service.revoke_delivery(root, order["id"], seller={"kind": "seller"})

    assert service.claim_share_delivery(root, order["id"], claim) is None
    revoked = schema_db.execute(
        "SELECT revoked_at FROM shop_share_claims WHERE claim_hash=?",
        (hash_share_claim(claim),),
    ).fetchone()
    assert revoked is not None
    assert revoked[0] is not None


def test_share_claim_is_revoked_by_delivery_rotation(schema_db, tmp_path):
    root, order, _token, first_claim, _orders, service = _fulfilled_order(
        schema_db, tmp_path
    )

    rotated, _new_token, second_claim = service.rotate_delivery(root, order["id"])
    assert rotated["status"] == "fulfilled"
    assert second_claim != first_claim

    # The rotated-away claim is revoked and can no longer be redeemed.
    assert service.claim_share_delivery(root, order["id"], first_claim) is None
    revoked = schema_db.execute(
        "SELECT revoked_at FROM shop_share_claims WHERE claim_hash=?",
        (hash_share_claim(first_claim),),
    ).fetchone()
    assert revoked is not None
    assert revoked[0] is not None

    # The replacement claim redeems normally, then stays single-use.
    result = service.claim_share_delivery(root, order["id"], second_claim)
    assert result is not None
    _claimant_order, receipt = result
    assert service.get_order_by_receipt(root, order["id"], receipt)["id"] == order["id"]
    assert service.claim_share_delivery(root, order["id"], second_claim) is None


def test_share_claim_redemption_is_atomic_under_concurrency(schema_db, tmp_path):
    root, order, _token, claim, _orders, service = _fulfilled_order(
        schema_db, tmp_path, max_downloads=1
    )

    def redeem_once():
        result = service.claim_share_delivery(root, order["id"], claim)
        return result is not None

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _index: redeem_once(), range(4)))

    assert sorted(results) == [False, False, False, True]
    claimed_rows = schema_db.execute(
        "SELECT COUNT(*) FROM shop_share_claims WHERE claimed_at IS NOT NULL"
    ).fetchone()
    assert claimed_rows == (1,)


def test_share_claim_redemption_falls_back_to_default_receipt_ttl(schema_db, tmp_path):
    root, order, _token, claim, _orders, service = _fulfilled_order(
        schema_db, tmp_path
    )
    # Simulate a legacy order without any primary receipt row: the claim must
    # still mint a usable receipt credential with the default TTL.
    schema_db.execute(
        "DELETE FROM shop_order_receipts WHERE order_id=?", (order["id"],)
    )
    _claimant_order, receipt = service.claim_share_delivery(root, order["id"], claim)
    row = schema_db.execute(
        "SELECT expires_at FROM shop_order_receipt_recoveries WHERE token_hash=?",
        (hash_receipt_token(receipt),),
    ).fetchone()
    assert row is not None
    assert row[0] == 1_000.0 + DEFAULT_RECEIPT_TTL
    assert service.get_order_by_receipt(root, order["id"], receipt)["id"] == order["id"]
