import asyncio
import json
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from AssetsManager.lan.routes import commerce_policy
from AssetsManager.lan.routes import seller_profile as routes


def _settings(monkeypatch, commerce=True, seller=True):
    class Settings:
        def get(self, key, default=None):
            return {
                "lan_commerce_enabled": commerce,
                "lan_seller_enabled": seller,
            }.get(key, default)

    monkeypatch.setattr(
        commerce_policy.AppSettings,
        "instance",
        classmethod(lambda cls: Settings()),
    )


def _request(method, payload=None):
    request = make_mocked_request(method, "/api/shop/seller-profile", app=web.Application())
    if payload is not None:
        async def read_json():
            return payload
        request.json = read_json
    return request


def test_get_and_put_seller_profile_handler(monkeypatch):
    _settings(monkeypatch)
    profile = {
        "store_name": "Store",
        "contact_email": "owner@example.com",
        "description": "Description",
        "accept_orders": True,
        "updated_at": 123.0,
    }
    calls = []

    class Service:
        def get_profile(self, root):
            calls.append(("get", root))
            return profile

        def update_profile(self, root, payload):
            calls.append(("put", root, payload))
            return {**profile, **payload}

    lan = SimpleNamespace(library_root="library")
    monkeypatch.setattr(routes, "get_lan", lambda request: lan)
    monkeypatch.setattr(routes, "require_seller", lambda request: asyncio.sleep(0, result={"kind": "seller"}))
    monkeypatch.setattr(routes, "get_seller_profile_service", lambda request: Service())

    response = asyncio.run(routes.handle_seller_profile(_request("GET")))
    assert response.status == 200
    assert json.loads(response.body)["profile"] == profile
    assert calls == [("get", "library")]

    response = asyncio.run(routes.handle_seller_profile(_request("PUT", {"store_name": "Updated"})))
    assert response.status == 200
    assert json.loads(response.body)["profile"]["store_name"] == "Updated"
    assert calls[-1] == ("put", "library", {"store_name": "Updated"})


def test_seller_profile_handler_preserves_policy_and_auth_gates(monkeypatch):
    _settings(monkeypatch)
    calls = []
    monkeypatch.setattr(routes, "get_seller_profile_service", lambda request: calls.append(True))
    monkeypatch.setattr(routes, "require_seller", lambda request: asyncio.sleep(0, result=None))

    response = asyncio.run(routes.handle_seller_profile(_request("GET")))
    assert response.status == 403
    body = json.loads(response.body)
    assert body["error"] == "Seller authentication required"
    assert body["code"] == "forbidden"
    assert calls == []

    _settings(monkeypatch, commerce=False, seller=True)
    response = asyncio.run(routes.handle_seller_profile(_request("GET")))
    assert response.status == 404
    assert json.loads(response.body) == commerce_policy.COMMERCE_DISABLED_BODY

    _settings(monkeypatch, commerce=True, seller=False)
    response = asyncio.run(routes.handle_seller_profile(_request("GET")))
    assert response.status == 404
    assert json.loads(response.body) == commerce_policy.SELLER_DISABLED_BODY
