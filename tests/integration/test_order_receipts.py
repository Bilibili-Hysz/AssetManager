from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from AssetsManager.application.order_service import (
    DEFAULT_RECEIPT_TTL,
    OrderService,
    hash_delivery_token,
    hash_receipt_token,
)
from AssetsManager.domain.errors import (
    NotFoundError,
    OperationNotPermitted,
    StoreNotAcceptingOrdersError,
    ValidationError,
)
from AssetsManager.repositories.order_repository import OrderRepository
from AssetsManager.repositories.seller_profile_repository import SellerProfileRepository
from AssetsManager.repositories.shop_repository import ShopRepository


def _service(schema_db, tmp_path, *, now: float = 1_000.0):
    root = tmp_path / "library"
    root.mkdir()
    (root / "asset.txt").write_text("asset", encoding="utf-8")
    shops = ShopRepository(schema_db)
    orders = OrderRepository(schema_db)
    item = shops.create_item(
        path="asset.txt",
        title="Asset",
        price_cents=125,
        metadata={"private": "seller-only"},
    )
    service = OrderService(
        repository=orders,
        shop_repository=shops,
        clock=lambda: now,
    )
    return root, item, orders, service


def test_create_order_with_receipt_persists_only_hash_and_returns_buyer_dto(
    schema_db, tmp_path
):
    root, item, _orders, service = _service(schema_db, tmp_path)

    buyer_order, receipt = service.create_order_with_receipt(
        root,
        {
            "item_id": item["id"],
            "buyer_name": "Private Buyer",
            "buyer_email": "buyer@example.com",
        },
    )

    assert buyer_order["status"] == "pending"
    assert set(buyer_order) == {
        "id",
        "item_id",
        "item_title",
        "amount_cents",
        "currency",
        "status",
        "created_at",
        "updated_at",
        "delivery_available",
    }
    assert buyer_order["delivery_available"] is False
    assert len(receipt) >= 40
    stored = schema_db.execute(
        "SELECT token_hash, order_id, created_at, expires_at, revoked_at "
        "FROM shop_order_receipts WHERE order_id=?",
        (buyer_order["id"],),
    ).fetchone()
    assert stored == (
        hash_receipt_token(receipt),
        buyer_order["id"],
        1_000.0,
        1_000.0 + DEFAULT_RECEIPT_TTL,
        None,
    )
    assert receipt not in repr(buyer_order)


def test_receipt_order_creation_is_atomically_blocked_when_store_pauses(
    schema_db, tmp_path
):
    root, item, _orders, service = _service(schema_db, tmp_path)
    SellerProfileRepository(schema_db).update_profile({"accept_orders": False})

    with pytest.raises(StoreNotAcceptingOrdersError):
        service.create_order_with_receipt(
            root,
            {"item_id": item["id"]},
            require_accepting_orders=True,
        )

    assert schema_db.execute("SELECT COUNT(*) FROM shop_orders").fetchone() == (0,)


def test_legacy_create_order_keeps_dict_shape_and_does_not_fabricate_receipt(
    schema_db, tmp_path
):
    root, item, _orders, service = _service(schema_db, tmp_path)

    order = service.create_order(root, {"item_id": item["id"]})

    assert isinstance(order, dict)
    assert schema_db.execute(
        "SELECT 1 FROM shop_order_receipts WHERE order_id=?", (order["id"],)
    ).fetchone() is None
    with pytest.raises(NotFoundError):
        service.get_order_by_receipt(root, order["id"], "x" * 43)


def test_receipt_query_separates_buyer_and_seller_dtos(schema_db, tmp_path):
    root, item, _orders, service = _service(schema_db, tmp_path)
    buyer_order, receipt = service.create_order_with_receipt(
        root,
        {
            "item_id": item["id"],
            "buyer_name": "Private Buyer",
            "buyer_email": "buyer@example.com",
        },
    )

    queried = service.get_order_by_receipt(root, buyer_order["id"], receipt)
    seller = service.get_seller_order(root, buyer_order["id"])

    assert queried == buyer_order
    assert "buyer_email" not in queried
    assert "buyer_name" not in queried
    assert "metadata" not in queried
    assert "item_path" not in queried
    assert seller["buyer_email"] == "buyer@example.com"
    assert seller["buyer_name"] == "Private Buyer"
    assert seller["metadata"] == {}
    assert seller["item_path"] == "asset.txt"
    assert "delivery_path" not in seller
    assert "delivery_token_hash" not in seller

    with pytest.raises(NotFoundError):
        service.get_order_by_receipt(root, buyer_order["id"], "wrong" * 10)


