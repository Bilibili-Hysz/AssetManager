from __future__ import annotations

import pytest
from PIL import Image

from AssetsManager.application.order_service import OrderService
from AssetsManager.application.quota_service import QuotaService
from AssetsManager.application.seller_auth_service import SellerAuthService, hash_seller_token
from AssetsManager.application.shop_authorization import UnauthorizedShopPathError
from AssetsManager.application.shop_service import ShopService
from AssetsManager.domain.errors import NotFoundError, OperationNotPermitted, ValidationError
from AssetsManager.repositories.order_repository import OrderRepository
from AssetsManager.repositories.quota_repository import QuotaRepository
from AssetsManager.repositories.shop_repository import ShopRepository


def _services(schema_db, tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    (root / "asset.txt").write_text("asset", encoding="utf-8")
    shops = ShopRepository(schema_db)
    orders = OrderRepository(schema_db)
    quotas = QuotaRepository(schema_db)
    return root, shops, orders, quotas, ShopService(repository=shops), OrderService(
        repository=orders, shop_repository=shops
    ), QuotaService(repository=quotas)


def test_shop_and_order_services_enforce_path_and_state_contract(schema_db, tmp_path):
    root, shops, orders, _quotas, shop, order_service, _quota = _services(schema_db, tmp_path)
    item = shop.create_item(root, {"path": "asset.txt", "title": "Asset", "price_cents": 100})
    assert item["path"] == "asset.txt"
    with pytest.raises(Exception):
        shop.create_item(root, {"path": "../outside", "title": "Bad", "price_cents": 1})

    order = order_service.create_order(root, {"item_id": item["id"], "buyer_email": "buyer@example.com"})
    assert order["status"] == "pending"
    with pytest.raises(OperationNotPermitted):
        order_service.fulfill(root, order["id"])
    assert order_service.confirm(root, order["id"])["status"] == "confirmed"
    fulfilled, token, _claim = order_service.fulfill(root, order["id"], max_downloads=1)
    assert fulfilled["status"] == "fulfilled"
    assert token not in {row[0] for row in schema_db.execute("SELECT token_hash FROM shop_delivery_tokens")}
    assert hash_seller_token(token) not in {token}
    assert order_service.resolve_delivery(root, token)[1] == root / "asset.txt"
    order_service.resolve_delivery(root, token, consume=True)
    with pytest.raises(OperationNotPermitted):
        order_service.resolve_delivery(root, token, consume=True)
    assert orders.get_order(order["id"])["status"] == "fulfilled"

def test_order_service_accepts_null_optional_buyer_fields(schema_db, tmp_path):
    root, _shops, orders, _quotas, shop, order_service, _quota = _services(schema_db, tmp_path)
    item = shop.create_item(root, {"path": "asset.txt", "title": "Asset", "price_cents": 100})

    order = order_service.create_order(
        root,
        {"item_id": item["id"], "buyer_name": None, "buyer_email": None},
    )

    stored = orders.get_order(order["id"])
    assert stored["buyer_name"] is None
    assert stored["buyer_email"] is None

def test_seller_session_is_separate_from_lan_token():
    class Auth:
        def has_active_users(self):
            return True

        def authenticate_user(self, username, password):
            if username == "seller" and password == "secret":
                return {"id": 7, "username": username, "role": "admin"}, ""
            return None, "Invalid password"

        def get_user_by_id(self, user_id):
            return {"id": user_id, "username": "seller", "role": "admin", "is_active": True}

    service = SellerAuthService(Auth(), clock=lambda: 100.0, session_ttl=10)
    seller, cookie = service.login("seller", "secret")
    assert seller["role"] == "seller"
    assert service.authenticate(cookie)["username"] == "seller"
    assert service.authenticate("lan-user-token") is None
    assert service.logout(cookie) is True
    assert service.authenticate(cookie) is None
    assert service.is_enabled() is True


def test_seller_session_is_revoked_when_current_admin_loses_authority():
    class Auth:
        def __init__(self):
            self._record = {"id": 7, "username": "seller", "role": "admin", "is_active": True}

        def has_active_users(self):
            return True

        def authenticate_user(self, username, password):
            return dict(self._record), ""

        def get_user_by_id(self, user_id):
            return dict(self._record) if user_id == 7 else None

    auth = Auth()
    service = SellerAuthService(auth, clock=lambda: 100.0)
    _seller, cookie = service.login("seller", "secret")
    assert service.authenticate(cookie) is not None

    auth._record["is_active"] = False
    assert service.authenticate(cookie) is None

    # A later reactivation cannot revive the already-revoked bearer.
    auth._record["is_active"] = True
    assert service.authenticate(cookie) is None

    _seller, second_cookie = service.login("seller", "secret")
    auth._record["role"] = "user"
    assert service.authenticate(second_cookie) is None

    auth._record["role"] = "admin"
    _seller, third_cookie = service.login("seller", "secret")
    assert service.revoke_all() == 1
    assert service.revoke_all() == 0
    assert service.authenticate(third_cookie) is None


def test_seller_session_generation_revokes_dormant_tokens():
    class Auth:
        def has_active_users(self):
            return True

        def authenticate_user(self, username, password):
            return {"id": 7, "username": "seller", "role": "admin"}, ""

        def get_user_by_id(self, user_id):
            return {"id": user_id, "username": "seller", "role": "admin", "is_active": True}

    generation = [0]
    service = SellerAuthService(
        Auth(),
        clock=lambda: 100.0,
        feature_generation=lambda: generation[0],
    )
    _seller, cookie = service.login("seller", "secret")

    generation[0] = 1
    assert service.authenticate(cookie) is None

    generation[0] = 2
    assert service.authenticate(cookie) is None


def test_quota_service_exposes_delivery_aggregate(schema_db, tmp_path):
    root, _shops, _orders, quotas, _shop, _orders_service, quota = _services(schema_db, tmp_path)
    assert quota.get_quota(root)["delivery_tokens"] == 0
    item = _shops.create_item(path="asset.txt", title="Asset", price_cents=0)
    order = _orders.create_order(item_id=item["id"], amount_cents=0, currency="CNY")
    quotas.issue("hash", order["id"], max_downloads=2, delivery_path="asset.txt")
    assert quota.get_quota(root)["downloads_remaining"] == 2


def test_shop_service_lists_by_status_and_validates_status(schema_db, tmp_path):
    root, shops, _orders, _quotas, shop, _orders_service, _quota = _services(schema_db, tmp_path)
    active = shop.create_item(root, {"path": "asset.txt", "title": "Active", "price_cents": 1})
    draft = shops.create_item(
        path="draft.txt", title="Draft", price_cents=1, enabled=False, metadata={"status": "draft"}
    )

    assert [item["id"] for item in shop.list_items(root, status="active")] == [active["id"]]
    assert shop.list_items(root, status="draft", include_disabled=True)[0]["id"] == draft["id"]
    with pytest.raises(ValidationError, match="status"):
        shop.list_items(root, status="unknown")


def test_shop_service_rejects_oversized_price_cents(schema_db, tmp_path):
    root, _shops, _orders, _quotas, shop, _orders_service, _quota = _services(schema_db, tmp_path)
    with pytest.raises(ValidationError, match="price_cents"):
        shop.create_item(root, {"path": "asset.txt", "title": "Pricey", "price_cents": 10**13})
    # The configured ceiling (10^12 cents) itself stays accepted.
    item = shop.create_item(root, {"path": "asset.txt", "title": "Pricey", "price_cents": 10**12})
    assert item["price_cents"] == 10**12
    with pytest.raises(ValidationError, match="price_cents"):
        shop.update_item(root, item["id"], {"price_cents": 10**13})


def test_shop_service_duplicate_path_is_a_business_error(schema_db, tmp_path):
    root, _shops, _orders, _quotas, shop, _orders_service, _quota = _services(schema_db, tmp_path)
    (root / "second.txt").write_text("second", encoding="utf-8")
    first = shop.create_item(root, {"path": "asset.txt", "title": "First", "price_cents": 1})
    second = shop.create_item(root, {"path": "second.txt", "title": "Second", "price_cents": 1})

    with pytest.raises(ValidationError, match="already exists"):
        shop.create_item(root, {"path": "second.txt", "title": "Duplicate", "price_cents": 1})
    with pytest.raises(ValidationError, match="already exists"):
        shop.update_item(root, first["id"], {"path": "second.txt"})
    # The failed mutations must not have disturbed either row.
    assert shop.get_item(root, first["id"])["path"] == "asset.txt"
    assert shop.get_item(root, second["id"])["path"] == "second.txt"


def test_shop_service_status_only_update_preserves_metadata_and_gallery(schema_db, tmp_path):
    root, _shops, _orders, _quotas, shop, _orders_service, _quota = _services(schema_db, tmp_path)
    (root / "shop").mkdir()
    (root / "shop" / "asset.txt").write_text("asset", encoding="utf-8")
    (root / "shop" / "cover.png").write_bytes(b"cover")
    item = shop.create_item(
        root,
        {
            "path": "shop/asset.txt",
            "title": "Asset",
            "price_cents": 1,
            "metadata": {"license": "standard", "region": "cn"},
            "gallery_paths": ["shop/cover.png"],
        },
    )

    updated = shop.update_item(root, item["id"], {"status": "draft"})

    assert updated["status"] == "draft"
    assert updated["enabled"] is False
    assert updated["metadata"]["license"] == "standard"
    assert updated["metadata"]["region"] == "cn"
    assert updated["metadata"]["status"] == "draft"
    assert updated["gallery_paths"] == ["shop/cover.png"]

    persisted = shop.get_item(root, item["id"])
    assert persisted["status"] == "draft"
    assert persisted["metadata"]["license"] == "standard"
    assert persisted["gallery_paths"] == ["shop/cover.png"]


def test_shop_service_metadata_only_update_shallow_merges_current_metadata(schema_db, tmp_path):
    root, _shops, _orders, _quotas, shop, _orders_service, _quota = _services(schema_db, tmp_path)
    (root / "shop").mkdir()
    (root / "shop" / "asset.txt").write_text("asset", encoding="utf-8")
    (root / "shop" / "cover.png").write_bytes(b"cover")
    item = shop.create_item(
        root,
        {
            "path": "shop/asset.txt",
            "title": "Asset",
            "price_cents": 1,
            "metadata": {"license": "standard", "region": "cn"},
            "gallery_paths": ["shop/cover.png"],
        },
    )

    updated = shop.update_item(root, item["id"], {"metadata": {"license": "extended"}})

    assert updated["metadata"]["license"] == "extended"
    assert updated["metadata"]["region"] == "cn"
    # No status was supplied: no status key is invented by a metadata merge.
    assert updated["metadata"].get("status") is None
    assert updated["status"] == "active"
    assert updated["gallery_paths"] == ["shop/cover.png"]

    persisted = shop.get_item(root, item["id"])
    assert persisted["metadata"]["license"] == "extended"
    assert persisted["metadata"]["region"] == "cn"


def test_shop_service_combined_update_merges_status_metadata_and_gallery(schema_db, tmp_path):
    root, _shops, _orders, _quotas, shop, _orders_service, _quota = _services(schema_db, tmp_path)
    (root / "shop").mkdir()
    (root / "shop" / "asset.txt").write_text("asset", encoding="utf-8")
    (root / "shop" / "old.png").write_bytes(b"old")
    (root / "shop" / "new.png").write_bytes(b"new")
    item = shop.create_item(
        root,
        {
            "path": "shop/asset.txt",
            "title": "Asset",
            "price_cents": 1,
            "metadata": {"license": "standard", "region": "cn"},
            "gallery_paths": ["shop/old.png"],
        },
    )

    updated = shop.update_item(
        root,
        item["id"],
        {
            "status": "archived",
            "metadata": {"license": "extended"},
            "gallery_paths": ["shop/new.png"],
        },
    )

    assert updated["status"] == "archived"
    assert updated["enabled"] is False
    assert updated["metadata"]["license"] == "extended"
    assert updated["metadata"]["region"] == "cn"
    assert updated["metadata"]["status"] == "archived"
    assert updated["gallery_paths"] == ["shop/new.png"]

    persisted = shop.get_item(root, item["id"])
    assert persisted["status"] == "archived"
    assert persisted["metadata"]["region"] == "cn"
    assert persisted["gallery_paths"] == ["shop/new.png"]


def test_shop_service_list_catalog_validates_and_returns_public_page(schema_db, tmp_path, monkeypatch):
    root, shops, _orders, _quotas, shop, _orders_service, _quota = _services(schema_db, tmp_path)
    (root / "shop").mkdir()
    (root / "shop" / "first.txt").write_text("first", encoding="utf-8")
    (root / "shop" / "second.txt").write_text("second", encoding="utf-8")
    shop.create_item(root, {"path": "shop/first.txt", "title": "First", "price_cents": 1})
    second = shop.create_item(root, {"path": "shop/second.txt", "title": "Second", "description": "A kit", "price_cents": 1})
    shops.create_item(path="outside.txt", title="Outside", price_cents=1, created_at=10)
    shops.create_item(path="shop/draft.txt", title="Draft", price_cents=1, enabled=False, metadata={"status": "draft"})

    class Settings:
        def get(self, key, default=None):
            return {"lan_shop_authorized_roots": ["shop"]}.get(key, default)

    from AssetsManager.application import shop_authorization

    monkeypatch.setattr(shop_authorization.AppSettings, "instance", classmethod(lambda cls: Settings()))
    result = shop.list_catalog(root, page=1, page_size=1)
    assert result["page"] == 1
    assert result["page_size"] == 1
    assert result["total"] == 2
    assert result["items"][0]["id"] == second["id"]
    assert "D:\\" not in str(result)
    assert shop.list_catalog(root, q="KIT")["items"][0]["id"] == second["id"]
    assert shop.list_catalog(root, q="  KIT  ")["items"][0]["id"] == second["id"]
    assert shop.list_catalog(root, q="   ")["total"] == 2

    with pytest.raises(ValidationError, match="at most 200"):
        shop.list_catalog(root, q="x" * 201)
    with pytest.raises(ValidationError, match="control characters"):
        shop.list_catalog(root, q="kit\npack")
    with pytest.raises(ValidationError, match="must be a string"):
        shop.list_catalog(root, q=object())

    with pytest.raises(ValidationError, match="page"):
        shop.list_catalog(root, page=0)
    with pytest.raises(ValidationError, match="page_size"):
        shop.list_catalog(root, page_size=101)
    with pytest.raises(ValidationError, match="sort"):
        shop.list_catalog(root, sort="price")







def test_shop_media_paths_respect_authorized_roots_and_allow_legacy_unconfigured(schema_db, tmp_path, monkeypatch):
    root, _shops, _orders, _quotas, shop, _orders_service, _quota = _services(schema_db, tmp_path)
    (root / "shop" / "sales").mkdir(parents=True)
    (root / "shop" / "other").mkdir()
    (root / "shop" / "sales" / "product.txt").write_text("product", encoding="utf-8")
    (root / "shop" / "sales" / "cover.png").write_bytes(b"cover")
    (root / "shop" / "sales" / "gallery.jpg").write_bytes(b"gallery")
    (root / "shop" / "other" / "cover.png").write_bytes(b"cover")
    (root / "shop" / "other" / "gallery.jpg").write_bytes(b"gallery")

    class Settings:
        def get(self, key, default=None):
            return {"lan_shop_authorized_roots": ["shop/sales"]}.get(key, default)

    from AssetsManager.application import shop_authorization

    monkeypatch.setattr(shop_authorization.AppSettings, "instance", classmethod(lambda cls: Settings()))
    item = shop.create_item(
        root,
        {
            "path": "shop/sales/product.txt",
            "title": "Media",
            "price_cents": 1,
            "cover_path": "shop/sales/cover.png",
            "gallery_paths": ["shop/sales/gallery.jpg"],
        },
    )
    assert item["cover_path"] == "shop/sales/cover.png"
    assert item["gallery_paths"] == ["shop/sales/gallery.jpg"]

    with pytest.raises(UnauthorizedShopPathError):
        shop.create_item(
            root,
            {
                "path": "shop/sales/product.txt",
                "title": "Blocked cover",
                "price_cents": 1,
                "cover_path": "shop/other/cover.png",
            },
        )
    with pytest.raises(UnauthorizedShopPathError):
        shop.update_item(root, item["id"], {"gallery_paths": ["shop/other/gallery.jpg"]})

    class UnconfiguredSettings:
        def get(self, key, default=None):
            return default

    monkeypatch.setattr(
        shop_authorization.AppSettings,
        "instance",
        classmethod(lambda cls: UnconfiguredSettings()),
    )
    legacy = shop.create_item(
        root,
        {
            "path": "asset.txt",
            "title": "Legacy media",
            "price_cents": 1,
            "cover_path": "shop/other/cover.png",
            "gallery_paths": ["shop/other/gallery.jpg"],
        },
    )
    assert legacy["cover_path"] == "shop/other/cover.png"
    assert legacy["gallery_paths"] == ["shop/other/gallery.jpg"]

def test_shop_create_ignores_internal_image_paths_and_uses_normalized_gallery(schema_db, tmp_path):
    root, shops, _orders, _quotas, shop, _orders_service, _quota = _services(schema_db, tmp_path)
    (root / "shop").mkdir(exist_ok=True)
    (root / "shop" / "asset.txt").write_text("asset", encoding="utf-8")
    (root / "shop" / "gallery.png").write_bytes(b"gallery")

    item = shop.create_item(
        root,
        {
            "path": "shop/asset.txt",
            "title": "Asset",
            "price_cents": 1,
            "metadata": {
                "license": "standard",
                "image_paths": ["../../outside.png"],
            },
            "gallery_paths": ["shop/gallery.png"],
        },
    )

    assert item["metadata"] == {"license": "standard"}
    assert item["gallery_paths"] == ["shop/gallery.png"]
    persisted = shop.get_item(root, item["id"])
    assert persisted["metadata"] == {"license": "standard"}
    assert persisted["gallery_paths"] == ["shop/gallery.png"]


def test_shop_create_rejects_non_mapping_metadata(schema_db, tmp_path):
    root, _shops, _orders, _quotas, shop, _orders_service, _quota = _services(schema_db, tmp_path)
    (root / "asset.txt").write_text("asset", encoding="utf-8")
    item = shop.create_item(
        root,
        {"path": "asset.txt", "title": "Asset", "price_cents": 1, "metadata": "ignored"},
    )
    assert item["metadata"] == {}


def test_public_shop_item_detail_by_path_normalizes_and_hides_non_public_items(schema_db, tmp_path, monkeypatch):
    root, shops, _orders, _quotas, shop, _orders_service, _quota = _services(schema_db, tmp_path)
    (root / "folder").mkdir()
    (root / "folder" / "asset.txt").write_text("asset", encoding="utf-8")
    active = shop.create_item(root, {"path": "folder/asset.txt", "title": "Active", "price_cents": 1})
    shops.create_item(
        path="folder/draft.txt", title="Draft", price_cents=1, enabled=False, metadata={"status": "draft"}
    )
    shops.create_item(
        path="folder/disabled.txt", title="Disabled", price_cents=1, enabled=False, metadata={"status": "active"}
    )

    assert shop.get_public_item_by_path(root, r"folder\asset.txt")["id"] == active["id"]
    for path in ("folder/draft.txt", "folder/disabled.txt", "folder/missing.txt"):
        with pytest.raises(NotFoundError):
            shop.get_public_item_by_path(root, path)

    class Settings:
        def get(self, key, default=None):
            return {"lan_shop_authorized_roots": ["other"]}.get(key, default)

    from AssetsManager.application import shop_authorization

    monkeypatch.setattr(shop_authorization.AppSettings, "instance", classmethod(lambda cls: Settings()))
    with pytest.raises(NotFoundError):
        shop.get_public_item_by_path(root, "folder/asset.txt")


def test_public_shop_item_detail_only_exposes_active_items(schema_db, tmp_path):
    root, shops, _orders, _quotas, shop, _orders_service, _quota = _services(schema_db, tmp_path)
    active = shop.create_item(root, {"path": "asset.txt", "title": "Active", "price_cents": 1})
    draft = shops.create_item(
        path="draft.txt", title="Draft", price_cents=1, enabled=False, metadata={"status": "draft"}
    )
    disabled_active = shops.create_item(
        path="disabled-active.txt", title="Disabled", price_cents=1, enabled=False, metadata={"status": "active"}
    )

    assert shop.get_public_item(root, active["id"])["status"] == "active"
    with pytest.raises(NotFoundError):
        shop.get_public_item(root, draft["id"])
    with pytest.raises(NotFoundError):
        shop.get_public_item(root, disabled_active["id"])


def test_public_shop_media_slots_are_allowlisted_and_authorized(schema_db, tmp_path):
    root, _shops, _orders, _quotas, shop, _orders_service, _quota = _services(schema_db, tmp_path)
    Image.new("RGB", (24, 12), (20, 40, 60)).save(root / "asset.png")
    Image.new("RGB", (24, 12), (60, 40, 20)).save(root / "gallery.png")
    item = shop.create_item(
        root,
        {
            "path": "asset.png",
            "title": "Media",
            "price_cents": 1,
            "gallery_paths": ["gallery.png"],
        },
    )

    assert shop.get_public_item_media_path(root, item["id"], "cover") == "asset.png"
    assert shop.get_public_item_media_path(root, item["id"], "gallery-0") == "gallery.png"
    for slot in ("../asset.png", "gallery-1", "cover/../asset.png", "gallery-x"):
        with pytest.raises(NotFoundError):
            shop.get_public_item_media_path(root, item["id"], slot)


def test_buyer_orders_keyset_pagination(schema_db, tmp_path):
    """list_buyer_orders returns pages with a stable opaque next_cursor."""
    from AssetsManager.application.order_service import (
        _decode_order_cursor,
        _encode_order_cursor,
    )

    root, shops, orders, _quotas, shop, order_service, _quota = _services(schema_db, tmp_path)
    item = shop.create_item(root, {"path": "asset.txt", "title": "Asset", "price_cents": 100})
    for i in range(7):
        order_service.create_order_with_receipt(
            root,
            {"item_id": item["id"], "buyer_email": f"b{i}@example.com"},
            buyer_owner_type="anonymous",
            buyer_owner_key="guest",
        )

    page1, cursor1 = order_service.list_buyer_orders(
        root, owner_type="anonymous", owner_key="guest", limit=3,
    )
    assert len(page1) == 3
    assert cursor1 is not None
    # Cursor round-trips through the opaque encoding.
    assert _decode_order_cursor(_encode_order_cursor(1.0, 5)) == (1.0, 5)

    page2, cursor2 = order_service.list_buyer_orders(
        root, owner_type="anonymous", owner_key="guest", limit=3, cursor=cursor1,
    )
    assert len(page2) == 3
    assert cursor2 is not None
    # Pages are disjoint and stable-ordered (newest first).
    ids1 = {row["id"] for row in page1}
    ids2 = {row["id"] for row in page2}
    assert ids1.isdisjoint(ids2)

    page3, cursor3 = order_service.list_buyer_orders(
        root, owner_type="anonymous", owner_key="guest", limit=3, cursor=cursor2,
    )
    assert len(page3) == 1
    assert cursor3 is None
    assert {row["id"] for row in page3}.isdisjoint(ids1 | ids2)

    # Invalid cursor is rejected.
    import pytest as _pytest
    with _pytest.raises(Exception):
        order_service.list_buyer_orders(
            root, owner_type="anonymous", owner_key="guest", cursor="not-a-cursor",
        )
