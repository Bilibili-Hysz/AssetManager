"""L2 tests — browse rate tier, query input budget, PBKDF2 off the loop."""
from __future__ import annotations

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from AssetsManager.lan.api import setup_routes
from AssetsManager.lan.route_policy import RoutePolicy, declare
from AssetsManager.lan.security import (
    IPBlacklist,
    RateLimiter,
    create_security_middleware,
)
from AssetsManager.lan.server import _LanServerImpl

@pytest.fixture
def anyio_backend():
    return "asyncio"


# ── Browse tier declarations ───────────────────────────────────────


def test_route_policy_accepts_browse_rate_class():
    policy = RoutePolicy(rate_limit="browse")
    assert policy.rate_limit == "browse"


def test_route_policy_rejects_unknown_rate_class():
    with pytest.raises(ValueError, match="unknown rate_limit class"):
        RoutePolicy(rate_limit="turbo")  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_browse_tier_uses_its_own_budget_and_does_not_touch_general():
    async def ok_handler(_request):
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_get("/api/gallery/home", ok_handler)
    app.router.add_get("/api/shares", ok_handler)
    declare(app, "/api/gallery/home", RoutePolicy(rate_limit="browse"))
    declare(app, "/api/shares", RoutePolicy())

    general = RateLimiter(max_requests=1, window_seconds=60)
    browse = RateLimiter(max_requests=2, window_seconds=60)
    middleware = create_security_middleware(
        general, IPBlacklist(), browse_rate_limiter=browse,
    )
    app.middlewares.append(middleware)

    from aiohttp.test_utils import TestClient, TestServer

    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        for _ in range(2):
            response = await client.get("/api/gallery/home")
            assert response.status == 200
        limited = await client.get("/api/gallery/home")
        assert limited.status == 429
        limited_body = await limited.json()
        assert limited_body["code"] == "browse_rate_limited"
        assert limited_body["details"]["retry_after"] == limited_body["retry_after"]
        assert limited.headers["Retry-After"] == str(limited_body["retry_after"])
        assert "Browse rate limit exceeded" in limited_body["error"]

        # The general budget is untouched by browse traffic.
        response = await client.get("/api/shares")
        assert response.status == 200
        limited_general = await client.get("/api/shares")
        assert limited_general.status == 429
        general_body = await limited_general.json()
        assert general_body["code"] == "rate_limited"
        assert general_body["details"]["retry_after"] == general_body["retry_after"]
    finally:
        await client.close()


# ── Query input budget ─────────────────────────────────────────────


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/api/search", "/api/quicksearch"])
async def test_search_query_over_256_characters_is_rejected(path, tmp_path):
    from tests.lan.support.api_helpers import _make_client, _make_lan_app

    app, _library, _conn = _make_lan_app(tmp_path)
    client = await _make_client(app)
    try:
        response = await client.get(path, params={"q": "x" * 257})
        assert response.status == 400
        body = await response.json()
        assert body["code"] == "bad_request"
        assert "at most 256" in body["error"]
    finally:
        await client.close()


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/api/search", "/api/quicksearch"])
async def test_search_query_at_budget_is_not_rejected_by_input_gate(path, tmp_path):
    from tests.lan.support.api_helpers import _make_client, _make_lan_app

    app, _library, _conn = _make_lan_app(tmp_path)
    client = await _make_client(app)
    try:
        response = await client.get(path, params={"q": "x" * 256})
        assert response.status == 200
    finally:
        await client.close()


# ── PBKDF2 off the event loop ──────────────────────────────────────


@pytest.mark.anyio
async def test_legacy_in_memory_revocation_is_checked_by_middleware():
    import hashlib
    import threading

    from AssetsManager.lan.routes._helpers import get_request_principal

    class LegacyAuthService:
        def has_active_users(self):
            return False

    server = object.__new__(_LanServerImpl)
    server._auth_mode = "key"
    server._access_key_hash = "salt:hash"
    server._password_hash = None
    server._auth_service = LegacyAuthService()
    server._token_secret = "runtime-secret"
    server._password_value = None
    server._access_key_value = "key"
    server._revoked_tokens = {
        hashlib.sha256(b"revoked").hexdigest(): 9999999999.0,
    }
    server._revoked_loaded = True
    server._has_users_cache = False
    server._has_users_cache_time = 0.0
    server._has_users_cache_ttl = 30.0
    server._has_users_cache_lock = threading.Lock()

    app = web.Application()
    setup_routes(app)
    request = make_mocked_request(
        "GET", "/api/projects",
        headers={"Authorization": "Bearer revoked"}, app=app,
    )
    match_info = await app.router.resolve(request)
    assert match_info is not None
    match_info.add_app(app)
    request._match_info = match_info

    async def handler(_request):
        raise AssertionError("revoked token reached handler")

    response = await server._auth_middleware(request, handler)
    assert response.status == 401
    assert get_request_principal(request) is None


