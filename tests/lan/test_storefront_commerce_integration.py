from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from AssetsManager.lan.api import setup_routes

from AssetsManager.lan.routes import shop as shop_routes
from AssetsManager.lan.routes import seller_profile
from AssetsManager.lan.routes import storefront_analytics


def test_buyer_checkout_returns_503_when_seller_pauses_new_orders(monkeypatch):
    monkeypatch.setattr(shop_routes, "commerce_gate", lambda: None)
    monkeypatch.setattr(shop_routes, "get_lan", lambda request: SimpleNamespace(library_root="library"))
    monkeypatch.setattr(
        seller_profile,
        "get_seller_profile_service",
        lambda request: SimpleNamespace(get_profile=lambda root: {"accept_orders": False}),
    )
    services = SimpleNamespace(orders=SimpleNamespace(create_order_with_receipt=lambda root, body: (_ for _ in ()).throw(AssertionError("order service must not run"))))
    monkeypatch.setattr(shop_routes, "get_commerce_services", lambda request: services)

    response = asyncio.run(
        shop_routes.handle_shop_order(make_mocked_request("POST", "/api/shop/order"))
    )

    assert response.status == 503
    assert json.loads(response.body) == {
        "error": "This store is not accepting new orders",
        "code": "store_not_accepting_orders",
        "details": {},
    }


def test_seller_stats_merges_aggregate_storefront_views_without_hiding_order_stats(monkeypatch):
    async def seller():
        return {"kind": "seller"}

    monkeypatch.setattr(shop_routes, "require_seller", lambda request: seller())
    monkeypatch.setattr(shop_routes, "get_lan", lambda request: SimpleNamespace(library_root="library"))
    monkeypatch.setattr(
        shop_routes,
        "get_commerce_services",
        lambda request: SimpleNamespace(orders=SimpleNamespace(stats=lambda root: {"total_orders": 2, "gross_cents": 500})),
    )
    monkeypatch.setattr(
        storefront_analytics,
        "get_storefront_analytics_service",
        lambda request: SimpleNamespace(stats=lambda root: {"store_views": 7}),
    )

    response = asyncio.run(
        shop_routes.handle_order_stats.__wrapped__(make_mocked_request("GET", "/api/shop/stats"))
    )

    assert response.status == 200
    assert json.loads(response.body) == {
        "stats": {"total_orders": 2, "gross_cents": 500, "store_views": 7}
    }

def test_new_storefront_backend_routes_are_registered():
    app = web.Application()
    setup_routes(app)
    registered = {(route.method, route.resource.canonical) for route in app.router.routes()}
    assert {
        ('GET', '/api/image'),
        ('GET', '/api/quicksearch'),
        ('GET', '/api/shop/profile'),
        ('GET', '/api/shop/seller-profile'),
        ('PUT', '/api/shop/seller-profile'),
        ('POST', '/api/shop/analytics/store-view'),
    } <= registered


def test_public_storefront_profile_exposes_only_buyer_safe_fields(monkeypatch):
    monkeypatch.setattr(seller_profile, "get_lan", lambda request: SimpleNamespace(library_root="library"))
    monkeypatch.setattr(
        seller_profile,
        "get_seller_profile_service",
        lambda request: SimpleNamespace(get_profile=lambda root: {
            "store_name": "North Studio",
            "contact_email": "private@example.com",
            "description": "Digital artwork",
            "accept_orders": False,
            "updated_at": 1,
        }),
    )

    response = asyncio.run(
        seller_profile.handle_public_seller_profile.__wrapped__(
            make_mocked_request("GET", "/api/shop/profile")
        )
    )

    assert response.status == 200
    assert json.loads(response.body) == {
        "profile": {
            "store_name": "North Studio",
            "description": "Digital artwork",
            "accept_orders": False,
        }
    }
