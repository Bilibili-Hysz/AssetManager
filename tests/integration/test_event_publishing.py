"""Tests verifying that application services publish correct domain events."""
import os
import sqlite3

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def event_bus():
    from AssetsManager.domain.event_bus import EventBus
    bus = EventBus()
    return bus


@pytest.fixture
def lib_root(tmp_path):
    return str(tmp_path)


def test_library_service_publishes_library_opened(tmp_path, monkeypatch):
    """LibraryService.open_library() publishes LibraryOpened."""
    from AssetsManager.application.library_service import LibraryService
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import LibraryOpened

    bus = EventBus()
    events = []
    bus.subscribe(LibraryOpened, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    svc = LibraryService()
    lib = tmp_path / "testlib"
    lib.mkdir()
    svc.open_library(str(lib))

    assert len(events) == 1
    assert events[0].library_root == str(lib.resolve())
    assert events[0].session_token == svc.current_session.event_token


def test_tag_service_publishes_tags_changed_on_add(tmp_path, monkeypatch):
    """TagService.add_tag() publishes TagsChanged."""
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate
    from AssetsManager.application.tag_service import TagService
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import TagsChanged

    bus = EventBus()
    events = []
    bus.subscribe(TagsChanged, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        conn.executescript(database._SCHEMA)
        migrate(conn)

        lib = str(tmp_path)
        from AssetsManager.application.library_service import LibraryService
        LibraryService().open_session(lib)

        svc = TagService()
        file_path = str(tmp_path / "file.txt")
        svc.add_tag(lib, file_path, "hero", db_conn=conn)

        assert len(events) == 1
        assert events[0].file_path == file_path
        assert "hero" in events[0].new_tags
    finally:
        conn.close()


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


def test_scoped_tag_rename_updates_each_affected_asset_once(tmp_path, monkeypatch):
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

        assert {event.file_path for event in asset_events} == {
            str(first.resolve()), str(second.resolve())
        }
        assert all(event.new_tags == ("champion",) for event in asset_events)
        assert len(catalog_events) == 1
    finally:
        bootstrap.library_service.close()


def test_tag_service_publishes_tags_changed_on_remove(tmp_path, monkeypatch):
    """TagService.remove_tag() publishes TagsChanged."""
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate
    from AssetsManager.application.tag_service import TagService
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import TagsChanged

    bus = EventBus()
    events = []
    bus.subscribe(TagsChanged, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        conn.executescript(database._SCHEMA)
        migrate(conn)

        lib = str(tmp_path)
        from AssetsManager.application.library_service import LibraryService
        LibraryService().open_session(lib)

        svc = TagService()
        file_path = str(tmp_path / "file.txt")
        svc.add_tag(lib, file_path, "hero", db_conn=conn)
        events.clear()

        svc.remove_tag(lib, file_path, "hero", db_conn=conn)
        assert len(events) == 1
        assert "hero" not in events[0].new_tags
    finally:
        conn.close()


def test_tag_service_publishes_on_rename(tmp_path, monkeypatch):
    """TagService.rename_tag() publishes TagsChanged."""
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate
    from AssetsManager.application.tag_service import TagService
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import TagsChanged

    bus = EventBus()
    events = []
    bus.subscribe(TagsChanged, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        conn.executescript(database._SCHEMA)
        migrate(conn)

        lib = str(tmp_path)
        from AssetsManager.application.library_service import LibraryService
        LibraryService().open_session(lib)

        svc = TagService()
        svc.add_tag(lib, str(tmp_path / "file.txt"), "hero", db_conn=conn)
        events.clear()

        svc.rename_tag(lib, "hero", "champion", db_conn=conn)
        assert len(events) == 1
    finally:
        conn.close()


def test_metadata_service_publishes_notes_changed(tmp_path, monkeypatch):
    """MetadataService.set_notes() publishes NotesChanged."""
    from AssetsManager.application.metadata_service import MetadataService
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import NotesChanged

    bus = EventBus()
    events = []
    bus.subscribe(NotesChanged, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    lib = str(tmp_path)
    from AssetsManager.application.library_service import LibraryService
    LibraryService().open_session(lib)

    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(database._SCHEMA)
    migrate(conn)

    svc = MetadataService(connection_provider=lambda _root: conn)
    file_path = str(tmp_path / "test.txt")
    svc.set_notes(lib, file_path, "hello")

    assert len(events) == 1
    assert events[0].file_path == file_path
    conn.close()


def test_metadata_service_publishes_urls_changed(tmp_path, monkeypatch):
    """MetadataService.add_url() publishes UrlsChanged."""
    from AssetsManager.application.metadata_service import MetadataService
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import UrlsChanged

    bus = EventBus()
    events = []
    bus.subscribe(UrlsChanged, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    lib = str(tmp_path)
    from AssetsManager.application.library_service import LibraryService
    LibraryService().open_session(lib)

    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(database._SCHEMA)
    migrate(conn)

    svc = MetadataService(connection_provider=lambda _root: conn)
    file_path = str(tmp_path / "test.txt")
    svc.add_url(lib, file_path, "https://example.com")

    assert len(events) == 1
    assert events[0].file_path == file_path
    assert "https://example.com" in events[0].new_urls
    conn.close()


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
    """FileOperationService.create_folder() publishes FileCreated."""
    from AssetsManager.application.file_operation_service import FileOperationService
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import FileCreated

    bus = EventBus()
    events = []
    bus.subscribe(FileCreated, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    svc = FileOperationService()
    svc.create_folder(tmp_path, "MyFolder")

    assert len(events) == 1
    assert events[0].is_dir is True
    assert "MyFolder" in events[0].path


def test_file_operation_publishes_file_renamed(tmp_path, monkeypatch):
    """FileOperationService.move() publishes FileRenamed."""
    from AssetsManager.application.file_operation_service import FileOperationService
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import FileRenamed

    (tmp_path / "old.txt").write_text("x")

    bus = EventBus()
    events = []
    bus.subscribe(FileRenamed, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    svc = FileOperationService()
    svc.move(tmp_path / "old.txt", tmp_path / "new.txt")

    assert len(events) == 1
    assert "old.txt" in events[0].old_path
    assert "new.txt" in events[0].new_path


def test_file_operation_publishes_file_deleted(tmp_path, monkeypatch):
    """FileOperationService.delete_permanent() publishes FileDeleted."""
    from AssetsManager.application.file_operation_service import FileOperationService
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import FileDeleted

    (tmp_path / "doomed.txt").write_text("x")

    bus = EventBus()
    events = []
    bus.subscribe(FileDeleted, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    svc = FileOperationService()
    svc.delete_permanent([tmp_path / "doomed.txt"])

    assert len(events) == 1
    assert "doomed.txt" in events[0].path
    assert events[0].is_dir is False


def test_file_operation_publishes_file_copied(tmp_path, monkeypatch):
    """FileOperationService.copy_to_directory() publishes FileCopied."""
    from AssetsManager.application.file_operation_service import FileOperationService
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import FileCopied

    (tmp_path / "source.txt").write_text("x")
    dest = tmp_path / "dest"
    dest.mkdir()

    bus = EventBus()
    events = []
    bus.subscribe(FileCopied, events.append)
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    svc = FileOperationService()
    svc.copy_to_directory([tmp_path / "source.txt"], dest)

    assert len(events) == 1
    assert events[0].source_path == str((tmp_path / "source.txt").resolve())
    assert events[0].destination_path == str((dest / "source.txt").resolve())


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
        assert events[0].old_paths == (str(source.resolve()),)
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
