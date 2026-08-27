from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiohttp.test_utils import make_mocked_request

from AssetsManager.lan.routes import storefront_analytics as routes


class AnalyticsService:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail = fail

    def record_storefront_view(self, root: str, token: str) -> bool:
        if self.fail:
            raise RuntimeError("database unavailable")
        self.calls.append((root, token))
        return True


def _lan() -> SimpleNamespace:
    return SimpleNamespace(library_root="library", token_secret="test-secret")


def test_storefront_view_issues_a_signed_cookie_and_rejects_tampering(monkeypatch):
    service = AnalyticsService()
    lan = _lan()
    monkeypatch.setattr(routes, "commerce_gate", lambda: None)
    monkeypatch.setattr(routes, "get_lan", lambda request: lan)
    monkeypatch.setattr(routes, "get_storefront_analytics_service", lambda request: service)

    first = asyncio.run(
        routes.handle_storefront_view(make_mocked_request("POST", "/api/shop/analytics/store-view"))
    )
    issued = first.cookies[routes._STORE_VISIT_COOKIE].value
    assert first.status == 200
    assert len(service.calls) == 1
    assert issued.count(".") == 2
    assert first.cookies[routes._STORE_VISIT_COOKIE]["httponly"]

    second = asyncio.run(
        routes.handle_storefront_view(
            make_mocked_request(
                "POST",
                "/api/shop/analytics/store-view",
                headers={"Cookie": f"{routes._STORE_VISIT_COOKIE}={issued}"},
            )
        )
    )
    assert second.status == 200
    assert len(service.calls) == 2
    assert routes._STORE_VISIT_COOKIE not in second.cookies

    tampered = issued[:-1] + ("A" if issued[-1] != "A" else "B")
    third = asyncio.run(
        routes.handle_storefront_view(
            make_mocked_request(
                "POST",
                "/api/shop/analytics/store-view",
                headers={"Cookie": f"{routes._STORE_VISIT_COOKIE}={tampered}"},
            )
        )
    )
    assert third.status == 200
    assert len(service.calls) == 3
    assert third.cookies[routes._STORE_VISIT_COOKIE].value != tampered


def test_storefront_view_returns_202_and_logs_when_analytics_fails(monkeypatch, caplog):
    service = AnalyticsService(fail=True)
    monkeypatch.setattr(routes, "commerce_gate", lambda: None)
    monkeypatch.setattr(routes, "get_lan", lambda request: _lan())
    monkeypatch.setattr(routes, "get_storefront_analytics_service", lambda request: service)

    with caplog.at_level("ERROR", logger=routes._LOGGER.name):
        response = asyncio.run(
            routes.handle_storefront_view(make_mocked_request("POST", "/api/shop/analytics/store-view"))
        )

    assert response.status == 202
    assert "Storefront analytics recording failed" in caplog.text


def test_storefront_view_respects_the_commerce_feature_gate(monkeypatch):
    expected = object()
    monkeypatch.setattr(routes, "commerce_gate", lambda: expected)

    assert asyncio.run(
        routes.handle_storefront_view(make_mocked_request("POST", "/api/shop/analytics/store-view"))
    ) is expected


def test_storefront_cookie_morsel_attributes_and_error_path(monkeypatch):
    service = AnalyticsService()
    lan = _lan()
    monkeypatch.setattr(routes, "commerce_gate", lambda: None)
    monkeypatch.setattr(routes, "get_lan", lambda request: lan)
    monkeypatch.setattr(routes, "get_storefront_analytics_service", lambda request: service)

    response = asyncio.run(
        routes.handle_storefront_view(make_mocked_request("POST", "/api/shop/analytics/store-view"))
    )
    morsel = response.cookies[routes._STORE_VISIT_COOKIE]
    assert morsel["httponly"]
    assert morsel["samesite"] == "Lax"
    assert morsel["path"] == "/api/shop"
    assert morsel["max-age"] == str(24 * 60 * 60)

    # Service failure keeps the bare 202 contract: no cookie, no record.
    class FailingService:
        def record_visit(self, *_args, **_kwargs):
            raise RuntimeError("store down")

    monkeypatch.setattr(
        routes, "get_storefront_analytics_service", lambda request: FailingService()
    )
    failed = asyncio.run(
        routes.handle_storefront_view(make_mocked_request("POST", "/api/shop/analytics/store-view"))
    )
    assert failed.status == 202
    assert routes._STORE_VISIT_COOKIE not in failed.cookies


def test_storefront_secret_shares_lan_fallback_with_quota_tunnel(monkeypatch):
    from AssetsManager.lan.routes import quota as quota_routes

    class BareLan:
        token_secret = None

    lan = BareLan()
    shared = routes._cookie_signing_secret(lan)
    assert getattr(lan, "_quota_cookie_secret") == shared
    assert quota_routes._quota_cookie_signing_secret(lan) == shared
