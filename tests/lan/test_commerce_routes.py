import asyncio
import json
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

import AssetsManager.lan.api as lan_api
from AssetsManager.application.shop_service import ShopService
from AssetsManager.domain.errors import ValidationError
from AssetsManager.repositories.shop_repository import ShopRepository
from AssetsManager.lan.api import setup_routes
from AssetsManager.lan.routes import shop as shop_routes


def test_commerce_contract_routes_are_registered():
    app = web.Application()
    setup_routes(app)
    registered = {(route.method, route.resource.canonical) for route in app.router.routes()}
    expected = {
        ("GET", "/api/shop/items"),
        ("GET", "/api/shop/catalog"),
        ("GET", "/api/shop/items/by-path"),
        ("GET", "/api/shop/items/{item_id}"),
        ("POST", "/api/shop/items"),
        ("PUT", "/api/shop/items"),
        ("DELETE", "/api/shop/items"),
        ("GET", "/api/shop/orders/order"),
        ("POST", "/api/shop/orders/order"),
        ("GET", "/api/shop/orders/stats"),
        ("GET", "/api/shop/orders/export"),
        ("GET", "/api/shop/buyer/orders"),
        ("POST", "/api/shop/buyer/merge"),
        ("GET", "/api/shop/delivery/{token}"),
        ("GET", "/api/shop/delivery/{token}/download"),
        ("GET", "/api/shop/auth/seller-status"),
        ("POST", "/api/shop/auth/login"),
        ("POST", "/api/shop/auth/logout"),
        ("GET", "/api/shop/quota"),
        ("GET", "/api/shop/cart/checkout/{checkout_group_id}"),
        ("POST", "/api/shop/order/{order_id}/delivery/rotate"),
        ("POST", "/api/shop/order/{order_id}/delivery/revoke"),
        ("POST", "/api/shop/orders/order/{order_id}/delivery/revoke"),
    }
    assert expected <= registered
    catalog_routes = [
        route
        for route in app.router.routes()
        if route.method == "GET" and route.resource.canonical == "/api/shop/catalog"
    ]
    assert len(catalog_routes) == 1
    assert catalog_routes[0].handler is lan_api.handle_public_shop_catalog


def test_reference_webui_page_aliases_are_registered():
    app = web.Application()
    setup_routes(app)
    registered = {(route.method, route.resource.canonical) for route in app.router.routes()}
    expected = {
        ("GET", "/storefront/cart"),
        ("GET", "/storefront/orders"),
        ("GET", "/storefront/wishlist"),
        ("GET", "/storefront/checkout/group"),
        ("GET", "/storefront/product/{id}"),
        ("GET", "/storefront/product/path/{item_path}"),
        ("GET", "/store"),
        ("GET", "/store/gallery/{tag}"),
        ("GET", "/store/checkout"),
        ("GET", "/store/delivery/{token}"),
        ("GET", "/store/{item_path}"),
        ("GET", "/app"),
        ("GET", "/app/items"),
        ("GET", "/app/orders"),
    }
    assert expected <= registered


def test_storefront_product_deep_links_serve_spa_on_direct_get(monkeypatch):
    async def storefront_page(_request):
        return web.Response(text="storefront spa")

    monkeypatch.setattr(lan_api, "handle_storefront_page", storefront_page)

    async def exercise_direct_gets():
        app = web.Application()
        setup_routes(app)
        for path in (
            "/storefront/product/path/folder/item.asset",
            "/storefront/product/17",
            "/store/legacy/item.asset",
        ):
            request = make_mocked_request("GET", path)
            match = await app.router.resolve(request)
            assert match.http_exception is None
            response = await match.handler(request)
            assert response.status == 200
            assert response.text == "storefront spa"

    asyncio.run(exercise_direct_gets())


def test_delivery_revoke_route_requires_seller(monkeypatch):
    from AssetsManager.lan.routes import commerce_policy

    class Settings:
        def get(self, key, default=None):
            return {
                "lan_commerce_enabled": True,
                "lan_seller_enabled": True,
            }.get(key, default)

    monkeypatch.setattr(
        commerce_policy.AppSettings,
        "instance",
        classmethod(lambda cls: Settings()),
    )

    async def no_seller(_request):
        return None

    monkeypatch.setattr(shop_routes, "require_seller", no_seller)
    request = make_mocked_request(
        "POST", "/api/shop/order/7/delivery/revoke", match_info={"order_id": "7"}
    )
    response = asyncio.run(shop_routes.handle_order_delivery_revoke(request))
    assert response.status == 403


