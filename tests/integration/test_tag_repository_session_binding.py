"""Strict TagRepository / TagService session, root, and transaction contracts."""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from AssetsManager.domain.errors import OperationNotPermitted

from AssetsManager.application import ApplicationBootstrap
from AssetsManager.application.tag_service import TagService
from AssetsManager.domain.event_bus import EventBus
from AssetsManager.domain.events import AssetTagsChanged, TagCatalogChanged
from AssetsManager.repositories.tag_repository import TagRepository


def _asset(root, name: str = "asset.txt"):
    root.mkdir(parents=True, exist_ok=True)
    asset = root / name
    asset.write_text("asset", encoding="utf-8")
    return asset


def _fake_session(root, conn):
    return SimpleNamespace(
        root=root,
        root_str=str(root),
        event_token="fake-session-token",
        connection_for=lambda _root: conn,
        operation=nullcontext,
    )


def test_tag_repository_factory_and_constructor_bind_managed_session(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        conn = session.connection_for(session.root)
        asset = _asset(session.root)
        factory_repo = TagRepository.for_session(session, library_root=session.root)
        constructor_repo = TagRepository(
            conn, library_root=session.root, session=session
        )

        factory_repo.add_tag(asset, "hero")

        assert factory_repo._session is session
        assert constructor_repo._session is session
        assert factory_repo._conn is conn
        assert constructor_repo.get_tags(asset) == ["hero"]
    finally:
        bootstrap.library_service.close()


@pytest.mark.parametrize("entry_point", ["factory", "constructor"])
def test_tag_repository_rejects_unmanaged_canonical_connection(entry_point, tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    raw = sqlite3.connect(":memory:")
    try:
        with pytest.raises((RuntimeError, ValueError), match=r"(?i)(managed|unmanaged|ownership|does not belong)"):
            if entry_point == "factory":
                fake_context = SimpleNamespace(
                    root_identity=session.context.root_identity,
                )
                # Keep the real-session marker but inject an unmanaged context
                # connection through a minimal LibrarySession-shaped object only
                # to exercise the strict owner boundary.
                from AssetsManager.application.context import LibraryContext, LibrarySession

                context = LibraryContext(
                    root=session.root,
                    data_dir=session.data_dir,
                    thumb_dir=session.thumb_dir,
                    db_conn=raw,
                    tag_store=SimpleNamespace(),
                    project_data=SimpleNamespace(),
                    root_key=session.context.root_key,
                )
                unmanaged_session = LibrarySession.from_context(context)
                assert fake_context.root_identity == unmanaged_session.context.root_identity
                TagRepository.for_session(unmanaged_session)
            else:
                TagRepository(raw, session=session)
    finally:
        raw.close()
        bootstrap.library_service.close()


def test_tag_repository_rejects_fake_session_even_when_connection_is_managed(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        conn = session.connection_for(session.root)
        fake = _fake_session(session.root, conn)
        with pytest.raises(TypeError, match="registered LibrarySession"):
            TagRepository.for_session(fake)
        with pytest.raises(TypeError, match="registered LibrarySession"):
            TagRepository(conn, session=fake)
    finally:
        bootstrap.library_service.close()


def test_tag_service_factory_rejects_fake_session_even_when_connection_is_managed(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        fake = _fake_session(session.root, session.connection_for(session.root))
        with pytest.raises(TypeError, match="real LibrarySession"):
            TagService.for_session(fake)
    finally:
        bootstrap.library_service.close()


def test_tag_repository_rejects_foreign_root_and_explicit_root_mismatch(tmp_path):
    bootstrap = ApplicationBootstrap()
    first = bootstrap.library_service.open_session(tmp_path / "first")
    second = bootstrap.library_service.open_session(tmp_path / "second")
    try:
        foreign_conn = second.connection_for(second.root)
        with pytest.raises(ValueError, match="does not belong"):
            TagRepository(foreign_conn, session=first)
        with pytest.raises(ValueError, match="does not match"):
            TagRepository.for_session(first, library_root=second.root)
    finally:
        bootstrap.library_service.close()


def test_tag_repository_same_session_is_idempotent_and_second_session_is_rejected(tmp_path):
    bootstrap = ApplicationBootstrap()
    first = bootstrap.library_service.open_session(tmp_path / "library")
    second = bootstrap.library_service.open_session(tmp_path / "other")
    try:
        repo = TagRepository.for_session(first)
        repo._bind_session(first)
        with pytest.raises(RuntimeError, match="already bound"):
            repo._bind_session(second)
    finally:
        bootstrap.library_service.close()


def test_tag_repository_cannot_bind_after_raw_operation_started(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        conn = session.connection_for(session.root)
        repo = TagRepository(conn)
        repo.get_all_tags()
        with pytest.raises(RuntimeError, match="raw operations"):
            repo._bind_session(session)
    finally:
        bootstrap.library_service.close()


def test_bound_tag_writes_preserve_caller_outer_transaction(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        repo = TagRepository.for_session(session)
        asset = _asset(session.root)
        conn = repo._conn
        conn.execute("CREATE TABLE caller_data (value TEXT NOT NULL)")
        conn.commit()

        conn.execute("BEGIN")
        conn.execute("INSERT INTO caller_data VALUES ('keep-me')")
        repo.add_tag(asset, "inside-outer")

        assert conn.in_transaction is True
        assert repo.get_tags(asset) == ["inside-outer"]
        assert conn.execute("SELECT * FROM caller_data").fetchall() == [("keep-me",)]

        conn.rollback()
        assert repo.get_tags(asset) == []
        assert conn.execute("SELECT * FROM caller_data").fetchall() == []
    finally:
        bootstrap.library_service.close()


def test_tag_migration_same_path_and_subtree_target_are_safe(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        repo = TagRepository.for_session(session)
        source = session.root / "source"
        child = source / "child.txt"
        source.mkdir(parents=True)
        child.write_text("asset", encoding="utf-8")
        repo.add_tag(source, "root")
        repo.add_tag(child, "child")

        assert repo.migrate_path(source, source) == 0
        assert repo.get_tags(source) == ["root"]
        with pytest.raises(ValueError, match="inside source subtree"):
            repo.migrate_path(source, source / "nested")
        assert repo.get_tags(source) == ["root"]
        assert repo.get_tags(child) == ["child"]
    finally:
        bootstrap.library_service.close()


def test_bound_tag_service_rejects_explicit_unmanaged_connection(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    raw = sqlite3.connect(":memory:")
    try:
        service = TagService(connection_provider=session.connection_for, session=session)
        asset = _asset(session.root)
        # Binding-mismatch now raises the domain type so the LAN error
        # contract maps it (minimal ValueError migration); message preserved.
        with pytest.raises(OperationNotPermitted, match="does not belong to the bound LibrarySession"):
            service.get_tags(session.root, asset, db_conn=raw)
    finally:
        raw.close()
        bootstrap.library_service.close()


def test_bound_tag_service_rejects_caller_outer_transaction_before_events(tmp_path, monkeypatch):
    import AssetsManager.domain.event_bus as event_bus_module

    bus = EventBus()
    events: list[object] = []
    for event_type in (AssetTagsChanged, TagCatalogChanged):
        bus.subscribe(event_type, events.append)
    monkeypatch.setattr(event_bus_module, "_instance", bus)

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        service = TagService(connection_provider=session.connection_for, session=session)
        asset = _asset(session.root)
        conn = session.connection_for(session.root)
        conn.execute("BEGIN")

        with pytest.raises(RuntimeError, match="clean transaction boundary"):
            service.add_tag(session.root, asset, "hero")

        assert conn.in_transaction is True
        assert service.get_tags(session.root, asset) == []
        assert events == []
        conn.rollback()
    finally:
        bootstrap.library_service.close()



def test_bound_tag_service_remove_file_publishes_empty_asset_state(tmp_path, monkeypatch):
    import AssetsManager.domain.event_bus as event_bus_module

    bus = EventBus()
    scoped: list[object] = []
    catalogs: list[object] = []
    bus.subscribe(AssetTagsChanged, scoped.append)
    bus.subscribe(TagCatalogChanged, catalogs.append)
    monkeypatch.setattr(event_bus_module, "_instance", bus)

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        service = TagService(connection_provider=session.connection_for, session=session)
        asset = _asset(session.root)
        service.add_tag(session.root, asset, "hero")
        scoped.clear()
        catalogs.clear()

        service.remove_file(session.root, asset)

        assert len(scoped) == len(catalogs) == 1
        assert scoped[0].file_path == str(asset.resolve())
        assert scoped[0].session_token == session.event_token
        assert scoped[0].new_tags == ()
    finally:
        bootstrap.library_service.close()


def test_bound_tag_service_metadata_mutations_publish_catalog_event(tmp_path, monkeypatch):
    import AssetsManager.domain.event_bus as event_bus_module

    bus = EventBus()
    catalogs: list[object] = []
    bus.subscribe(TagCatalogChanged, catalogs.append)
    monkeypatch.setattr(event_bus_module, "_instance", bus)

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        service = TagService(connection_provider=session.connection_for, session=session)
        service.set_tag_metadata(session.root, "hero", color="#fff")
        assert len(catalogs) == 1
        assert catalogs[0].session_token == session.event_token

        service.set_tag_metadata(session.root, "hero", color="#fff")
        assert len(catalogs) == 1

        service.delete_tag_metadata(session.root, "hero")
        assert len(catalogs) == 2
        assert service.get_tag_metadata(session.root, "hero") is None
    finally:
        bootstrap.library_service.close()


def test_delete_tag_removes_orphaned_tag_metadata_in_same_contract(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        repo = TagRepository.for_session(session)
        repo.add_tag(_asset(session.root), "hero")
        repo.set_tag_metadata("hero", color="#fff")
        assert repo.delete_tag("hero") == 1
        assert repo.get_tag_metadata("hero") is None
    finally:
        bootstrap.library_service.close()
