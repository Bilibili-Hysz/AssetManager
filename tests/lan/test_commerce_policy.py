import asyncio
import json
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from AssetsManager.lan.api import setup_routes
from AssetsManager.lan.routes import commerce_policy
from AssetsManager.lan.routes._helpers import PRINCIPAL_REQUEST_KEY
from AssetsManager.lan.routes import quota as quota_routes
from AssetsManager.lan.routes import seller_auth, seller_profile, shop


def _payload(response):
    return json.loads(response.body)


def _settings(monkeypatch, values=None, error=None):
    values = {} if values is None else values

    class Settings:
        def get(self, key, default=None):
            if error is not None:
                raise error
            return values.get(key, default)

    settings = Settings()
    monkeypatch.setattr(
        commerce_policy.AppSettings,
        "instance",
        classmethod(lambda cls: settings),
    )
    return values


def _registered_handler(method, canonical):
    app = web.Application()
    setup_routes(app)
    for route in app.router.routes():
        if route.method == method and route.resource.canonical == canonical:
            return route.handler
    raise AssertionError(f"route not registered: {method} {canonical}")


def test_policy_is_dynamic_exact_true_and_fail_closed(monkeypatch):
    values = _settings(monkeypatch, {
        "lan_commerce_enabled": True,
        "lan_seller_enabled": True,
    })
    calls = []

    @commerce_policy.seller_required
    def endpoint(request):
        calls.append(request)
        return web.json_response({"ok": True})

    response = asyncio.run(endpoint(object()))
    assert response.status == 200
    assert calls == [calls[0]]

    values["lan_seller_enabled"] = False
    response = asyncio.run(endpoint(object()))
    assert response.status == 404
    assert _payload(response) == commerce_policy.SELLER_DISABLED_BODY
    assert len(calls) == 1

    values["lan_seller_enabled"] = True
    values["lan_commerce_enabled"] = False
    response = asyncio.run(endpoint(object()))
    assert response.status == 404
    assert _payload(response) == commerce_policy.COMMERCE_DISABLED_BODY
    assert len(calls) == 1

    for malformed in (1, "true", [], object(), None):
        values["lan_commerce_enabled"] = malformed
        values["lan_seller_enabled"] = True
        policy = commerce_policy.get_commerce_policy()
        assert policy.commerce_enabled is False
        assert policy.seller_enabled is False

    _settings(monkeypatch, error=RuntimeError("settings unavailable"))
    assert commerce_policy.get_commerce_policy() == commerce_policy.CommercePolicy(False, False)


def test_commerce_disabled_short_circuits_all_shop_business_routes(monkeypatch):
    _settings(monkeypatch, {
        "lan_commerce_enabled": False,
        "lan_seller_enabled": True,
    })
    app = web.Application()
    setup_routes(app)

    exceptions = {
        ("GET", "/api/shop/auth/seller-status"),
        ("POST", "/api/shop/auth/logout"),
    }
    checked = set()
    for route in app.router.routes():
        key = (route.method, route.resource.canonical)
        if route.method == "HEAD" or not route.resource.canonical.startswith("/api/shop/"):
            continue
        request = make_mocked_request(route.method, route.resource.canonical)
        response = asyncio.run(route.handler(request))
        checked.add(key)
        if key in exceptions:
            assert response.status == 200
        else:
            assert response.status == 404, key
            assert _payload(response) == commerce_policy.COMMERCE_DISABLED_BODY, key

    assert exceptions <= checked
    assert ("GET", "/api/shop/items") in checked
    assert ("GET", "/api/shop/quota") in checked


