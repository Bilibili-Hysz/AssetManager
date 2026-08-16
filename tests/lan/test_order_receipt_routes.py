import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from aiohttp import CookieJar, web
from yarl import URL
from aiohttp.test_utils import make_mocked_request

from AssetsManager.application.order_service import DEFAULT_RECEIPT_TTL
from AssetsManager.domain.errors import NotFoundError
from AssetsManager.lan.api import setup_routes
from AssetsManager.lan.routes import commerce_policy
from AssetsManager.lan.routes import seller_profile
from AssetsManager.lan.routes import shop as shop_routes


BUYER_ORDER = {
    "id": 7,
    "item_id": 3,
    "item_title": "Asset",
    "amount_cents": 1200,
    "currency": "CNY",
    "status": "pending",
    "created_at": 1.0,
    "updated_at": 1.0,
    "delivery_available": False,
}


def _enable_commerce(monkeypatch):
    class Settings:
        def get(self, key, default=None):
            return {
                "lan_commerce_enabled": True,
                "lan_seller_enabled": True,
            }.get(key, default)

    monkeypatch.setattr(
        commerce_policy.AppSettings,
        "instance",
        classmethod(lambda _cls: Settings()),
    )


def _request(method, path, *, cookies=None, order_id="7", headers=None):
    headers = dict(headers or {})
    if cookies:
        headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in cookies.items())
    return make_mocked_request(
        method,
        path,
        headers=headers,
        match_info={"order_id": order_id}
    )


def _install_services(monkeypatch, tmp_path, orders):
    lan = SimpleNamespace(library_root=Path(tmp_path))
    monkeypatch.setattr(shop_routes, "get_lan", lambda _request: lan)
    monkeypatch.setattr(
        shop_routes,
        "get_commerce_services",
        lambda _request: SimpleNamespace(orders=orders),
    )


def test_cart_checkout_rejects_mismatched_header_and_body_idempotency_keys(
    monkeypatch,
):
    _enable_commerce(monkeypatch)

    async def body(_request):
        return {"idempotency_key": "body-key"}

    monkeypatch.setattr(shop_routes, "_json_body", body)
    request = make_mocked_request(
        "POST",
        "/api/shop/cart/checkout",
        headers={"Idempotency-Key": "header-key"},
    )
    response = asyncio.run(shop_routes.handle_shop_cart_checkout(request))

    assert response.status == 400
    assert json.loads(response.text) == {
        "error": "Validation error on 'idempotency_key': header and body values must match",
        "code": "validation_error",
        "field": "idempotency_key",
        "details": {},
    }


def test_receipt_order_creation_sets_scoped_http_only_cookie_without_json_token(
    monkeypatch, tmp_path
):
    _enable_commerce(monkeypatch)
    calls = []

    class Orders:
        def create_order_with_receipt(self, root, body, **_kwargs):
            calls.append((root, body))
            return dict(BUYER_ORDER), "receipt-secret-value" * 3

    _install_services(monkeypatch, tmp_path, Orders())
    # Buyer-order coverage is about receipt behavior; model the persisted
    # seller-profile default explicitly so the availability guard is covered
    # without coupling this route test to SQLite setup.
    monkeypatch.setattr(
        seller_profile,
        "get_seller_profile_service",
        lambda _request: SimpleNamespace(
            get_profile=lambda _root: {"accept_orders": True}
        ),
    )

    async def body(_request):
        return {"item_id": 3}

    monkeypatch.setattr(shop_routes, "_json_body", body)
    response = asyncio.run(shop_routes.handle_shop_order(
        _request("POST", "/api/shop/order")
    ))

    assert response.status == 201
    assert calls == [(Path(tmp_path), {"item_id": 3})]
    assert json.loads(response.text) == {"order": BUYER_ORDER}
    assert "receipt-secret-value" not in response.text
    cookie = response.cookies["shop_order_receipt_7"]
    assert cookie.value == "receipt-secret-value" * 3
    assert cookie["httponly"] is True
    secure_response = web.Response()
    shop_routes._set_order_receipt_cookie(
        secure_response,
        SimpleNamespace(secure=True),
        7,
        "receipt-secret-value" * 3,
    )
    assert secure_response.cookies["shop_order_receipt_7"]["secure"] is True
    assert cookie["samesite"] == "Lax"
    assert cookie["path"] == "/api/shop"
    assert cookie["max-age"] == str(DEFAULT_RECEIPT_TTL)
    assert response.headers["Cache-Control"] == "no-store"