def test_delivery_revoke_route_forwards_seller_and_returns_seller_order(monkeypatch):
    from AssetsManager.lan.routes import commerce_policy

    class Settings:
        def get(self, key, default=None):
            return {
                "lan_commerce_enabled": True,
                "lan_seller_enabled": True,
            }.get(key, default)

    monkeypatch.setattr(
        commerce_policy.AppSettings,
        "instance",
        classmethod(lambda cls: Settings()),
    )
    calls = []

    class Orders:
        def revoke_delivery(self, root, order_id, *, seller):
            calls.append((root, order_id, seller))
            return {
                "id": 7,
                "item_id": 3,
                "item_path": "asset.txt",
                "item_title": "Asset",
                "buyer_name": "Buyer",
                "buyer_email": "buyer@example.com",
                "amount_cents": 1200,
                "currency": "CNY",
                "status": "fulfilled",
                "metadata": {},
                "created_at": 1.0,
                "updated_at": 1.0,
            }

    lan = SimpleNamespace(library_root="library")
    services = SimpleNamespace(orders=Orders())
    monkeypatch.setattr(shop_routes, "get_lan", lambda request: lan)
    monkeypatch.setattr(shop_routes, "get_commerce_services", lambda request: services)

    async def seller(_request):
        return {"kind": "seller"}

    monkeypatch.setattr(shop_routes, "require_seller", seller)
    request = make_mocked_request(
        "POST", "/api/shop/order/7/delivery/revoke", match_info={"order_id": "7"}
    )
    response = asyncio.run(shop_routes.handle_order_delivery_revoke(request))
    assert response.status == 200
    assert calls == [("library", "7", {"kind": "seller"})]
    body = json.loads(response.body)
    assert body["order"]["status"] == "fulfilled"
    assert body["revoked"] is True


def test_shop_items_status_query_is_validated_and_forwarded(monkeypatch):
    from AssetsManager.lan.routes import commerce_policy

    class Settings:
        def get(self, key, default=None):
            return {
                "lan_commerce_enabled": True,
                "lan_seller_enabled": True,
            }.get(key, default)

    monkeypatch.setattr(
        commerce_policy.AppSettings,
        "instance",
        classmethod(lambda cls: Settings()),
    )
    calls = []

    class Shop:
        def list_items(self, root, **kwargs):
            calls.append((root, kwargs))
            return []

    async def seller():
        return {"kind": "seller"}

    lan = SimpleNamespace(library_root="library")
    services = SimpleNamespace(shop=Shop())
    monkeypatch.setattr(shop_routes, "get_lan", lambda request: lan)
    monkeypatch.setattr(shop_routes, "get_commerce_services", lambda request: services)
    monkeypatch.setattr(shop_routes, "require_seller", lambda request: seller())

    response = asyncio.run(
        shop_routes.handle_shop_items(
            make_mocked_request("GET", "/api/shop/items?status=draft&include_disabled=true")
        )
    )
    assert response.status == 200
    assert calls == [("library", {"include_disabled": True, "status": "draft"})]

    async def public_seller():
        return None

    monkeypatch.setattr(shop_routes, "require_seller", lambda request: public_seller())
    response = asyncio.run(
        shop_routes.handle_shop_items(
            make_mocked_request("GET", "/api/shop/items?status=draft&include_disabled=true")
        )
    )
    assert response.status == 200
    assert calls[-1] == ("library", {"include_disabled": False, "status": "active"})

    response = asyncio.run(
        shop_routes.handle_shop_items(
            make_mocked_request("GET", "/api/shop/items?status=unknown")
        )
    )
    assert response.status == 400


def test_public_shop_item_route_forwards_id_without_seller(monkeypatch):
    from AssetsManager.lan.routes import commerce_policy

    class Settings:
        def get(self, key, default=None):
            return {"lan_commerce_enabled": True}.get(key, default)

    monkeypatch.setattr(
        commerce_policy.AppSettings,
        "instance",
        classmethod(lambda cls: Settings()),
    )
    calls = []

    class Shop:
        def get_public_item(self, root, item_id):
            calls.append((root, item_id))
            return {"id": item_id, "status": "active"}

    lan = SimpleNamespace(library_root="library")
    services = SimpleNamespace(shop=Shop())
    monkeypatch.setattr(shop_routes, "get_lan", lambda request: lan)
    monkeypatch.setattr(shop_routes, "get_commerce_services", lambda request: services)

    response = asyncio.run(
        shop_routes.handle_public_shop_item(
            make_mocked_request("GET", "/api/shop/items?id=17")
        )
    )

    assert response.status == 200
    assert calls == [("library", 17)]


