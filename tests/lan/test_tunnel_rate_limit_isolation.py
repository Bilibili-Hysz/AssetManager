"""Tunnel-mode rate-limit identity isolation regressions.

Under the cloudflared tunnel every visitor arrives from 127.0.0.1, so IP-keyed
limiter buckets collapse all tunneled users into one shared budget (a burst of
failed logins locks out everyone).  These tests pin the cookie-based isolation:

* a valid signed visitor cookie keys buckets as ``tunnel:<id>`` so clients are
  isolated despite the identical peer address;
* a request with no valid cookie stays in the shared loopback bucket (freshly
  minted identities must never buy immediate isolation — that would let an
  attacker rotate buckets per request) and receives a minted cookie so the
  *next* request isolates;
* tampered cookies fall back to the shared bucket;
* direct (non-tunnel) traffic keeps pure IP keying, cookies ignored.
"""
import pytest

from AssetsManager.lan import tunnel_identity
from AssetsManager.lan.route_policy import RoutePolicy, declare
from AssetsManager.lan.security import (
    AuthRateLimiter,
    IPBlacklist,
    RateLimiter,
    create_security_middleware,
)


def pytest_configure(config):
    config.addinivalue_line("markers", "anyio: run test using anyio")


def pytest_generate_tests(metafunc):
    if "anyio_backend" in metafunc.fixturenames:
        metafunc.parametrize("anyio_backend", ["asyncio"])


class _FakeLan:
    """Secret holder mirroring the lan object's attribute surface."""


_SECRET = tunnel_identity.signing_secret(_FakeLan())


def _resolver(request):
    token = tunnel_identity.valid_token(
        request.cookies.get(tunnel_identity.COOKIE_NAME), _SECRET
    )
    return tunnel_identity.token_client_id(token) if token else None


def _minter():
    token = tunnel_identity.new_token(_SECRET)
    return tunnel_identity.token_client_id(token), token


