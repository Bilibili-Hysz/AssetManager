"""WebSocket access-key authorization offloads PBKDF2 to a worker thread."""
from __future__ import annotations

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from AssetsManager.lan.principal import principal_for_request
from AssetsManager.lan.routes import websocket as websocket_module
from AssetsManager.lan.routes.websocket import _authorization_validator


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_access_key_validator_runs_verify_key_through_to_thread(monkeypatch):
    calls: list[tuple] = []

    async def fake_to_thread(function, *args):
        calls.append((function, args))
        return function(*args)

    monkeypatch.setattr(websocket_module.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(
        websocket_module,
        "verify_key",
        lambda key, stored: key == "k" and stored == "salt:hash",
    )

    class FakeLan:
        access_key_hash = "salt:hash"

    request = make_mocked_request(
        "GET", "/ws",
        headers={"Authorization": "Bearer k"}, app=web.Application(),
    )
    principal = principal_for_request("access_key")

    validator = _authorization_validator(request, FakeLan(), principal)

    assert await validator() is True
    assert len(calls) == 1
    function, args = calls[0]
    assert function is websocket_module.verify_key
    assert args == ("k", "salt:hash")
