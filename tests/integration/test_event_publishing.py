"""Tests verifying that application services publish correct domain events."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _no_reconciliation_worker(monkeypatch):
    """Keep the reconciliation background worker out of these tests.

    The worker shares the session's single SQLite connection and periodically
    opens short claim/read transactions (``BEGIN IMMEDIATE`` / ``BEGIN`` ...
    ``COMMIT``).  On slower Linux CI those few-millisecond windows land inside
    the service calls under test, tripping the (correct, fail-closed)
    clean-boundary checks with flaky ``RuntimeError: ... clean transaction
    boundary`` or ``sqlite3.OperationalError: cannot start a transaction
    within a transaction``.  Windows-native tmpfs timing hides the race, which
    is why these tests only fail on Linux.  Same rationale as the explicit
    ``reconciliation_service.stop()`` calls in test_asset_index_service.py and
    test_file_operation_service.py; none of these tests assert on
    reconciliation behaviour.
    """
    from AssetsManager.application.asset_index_reconciliation_service import (
        AssetIndexReconciliationService,
    )

    monkeypatch.setattr(
        AssetIndexReconciliationService, "start", lambda self: False
    )


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