def test_receipt_recovery_adds_owner_scoped_credential_without_revoking_old_one(
    schema_db, tmp_path
):
    root, item, _orders, service = _service(schema_db, tmp_path)
    owner = "a" * 64
    order, original = service.create_order_with_receipt(
        root,
        {"item_id": item["id"]},
        buyer_owner_type="anonymous",
        buyer_owner_key=owner,
    )

    recovered = service.recover_receipt_for_owner(
        root,
        order["id"],
        owner_type="anonymous",
        owner_key=owner,
    )
    assert recovered != original
    assert service.get_order_by_receipt(root, order["id"], original)["id"] == order["id"]
    assert service.get_order_by_receipt(root, order["id"], recovered)["id"] == order["id"]
    with pytest.raises(NotFoundError):
        service.recover_receipt_for_owner(
            root,
            order["id"],
            owner_type="anonymous",
            owner_key="b" * 64,
        )


def test_receipt_delivery_shares_atomic_download_limit_with_bearer_api(
    schema_db, tmp_path
):
    root, item, _orders, service = _service(schema_db, tmp_path)
    order, receipt = service.create_order_with_receipt(root, {"item_id": item["id"]})
    with pytest.raises(NotFoundError):
        service.confirm_by_receipt(root, order["id"], "wrong" * 10)
    confirmed = service.confirm_by_receipt(root, order["id"], receipt)
    assert confirmed["delivery_available"] is False
    replayed = service.confirm_by_receipt(root, order["id"], receipt)
    assert replayed == confirmed
    fulfilled, bearer, _claim = service.fulfill(root, order["id"], max_downloads=2, expires_in=60)

    assert "buyer_email" in fulfilled
    assert "metadata" in fulfilled
    assert "delivery_path" not in fulfilled
    assert "delivery_token_hash" not in fulfilled
    buyer_fulfilled = service.get_order_by_receipt(root, order["id"], receipt)
    assert buyer_fulfilled["delivery_available"] is True

    delivery, target = service.resolve_delivery(root, bearer, consume=True)
    assert target == root / "asset.txt"
    assert set(delivery) == {
        "order_id",
        "item_id",
        "item_title",
        "status",
        "max_downloads",
        "download_count",
        "expires_at",
        "last_download_at",
    }
    assert delivery["download_count"] == 1

    receipt_delivery, receipt_target = service.resolve_delivery_by_receipt(
        root, order["id"], receipt, consume=True
    )
    assert receipt_target == target
    assert receipt_delivery["download_count"] == 2

    with pytest.raises(OperationNotPermitted, match="Download limit"):
        service.resolve_delivery_by_receipt(root, order["id"], receipt, consume=True)


def test_delivery_rotation_revokes_old_token_and_issues_replacement(
    schema_db, tmp_path
):
    root, item, orders, service = _service(schema_db, tmp_path)
    order, receipt = service.create_order_with_receipt(root, {"item_id": item["id"]})
    service.confirm_by_receipt(root, order["id"], receipt)
    _fulfilled, old_token, _claim = service.fulfill(root, order["id"], max_downloads=2, expires_in=60)

    rotated, new_token, _claim = service.rotate_delivery(root, order["id"])
    assert rotated["status"] == "fulfilled"
    assert new_token != old_token
    # The rotated-away token is revoked: it can no longer be consumed.
    assert orders.get_delivery(hash_delivery_token(old_token))["revoked_at"] is not None
    with pytest.raises(OperationNotPermitted):
        service.resolve_delivery(root, old_token, consume=False)
    assert service.resolve_delivery(root, new_token, consume=True)[1] == root / "asset.txt"
    assert orders.get_delivery(hash_delivery_token(new_token))["download_count"] == 1
    assert service.resolve_delivery_by_receipt(root, order["id"], receipt, consume=True)[1] == root / "asset.txt"


def test_delivery_rotation_inherits_remaining_quota_and_never_inflates(
    schema_db, tmp_path
):
    root, item, orders, service = _service(schema_db, tmp_path)
    order, receipt = service.create_order_with_receipt(root, {"item_id": item["id"]})
    service.confirm_by_receipt(root, order["id"], receipt)
    _fulfilled, bearer, _claim = service.fulfill(root, order["id"], max_downloads=5, expires_in=60)
    for _ in range(3):
        service.resolve_delivery(root, bearer, consume=True)

    rotated, new_token, _claim = service.rotate_delivery(root, order["id"])
    assert rotated["status"] == "fulfilled"
    new_delivery = orders.get_delivery(hash_delivery_token(new_token))
    assert new_delivery is not None
    # The newest token inherits only the remaining quota (5 used 3 -> 2).
    assert new_delivery["max_downloads"] == 2
    assert new_delivery["download_count"] == 0

    # A second rotation must not restore the full quota.
    _rotated2, new_token2, _claim = service.rotate_delivery(root, order["id"])
    assert orders.get_delivery(hash_delivery_token(new_token2))["max_downloads"] == 2

    # An explicit cap cannot exceed the inherited remaining quota either.
    _rotated3, new_token3, _claim = service.rotate_delivery(
        root, order["id"], max_downloads=100
    )
    assert orders.get_delivery(hash_delivery_token(new_token3))["max_downloads"] == 2

    # Total live quota never inflates: only the newest token counts.
    from AssetsManager.repositories.quota_repository import QuotaRepository

    quota = QuotaRepository(schema_db).get_quota()
    assert quota["delivery_tokens"] == 1
    assert quota["download_limit"] == 2
    assert quota["downloads_used"] == 0
    assert quota["downloads_remaining"] == 2


