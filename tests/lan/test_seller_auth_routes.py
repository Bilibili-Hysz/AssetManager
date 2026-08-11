"""Seller authentication HTTP route error-contract tests."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from AssetsManager.domain.errors import OperationNotPermitted
from AssetsManager.lan.routes import commerce_policy, seller_auth


def _enable_seller(monkeypatch):
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


def _request(body=None):
    request = make_mocked_request("POST", "/api/shop/auth/login", app=web.Application())
    if body is not None:

        async def read_json():
            return body

        request.json = read_json
    return request


def _stub_services(monkeypatch, login):
    monkeypatch.setattr(
        seller_auth,
        "get_commerce_services",
        lambda request: SimpleNamespace(
            seller_auth=SimpleNamespace(login=login)
        ),
    )


def test_seller_login_success_returns_token_cookie(monkeypatch):
    _enable_seller(monkeypatch)
    calls = []

    def login(username, password):
        calls.append((username, password))
        return {"id": 1, "username": "admin", "role": "seller"}, "bearer-token"

    _stub_services(monkeypatch, login)
    response = asyncio.run(
        seller_auth.handle_seller_login(_request({"username": "admin", "password": "secret"}))
    )
    assert response.status == 200
    assert json.loads(response.body) == {
        "ok": True,
        "authenticated": True,
        "seller": {"id": 1, "username": "admin", "role": "seller"},
    }
    assert calls == [("admin", "secret")]
    assert response.cookies["seller_session"].value == "bearer-token"


def test_seller_login_invalid_credentials_remain_401(monkeypatch):
    _enable_seller(monkeypatch)

    def login(_username, _password):
        raise OperationNotPermitted("Invalid seller credentials")

    _stub_services(monkeypatch, login)
    response = asyncio.run(
        seller_auth.handle_seller_login(_request({"username": "admin", "password": "wrong"}))
    )
    assert response.status == 401
    assert json.loads(response.body) == {"error": "Invalid seller credentials"}


def test_seller_login_malformed_json_is_400_not_500(monkeypatch):
    _enable_seller(monkeypatch)

    def should_not_login(*_args):
        raise AssertionError("malformed JSON must not reach the auth service")

    _stub_services(monkeypatch, should_not_login)
    request = _request()

    async def bad_json():
        raise json.JSONDecodeError("Expecting value", "doc", 0)

    request.json = bad_json
    response = asyncio.run(seller_auth.handle_seller_login(request))
    assert response.status == 400
    assert json.loads(response.body) == {"error": "Invalid request"}


def test_seller_login_database_failure_is_500_and_logged(monkeypatch, caplog):
    _enable_seller(monkeypatch)

    def login(_username, _password):
        raise sqlite3.OperationalError("database is locked")

    _stub_services(monkeypatch, login)
    response = asyncio.run(
        seller_auth.handle_seller_login(_request({"username": "admin", "password": "secret"}))
    )
    assert response.status == 500
    assert json.loads(response.body) == {"error": "Internal server error"}
    assert "Seller login failed unexpectedly" in caplog.text
