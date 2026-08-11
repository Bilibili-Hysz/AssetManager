"""HTTP contract for one-time share-claim delivery redemption."""
import asyncio
import json
from types import SimpleNamespace
from unittest import mock

import pytest
from aiohttp import streams, web
from aiohttp.test_utils import make_mocked_request

from AssetsManager.lan.api import setup_routes
from AssetsManager.lan.routes import shop as shop_routes


@pytest.fixture(autouse=True)
def _commerce_enabled(monkeypatch):
    """Enable the Commerce feature gate for every route in this module."""
    from AssetsManager.lan.routes import commerce_policy

    class Settings:
        def get(self, key, default=None):
            return {"lan_commerce_enabled": True}.get(key, default)

    monkeypatch.setattr(
        commerce_policy.AppSettings,
        "instance",
        classmethod(lambda cls: Settings()),
    )


def _claim_post(order_id, claim, remote):
    """Build a mocked POST claim request inside the running event loop.

    aiohttp's ``StreamReader`` requires a live loop, so the payload must be
    constructed where ``asyncio.run`` is already running.  The per-IP key is
    pinned so route tests never share a throttling bucket.
    """
    protocol = mock.Mock()
    reader = streams.StreamReader(protocol, limit=2**20)
    reader.feed_data(json.dumps({"claim": claim}).encode("utf-8"))
    reader.feed_eof()
    request = make_mocked_request(
        "POST",
        f"/api/shop/delivery/{order_id}/claim",
        match_info={"order_id": str(order_id)},
        payload=reader,
    )
    shop_routes._claim_request_remote = lambda _request: remote
    return request


def test_share_claim_route_is_registered():
    app = web.Application()
    setup_routes(app)
    registered = {(route.method, route.resource.canonical) for route in app.router.routes()}
    assert ("POST", "/api/shop/delivery/{order_id}/claim") in registered


def test_share_claim_route_returns_ok_and_sets_receipt_cookie(monkeypatch):
    calls = []

    class Orders:
        def claim_share_delivery(self, root, order_id, claim):
            calls.append((root, order_id, claim))
            return (
                {
                    "id": int(order_id),
                    "item_id": 3,
                    "item_title": "Asset",
                    "amount_cents": 1200,
                    "currency": "CNY",
                    "status": "fulfilled",
                    "created_at": 1.0,
                    "updated_at": 1.0,
                    "delivery_available": True,
                },
                "claim-receipt-token",
            )

    lan = SimpleNamespace(library_root="library")
    services = SimpleNamespace(orders=Orders())
    monkeypatch.setattr(shop_routes, "get_lan", lambda request: lan)
    monkeypatch.setattr(shop_routes, "get_commerce_services", lambda request: services)

    async def exercise():
        request = _claim_post(7, "claim-code-12345678901234567890", "198.51.100.10")
        response = await shop_routes.handle_shop_claim_delivery(request)
        assert response.status == 200
        assert json.loads(response.body) == {"ok": True}
        cookie = response.cookies["shop_order_receipt_7"]
        assert cookie.value == "claim-receipt-token"
        assert cookie["httponly"] is True
        assert cookie["path"] == "/api/shop"
        return calls

    assert asyncio.run(exercise()) == [
        ("library", "7", "claim-code-12345678901234567890")
    ]


def test_share_claim_route_returns_uniform_404_on_failure(monkeypatch):
    class Orders:
        def claim_share_delivery(self, root, order_id, claim):
            return None

    lan = SimpleNamespace(library_root="library")
    services = SimpleNamespace(orders=Orders())
    monkeypatch.setattr(shop_routes, "get_lan", lambda request: lan)
    monkeypatch.setattr(shop_routes, "get_commerce_services", lambda request: services)

    async def exercise():
        request = _claim_post(7, "used-or-wrong-claim-code-123456", "198.51.100.11")
        return await shop_routes.handle_shop_claim_delivery(request)

    response = asyncio.run(exercise())
    assert response.status == 404
    assert json.loads(response.body)["code"] == "delivery_not_found"


def test_share_claim_route_rejects_missing_claim_field(monkeypatch):
    def should_not_resolve(_request):
        raise AssertionError("missing claim must fail before service resolution")

    monkeypatch.setattr(shop_routes, "get_lan", should_not_resolve)
    monkeypatch.setattr(shop_routes, "get_commerce_services", should_not_resolve)

    async def exercise():
        protocol = mock.Mock()
        reader = streams.StreamReader(protocol, limit=2**20)
        reader.feed_data(b"{}")
        reader.feed_eof()
        request = make_mocked_request(
            "POST",
            "/api/shop/delivery/7/claim",
            match_info={"order_id": "7"},
            payload=reader,
        )
        shop_routes._claim_request_remote = lambda _request: "198.51.100.12"
        return await shop_routes.handle_shop_claim_delivery(request)

    response = asyncio.run(exercise())
    assert response.status == 400
    assert json.loads(response.body)["code"] == "validation_error"


def test_share_claim_route_throttles_failed_attempts_per_ip(monkeypatch):
    class Orders:
        def claim_share_delivery(self, root, order_id, claim):
            return None

    lan = SimpleNamespace(library_root="library")
    services = SimpleNamespace(orders=Orders())
    monkeypatch.setattr(shop_routes, "get_lan", lambda request: lan)
    monkeypatch.setattr(shop_routes, "get_commerce_services", lambda request: services)

    async def exercise():
        for _ in range(shop_routes._CLAIM_MAX_FAILURES):
            request = _claim_post(7, "wrong-claim-code-1234567890", "203.0.113.77")
            response = await shop_routes.handle_shop_claim_delivery(request)
            assert response.status == 404
        request = _claim_post(7, "wrong-claim-code-1234567890", "203.0.113.77")
        throttled = await shop_routes.handle_shop_claim_delivery(request)
        assert throttled.status == 429
        body = json.loads(throttled.body)
        assert "retry_after" in body
        assert throttled.headers.get("Retry-After") == str(body["retry_after"])
        # A different IP is unaffected by the throttled IP.
        request = _claim_post(7, "wrong-claim-code-1234567890", "203.0.113.78")
        response = await shop_routes.handle_shop_claim_delivery(request)
        assert response.status == 404
        return throttled

    throttled = asyncio.run(exercise())
    assert throttled.status == 429


def test_share_claim_limiter_counts_failures_within_window():
    window = shop_routes._CLAIM_WINDOW_SECONDS
    now = 1_000.0
    remote = "203.0.113.99"
    shop_routes._claim_failures.pop(remote, None)
    try:
        for _ in range(shop_routes._CLAIM_MAX_FAILURES):
            assert shop_routes._claim_brute_force_allowed(remote, now) is True
            shop_routes._record_claim_failure(remote, now)
        assert shop_routes._claim_brute_force_allowed(remote, now) is False
        # Failures leave the window and the IP recovers.
        assert shop_routes._claim_brute_force_allowed(remote, now + window) is True
    finally:
        shop_routes._claim_failures.pop(remote, None)