def test_seller_disabled_aliases_are_consistent_and_do_no_work(monkeypatch):
    _settings(monkeypatch, {
        "lan_commerce_enabled": True,
        "lan_seller_enabled": False,
    })
    seller_routes = {
        ("POST", "/api/shop/items"),
        ("PUT", "/api/shop/items"),
        ("DELETE", "/api/shop/items"),
        ("PUT", "/api/shop/items/{item_id}"),
        ("DELETE", "/api/shop/items/{item_id}"),
        ("GET", "/api/shop/orders/order"),
        ("GET", "/api/shop/orders"),
        ("POST", "/api/shop/orders/order/{order_id}/fulfill"),
        ("POST", "/api/shop/order/{order_id}/fulfill"),
        ("POST", "/api/shop/orders/order/{order_id}/revoke"),
        ("POST", "/api/shop/order/{order_id}/revoke"),
        ("GET", "/api/shop/orders/stats"),
        ("GET", "/api/shop/stats"),
        ("GET", "/api/shop/orders/export"),
        ("GET", "/api/shop/quota"),
        ("POST", "/api/shop/auth/login"),
        ("POST", "/api/auth/seller-login"),
    }
    for method, canonical in seller_routes:
        handler = _registered_handler(method, canonical)
        response = asyncio.run(handler(make_mocked_request(method, canonical)))
        assert response.status == 404, (method, canonical)
        assert _payload(response) == commerce_policy.SELLER_DISABLED_BODY


def test_seller_disabled_stale_principal_and_cookie_cannot_see_inactive_items(monkeypatch):
    _settings(monkeypatch, {
        "lan_commerce_enabled": True,
        "lan_seller_enabled": False,
    })
    calls = []

    class Shop:
        def list_items(self, root, **kwargs):
            calls.append((root, kwargs))
            return []

    class SellerAuth:
        def authenticate(self, token):
            raise AssertionError("disabled Seller must not authenticate stale cookies")

    monkeypatch.setattr(shop, "get_lan", lambda request: SimpleNamespace(library_root="library"))
    monkeypatch.setattr(
        shop,
        "get_commerce_services",
        lambda request: SimpleNamespace(shop=Shop(), seller_auth=SellerAuth()),
    )
    request = make_mocked_request(
        "GET",
        "/api/shop/items?status=draft&include_disabled=true",
        headers={"Cookie": "seller_session=stale"},
    )
    request[PRINCIPAL_REQUEST_KEY] = SimpleNamespace(
        authenticated=True,
        display_name="stale-admin",
        capabilities=SimpleNamespace(settings=True, manage_links=True),
    )

    response = asyncio.run(shop.handle_shop_items(request))
    assert response.status == 200
    assert calls == [("library", {"include_disabled": False, "status": "active"})]


def test_disabled_status_and_logout_never_resolve_services(monkeypatch):
    values = _settings(monkeypatch, {
        "lan_commerce_enabled": True,
        "lan_seller_enabled": False,
    })
    monkeypatch.setattr(
        seller_auth,
        "get_commerce_services",
        lambda request: (_ for _ in ()).throw(AssertionError("service resolution forbidden")),
    )

    for status_path in ("/api/shop/auth/seller-status", "/api/auth/seller-status"):
        response = asyncio.run(seller_auth.handle_seller_status(
            make_mocked_request("GET", status_path, headers={"Cookie": "seller_session=stale"})
        ))
        assert response.status == 200
        assert _payload(response) == {
            "enabled": False,
            "authenticated": False,
            "seller": None,
        }

    for logout_path in ("/api/shop/auth/logout", "/api/auth/seller-logout"):
        response = asyncio.run(seller_auth.handle_seller_logout(
            make_mocked_request("POST", logout_path, headers={"Cookie": "seller_session=stale"})
        ))
        assert response.status == 200
        assert _payload(response) == {"ok": True, "authenticated": False}
        cookie = response.cookies["seller_session"]
        assert cookie.value == ""
        assert cookie["max-age"] == "0"

    values["lan_commerce_enabled"] = False
    response = asyncio.run(seller_auth.handle_seller_logout(
        make_mocked_request("POST", "/api/shop/auth/logout")
    ))
    assert response.status == 200


