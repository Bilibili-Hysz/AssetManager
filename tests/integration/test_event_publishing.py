"""Tests verifying that application services publish correct domain events."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _fake_session(root, token):
    """Minimal session stand-in satisfying the session_operation contract."""
    from contextlib import nullcontext
    from types import SimpleNamespace

    return SimpleNamespace(
        root=root,
        root_str=str(root),
        event_token=token,
        operation=nullcontext,
    )


def _install_event_bus(monkeypatch):
    """Swap the global EventBus singleton and return the fresh bus."""
    from AssetsManager.domain.event_bus import EventBus

    bus = EventBus()
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)
    return bus


def _fulfilled_order(schema_db, tmp_path, *, max_downloads=3):
    """Create a confirmed+fulfilled order and its bearer/receipt credentials."""
    from AssetsManager.application.order_service import OrderService
    from AssetsManager.repositories.order_repository import OrderRepository
    from AssetsManager.repositories.shop_repository import ShopRepository

    root = tmp_path / "library"
    root.mkdir()
    (root / "asset.txt").write_text("asset", encoding="utf-8")
    shops = ShopRepository(schema_db)
    orders = OrderRepository(schema_db)
    item = shops.create_item(path="asset.txt", title="Asset", price_cents=125)
    # Setup runs on a session-less service so its publishes are no-ops.
    setup = OrderService(repository=orders, shop_repository=shops)
    order, receipt = setup.create_order_with_receipt(root, {"item_id": item["id"]})
    setup.confirm_by_receipt(root, order["id"], receipt)
    _fulfilled, bearer, _claim = setup.fulfill(
        root, order["id"], max_downloads=max_downloads, expires_in=60
    )
    return root, order, receipt, bearer, orders, shops


def test_tag_service_publishes_tags_changed_on_add(tmp_path, monkeypatch):
    """TagService.add_tag() publishes AssetTagsChanged."""
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import AssetTagsChanged

    bus = EventBus()
    events = []
    bus.subscribe(AssetTagsChanged, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    service = bootstrap.runtime_for(session).services.tag_service
    file_path = str(tmp_path / "library" / "file.txt")
    try:
        service.add_tag(session.root, file_path, "hero")

        assert len(events) == 1
        assert events[0].file_path == file_path
        assert "hero" in events[0].new_tags
    finally:
        bootstrap.library_service.close()


def test_scoped_tag_add_publishes_asset_and_catalog_events(tmp_path, monkeypatch):
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import AssetTagsChanged, TagCatalogChanged

    bus = EventBus()
    asset_events = []
    catalog_events = []
    bus.subscribe(AssetTagsChanged, asset_events.append)
    bus.subscribe(TagCatalogChanged, catalog_events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path)
    service = bootstrap.runtime_for(session).services.tag_service
    asset = tmp_path / "file.txt"
    try:
        service.add_tag(tmp_path, asset, "hero")

        assert len(asset_events) == len(catalog_events) == 1
        assert asset_events[0].library_root == session.root_str
        assert asset_events[0].session_token == session.event_token
        assert asset_events[0].file_path == str(asset.resolve())
        assert asset_events[0].new_tags == ("hero",)
        assert catalog_events[0].session_token == session.event_token
    finally:
        bootstrap.library_service.close()


def test_scoped_tag_rename_publishes_one_batch_event(tmp_path, monkeypatch):
    """rename_tag() collapses per-file events into one batch event."""
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import AssetTagsChanged, TagCatalogChanged

    bus = EventBus()
    asset_events = []
    catalog_events = []
    bus.subscribe(AssetTagsChanged, asset_events.append)
    bus.subscribe(TagCatalogChanged, catalog_events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path)
    service = bootstrap.runtime_for(session).services.tag_service
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    try:
        service.add_tag(tmp_path, first, "hero")
        service.add_tag(tmp_path, second, "hero")
        asset_events.clear()
        catalog_events.clear()

        service.rename_tag(tmp_path, "hero", "champion")

        # Exactly one batch AssetTagsChanged covering both affected assets.
        assert len(asset_events) == 1
        event = asset_events[0]
        assert sorted(event.paths) == sorted(
            [str(first.resolve()), str(second.resolve())]
        )
        assert event.file_path == ""
        assert event.new_tags == ()
        assert event.session_token == session.event_token
        assert len(catalog_events) == 1
    finally:
        bootstrap.library_service.close()


def test_scoped_tag_rename_100_files_publishes_single_event(tmp_path, monkeypatch):
    """Batch boundary holds at scale: 100 affected files -> one event."""
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import AssetTagsChanged

    bus = EventBus()
    asset_events = []
    bus.subscribe(AssetTagsChanged, asset_events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path)
    service = bootstrap.runtime_for(session).services.tag_service
    try:
        for index in range(100):
            (tmp_path / f"asset_{index:03}.txt").write_text("x", encoding="utf-8")
            service.add_tag(tmp_path, tmp_path / f"asset_{index:03}.txt", "hero")
        asset_events.clear()

        service.rename_tag(tmp_path, "hero", "champion")

        assert len(asset_events) == 1
        assert len(asset_events[0].paths) == 100
    finally:
        bootstrap.library_service.close()


def test_tag_service_publishes_tags_changed_on_remove(tmp_path, monkeypatch):
    """TagService.remove_tag() publishes AssetTagsChanged."""
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import AssetTagsChanged

    bus = EventBus()
    events = []
    bus.subscribe(AssetTagsChanged, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    service = bootstrap.runtime_for(session).services.tag_service
    file_path = str(tmp_path / "library" / "file.txt")
    try:
        service.add_tag(session.root, file_path, "hero")
        events.clear()

        service.remove_tag(session.root, file_path, "hero")
        assert len(events) == 1
        assert "hero" not in events[0].new_tags
    finally:
        bootstrap.library_service.close()


def test_tag_service_publishes_on_rename(tmp_path, monkeypatch):
    """TagService.rename_tag() publishes AssetTagsChanged."""
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import AssetTagsChanged

    bus = EventBus()
    events = []
    bus.subscribe(AssetTagsChanged, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    service = bootstrap.runtime_for(session).services.tag_service
    file_path = str(tmp_path / "library" / "file.txt")
    try:
        service.add_tag(session.root, file_path, "hero")
        events.clear()

        service.rename_tag(session.root, "hero", "champion")
        assert len(events) == 1
    finally:
        bootstrap.library_service.close()


def test_metadata_service_publishes_notes_changed(tmp_path, monkeypatch):
    """MetadataService.set_notes() publishes AssetNotesChanged."""
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import AssetNotesChanged

    bus = EventBus()
    events = []
    bus.subscribe(AssetNotesChanged, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    service = bootstrap.runtime_for(session).services.metadata_service
    file_path = str(tmp_path / "library" / "test.txt")
    try:
        service.set_notes(session.root, file_path, "hello")

        assert len(events) == 1
        assert events[0].file_path == file_path
    finally:
        bootstrap.library_service.close()


def test_metadata_service_publishes_urls_changed(tmp_path, monkeypatch):
    """MetadataService.add_url() publishes AssetUrlsChanged."""
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import AssetUrlsChanged

    bus = EventBus()
    events = []
    bus.subscribe(AssetUrlsChanged, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    service = bootstrap.runtime_for(session).services.metadata_service
    file_path = str(tmp_path / "library" / "test.txt")
    try:
        service.add_url(session.root, file_path, "https://example.com")

        assert len(events) == 1
        assert events[0].file_path == file_path
        assert "https://example.com" in events[0].new_urls
    finally:
        bootstrap.library_service.close()


def test_metadata_remove_url_rejects_caller_transaction_before_publishing(tmp_path, monkeypatch):
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import AssetUrlsChanged

    bus = EventBus()
    events = []
    bus.subscribe(AssetUrlsChanged, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    service = bootstrap.runtime_for(session).services.metadata_service
    asset = session.root / "file.txt"
    try:
        service.add_url(session.root, asset, "https://example.com")
        events.clear()
        conn = session.connection_for(session.root)
        conn.execute("BEGIN")
        with pytest.raises(RuntimeError, match="clean transaction boundary"):
            service.remove_url(session.root, asset, "https://example.com")
        assert events == []
        assert service.get_urls(session.root, asset) == ["https://example.com"]
        conn.rollback()
    finally:
        bootstrap.library_service.close()


def test_metadata_remove_url_publishes_after_clean_mutation(tmp_path, monkeypatch):
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import AssetUrlsChanged

    bus = EventBus()
    events = []
    bus.subscribe(AssetUrlsChanged, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    service = bootstrap.runtime_for(session).services.metadata_service
    asset = session.root / "file.txt"
    try:
        service.add_url(session.root, asset, "https://example.com")
        events.clear()
        service.remove_url(session.root, asset, "https://example.com")
        assert service.get_urls(session.root, asset) == []
        assert len(events) == 1
        assert events[0].new_urls == ()
    finally:
        bootstrap.library_service.close()


def test_scoped_metadata_events_include_session_identity(tmp_path, monkeypatch):
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import AssetNotesChanged, AssetUrlsChanged

    bus = EventBus()
    note_events = []
    url_events = []
    bus.subscribe(AssetNotesChanged, note_events.append)
    bus.subscribe(AssetUrlsChanged, url_events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path)
    service = bootstrap.runtime_for(session).services.metadata_service
    asset = tmp_path / "file.txt"
    try:
        service.set_notes(tmp_path, asset, "hello")
        service.add_url(tmp_path, asset, "https://example.com")

        assert note_events[0].session_token == session.event_token
        assert note_events[0].file_path == str(asset.resolve())
        assert url_events[0].session_token == session.event_token
        assert url_events[0].new_urls == ("https://example.com",)
    finally:
        bootstrap.library_service.close()


def test_file_operation_publishes_file_created(tmp_path, monkeypatch):
    """FileOperationService.create_folder() publishes FileSystemChanged."""
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import FileSystemChanged

    bus = EventBus()
    events = []
    bus.subscribe(FileSystemChanged, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    service = bootstrap.runtime_for(session).services.file_operation_service
    try:
        (tmp_path / "library").mkdir(exist_ok=True)
        service.create_folder(tmp_path / "library", "MyFolder")

        assert len(events) == 1
        assert events[0].kind == "created"
        assert "MyFolder" in events[0].paths[0]
    finally:
        bootstrap.library_service.close()


def test_file_operation_publishes_file_renamed(tmp_path, monkeypatch):
    """FileOperationService.move() publishes FileSystemChanged."""
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import FileSystemChanged

    (tmp_path / "library").mkdir()
    (tmp_path / "library" / "old.txt").write_text("x")

    bus = EventBus()
    events = []
    bus.subscribe(FileSystemChanged, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    service = bootstrap.runtime_for(session).services.file_operation_service
    try:
        service.move(tmp_path / "library" / "old.txt", tmp_path / "library" / "new.txt")

        assert len(events) == 1
        assert events[0].kind == "moved"
        assert "old.txt" in events[0].old_paths[0]
        assert "new.txt" in events[0].paths[0]
    finally:
        bootstrap.library_service.close()


def test_file_operation_publishes_file_deleted(tmp_path, monkeypatch):
    """FileOperationService.delete_permanent() publishes FileSystemChanged."""
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import FileSystemChanged

    (tmp_path / "library").mkdir()
    (tmp_path / "library" / "doomed.txt").write_text("x")

    bus = EventBus()
    events = []
    bus.subscribe(FileSystemChanged, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    service = bootstrap.runtime_for(session).services.file_operation_service
    try:
        service.delete_permanent([tmp_path / "library" / "doomed.txt"])

        assert len(events) == 1
        assert events[0].kind == "deleted"
        assert "doomed.txt" in events[0].paths[0]
    finally:
        bootstrap.library_service.close()


def test_file_operation_publishes_file_copied(tmp_path, monkeypatch):
    """FileOperationService.copy_to_directory() publishes FileSystemChanged."""
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import FileSystemChanged

    (tmp_path / "library").mkdir()
    (tmp_path / "library" / "source.txt").write_text("x")
    dest = tmp_path / "library" / "dest"
    dest.mkdir()

    bus = EventBus()
    events = []
    bus.subscribe(FileSystemChanged, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    service = bootstrap.runtime_for(session).services.file_operation_service
    try:
        service.copy_to_directory([tmp_path / "library" / "source.txt"], dest)

        assert len(events) == 1
        assert events[0].kind == "copied"
        # Copies have no old location: old_paths must stay empty.
        assert events[0].old_paths == ()
        assert events[0].paths == (str((dest / "source.txt").resolve()),)
    finally:
        bootstrap.library_service.close()


def test_scoped_copy_publishes_session_scoped_file_change(tmp_path, monkeypatch):
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import FileSystemChanged

    source = tmp_path / "source.txt"
    source.write_text("x")
    destination = tmp_path / "dest"
    destination.mkdir()
    bus = EventBus()
    events = []
    bus.subscribe(FileSystemChanged, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path)
    service = bootstrap.runtime_for(session).services.file_operation_service
    try:
        service.copy_to_directory([source], destination)

        assert len(events) == 1
        assert events[0].library_root == session.root_str
        assert events[0].session_token == session.event_token
        assert events[0].kind == "copied"
        # Copies have no old location: old_paths must stay empty.
        assert events[0].old_paths == ()
        assert events[0].paths == (str((destination / source.name).resolve()),)
    finally:
        bootstrap.library_service.close()


def test_runtime_router_receives_scoped_service_events_once(tmp_path, monkeypatch):
    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import AssetTagsChanged

    bus = EventBus()
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path)
    runtime = bootstrap.runtime_for(session)
    received = []
    runtime.event_router.subscribe(received.append)
    event = AssetTagsChanged(
        library_root=session.root_str,
        session_token=session.event_token,
        file_path=str(tmp_path / "asset.png"),
        new_tags=("hero",),
    )
    try:
        bus.publish(event)
        assert len(received) == 1
        assert received[0].revision == 1
        assert runtime.revision == 1
        assert received[0].paths == ("asset.png",)
    finally:
        bootstrap.library_service.close()


def _delivery_service(schema_db, tmp_path):
    from AssetsManager.application.order_service import OrderService

    root, order, receipt, bearer, _orders, _shops = _fulfilled_order(schema_db, tmp_path)
    service = OrderService(
        repository=_orders,
        shop_repository=_shops,
        session=_fake_session(root, "delivery-session-token"),
    )
    return root, order, receipt, bearer, service


def test_resolve_delivery_consume_publishes_order_events(schema_db, tmp_path, monkeypatch):
    """A consumed bearer download publishes the Activity/Order/Quota trio."""
    from AssetsManager.domain.events import ActivityChanged, QuotaChanged, ShopOrderChanged

    bus = _install_event_bus(monkeypatch)
    activity, order_events, quota = [], [], []
    bus.subscribe(ActivityChanged, activity.append)
    bus.subscribe(ShopOrderChanged, order_events.append)
    bus.subscribe(QuotaChanged, quota.append)
    root, order, _receipt, bearer, service = _delivery_service(schema_db, tmp_path)

    # Non-consuming resolution (preview) must not publish anything.
    service.resolve_delivery(root, bearer)
    assert activity == [] and order_events == [] and quota == []

    service.resolve_delivery(root, bearer, consume=True)

    assert len(activity) == 1
    assert len(order_events) == 1
    assert len(quota) == 1
    assert order_events[0].order_id == str(order["id"])
    assert order_events[0].library_root == str(root)
    assert order_events[0].session_token == "delivery-session-token"
    assert quota[0].name == "orders"
    assert quota[0].session_token == "delivery-session-token"


def test_resolve_delivery_by_receipt_consume_publishes_order_events(
    schema_db, tmp_path, monkeypatch
):
    """A consumed receipt download publishes the Activity/Order/Quota trio."""
    from AssetsManager.domain.events import ActivityChanged, QuotaChanged, ShopOrderChanged

    bus = _install_event_bus(monkeypatch)
    activity, order_events, quota = [], [], []
    bus.subscribe(ActivityChanged, activity.append)
    bus.subscribe(ShopOrderChanged, order_events.append)
    bus.subscribe(QuotaChanged, quota.append)
    root, order, receipt, _bearer, service = _delivery_service(schema_db, tmp_path)

    # Non-consuming receipt resolution (preview) must not publish anything.
    service.resolve_delivery_by_receipt(root, order["id"], receipt)
    assert activity == [] and order_events == [] and quota == []

    service.resolve_delivery_by_receipt(root, order["id"], receipt, consume=True)

    assert len(activity) == 1
    assert len(order_events) == 1
    assert len(quota) == 1
    assert order_events[0].order_id == str(order["id"])
    assert order_events[0].library_root == str(root)
    assert order_events[0].session_token == "delivery-session-token"
    assert quota[0].name == "orders"
    assert quota[0].session_token == "delivery-session-token"


def test_seller_profile_update_publishes_seller_profile_changed(
    schema_db, tmp_path, monkeypatch
):
    """SellerProfileService.update_profile() publishes SellerProfileChanged."""
    from AssetsManager.application.seller_profile_service import SellerProfileService
    from AssetsManager.domain.events import SellerProfileChanged
    from AssetsManager.repositories.seller_profile_repository import (
        SellerProfileRepository,
    )

    bus = _install_event_bus(monkeypatch)
    events = []
    bus.subscribe(SellerProfileChanged, events.append)
    root = tmp_path / "library"
    root.mkdir()
    service = SellerProfileService(
        repository=SellerProfileRepository(schema_db),
        session=_fake_session(root, "seller-session-token"),
    )

    service.update_profile(root, {"store_name": "My Store"})

    assert len(events) == 1
    assert events[0].library_root == str(root)
    assert events[0].session_token == "seller-session-token"
