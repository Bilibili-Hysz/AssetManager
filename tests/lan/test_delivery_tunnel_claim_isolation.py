import asyncio
import json
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from AssetsManager.lan import tunnel_identity
from AssetsManager.lan.routes.shop import delivery as delivery_routes
from AssetsManager.lan.security import (
    IPBlacklist,
    RateLimiter,
    SECURITY_BUCKET_KEY,
    create_security_middleware,
)


class _Lan:
    local_ui_auth_secret = b"claim-test-secret"
    token_secret = None


_SECRET = _Lan.local_ui_auth_secret


def _cookie(seed: str) -> str:
    import base64
    import hashlib
    import hmac

    payload = f"v1.{seed}"
    signature = hmac.new(_SECRET, payload.encode("ascii"), hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{payload}.{encoded}"


def _request(cookie: str | None = None):
    headers = {}
    if cookie:
        headers["Cookie"] = f"{tunnel_identity.COOKIE_NAME}={cookie}"
    request = make_mocked_request("GET", "/claim", headers=headers)
    request._cache["remote"] = "127.0.0.1"
    return request


def _middleware():
    return create_security_middleware(
        RateLimiter(max_requests=100),
        IPBlacklist(),
        tunnel_active=lambda: True,
        tunnel_identity_resolver=lambda request: (
            tunnel_identity.token_client_id(
                tunnel_identity.valid_token(
                    request.cookies.get(tunnel_identity.COOKIE_NAME), _SECRET
                )
            )
            if tunnel_identity.valid_token(
                request.cookies.get(tunnel_identity.COOKIE_NAME), _SECRET
            )
            else None
        ),
        tunnel_identity_minter=lambda: (
            tunnel_identity.token_client_id(token := tunnel_identity.new_token(_SECRET)),
            token,
        ),
    )


async def _capture(request):
    return web.json_response({"bucket": request.get(SECURITY_BUCKET_KEY)})


def test_security_bucket_context_matches_claim_key_for_tunnel_cookie():
    middleware = _middleware()
    request = _request(_cookie("a" * 32))
    response = asyncio.run(middleware(request, _capture))
    assert response.status == 200
    body = json.loads(response.text)
    assert body["bucket"] == "tunnel:" + "a" * 32
    assert delivery_routes._claim_request_remote(request) == body["bucket"]


def test_cookieless_claim_key_stays_shared_and_direct_mode_ignores_cookie():
    middleware = _middleware()
    first = _request()
    response = asyncio.run(middleware(first, _capture))
    assert json.loads(response.text)["bucket"] == "127.0.0.1"
    assert delivery_routes._claim_request_remote(first) == "127.0.0.1"

    direct = create_security_middleware(
        RateLimiter(max_requests=100),
        IPBlacklist(),
        tunnel_active=None,
        tunnel_identity_resolver=lambda _request: "should-not-be-used",
    )
    direct_request = _request(_cookie("b" * 32))
    direct_response = asyncio.run(direct(direct_request, _capture))
    assert json.loads(direct_response.text)["bucket"] == "127.0.0.1"
    assert delivery_routes._claim_request_remote(direct_request) == "127.0.0.1"


def test_claim_handler_reuses_identity_bucket_from_middleware(monkeypatch):
    import AssetsManager.lan.routes.commerce_policy as commerce_policy

    monkeypatch.setattr(commerce_policy, "commerce_gate", lambda: None)
    monkeypatch.setattr(
        delivery_routes,
        "_package_function",
        lambda name: {
            "_json_body": lambda _request: asyncio.sleep(0, result={"claim": "wrong"}),
            "get_lan": lambda _request: SimpleNamespace(library_root="library"),
            "get_commerce_services": lambda _request: SimpleNamespace(
                orders=SimpleNamespace(claim_share_delivery=lambda *_args: None)
            ),
            "_claim_request_remote": delivery_routes._claim_request_remote,
        }[name],
    )
    delivery_routes._claim_failures.clear()

    async def invoke(cookie):
        request = _request(cookie)
        request._match_info = {"order_id": "1"}
        return await _middleware()(request, delivery_routes.handle_shop_claim_delivery)

    try:
        for _ in range(delivery_routes._CLAIM_MAX_FAILURES):
            assert asyncio.run(invoke(_cookie("a" * 32))).status == 404
        assert asyncio.run(invoke(_cookie("a" * 32))).status == 429
        assert asyncio.run(invoke(_cookie("b" * 32))).status == 404
        assert "tunnel:" + "a" * 32 in delivery_routes._claim_failures
        assert "tunnel:" + "b" * 32 in delivery_routes._claim_failures
    finally:
        delivery_routes._claim_failures.clear()


def test_malformed_claim_body_consumes_a_reservation_slot(monkeypatch):
    import AssetsManager.lan.routes.commerce_policy as commerce_policy

    monkeypatch.setattr(commerce_policy, "commerce_gate", lambda: None)
    monkeypatch.setattr(
        delivery_routes,
        "_package_function",
        lambda name: {
            "_json_body": lambda _request: asyncio.sleep(0, result={}),
            "_claim_request_remote": delivery_routes._claim_request_remote,
        }[name],
    )
    delivery_routes._claim_failures.clear()

    async def invoke():
        request = _request()
        request._match_info = {"order_id": "1"}
        return await delivery_routes.handle_shop_claim_delivery(request)

    try:
        assert asyncio.run(invoke()).status == 400
        # Every admitted POST spends a slot, even one rejected for an empty
        # claim body — the brute-force gate counts attempts, not outcomes.
        bucket = next(iter(delivery_routes._claim_failures.values()), [])
        assert len(bucket) == 1
    finally:
        delivery_routes._claim_failures.clear()


def test_concurrent_claims_cannot_exceed_reservation_window(monkeypatch):
    import threading

    import AssetsManager.lan.routes.commerce_policy as commerce_policy

    monkeypatch.setattr(commerce_policy, "commerce_gate", lambda: None)
    monkeypatch.setattr(
        delivery_routes,
        "_package_function",
        lambda name: {
            "_json_body": lambda _request: asyncio.sleep(0, result={"claim": "wrong"}),
            "get_lan": lambda _request: SimpleNamespace(library_root="library"),
            "get_commerce_services": lambda _request: SimpleNamespace(
                orders=SimpleNamespace(claim_share_delivery=lambda *_args: None)
            ),
            "_claim_request_remote": delivery_routes._claim_request_remote,
        }[name],
    )
    delivery_routes._claim_failures.clear()

    async def invoke():
        request = _request(_cookie("c" * 32))
        request._match_info = {"order_id": "1"}
        return await delivery_routes.handle_shop_claim_delivery(request)

    total = delivery_routes._CLAIM_MAX_FAILURES * 2 + 5
    results: list[int] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(total)
    workers = []

    def worker():
        barrier.wait()
        status = asyncio.run(invoke()).status
        with results_lock:
            results.append(status)

    try:
        workers = [threading.Thread(target=worker) for _ in range(total)]
        for thread in workers:
            thread.start()
        for thread in workers:
            thread.join()

        not_found = results.count(404)
        throttled = results.count(429)
        # Reservation-based accounting: the identity can reach at most
        # MAX_FAILURES service calls no matter how the threads interleave;
        # every other concurrent POST answers 429.
        assert not_found <= delivery_routes._CLAIM_MAX_FAILURES
        assert not_found >= 1
        assert not_found + throttled == total
    finally:
        delivery_routes._claim_failures.clear()