def test_disabled_status_and_logout_revoke_cached_seller_sessions_without_resolving_services(monkeypatch):
    _settings(monkeypatch, {
        "lan_commerce_enabled": True,
        "lan_seller_enabled": False,
    })
    calls = []
    cached = SimpleNamespace(
        seller_auth=SimpleNamespace(
            revoke_all=lambda: calls.append("revoke") or 2,
        ),
    )
    app = {
        __import__(
            "AssetsManager.lan.routes._helpers",
            fromlist=["LAN_APP_KEY"],
        ).LAN_APP_KEY: SimpleNamespace(commerce_services=cached),
    }

    for path in ("/api/shop/auth/seller-status", "/api/auth/seller-status"):
        response = asyncio.run(seller_auth.handle_seller_status(
            make_mocked_request("GET", path, app=app, headers={"Cookie": "seller_session=stale"})
        ))
        assert response.status == 200

    for path in ("/api/shop/auth/logout", "/api/auth/seller-logout"):
        response = asyncio.run(seller_auth.handle_seller_logout(
            make_mocked_request("POST", path, app=app, headers={"Cookie": "seller_session=stale"})
        ))
        assert response.status == 200

    assert calls == ["revoke", "revoke", "revoke", "revoke"]


def test_disabled_seller_policy_revokes_all_cached_service_aliases(monkeypatch):
    _settings(monkeypatch, {
        "lan_commerce_enabled": True,
        "lan_seller_enabled": False,
    })
    calls = []

    def seller(name):
        return SimpleNamespace(
            revoke_all=lambda: calls.append(name) or 1,
        )

    from AssetsManager.lan.routes._helpers import LAN_APP_KEY

    app = {
        LAN_APP_KEY: SimpleNamespace(
            commerce_services=SimpleNamespace(seller_auth=seller("cached")),
            services=SimpleNamespace(seller_auth_service=seller("scoped")),
            _services=SimpleNamespace(seller_auth_service=seller("injected")),
        ),
    }
    response = asyncio.run(seller_auth.handle_seller_status(
        make_mocked_request("GET", "/api/shop/auth/seller-status", app=app)
    ))

    assert response.status == 200
    assert calls == ["cached", "scoped", "injected"]


def test_unauthenticated_order_listing_is_403_when_seller_enabled(monkeypatch):
    _settings(monkeypatch, {
        "lan_commerce_enabled": True,
        "lan_seller_enabled": True,
    })
    monkeypatch.setattr(shop, "get_lan", lambda request: SimpleNamespace(library_root="library"))
    monkeypatch.setattr(
        shop,
        "get_commerce_services",
        lambda request: (_ for _ in ()).throw(AssertionError("unauthenticated listing must not resolve services")),
    )

    for path in ("/api/shop/orders", "/api/shop/orders/order"):
        response = asyncio.run(shop.handle_shop_order(make_mocked_request("GET", path)))
        assert response.status == 403
        assert _payload(response) == {"error": "Seller authentication required"}



def test_seller_order_listing_rejects_invalid_limit_with_400(monkeypatch):
    _settings(monkeypatch, {
        "lan_commerce_enabled": True,
        "lan_seller_enabled": True,
    })
    monkeypatch.setattr(shop, "get_lan", lambda _request: SimpleNamespace(library_root="library"))

    async def seller(_request):
        return {"kind": "seller"}

    monkeypatch.setattr(shop, "require_seller", seller)
    monkeypatch.setattr(
        shop,
        "get_commerce_services",
        lambda _request: (_ for _ in ()).throw(
            AssertionError("invalid limit must be rejected before service resolution")
        ),
    )

    response = asyncio.run(shop.handle_shop_order(
        make_mocked_request("GET", "/api/shop/orders?limit=not-a-number")
    ))

    assert response.status == 400
    assert "limit" in _payload(response)["error"]


