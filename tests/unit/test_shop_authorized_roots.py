from __future__ import annotations

import pytest

from AssetsManager.application.order_service import OrderService
from AssetsManager.application.shop_authorization import (
    ShopAuthorizationConfigError,
    UnauthorizedShopPathError,
    get_shop_authorized_roots,
    normalize_relative_shop_path,
)
from AssetsManager.application.shop_service import ShopService
from AssetsManager.core.settings import AppSettings
from AssetsManager.domain.errors import ValidationError
from AssetsManager.repositories.order_repository import OrderRepository
from AssetsManager.repositories.shop_repository import ShopRepository


class _Settings:
    def __init__(self, value=object()):
        self.value = value

    def get(self, key, default=None):
        if key == "lan_shop_authorized_roots" and self.value is not _MISSING:
            return self.value
        return default


_MISSING = object()


def _bind_settings(monkeypatch, value=_MISSING):
    settings = _Settings(value)
    monkeypatch.setattr(AppSettings, "instance", classmethod(lambda cls: settings))
    return settings


def test_shop_authorized_roots_support_setting_and_environment_fallback(monkeypatch):
    _bind_settings(monkeypatch, ["shop\\sales", " original ", "shop/sales"])
    monkeypatch.setenv("SHOP_AUTHORIZED_ROOTS", "ignored")
    assert get_shop_authorized_roots() == ("shop/sales", "original")

    _bind_settings(monkeypatch, _MISSING)
    monkeypatch.setenv("SHOP_AUTHORIZED_ROOTS", "shop/sales;original")
    assert get_shop_authorized_roots() == ("shop/sales", "original")

    _bind_settings(monkeypatch, "")
    monkeypatch.setenv("SHOP_AUTHORIZED_ROOTS", "shop/sales")
    assert get_shop_authorized_roots() == ()


def test_invalid_non_empty_shop_authorized_config_fails_closed(monkeypatch):
    _bind_settings(monkeypatch, ["/absolute", "../outside"])
    with pytest.raises(ShopAuthorizationConfigError) as exc_info:
        get_shop_authorized_roots()
    assert "/absolute" not in str(exc_info.value)
    assert "outside" not in str(exc_info.value)


def test_shop_paths_normalize_and_reject_absolute_or_parent_paths():
    assert normalize_relative_shop_path(r"shop\\sales//hero") == "shop/sales/hero"
    with pytest.raises(ValidationError, match="relative path") as absolute:
        normalize_relative_shop_path(r"C:\\library\\hero")
    assert "library" not in str(absolute.value)
    with pytest.raises(ValidationError, match="parent paths") as parent:
        normalize_relative_shop_path("shop/../hero")
    assert "hero" not in str(parent.value)


def test_shop_create_update_and_listing_apply_authorized_roots(monkeypatch, schema_db, tmp_path):
    _bind_settings(monkeypatch, ["shop/sales"])
    root = tmp_path / "library"
    (root / "shop" / "sales").mkdir(parents=True)
    (root / "shop" / "other").mkdir(parents=True)
    (root / "shop" / "sales" / "allowed.txt").write_text("allowed", encoding="utf-8")
    (root / "shop" / "other" / "blocked.txt").write_text("blocked", encoding="utf-8")

    shops = ShopRepository(schema_db)
    shop = ShopService(repository=shops)
    allowed = shop.create_item(root, {"path": r"shop\\sales\\allowed.txt", "title": "Allowed", "price_cents": 1})
    assert allowed["path"] == "shop/sales/allowed.txt"

    with pytest.raises(UnauthorizedShopPathError) as create_error:
        shop.create_item(root, {"path": "shop/other/blocked.txt", "title": "Blocked", "price_cents": 1})
    assert "blocked.txt" not in str(create_error.value)

    blocked = shops.create_item(path="shop/other/blocked.txt", title="Legacy", price_cents=1)
    listed = shop.list_items(root, include_disabled=True)
    assert [item["id"] for item in listed] == [allowed["id"]]

    with pytest.raises(UnauthorizedShopPathError):
        shop.update_item(root, blocked["id"], {"title": "Still blocked"})
    with pytest.raises(UnauthorizedShopPathError):
        shop.update_item(root, allowed["id"], {"path": "shop/other/blocked.txt"})


def test_order_creation_and_delivery_reject_unauthorized_item(monkeypatch, schema_db, tmp_path):
    _bind_settings(monkeypatch, ["shop/sales"])
    root = tmp_path / "library"
    root.mkdir()
    (root / "blocked.txt").write_text("blocked", encoding="utf-8")
    shops = ShopRepository(schema_db)
    orders = OrderRepository(schema_db)
    blocked = shops.create_item(path="blocked.txt", title="Blocked", price_cents=1)
    service = OrderService(repository=orders, shop_repository=shops)

    with pytest.raises(UnauthorizedShopPathError):
        service.create_order(root, {"item_id": blocked["id"]})

    with pytest.raises(UnauthorizedShopPathError):
        service._delivery_target(root, {"delivery_path": "blocked.txt"})
