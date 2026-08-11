from __future__ import annotations

import pytest
from aiohttp.test_utils import make_mocked_request

from AssetsManager.lan.routes._helpers import get_request_principal
from AssetsManager.lan.server import _LanServerImpl


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path",
    [
        "/storefront",
        "/storefront/product/7",
        "/store",
        "/seller",
        "/app",
        "/api/shop/items",
        "/api/shop/catalog",
        "/api/shop/items/7",
        "/api/shop/items/7/media/cover",
        "/api/shop/cart",
        "/api/shop/wishlist",
        "/api/shop/auth/seller-status",
        "/api/shop/order/7/delivery",
        "/api/shop/delivery/token",
        "/api/quota",
    ],
)
async def test_password_protected_lan_does_not_block_migrated_webui_surfaces(path):
    """Global LAN auth must defer to storefront/seller/receipt route guards."""
    server = object.__new__(_LanServerImpl)
    request = make_mocked_request("GET", path)
    marker = object()

    async def handler(_request):
        return marker

    response = await server._auth_middleware(request, handler)

    assert response is marker
    principal = get_request_principal(request)
    assert principal is not None
    assert principal.kind == "guest"

@pytest.mark.anyio
async def test_password_protected_canonical_server_exposes_buyer_surface_but_keeps_seller_mutations_guarded(
    tmp_path, monkeypatch
):
    """Exercise the real LAN middleware + route stack, not only the helper method."""
    from aiohttp.test_utils import TestClient, TestServer

    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.core.settings import AppSettings
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

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    server = _LanServerImpl(runtime=runtime, password="real-test-password")
    client = TestClient(TestServer(server._app))
    await client.start_server()
    try:
        storefront = await client.get("/storefront")
        assert storefront.status == 200

        items = await client.get("/api/shop/items")
        assert items.status == 200
        assert (await items.json())["items"] == []

        catalog = await client.get("/api/shop/catalog")
        assert catalog.status == 200
        catalog_body = await catalog.json()
        assert set(catalog_body) == {"items", "page", "page_size", "total"}
        assert catalog_body["items"] == []

        item_detail = await client.get("/api/shop/items/7")
        assert item_detail.status == 404

        cart = await client.get("/api/shop/cart")
        assert cart.status == 200
        assert (await cart.json())["cart"]["owner_type"] == "anonymous"

        seller_orders = await client.get("/api/shop/orders")
        assert seller_orders.status == 403

        seller_create = await client.post(
            "/api/shop/items",
            json={"title": "unauthorized", "path": "missing.file", "price_cents": 100},
        )
        assert seller_create.status == 403
    finally:
        await client.close()
        session.close()


@pytest.mark.anyio
async def test_public_commerce_attempts_optional_user_authentication():
    """Public Commerce must preserve guest access while exposing a valid LAN user."""
    class AuthService:
        def verify_user_token(self, token):
            assert token == "user-token"
            return {
                "id": 7,
                "username": "buyer",
                "role": "user",
                "is_active": True,
                "created_at": 0,
            }

    server = object.__new__(_LanServerImpl)
    server._auth_mode = "user"
    server._access_key_hash = None
    server._password_hash = None
    server._auth_service = AuthService()
    server._revoked_tokens = {}
    request = make_mocked_request(
        "POST",
        "/api/shop/buyer/merge",
        headers={"Authorization": "Bearer user-token"},
    )
    marker = object()

    async def handler(_request):
        return marker

    response = await server._auth_middleware(request, handler)

    assert response is marker
    principal = get_request_principal(request)
    assert principal is not None
    assert principal.kind == "user"
    assert principal.user_profile is not None
    assert principal.user_profile["id"] == 7