def test_receipt_recovery_sets_a_cookie_without_returning_plaintext_token(monkeypatch, tmp_path):
    _enable_commerce(monkeypatch)
    calls = []

    class Orders:
        def recover_receipt_for_owner(self, root, order_id, **kwargs):
            calls.append((root, order_id, kwargs))
            return "recovered-receipt" * 3

    _install_services(monkeypatch, tmp_path, Orders())
    monkeypatch.setattr(
        shop_routes,
        "_buyer_owner",
        lambda _request: ("anonymous", None, "a" * 64, None),
    )
    response = asyncio.run(shop_routes.handle_order_receipt_recover(
        _request("POST", "/api/shop/order/7/receipt/recover")
    ))

    assert response.status == 200
    assert json.loads(response.text) == {"ok": True, "order_id": 7}
    assert "recovered-receipt" not in response.text
    assert response.cookies["shop_order_receipt_7"].value == "recovered-receipt" * 3
    assert calls == [
        (Path(tmp_path), "7", {"owner_type": "anonymous", "owner_key": "a" * 64})
    ]


def test_receipt_cookie_is_sent_to_legacy_and_plural_order_routes(monkeypatch, tmp_path):
    _enable_commerce(monkeypatch)

    class Orders:
        def create_order_with_receipt(self, root, body, **_kwargs):
            return dict(BUYER_ORDER), "receipt-secret-value" * 3

    _install_services(monkeypatch, tmp_path, Orders())
    async def body(_request):
        return {"item_id": 3}
    monkeypatch.setattr(shop_routes, "_json_body", body)
    monkeypatch.setattr(
        seller_profile,
        "get_seller_profile_service",
        lambda _request: SimpleNamespace(
            get_profile=lambda _root: {"accept_orders": True}
        ),
    )

    response = asyncio.run(shop_routes.handle_shop_order(
        _request("POST", "/api/shop/orders/order")
    ))
    async def check_cookie_paths():
        cookie_name = "shop_order_receipt_7"
        jar = CookieJar(unsafe=True)
        jar.update_cookies(
            response.cookies,
            response_url=URL("http://127.0.0.1/api/shop/orders/order"),
        )

        receipt = "receipt-secret-value" * 3
        for path in (
            "/api/shop/order/7",
            "/api/shop/order/7/confirm",
            "/api/shop/orders/order?id=7",
            "/api/shop/orders/order/7/confirm",
        ):
            filtered = jar.filter_cookies(URL(f"http://127.0.0.1{path}"))
            assert filtered.get(cookie_name) is not None, (path, jar._cookies, response.cookies)
            assert filtered.get(cookie_name).value == receipt

    asyncio.run(check_cookie_paths())

def test_buyer_order_lookup_and_confirmation_require_the_matching_receipt(
    monkeypatch, tmp_path
):
    _enable_commerce(monkeypatch)
    receipt = "buyer-receipt" * 4
    calls = []

    class Orders:
        def get_order_by_receipt(self, root, order_id, received_receipt):
            calls.append(("get", root, order_id, received_receipt))
            if received_receipt != receipt:
                raise NotFoundError("order receipt", str(order_id))
            return dict(BUYER_ORDER)

        def confirm_by_receipt(self, root, order_id, received_receipt):
            calls.append(("confirm", root, order_id, received_receipt))
            if received_receipt != receipt:
                raise NotFoundError("order receipt", str(order_id))
            return {**BUYER_ORDER, "status": "confirmed"}

    _install_services(monkeypatch, tmp_path, Orders())

    async def no_seller(_request):
        return None

    monkeypatch.setattr(shop_routes, "require_seller", no_seller)
    cookie_name = "shop_order_receipt_7"

    denied = asyncio.run(shop_routes.handle_shop_order(
        _request("GET", "/api/shop/order/7")
    ))
    assert denied.status == 404
    assert calls == [("get", Path(tmp_path), "7", "")]

    looked_up = asyncio.run(shop_routes.handle_shop_order(
        _request("GET", "/api/shop/order/7", cookies={cookie_name: receipt})
    ))
    assert looked_up.status == 200
    assert json.loads(looked_up.text) == {"order": BUYER_ORDER}
    assert "buyer_email" not in looked_up.text
    assert "metadata" not in looked_up.text

    confirmed = asyncio.run(shop_routes.handle_order_confirm(
        _request("POST", "/api/shop/order/7/confirm", cookies={cookie_name: receipt})
    ))
    assert confirmed.status == 200
    assert json.loads(confirmed.text)["order"]["status"] == "confirmed"
    assert calls[-1] == ("confirm", Path(tmp_path), "7", receipt)