def test_delivery_rotation_is_rejected_when_remaining_quota_is_exhausted(
    schema_db, tmp_path
):
    root, item, orders, service = _service(schema_db, tmp_path)
    order, receipt = service.create_order_with_receipt(root, {"item_id": item["id"]})
    service.confirm_by_receipt(root, order["id"], receipt)
    _fulfilled, bearer, _claim = service.fulfill(root, order["id"], max_downloads=2, expires_in=60)
    service.resolve_delivery(root, bearer, consume=True)
    service.resolve_delivery(root, bearer, consume=True)

    with pytest.raises(OperationNotPermitted, match="No download quota remains"):
        service.rotate_delivery(root, order["id"])


def test_revoke_delivery_requires_seller_and_blocks_every_token(schema_db, tmp_path):
    root, item, orders, service = _service(schema_db, tmp_path)
    order, receipt = service.create_order_with_receipt(root, {"item_id": item["id"]})
    service.confirm_by_receipt(root, order["id"], receipt)
    _fulfilled, bearer, _claim = service.fulfill(root, order["id"], max_downloads=2, expires_in=60)
    _rotated, rotated_token, _claim = service.rotate_delivery(root, order["id"])

    with pytest.raises(OperationNotPermitted, match="Seller authentication required"):
        service.revoke_delivery(root, order["id"])

    result = service.revoke_delivery(root, order["id"], seller={"kind": "seller"})
    assert result["status"] == "fulfilled"
    remaining = schema_db.execute(
        "SELECT COUNT(*) FROM shop_delivery_tokens "
        "WHERE order_id=? AND revoked_at IS NULL",
        (order["id"],),
    ).fetchone()
    assert remaining == (0,)

    with pytest.raises(OperationNotPermitted, match="revoked"):
        service.resolve_delivery(root, bearer, consume=False)
    with pytest.raises(OperationNotPermitted, match="revoked"):
        service.resolve_delivery(root, rotated_token, consume=False)
    # Rotation cannot resurrect delivery after revocation.
    with pytest.raises(OperationNotPermitted):
        service.rotate_delivery(root, order["id"])


def test_fulfill_and_rotate_reject_expiry_beyond_one_year(schema_db, tmp_path):
    root, item, _orders, service = _service(schema_db, tmp_path)
    order, receipt = service.create_order_with_receipt(root, {"item_id": item["id"]})
    service.confirm_by_receipt(root, order["id"], receipt)
    too_long = 366 * 24 * 60 * 60

    with pytest.raises(ValidationError, match="expires_in"):
        service.fulfill(root, order["id"], expires_in=too_long)

    _fulfilled, _bearer, _claim = service.fulfill(root, order["id"], expires_in=60)
    with pytest.raises(ValidationError, match="expires_in"):
        service.rotate_delivery(root, order["id"], expires_in=too_long)


def test_receipt_delivery_consumption_is_atomic_under_concurrency(schema_db, tmp_path):
    root, item, orders, service = _service(schema_db, tmp_path)
    order, receipt = service.create_order_with_receipt(root, {"item_id": item["id"]})
    service.confirm_by_receipt(root, order["id"], receipt)
    _fulfilled, bearer, _claim = service.fulfill(root, order["id"], max_downloads=1, expires_in=60)

    def consume_once():
        try:
            service.resolve_delivery_by_receipt(
                root, order["id"], receipt, consume=True
            )
            return True
        except OperationNotPermitted:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: consume_once(), range(2)))

    assert sorted(results) == [False, True]
    stored = orders.get_delivery(hash_delivery_token(bearer))
    assert stored is not None
    assert stored["download_count"] == 1


def test_receipt_expiry_and_revocation_block_query_and_delivery(schema_db, tmp_path):
    now = [1_000.0]
    root = tmp_path / "library"
    root.mkdir()
    (root / "asset.txt").write_text("asset", encoding="utf-8")
    shops = ShopRepository(schema_db)
    orders = OrderRepository(schema_db)
    item = shops.create_item(path="asset.txt", title="Asset", price_cents=0)
    service = OrderService(
        repository=orders,
        shop_repository=shops,
        clock=lambda: now[0],
    )
    order, receipt = service.create_order_with_receipt(root, {"item_id": item["id"]})

    now[0] += DEFAULT_RECEIPT_TTL
    with pytest.raises(OperationNotPermitted, match="expired"):
        service.get_order_by_receipt(root, order["id"], receipt)

    now[0] = 1_001.0
    revoked_order, revoked_receipt = service.create_order_with_receipt(
        root, {"item_id": item["id"]}
    )
    service.revoke(root, revoked_order["id"])
    with pytest.raises(OperationNotPermitted, match="revoked"):
        service.get_order_by_receipt(root, revoked_order["id"], revoked_receipt)