def test_buyer_order_and_legacy_delivery_flows_remain_public_when_seller_is_off(monkeypatch):
    _settings(monkeypatch, {
        "lan_commerce_enabled": True,
        "lan_seller_enabled": False,
    })
    calls = []
    target = SimpleNamespace(
        name="asset.zip",
        is_dir=lambda: False,
    )

    receipt = "buyer-receipt" * 4

    class Orders:
        def create_order_with_receipt(self, root, body, **_kwargs):
            calls.append(("create", root, body))
            return {"id": 7, "delivery_available": False}, receipt

        def get_order_by_receipt(self, root, order_id, received_receipt):
            calls.append(("lookup", root, order_id, received_receipt))
            return {"id": int(order_id), "delivery_available": False}

        def confirm_by_receipt(self, root, order_id, received_receipt):
            calls.append(("confirm", root, order_id, received_receipt))
            return {"id": int(order_id), "status": "confirmed", "delivery_available": False}

        def resolve_delivery(self, root, token, consume=False):
            calls.append(("delivery", root, token, consume))
            return {"id": 7}, target

    services = SimpleNamespace(orders=Orders())
    monkeypatch.setattr(shop, "get_lan", lambda request: SimpleNamespace(library_root="library"))
    monkeypatch.setattr(shop, "get_commerce_services", lambda request: services)
    # The new seller-profile availability guard must retain the historical
    # default: a store with no explicit pause setting accepts buyer orders.
    monkeypatch.setattr(
        seller_profile,
        "get_seller_profile_service",
        lambda _request: SimpleNamespace(
            get_profile=lambda _root: {"accept_orders": True}
        ),
    )

    async def body(request):
        return {"item_id": 7}

    monkeypatch.setattr(shop, "_json_body", body)
    receipt_cookie = {"Cookie": f"shop_order_receipt_7={receipt}"}

    created = asyncio.run(shop.handle_shop_order(
        make_mocked_request("POST", "/api/shop/orders/order")
    ))
    looked_up = asyncio.run(shop.handle_shop_order(
        make_mocked_request("GET", "/api/shop/orders/order?id=7", headers=receipt_cookie)
    ))
    confirmed = asyncio.run(shop.handle_order_confirm(
        make_mocked_request(
            "POST",
            "/api/shop/orders/order/7/confirm",
            headers=receipt_cookie,
            match_info={"order_id": "7"},
        )
    ))
    delivered = asyncio.run(shop.handle_delivery(
        make_mocked_request(
            "GET",
            "/api/shop/delivery/legacy-token",
            match_info={"token": "legacy-token"},
        )
    ))

    assert [created.status, looked_up.status, confirmed.status, delivered.status] == [201, 200, 200, 200]
    assert calls == [
        ("create", "library", {"item_id": 7}),
        ("lookup", "library", "7", receipt),
        ("confirm", "library", "7", receipt),
        ("delivery", "library", "legacy-token", False),
    ]

def test_public_catalog_and_receipt_hook_policy_remain_available_when_seller_is_off(monkeypatch):
    _settings(monkeypatch, {
        "lan_commerce_enabled": True,
        "lan_seller_enabled": False,
    })
    calls = []

    @commerce_policy.commerce_required
    async def future_receipt_handler(request):
        calls.append(request)
        return web.json_response({"delivery": "ready"})

    response = asyncio.run(future_receipt_handler(
        make_mocked_request("GET", "/api/shop/order/abc/delivery")
    ))
    assert response.status == 200
    assert _payload(response) == {"delivery": "ready"}
    assert len(calls) == 1

    app = web.Application()
    setup_routes(app)
    assert not any(
        route.resource.canonical in {"/api/shop/{tail}", "/api/shop/{path}"}
        for route in app.router.routes()
    )


def test_free_quota_route_is_not_commerce_gated(monkeypatch):
    _settings(monkeypatch, {
        "lan_commerce_enabled": False,
        "lan_seller_enabled": False,
    })
    monkeypatch.setattr(
        quota_routes,
        "get_free_download_quota_info",
        lambda request: {"enabled": False, "remaining": None},
    )
    handler = _registered_handler("GET", "/api/quota")
    response = asyncio.run(handler(make_mocked_request("GET", "/api/quota")))
    assert response.status == 200
    assert _payload(response) == {"enabled": False, "remaining": None}
