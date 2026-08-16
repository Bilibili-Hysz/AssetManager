"""L1 tests — declarative route capabilities and middleware enforcement."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from AssetsManager.lan.principal import principal_for_request
from AssetsManager.lan.route_policy import (
    GUEST_ALLOWED_CAPABILITIES,
    KNOWN_CAPABILITIES,
    RoutePolicy,
)
from AssetsManager.lan.routes._helpers import PRINCIPAL_REQUEST_KEY
from AssetsManager.lan.authorization import enforce_capabilities

ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = ROOT / "scripts" / "check_route_capabilities.py"
_spec = importlib.util.spec_from_file_location("check_route_capabilities", _SCRIPT)
assert _spec is not None and _spec.loader is not None
check_route_capabilities = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = check_route_capabilities
_spec.loader.exec_module(check_route_capabilities)


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ── Declaration vocabulary ─────────────────────────────────────────


def test_route_capability_gate_passes_on_current_tree():
    violations = check_route_capabilities.collect_violations(ROOT)
    assert violations == [], "\n".join(v.format() for v in violations)


def test_unknown_route_capability_fails_closed_at_declaration():
    with pytest.raises(ValueError, match="unknown route capabilities"):
        RoutePolicy(auth="public_optional", capabilities=("superpower",))


def test_guest_allowed_capabilities_are_a_subset_of_known_capabilities():
    assert GUEST_ALLOWED_CAPABILITIES <= KNOWN_CAPABILITIES


def test_capability_vocabulary_covers_principal_fields():
    principal_fields = {
        "browse", "preview", "download", "manage_links", "manage_users",
        "settings", "realtime",
    }
    assert principal_fields <= KNOWN_CAPABILITIES


# ── Enforcement unit tests ─────────────────────────────────────────


def _request_with_principal(kind="guest", **user):
    request = make_mocked_request("POST", "/", app=web.Application())
    request[PRINCIPAL_REQUEST_KEY] = principal_for_request(kind, user=user or None)
    return request


@pytest.mark.anyio
async def test_enforce_allows_when_principal_has_capability():
    request = _request_with_principal("access_key")
    policy = RoutePolicy(capabilities=("manage_links",))
    assert await enforce_capabilities(request, policy) is None


@pytest.mark.anyio
async def test_enforce_denies_guest_for_principal_backed_write():
    request = _request_with_principal("guest")
    policy = RoutePolicy(capabilities=("manage_links",))
    response = await enforce_capabilities(request, policy)
    assert response is not None
    assert response.status == 403
    assert b'"code": "forbidden"' in response.body


@pytest.mark.anyio
async def test_enforce_write_notes_uses_require_user_write():
    request = _request_with_principal(
        "user", user={"id": 1, "username": "alice", "role": "user", "can_write": 0},
    )
    response = await enforce_capabilities(
        request, RoutePolicy(capabilities=("write_notes",)))
    assert response is not None and response.status == 403

    request[PRINCIPAL_REQUEST_KEY] = principal_for_request(
        "user", user={"id": 1, "username": "alice", "role": "user", "can_write": 1})
    assert await enforce_capabilities(
        request, RoutePolicy(capabilities=("write_notes",))) is None


@pytest.mark.anyio
async def test_enforce_admin_tags_denies_can_write_user():
    request = _request_with_principal(
        "user", user={"id": 1, "username": "alice", "role": "user", "can_write": 1},
    )
    response = await enforce_capabilities(
        request, RoutePolicy(capabilities=("admin_tags",)))
    assert response is not None and response.status == 403


@pytest.mark.anyio
async def test_guest_allowed_commerce_capabilities_pass():
    request = _request_with_principal("guest")
    for capability in ("buyer_cart", "buyer_wishlist", "buyer_orders",
                       "buyer_claim", "public_auth", "public_signal",
                       "share_verify"):
        assert await enforce_capabilities(
            request, RoutePolicy(capabilities=(capability,))) is None


@pytest.mark.anyio
async def test_seller_capability_requires_seller_session(monkeypatch):
    from AssetsManager.lan.routes import shop as shop_package
    from AssetsManager.lan.routes import commerce_policy

    monkeypatch.setattr(commerce_policy, "seller_gate", lambda: None)
    calls: list[int] = []

    async def fake_require_seller(_request):
        calls.append(1)
        return None

    monkeypatch.setattr(shop_package, "require_seller", fake_require_seller)
    response = await enforce_capabilities(
        _request_with_principal("guest"), RoutePolicy(capabilities=("seller",)))
    assert response is not None and response.status == 403
    assert calls == [1]


@pytest.mark.anyio
async def test_seller_capability_preserves_feature_disabled_response(monkeypatch):
    from AssetsManager.lan.routes import shop as shop_package
    from AssetsManager.lan.routes import commerce_policy

    disabled = web.json_response(
        {"error": "Seller is disabled", "code": "feature_disabled"}, status=404)
    monkeypatch.setattr(commerce_policy, "seller_gate", lambda: disabled)
    calls: list[int] = []

    async def fake_require_seller(_request):
        calls.append(1)
        return {"kind": "seller"}

    monkeypatch.setattr(shop_package, "require_seller", fake_require_seller)
    response = await enforce_capabilities(
        _request_with_principal("guest"), RoutePolicy(capabilities=("seller",)))
    assert response is disabled
    assert calls == []


# ── Middleware-before-handler integration ──────────────────────────


@pytest.mark.anyio
async def test_guest_seller_write_is_blocked_by_middleware_before_handler(
    tmp_path, monkeypatch,
):
    from aiohttp.test_utils import TestClient, TestServer

    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.core.settings import AppSettings
    from AssetsManager.lan.routes import shop as shop_package
    from AssetsManager.lan.server import _LanServerImpl

    class Settings:
        def get(self, key, default=None):
            return {
                "lan_commerce_enabled": True,
                "lan_seller_enabled": True,
                "lan_quota_enabled": False,
                "lan_guest_list": True,
                "lan_guest_download": False,
            }.get(key, default)

    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda _cls: Settings()))

    calls: list[int] = []

    async def fake_require_seller(_request):
        calls.append(1)
        return None

    monkeypatch.setattr(shop_package, "require_seller", fake_require_seller)

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    server = _LanServerImpl(runtime=bootstrap.runtime_for(session),
                            password="real-test-password")
    client = TestClient(TestServer(server._app))
    await client.start_server()
    try:
        response = await client.put(
            "/api/shop/items",
            json={"title": "unauthorized", "path": "missing.file",
                  "price_cents": 100},
        )
        assert response.status == 403
        # Exactly one resolution: the middleware rejected the request before
        # handle_shop_items could run its own seller guard.
        assert calls == [1]
    finally:
        await client.close()
        session.close()