def _cookie_for(client_seed: str) -> str:
    # Deterministic per-test client identities: sign a fixed 32-hex id with
    # the test secret (same format tunnel_identity mints).
    import base64
    import hashlib
    import hmac as hmac_mod

    payload = f"v1.{client_seed}"
    signature = hmac_mod.new(_SECRET, payload.encode("ascii"), hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{payload}.{encoded}"


def _middleware(max_requests=2, *, tunnel_active=True):
    return create_security_middleware(
        RateLimiter(max_requests=max_requests),
        IPBlacklist(),
        tunnel_active=(lambda: True) if tunnel_active else None,
        tunnel_identity_resolver=_resolver,
        tunnel_identity_minter=_minter,
    )


def _request(cookie_token=None):
    from aiohttp.test_utils import make_mocked_request

    headers = {}
    if cookie_token:
        headers["Cookie"] = f"{tunnel_identity.COOKIE_NAME}={cookie_token}"
    request = make_mocked_request("GET", "/", headers=headers)
    request._cache["remote"] = "127.0.0.1"
    return request


async def _call(middleware, handler, request):
    return await middleware(request, handler)


def _ok_handler():
    from aiohttp import web

    async def handler(_request):
        return web.json_response({"ok": True})

    return handler


@pytest.mark.anyio
async def test_valid_cookies_isolate_buckets_despite_shared_loopback_peer():
    middleware = _middleware(max_requests=2)
    handler = _ok_handler()
    cookie_a = _cookie_for("a" * 32)
    cookie_b = _cookie_for("b" * 32)

    first = await _call(middleware, handler, _request(cookie_a))
    second = await _call(middleware, handler, _request(cookie_a))
    assert first.status == 200 and second.status == 200
    assert first.headers["X-RateLimit-Remaining"] == "1"
    assert second.headers["X-RateLimit-Remaining"] == "0"

    third = await _call(middleware, handler, _request(cookie_a))
    assert third.status == 429
    assert third.code if hasattr(third, "code") else True

    # Client B keeps a full isolated budget while A is locked out.
    fresh = await _call(middleware, handler, _request(cookie_b))
    assert fresh.status == 200
    assert fresh.headers["X-RateLimit-Remaining"] == "1"


@pytest.mark.anyio
async def test_cookieless_requests_share_bucket_and_receive_minted_cookie():
    middleware = _middleware(max_requests=1)
    handler = _ok_handler()

    first = await _call(middleware, handler, _request())
    second = await _call(middleware, handler, _request())
    assert first.status == 200
    assert second.status == 429  # both consumed the one shared loopback slot
    # Rejected requests must not farm a fresh identity out of their 429.
    assert tunnel_identity.COOKIE_NAME not in second.cookies

    # The first response minted a visitor cookie; presenting it isolates the
    # next request even though the shared loopback bucket is exhausted.
    # (Unprepared responses expose cookies via .cookies, not raw headers.)
    assert tunnel_identity.COOKIE_NAME in first.cookies
    token = first.cookies[tunnel_identity.COOKIE_NAME].value
    assert tunnel_identity.valid_token(token, _SECRET)

    isolated = await _call(middleware, handler, _request(token))
    assert isolated.status == 200
    assert isolated.headers["X-RateLimit-Remaining"] == "0"


@pytest.mark.anyio
async def test_tampered_cookie_falls_back_to_shared_bucket():
    middleware = _middleware(max_requests=1)
    handler = _ok_handler()
    valid_cookie = _cookie_for("c" * 32)
    tampered = valid_cookie[:-6] + ("AAAAAA" if not valid_cookie.endswith("AAAAAA") else "BBBBBB")

    spent = await _call(middleware, handler, _request())  # burn shared slot
    assert spent.status == 200

    rejected = await _call(middleware, handler, _request(tampered))
    assert rejected.status == 429  # treated as cookieless: shared bucket full
    # The rejection answer carries no minted identity either.
    assert tunnel_identity.COOKIE_NAME not in rejected.cookies


@pytest.mark.anyio
async def test_blacklist_rejection_issues_no_minted_cookie():
    from AssetsManager.lan.security import IPBlacklist as _Blacklist

    blacklist = _Blacklist()
    blacklist.load_from_settings(["127.0.0.1"])
    middleware = create_security_middleware(
        RateLimiter(max_requests=100),
        blacklist,
        tunnel_active=lambda: True,
        tunnel_identity_resolver=_resolver,
        tunnel_identity_minter=_minter,
    )

    response = await _call(middleware, _ok_handler(), _request())
    assert response.status == 403
    assert tunnel_identity.COOKIE_NAME not in getattr(response, "cookies", {})


@pytest.mark.anyio
async def test_route_issued_am_quota_id_cookie_is_not_overwritten():
    from aiohttp import web as _web

    middleware = _middleware(max_requests=5)
    preset_token = "v1." + "9" * 32 + ".preset"

    async def handler(_request):
        response = _web.json_response({"ok": True})
        tunnel_identity.apply_visitor_cookie(response, preset_token)
        return response

    response = await _call(middleware, handler, _request())
    # Exactly one identity cookie survives, and it is the route's own.
    assert tunnel_identity.COOKIE_NAME in response.cookies
    assert response.cookies[tunnel_identity.COOKIE_NAME].value == preset_token


def test_apply_visitor_cookie_honors_secure_flag():
    from aiohttp import web as _web

    token = "t"
    plain = _web.Response()
    secure = _web.Response()
    tunnel_identity.apply_visitor_cookie(plain, token)
    tunnel_identity.apply_visitor_cookie(secure, token, secure=True)

    assert not plain.cookies[tunnel_identity.COOKIE_NAME]["secure"]
    assert bool(secure.cookies[tunnel_identity.COOKIE_NAME]["secure"])


@pytest.mark.anyio
async def test_direct_mode_ignores_visitor_cookie_and_keys_on_ip():
    middleware = _middleware(max_requests=1, tunnel_active=False)
    handler = _ok_handler()
    cookie = _cookie_for("d" * 32)

    first = await _call(middleware, handler, _request(cookie))
    second = await _call(middleware, handler, _request(cookie))
    assert first.status == 200
    assert second.status == 429  # same remote, cookie ignored: one IP bucket
    assert tunnel_identity.COOKIE_NAME not in first.cookies


@pytest.mark.anyio
async def test_auth_strict_lockout_is_per_tunnel_identity():
    from aiohttp import web
    from aiohttp.test_utils import make_mocked_request

    app = web.Application()

    async def login(_request):
        return web.json_response({"ok": True})

    app.router.add_post("/api/auth/login", login)
    declare(app, "/api/auth/login", RoutePolicy(rate_limit="auth_strict"))
    middleware = create_security_middleware(
        RateLimiter(),
        IPBlacklist(),
        AuthRateLimiter(max_attempts=2, window_seconds=300),
        tunnel_active=lambda: True,
        tunnel_identity_resolver=_resolver,
        tunnel_identity_minter=_minter,
    )

    async def handler(_request):
        return web.json_response({"ok": True})

    async def authed_call(cookie_token):
        request = make_mocked_request(
            "POST",
            "/api/auth/login",
            headers={"Cookie": f"{tunnel_identity.COOKIE_NAME}={cookie_token}"},
            app=app,
        )
        request._cache["remote"] = "127.0.0.1"
        match_info = await app.router.resolve(request)
        match_info.add_app(app)
        request._match_info = match_info
        return await middleware(request, handler)

    cookie_a = _cookie_for("e" * 32)
    cookie_b = _cookie_for("f" * 32)

    assert (await authed_call(cookie_a)).status == 200
    assert (await authed_call(cookie_a)).status == 200
    locked = await authed_call(cookie_a)
    assert locked.status == 429
    # An auth_strict lockout answer also carries no freshly minted identity.
    assert tunnel_identity.COOKIE_NAME not in getattr(locked, "cookies", {})

    # Identity B is unaffected by A's lockout.
    assert (await authed_call(cookie_b)).status == 200