def test_public_shop_item_by_path_route_forwards_decoded_path_and_validates_missing(monkeypatch):
    from AssetsManager.lan.routes import commerce_policy

    class Settings:
        def get(self, key, default=None):
            return {"lan_commerce_enabled": True}.get(key, default)

    monkeypatch.setattr(
        commerce_policy.AppSettings,
        "instance",
        classmethod(lambda cls: Settings()),
    )
    calls = []

    from AssetsManager.domain.errors import ValidationError

    class Shop:
        def get_public_item_by_path(self, root, path):
            if path is None:
                raise ValidationError("path", "must be a relative path")
            calls.append((root, path))
            return {"path": path, "status": "active"}

    lan = SimpleNamespace(library_root="library")
    services = SimpleNamespace(shop=Shop())
    monkeypatch.setattr(shop_routes, "get_lan", lambda request: lan)
    monkeypatch.setattr(shop_routes, "get_commerce_services", lambda request: services)

    response = asyncio.run(
        shop_routes.handle_public_shop_item_by_path(
            make_mocked_request("GET", "/api/shop/items/by-path?path=folder%5Casset.txt")
        )
    )

    assert response.status == 200
    assert calls == [("library", "folder\\asset.txt")]

    response = asyncio.run(
        shop_routes.handle_public_shop_item_by_path(
            make_mocked_request("GET", "/api/shop/items/by-path")
        )
    )
    assert response.status == 400


def test_public_shop_media_route_gates_and_forwards_slot(monkeypatch):
    from AssetsManager.lan.routes import commerce_policy

    class Settings:
        def get(self, key, default=None):
            return {"lan_commerce_enabled": True}.get(key, default)

    monkeypatch.setattr(
        commerce_policy.AppSettings,
        "instance",
        classmethod(lambda cls: Settings()),
    )
    calls = []

    class Shop:
        def get_public_item_media_path(self, root, item_id, slot):
            calls.append((root, item_id, slot))
            return "media/cover.png"

    async def fake_delivery(request, target, *, max_size, public):
        calls.append((str(target).replace("\\", "/"), max_size, public))
        return web.Response(status=200, body=b"ok", content_type="image/png")

    lan = SimpleNamespace(library_root="library")
    services = SimpleNamespace(shop=Shop())
    monkeypatch.setattr(shop_routes, "get_lan", lambda request: lan)
    monkeypatch.setattr(shop_routes, "get_commerce_services", lambda request: services)
    monkeypatch.setattr(shop_routes, "serve_verified_image", fake_delivery)

    request = make_mocked_request("GET", "/api/shop/items/17/media/cover?size=64")
    request.match_info.update({"item_id": "17", "slot": "cover"})
    response = asyncio.run(shop_routes.handle_public_shop_item_media(request))

    assert response.status == 200
    assert calls[0] == ("library", 17, "cover")
    assert calls[1][1:] == (64, True)



def test_public_shop_catalog_route_forwards_query_and_defaults(monkeypatch):
    from AssetsManager.lan.routes import commerce_policy

    class Settings:
        def get(self, key, default=None):
            return {"lan_commerce_enabled": True}.get(key, default)

    monkeypatch.setattr(
        commerce_policy.AppSettings,
        "instance",
        classmethod(lambda cls: Settings()),
    )
    calls = []

    class Shop:
        def list_catalog(self, root, **kwargs):
            calls.append((root, kwargs))
            return {
                "items": [],
                "page": kwargs["page"],
                "page_size": kwargs["page_size"],
                "total": 0,
            }

    lan = SimpleNamespace(library_root="library")
    services = SimpleNamespace(shop=Shop())
    monkeypatch.setattr(shop_routes, "get_lan", lambda request: lan)
    monkeypatch.setattr(shop_routes, "get_commerce_services", lambda request: services)

    response = asyncio.run(
        shop_routes.handle_public_shop_catalog(
            make_mocked_request(
                "GET",
                "/api/shop/catalog?q=brush&page=2&page_size=12&sort=newest",
            )
        )
    )

    assert response.status == 200
    assert set(json.loads(response.body)) == {"items", "page", "page_size", "total"}
    assert json.loads(response.body)["items"] == []
    assert calls == [
        (
            "library",
            {"q": "brush", "page": 2, "page_size": 12, "sort": "newest"},
        )
    ]

    response = asyncio.run(
        shop_routes.handle_public_shop_catalog(
            make_mocked_request("GET", "/api/shop/catalog")
        )
    )

    assert response.status == 200
    assert calls[-1] == (
        "library",
        {"q": None, "page": 1, "page_size": 24, "sort": "newest"},
    )