@pytest.mark.anyio
async def test_access_key_verification_runs_through_to_thread(monkeypatch):
    import threading

    from AssetsManager.lan import server as server_module
    from AssetsManager.lan.routes._helpers import get_request_principal

    calls: list[tuple] = []

    async def fake_to_thread(function, *args):
        calls.append((function, args))
        return function(*args)

    monkeypatch.setattr(server_module.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(server_module, "verify_key", lambda key, stored: key == "k")

    class FakeAuthService:
        def has_active_users(self):
            return False

    server = object.__new__(_LanServerImpl)
    server._auth_mode = "key"
    server._access_key_hash = "salt:hash"
    server._password_hash = None
    server._auth_service = FakeAuthService()
    server._revoked_tokens = {}
    server._has_users_cache = None
    server._has_users_cache_time = 0.0
    server._has_users_cache_ttl = 30.0
    server._has_users_cache_lock = threading.Lock()

    app = web.Application()
    setup_routes(app)
    request = make_mocked_request(
        "GET", "/api/projects",
        headers={"Authorization": "Bearer k"}, app=app,
    )
    match_info = await app.router.resolve(request)
    assert match_info is not None
    match_info.add_app(app)
    request._match_info = match_info
    marker = object()

    async def handler(_request):
        return marker

    response = await server._auth_middleware(request, handler)

    assert response is marker
    assert len(calls) == 1
    function, args = calls[0]
    assert function is server_module.verify_key
    assert args == ("k", "salt:hash")
    principal = get_request_principal(request)
    assert principal is not None and principal.kind == "access_key"


@pytest.mark.anyio
async def test_password_token_verification_runs_through_to_thread(monkeypatch):
    import threading

    from AssetsManager.lan import auth as auth_module
    from AssetsManager.lan import server as server_module
    from AssetsManager.lan.routes._helpers import get_request_principal

    calls: list[tuple] = []

    async def fake_to_thread(function, *args):
        calls.append((function, args))
        return function(*args)

    monkeypatch.setattr(server_module.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(auth_module, "verify_token", lambda token, stored: token == "p" and stored == "hash")

    class FakeAuthService:
        def has_active_users(self):
            return False

        def verify_user_token(self, _token):
            return None

    server = object.__new__(_LanServerImpl)
    server._auth_mode = "password"
    server._access_key_hash = None
    server._password_hash = "hash"
    server._password_value = "password"
    server._access_key_value = None
    server._token_secret = "runtime-secret"
    server._auth_service = FakeAuthService()
    server._revoked_tokens = {}
    server._has_users_cache = False
    server._has_users_cache_time = 0.0
    server._has_users_cache_ttl = 30.0
    server._has_users_cache_lock = threading.Lock()
    server.is_auth_token_revoked = lambda _token: False

    app = web.Application()
    setup_routes(app)
    request = make_mocked_request(
        "GET", "/api/projects",
        headers={"Authorization": "Bearer p"}, app=app,
    )
    match_info = await app.router.resolve(request)
    assert match_info is not None
    match_info.add_app(app)
    request._match_info = match_info
    marker = object()

    async def handler(_request):
        return marker

    response = await server._auth_middleware(request, handler)

    assert response is marker
    # The unified credential chain offloads the user-token DB lookup as well
    # as the CPU-heavy PBKDF2 password verification (both async on workers).
    assert len(calls) == 2
    assert calls[0][0].__func__ is FakeAuthService.verify_user_token
    assert calls[0][1] == ("p",)
    function, args = calls[1]
    assert function is auth_module.verify_token
    assert args == ("p", "hash")
    principal = get_request_principal(request)
    assert principal is not None and principal.kind == "password"