def test_seller_order_lookup_keeps_seller_projection_without_using_buyer_receipt(
    monkeypatch, tmp_path
):
    _enable_commerce(monkeypatch)
    seller_order = {
        **BUYER_ORDER,
        "item_path": "asset.txt",
        "buyer_name": "Buyer",
        "buyer_email": "buyer@example.com",
        "metadata": {},
    }

    class Orders:
        def get_seller_order(self, root, order_id):
            assert root == Path(tmp_path)
            assert order_id == "7"
            return seller_order

        def get_order_by_receipt(self, *_args):
            raise AssertionError("seller lookup must not use the buyer receipt")

    _install_services(monkeypatch, tmp_path, Orders())

    async def seller(_request):
        return {"kind": "seller"}

    monkeypatch.setattr(shop_routes, "require_seller", seller)
    response = asyncio.run(shop_routes.handle_shop_order(
        _request("GET", "/api/shop/order/7")
    ))
    assert response.status == 200
    assert json.loads(response.text)["order"] == seller_order


def test_receipt_delivery_uses_cookie_only_and_consumes_once(monkeypatch, tmp_path):
    _enable_commerce(monkeypatch)
    receipt = "delivery-receipt" * 4
    target = Path(tmp_path) / "asset.txt"
    target.write_text("asset", encoding="utf-8")
    calls = []

    class Orders:
        def resolve_delivery_by_receipt(self, root, order_id, received_receipt, *, consume):
            calls.append((root, order_id, received_receipt, consume))
            if received_receipt != receipt:
                raise NotFoundError("order receipt", str(order_id))
            return {"order_id": 7, "download_count": 1}, target

    _install_services(monkeypatch, tmp_path, Orders())
    cookie_name = "shop_order_receipt_7"

    denied = asyncio.run(shop_routes.handle_order_delivery(
        _request("GET", "/api/shop/order/7/delivery")
    ))
    assert denied.status == 404

    delivered = asyncio.run(shop_routes.handle_order_delivery(
        _request("GET", "/api/shop/order/7/delivery", cookies={cookie_name: receipt})
    ))
    assert isinstance(delivered, web.FileResponse)
    assert delivered.headers["Cache-Control"] == "private, no-store"
    assert calls[-1] == (Path(tmp_path), "7", receipt, True)


def test_delivery_request_key_is_forwarded_and_prepare_failure_is_recorded(
    monkeypatch, tmp_path
):
    _enable_commerce(monkeypatch)
    target = Path(tmp_path) / "bundle"
    target.mkdir()
    calls = []
    failed = []

    class Orders:
        def resolve_delivery(self, root, token, *, consume, request_key=None):
            calls.append((root, token, consume, request_key))
            return {"order_id": 7}, target

        def fail_delivery_attempt(self, root, token, *, request_key):
            failed.append((root, token, request_key))
            return True

    _install_services(monkeypatch, tmp_path, Orders())

    async def fail_zip(*_args):
        return None

    from AssetsManager.lan.routes import _helpers
    monkeypatch.setattr(_helpers, "build_zip_async", fail_zip)
    response = asyncio.run(
        shop_routes.handle_delivery_download(
            make_mocked_request(
                "GET",
                "/api/shop/delivery/bearer/download",
                headers={"Idempotency-Key": "download-route-1"},
                match_info={"token": "bearer"},
            )
        )
    )

    assert response.status == 500
    assert calls == [(Path(tmp_path), "bearer", False, "download-route-1")]
    assert failed == [(Path(tmp_path), "bearer", "download-route-1")]


def test_delivery_zip_failure_does_not_consume_quota(monkeypatch, tmp_path):
    target = Path(tmp_path) / "bundle"
    target.mkdir()
    calls = []

    async def fail_zip(*_args):
        return None

    from AssetsManager.lan.routes import _helpers
    monkeypatch.setattr(_helpers, "build_zip_async", fail_zip)

    # request=None: the failing zip path returns before the cleanup wrapper
    # needs the request task.
    response = asyncio.run(shop_routes._delivery_file_response(
        None,
        target,
        consume=lambda: calls.append("consumed"),
    ))

    assert response.status == 500
    assert calls == []

def test_receipt_delivery_route_is_registered_as_exact_public_commerce_endpoint():
    app = web.Application()
    setup_routes(app)
    registered = {(route.method, route.resource.canonical) for route in app.router.routes()}
    assert ("GET", "/api/shop/order/{order_id}/delivery") in registered
    assert ("HEAD", "/api/shop/order/{order_id}/delivery") not in registered
    assert ("HEAD", "/api/shop/delivery/{token}/download") not in registered
    assert ("GET", "/api/shop/{tail:.*}") not in registered