def test_public_shop_catalog_route_normalizes_q_and_rejects_repeated_q(monkeypatch):
    from AssetsManager.lan.routes import commerce_policy

    class Settings:
        def get(self, key, default=None):
            return {"lan_commerce_enabled": True}.get(key, default)

    monkeypatch.setattr(
        commerce_policy.AppSettings,
        "instance",
        classmethod(lambda cls: Settings()),
    )
    calls = []

    class Shop:
        def list_catalog(self, root, **kwargs):
            calls.append((root, kwargs))
            return {"items": [], "page": kwargs["page"], "page_size": kwargs["page_size"], "total": 0}

    monkeypatch.setattr(
        shop_routes,
        "get_lan",
        lambda request: SimpleNamespace(library_root="library"),
    )
    monkeypatch.setattr(
        shop_routes,
        "get_commerce_services",
        lambda request: SimpleNamespace(shop=Shop()),
    )

    response = asyncio.run(
        shop_routes.handle_public_shop_catalog(
            make_mocked_request("GET", "/api/shop/catalog?q=%20%20brush%20%20")
        )
    )
    assert response.status == 200
    assert calls[-1][1]["q"] == "  brush  "

    response = asyncio.run(
        shop_routes.handle_public_shop_catalog(
            make_mocked_request("GET", "/api/shop/catalog?q=one&q=two")
        )
    )
    assert response.status == 400
    assert json.loads(response.body) == {
        "error": "Validation error on 'q': must be provided once",
        "code": "validation_error",
        "field": "q",
        "details": {},
    }
    assert len(calls) == 1


def test_public_shop_catalog_route_rejects_non_integer_pagination(monkeypatch):
    from AssetsManager.lan.routes import commerce_policy

    class Settings:
        def get(self, key, default=None):
            return {"lan_commerce_enabled": True}.get(key, default)

    monkeypatch.setattr(
        commerce_policy.AppSettings,
        "instance",
        classmethod(lambda cls: Settings()),
    )
    calls = []

    class Shop:
        def list_catalog(self, *_args, **_kwargs):
            calls.append(True)
            return {"items": [], "page": 1, "page_size": 24, "total": 0}

    monkeypatch.setattr(
        shop_routes,
        "get_lan",
        lambda request: SimpleNamespace(library_root="library"),
    )
    monkeypatch.setattr(
        shop_routes,
        "get_commerce_services",
        lambda request: SimpleNamespace(shop=Shop()),
    )

    response = asyncio.run(
        shop_routes.handle_public_shop_catalog(
            make_mocked_request("GET", "/api/shop/catalog?page=not-an-int")
        )
    )

    assert response.status == 400
    assert calls == []



def test_public_shop_catalog_route_returns_one_public_page_without_leaking_inactive_or_unauthorized_items(
    schema_db, tmp_path, monkeypatch
):
    from AssetsManager.lan.routes import commerce_policy

    class Settings:
        def get(self, key, default=None):
            return {
                "lan_commerce_enabled": True,
                "lan_shop_authorized_roots": ["shop"],
            }.get(key, default)

    monkeypatch.setattr(
        commerce_policy.AppSettings,
        "instance",
        classmethod(lambda cls: Settings()),
    )

    repository = ShopRepository(schema_db)
    active = repository.create_item(path="shop/active.asset", title="Active", price_cents=100)
    repository.create_item(
        path="shop/draft.asset",
        title="Draft",
        price_cents=100,
        metadata={"status": "draft"},
    )
    repository.create_item(
        path="shop/archived.asset",
        title="Archived",
        price_cents=100,
        metadata={"status": "archived"},
    )
    repository.create_item(
        path="shop/disabled.asset",
        title="Disabled",
        price_cents=100,
        enabled=False,
    )
    repository.create_item(path="outside/hidden.asset", title="Outside", price_cents=100)

    lan = SimpleNamespace(library_root=tmp_path)
    services = SimpleNamespace(shop=ShopService(repository=repository))
    monkeypatch.setattr(shop_routes, "get_lan", lambda request: lan)
    monkeypatch.setattr(shop_routes, "get_commerce_services", lambda request: services)

    response = asyncio.run(
        shop_routes.handle_public_shop_catalog(
            make_mocked_request("GET", "/api/shop/catalog?page=1&page_size=20")
        )
    )

    assert response.status == 200
    body = json.loads(response.body)
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [active["id"]]
    assert {item["title"] for item in body["items"]} == {"Active"}



