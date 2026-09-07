"""Regression coverage for the production credential-probe middleware chain."""
from __future__ import annotations

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from AssetsManager.lan import server as server_module
from AssetsManager.lan.route_policy import RoutePolicy, declare
from AssetsManager.lan.security import IPBlacklist, RateLimiter
from AssetsManager.lan.server import _LanServerImpl


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def auth_server(monkeypatch):
    """Keep production assembly/auth, replacing only expensive I/O and routes."""
    server = object.__new__(_LanServerImpl)
    server._rate_limiter = RateLimiter()
    server._browse_rate_limiter = RateLimiter()
    server._auth_rate_limiter = None
    server._skip_auth_rate_limiter = RateLimiter(max_requests=120)
    server._ip_blacklist = IPBlacklist()
    server._ip_whitelist = []
    server._auth_mode = "key"
    server._access_key_hash = "stored-key-hash"
    server._password_hash = None
    server._auth_service = None
    server._revoked_loaded = True
    server._has_active_users = lambda: False
    server._current_local_ui_auth_secret = lambda: None
    server._ensure_zip_executor = lambda: None
    calls = []
    revoked = set()

    async def check_revoked(token):
        calls.append(token)
        return token in revoked

    server.is_auth_token_revoked_async = check_revoked
    monkeypatch.setattr(server_module, "verify_key", lambda token, _: token == "valid")

    @web.middleware
    async def metrics(request, handler):
        return await handler(request)

    server._metrics_middleware = metrics

    def routes(app):
        async def ok(_request):
            return web.json_response({"ok": True})

        for path, policy in [
            ("/api/image", RoutePolicy(rate_limit="skip")),
            ("/api/info", RoutePolicy(auth="public_optional", rate_limit="browse")),
            ("/public", RoutePolicy(auth="public", rate_limit="skip")),
        ]:
            app.router.add_get(path, ok)
            declare(app, path, policy)

        async def stream(_request):
            return web.StreamResponse()

        app.router.add_get("/stream", stream)
        declare(app, "/stream", RoutePolicy(auth="public"))

    monkeypatch.setattr(server_module, "setup_routes", routes)
    server._build_app()
    return server, calls, revoked


def test_app_rebuild_initializes_missing_probe_limiter(auth_server):
    server, _, _ = auth_server
    del server._skip_auth_rate_limiter
    server._build_app()
    assert isinstance(server._skip_auth_rate_limiter, RateLimiter)
    assert server._skip_auth_rate_limiter.get_remaining("127.0.0.1") == 120


@pytest.mark.anyio
async def test_unprepared_stream_response_carries_rate_metadata(auth_server):
    server, _, _ = auth_server
    async with TestClient(TestServer(server._app)) as client:
        response = await client.get("/stream")
        assert response.status == 200
        assert response.headers["X-RateLimit-Remaining"] == "999"


@pytest.mark.anyio
@pytest.mark.parametrize("source", ["bearer", "cookie"])
async def test_authenticated_grid_exceeds_probe_budget_without_skipping_auth(auth_server, source):
    server, calls, _ = auth_server
    headers = {"Authorization": "Bearer valid"} if source == "bearer" else {"Cookie": "lan_token=valid"}
    async with TestClient(TestServer(server._app)) as client:
        # Normal metadata bootstrap authenticates before the thumbnail burst.
        assert (await client.get("/api/info", headers=headers)).status == 200
        responses = await asyncio.gather(*[
            client.get("/api/image", headers=headers) for _ in range(150)
        ])
        assert {response.status for response in responses} == {200}
        assert calls == ["valid"] * 151
        assert server._skip_auth_rate_limiter.get_remaining("127.0.0.1") == 120


@pytest.mark.anyio
@pytest.mark.parametrize("source", ["bearer", "cookie"])
async def test_random_credentials_are_bounded_before_revocation_or_crypto(auth_server, source):
    server, calls, _ = auth_server
    async with TestClient(TestServer(server._app)) as client:
        for i in range(121):
            headers = (
                {"Authorization": f"Bearer bad-{i}"} if source == "bearer"
                else {"Cookie": f"lan_token=bad-{i}"}
            )
            response = await client.get("/api/image", headers=headers)
            assert response.status == (401 if i < 120 else 429)
        assert len(calls) == 120
        body = await response.json()
        assert body["code"] == "auth_rate_limited"
        assert int(response.headers["Retry-After"]) >= 1


@pytest.mark.anyio
async def test_known_token_is_rechecked_and_revocation_removes_exemption(auth_server):
    server, calls, revoked = auth_server
    server._skip_auth_rate_limiter._max = 1
    async with TestClient(TestServer(server._app)) as client:
        headers = {"Authorization": "Bearer valid"}
        assert (await client.get("/api/image", headers=headers)).status == 200
        assert (await client.get("/api/image", headers=headers)).status == 200
        revoked.add("valid")
        assert (await client.get("/api/image", headers=headers)).status == 401
        assert (await client.get("/api/image", headers=headers)).status == 429
        assert calls == ["valid"] * 3


@pytest.mark.anyio
async def test_bad_bearer_cannot_borrow_a_known_cookie_exemption(auth_server):
    server, calls, _ = auth_server
    server._skip_auth_rate_limiter._max = 1
    async with TestClient(TestServer(server._app)) as client:
        assert (await client.get("/api/image", headers={"Cookie": "lan_token=valid"})).status == 200
        response = await client.get("/api/image", headers={
            "Cookie": "lan_token=valid", "Authorization": "Bearer bad",
        })
        assert response.status == 429
        assert calls == ["valid"]


@pytest.mark.anyio
@pytest.mark.parametrize("mode,path", [("key", "/public"), ("none", "/api/image"), ("none", "/api/info")])
async def test_routes_without_credential_resolution_do_not_consume_probe_budget(auth_server, mode, path):
    server, calls, _ = auth_server
    server._auth_mode = mode
    if mode == "none":
        server._access_key_hash = None
    async with TestClient(TestServer(server._app)) as client:
        for _ in range(125):
            assert (await client.get(path, headers={"Cookie": "lan_token=stale"})).status == 200
        assert calls == []
        assert server._skip_auth_rate_limiter.get_remaining("127.0.0.1") == 120


@pytest.mark.anyio
async def test_exemption_expires_and_cannot_override_exhausted_probe_budget(auth_server, monkeypatch):
    from AssetsManager.lan import security

    server, calls, _ = auth_server
    server._skip_auth_rate_limiter._max = 1
    now = [1000.0]
    # Replace the module's time binding, leaving asyncio's monotonic clock intact.
    from types import SimpleNamespace
    import time

    monkeypatch.setattr(security, "time", SimpleNamespace(time=time.time, monotonic=lambda: now[0]))
    async with TestClient(TestServer(server._app)) as client:
        headers = {"Authorization": "Bearer valid"}
        assert (await client.get("/api/image", headers=headers)).status == 200
        now[0] += 61.0
        assert (await client.get("/api/image", headers=headers)).status == 429
        assert calls == ["valid"]
