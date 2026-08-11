from concurrent.futures import ThreadPoolExecutor

import pytest

from AssetsManager.application.order_service import (
    OrderService,
    hash_delivery_request_key,
    hash_delivery_token,
)
from AssetsManager.domain.errors import OperationNotPermitted, ValidationError
from AssetsManager.repositories.order_repository import OrderRepository
from AssetsManager.repositories.shop_repository import ShopRepository


def _setup(schema_db, tmp_path, *, max_downloads=3):
    root = tmp_path / "library"
    root.mkdir()
    (root / "asset.txt").write_text("asset", encoding="utf-8")
    shops = ShopRepository(schema_db)
    orders = OrderRepository(schema_db)
    item = shops.create_item(path="asset.txt", title="Asset", price_cents=125)
    service = OrderService(repository=orders, shop_repository=shops)
    order, receipt = service.create_order_with_receipt(root, {"item_id": item["id"]})
    service.confirm_by_receipt(root, order["id"], receipt)
    _fulfilled, bearer, _claim = service.fulfill(
        root, order["id"], max_downloads=max_downloads, expires_in=60
    )
    return root, order, receipt, bearer, orders, service


def test_bearer_download_request_key_replay_does_not_consume_again(schema_db, tmp_path):
    root, order, _receipt, bearer, orders, service = _setup(schema_db, tmp_path, max_downloads=1)

    first, first_target = service.resolve_delivery(
        root, bearer, consume=True, request_key="download-attempt-1"
    )
    second, second_target = service.resolve_delivery(
        root, bearer, consume=True, request_key="download-attempt-1"
    )

    assert first_target == second_target == root / "asset.txt"
    assert first["download_count"] == second["download_count"] == 1
    stored = orders.get_delivery(hash_delivery_token(bearer))
    assert stored is not None
    assert stored["download_count"] == 1
    attempt = orders.get_delivery_attempt(
        credential_kind="bearer",
        credential_hash=hash_delivery_token(bearer),
        request_key_hash=hash_delivery_request_key("download-attempt-1"),
    )
    assert attempt is not None
    assert attempt["state"] == "consumed"

    with pytest.raises(OperationNotPermitted, match="Download limit"):
        service.resolve_delivery(root, bearer, consume=True, request_key="download-attempt-2")


def test_receipt_download_request_key_replay_is_idempotent(schema_db, tmp_path):
    root, order, receipt, bearer, orders, service = _setup(schema_db, tmp_path, max_downloads=1)

    first, first_target = service.resolve_delivery_by_receipt(
        root, order["id"], receipt, consume=True, request_key="receipt-attempt-1"
    )
    second, second_target = service.resolve_delivery_by_receipt(
        root, order["id"], receipt, consume=True, request_key="receipt-attempt-1"
    )

    assert first_target == second_target == root / "asset.txt"
    assert first["download_count"] == second["download_count"] == 1
    stored = orders.get_delivery(hash_delivery_token(bearer))
    assert stored is not None
    assert stored["download_count"] == 1


def test_same_bearer_request_key_is_atomic_under_concurrency(schema_db, tmp_path):
    root, _order, _receipt, bearer, orders, service = _setup(
        schema_db, tmp_path, max_downloads=1
    )

    def consume_once(_index):
        try:
            service.resolve_delivery(
                root, bearer, consume=True, request_key="concurrent-download"
            )
            return True
        except OperationNotPermitted:
            return False

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(consume_once, range(4)))

    assert results == [True, True, True, True]
    stored = orders.get_delivery(hash_delivery_token(bearer))
    assert stored is not None
    assert stored["download_count"] == 1


def test_different_request_keys_can_consume_remaining_quota_concurrently(
    schema_db, tmp_path
):
    root, _order, _receipt, bearer, orders, service = _setup(
        schema_db, tmp_path, max_downloads=2
    )

    def consume_once(request_key):
        try:
            service.resolve_delivery(
                root, bearer, consume=True, request_key=request_key
            )
            return True
        except OperationNotPermitted:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(consume_once, ("concurrent-download-a", "concurrent-download-b"))
        )

    assert sorted(results) == [True, True]
    stored = orders.get_delivery(hash_delivery_token(bearer))
    assert stored is not None
    assert stored["download_count"] == 2


def test_download_request_key_is_validated(schema_db, tmp_path):
    root, _order, _receipt, bearer, _orders, service = _setup(schema_db, tmp_path)

    with pytest.raises(ValidationError, match="idempotency_key"):
        service.resolve_delivery(root, bearer, consume=True, request_key=" ")
    with pytest.raises(ValidationError, match="idempotency_key"):
        service.resolve_delivery(root, bearer, consume=True, request_key="x" * 201)