def test_public_shop_catalog_route_returns_unified_disabled_response_without_resolving_services(
    monkeypatch,
):
    from AssetsManager.lan.routes import commerce_policy

    class Settings:
        def get(self, key, default=None):
            return {"lan_commerce_enabled": False}.get(key, default)

    monkeypatch.setattr(
        commerce_policy.AppSettings,
        "instance",
        classmethod(lambda cls: Settings()),
    )

    def should_not_resolve(_request):
        raise AssertionError("disabled catalog must not resolve LAN or Commerce services")

    monkeypatch.setattr(shop_routes, "get_lan", should_not_resolve)
    monkeypatch.setattr(shop_routes, "get_commerce_services", should_not_resolve)

    response = asyncio.run(
        shop_routes.handle_public_shop_catalog(
            make_mocked_request("GET", "/api/shop/catalog?page=not-an-int")
        )
    )

    assert response.status == 404
    assert json.loads(response.body) == {
        "error": "Commerce is disabled",
        "code": "feature_disabled",
    }


@pytest.mark.parametrize(
    ("query", "field", "message"),
    [
        ("page=not-an-int", "page", "must be an integer"),
        ("page=0", "page", "must be a positive integer"),
        ("page_size=not-an-int", "page_size", "must be an integer"),
        ("page_size=0", "page_size", "must be between 1 and 100"),
        ("page_size=101", "page_size", "must be between 1 and 100"),
        (f"q={'x' * 201}", "q", "must be at most 200 characters"),
        ("q=one%0Atwo", "q", "must not contain control characters"),
        ("sort=price", "sort", "must be newest"),
    ],
)
def test_public_shop_catalog_route_maps_invalid_query_to_fielded_400(
    query, field, message, monkeypatch
):
    from AssetsManager.lan.routes import commerce_policy

    class Settings:
        def get(self, key, default=None):
            return {"lan_commerce_enabled": True}.get(key, default)

    monkeypatch.setattr(
        commerce_policy.AppSettings,
        "instance",
        classmethod(lambda cls: Settings()),
    )

    class Shop:
        def list_catalog(self, root, **kwargs):
            return ShopService(repository=object()).list_catalog(root, **kwargs)

    monkeypatch.setattr(
        shop_routes,
        "get_lan",
        lambda request: SimpleNamespace(library_root="library"),
    )
    monkeypatch.setattr(
        shop_routes,
        "get_commerce_services",
        lambda request: SimpleNamespace(shop=Shop()),
    )

    response = asyncio.run(
        shop_routes.handle_public_shop_catalog(
            make_mocked_request("GET", f"/api/shop/catalog?{query}")
        )
    )

    assert response.status == 400
    assert json.loads(response.body) == {
        "error": f"Validation error on '{field}': {message}",
        "code": "validation_error",
        "field": field,
        "details": {},
    }



def test_public_shop_catalog_route_preserves_service_q_validation_contract(monkeypatch):
    """The HTTP query is always text; q type validation belongs to the service."""
    from AssetsManager.lan.routes import commerce_policy

    class Settings:
        def get(self, key, default=None):
            return {"lan_commerce_enabled": True}.get(key, default)

    monkeypatch.setattr(
        commerce_policy.AppSettings,
        "instance",
        classmethod(lambda cls: Settings()),
    )

    class Shop:
        def list_catalog(self, *_args, **_kwargs):
            raise ValidationError("q", "must be a string")

    monkeypatch.setattr(
        shop_routes,
        "get_lan",
        lambda request: SimpleNamespace(library_root="library"),
    )
    monkeypatch.setattr(
        shop_routes,
        "get_commerce_services",
        lambda request: SimpleNamespace(shop=Shop()),
    )

    response = asyncio.run(
        shop_routes.handle_public_shop_catalog(
            make_mocked_request("GET", "/api/shop/catalog?q=invalid")
        )
    )

    assert response.status == 400
    assert json.loads(response.body) == {
        "error": "Validation error on 'q': must be a string",
        "code": "validation_error",
        "field": "q",
        "details": {},
    }
