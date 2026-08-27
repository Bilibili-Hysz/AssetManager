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


def test_share_claim_limiter_counts_reserved_attempts_within_window():
    window = shop_routes._CLAIM_WINDOW_SECONDS
    now = 1_000.0
    remote = "203.0.113.99"
    shop_routes._claim_failures.pop(remote, None)
    try:
        for _ in range(shop_routes._CLAIM_MAX_FAILURES):
            assert shop_routes._reserve_claim_attempt(remote, now) is True
        assert shop_routes._reserve_claim_attempt(remote, now) is False
        # The window fully elapses and the identity recovers.
        assert shop_routes._claim_retry_after(remote, now + window + 1) == window
        assert shop_routes._reserve_claim_attempt(remote, now + window + 1) is True
    finally:
        shop_routes._claim_failures.pop(remote, None)


def test_claim_reservation_sweeps_expired_other_identity_buckets():
    from AssetsManager.lan.routes.shop.delivery import (
        _CLAIM_WINDOW_SECONDS,
        _claim_failures,
        _reserve_claim_attempt,
    )

    now = 1_000_000.0
    stale_ip = "9.9.9.9"
    active_ip = "8.8.8.8"
    _claim_failures[stale_ip] = [now - _CLAIM_WINDOW_SECONDS - 1]
    try:
        assert _reserve_claim_attempt(active_ip, now) is True

        assert stale_ip not in _claim_failures
        assert _claim_failures[active_ip] == [now]
        # The swept identity is immediately allowed again: nothing can
        # accumulate toward a lockout once its window has fully elapsed.
        assert _reserve_claim_attempt(stale_ip, now) is True
    finally:
        _claim_failures.pop(active_ip, None)
        _claim_failures.pop(stale_ip, None)


def test_claim_hard_cap_bounds_active_identities(monkeypatch):
    from AssetsManager.lan.routes.shop import delivery as delivery_mod

    monkeypatch.setattr(delivery_mod, "_CLAIM_MAX_ACTIVE_KEYS", 50)
    now = 2_000_000.0
    recent_identity = f"recent-{'x' * 64}"
    try:
        assert delivery_mod._reserve_claim_attempt(recent_identity, now) is True
        for index in range(120):
            assert (
                delivery_mod._reserve_claim_attempt(f"flood-{index}", now + 1 + index / 1000)
                is True
            )
        assert len(delivery_mod._claim_failures) <= 50
        # Capacity eviction follows insertion order: the earliest identities
        # (including the pre-flood one) are dropped while the most recently
        # reserved identity survives.
        assert recent_identity not in delivery_mod._claim_failures
        assert delivery_mod._claim_failures.get("flood-0") is None
        assert delivery_mod._claim_failures.get("flood-119") == [2000001.119]
    finally:
        delivery_mod._claim_failures.clear()


def test_claim_active_identity_refresh_is_lru_preserved(monkeypatch):
    """A refreshed identity survives capacity eviction over idle ones."""
    from AssetsManager.lan.routes.shop import delivery as delivery_mod

    monkeypatch.setattr(delivery_mod, "_CLAIM_MAX_ACTIVE_KEYS", 3)
    now = 3_000_000.0
    ids = [f"id-{index}" for index in range(4)]
    try:
        for index in range(3):
            assert delivery_mod._reserve_claim_attempt(ids[index], now + index) is True
        # Refresh id-0 so it becomes the most recently active identity.
        assert delivery_mod._reserve_claim_attempt(ids[0], now + 10) is True
        # New identity forces eviction of the longest-idle one (id-1).
        assert delivery_mod._reserve_claim_attempt(ids[3], now + 11) is True

        assert ids[0] in delivery_mod._claim_failures, "refreshed identity kept"
        assert ids[2] in delivery_mod._claim_failures
        assert ids[3] in delivery_mod._claim_failures
        assert ids[1] not in delivery_mod._claim_failures, "idle identity evicted first"
        assert len(delivery_mod._claim_failures) <= 3
    finally:
        delivery_mod._claim_failures.clear()
