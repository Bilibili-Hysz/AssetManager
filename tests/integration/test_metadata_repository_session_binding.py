"""Strict MetadataRepository and MetadataService session/root contracts."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from AssetsManager.domain.errors import OperationNotPermitted

from AssetsManager.application import ApplicationBootstrap
from AssetsManager.application.metadata_service import MetadataService
from AssetsManager.domain.event_bus import EventBus
from AssetsManager.domain.events import AssetNotesChanged, AssetUrlsChanged
from AssetsManager.repositories.metadata_repository import MetadataRepository


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


def _unmanaged_real_session(root, conn):
    from AssetsManager.application.context import LibraryContext, LibrarySession
    from AssetsManager.core.path_resolver import root_identity

    identity = root_identity(root, strict=False)
    context = LibraryContext(
        root=identity.display_path,
        data_dir=identity.display_path / ".data",
        thumb_dir=identity.display_path / ".thumbs",
        db_conn=conn,
        tag_store=SimpleNamespace(),
        project_data=SimpleNamespace(),
        root_key=identity.map_key,
    )
    return LibrarySession.from_context(context)


def test_metadata_repository_factory_and_constructor_bind_managed_session(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        bootstrap.runtime_for(session)
        conn = session.connection_for(session.root)
        asset = _asset(session.root)
        factory_repo = MetadataRepository.for_session(
            session, library_root=session.root
        )
        constructor_repo = MetadataRepository(
            conn, library_root=session.root, session=session
        )

        factory_repo.set_notes(asset, "factory")

        assert factory_repo._session is session
        assert constructor_repo._session is session
        assert factory_repo._conn is conn
        assert constructor_repo._conn is conn
        assert constructor_repo.get_notes(asset) == "factory"
        factory_repo.set_library_total_size(session.root, 123)
        assert constructor_repo.get_library_total_size(session.root) == 123
    finally:
        bootstrap.library_service.close()


@pytest.mark.parametrize("entry_point", ["factory", "constructor"])
def test_metadata_repository_rejects_unmanaged_canonical_connection(
    entry_point, tmp_path
):
    conn = sqlite3.connect(":memory:")
    session = _unmanaged_real_session(tmp_path / "library", conn)
    try:
        with pytest.raises(RuntimeError, match=r"(?i)(managed|unmanaged|ownership)"):
            if entry_point == "factory":
                MetadataRepository.for_session(session)
            else:
                MetadataRepository(conn, session=session)
    finally:
        session.close()
        conn.close()


def test_fake_session_cannot_borrow_a_real_managed_metadata_connection(tmp_path):
    bootstrap = ApplicationBootstrap()
    real_session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        conn = real_session.connection_for(real_session.root)
        fake = _fake_session(real_session.root, conn)
        with pytest.raises(TypeError, match="registered LibrarySession"):
            MetadataRepository.for_session(fake)
        with pytest.raises(TypeError, match="registered LibrarySession"):
            MetadataRepository(conn, session=fake)
        with pytest.raises(TypeError, match="real LibrarySession"):
            MetadataService(connection_provider=fake.connection_for, session=fake)
    finally:
        bootstrap.library_service.close()


def test_metadata_repository_rejects_foreign_managed_connection_and_root(tmp_path):
    bootstrap = ApplicationBootstrap()
    first = bootstrap.library_service.open_session(tmp_path / "first")
    second = bootstrap.library_service.open_session(tmp_path / "second")
    try:
        foreign_conn = first.connection_for(first.root)
        with pytest.raises(ValueError, match=r"(?i)(different|belong|root)"):
            MetadataRepository(foreign_conn, session=second)

        second_conn = second.connection_for(second.root)
        with pytest.raises(ValueError, match=r"(?i)(match|root|different)"):
            MetadataRepository(
                second_conn,
                library_root=first.root,
                session=second,
            )
    finally:
        bootstrap.library_service.close()


def test_bound_metadata_repository_rejects_paths_outside_root_before_sql(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        repo = MetadataRepository.for_session(session)
        asset = _asset(session.root)
        repo.set_notes(asset, "inside")
        statements: list[str] = []
        repo._conn.set_trace_callback(statements.append)
        statements.clear()

        operations = (
            lambda: repo.get_notes(outside / "asset.txt"),
            lambda: repo.set_notes(outside / "asset.txt", "blocked"),
            lambda: repo.migrate_path(asset, outside / "asset.txt"),
            lambda: repo.get_library_total_size(outside),
        )
        for operation in operations:
            with pytest.raises(ValueError, match=r"(?i)(under library_root|bound library root)"):
                operation()

        assert statements == []
    finally:
        bootstrap.library_service.close()


def test_metadata_repository_rebinding_and_closing_publication_contract(
    tmp_path, monkeypatch
):
    from AssetsManager.application.context import LibrarySession

    bootstrap = ApplicationBootstrap()
    first = bootstrap.library_service.open_session(tmp_path / "first")
    second = bootstrap.library_service.open_session(tmp_path / "second")
    try:
        repository = MetadataRepository.for_session(first)
        assert repository._bind_session(first) is None
        with pytest.raises(ValueError, match=r"(?i)(match|root)"):
            repository._bind_session(first, library_root=second.root)
        with pytest.raises(RuntimeError, match=r"(?i)(already bound|another session)"):
            repository._bind_session(second)

        conn = first.connection_for(first.root)

        def reject_publication(self, _callback):
            raise RuntimeError("Cannot publish services for a closing LibrarySession")

        monkeypatch.setattr(
            LibrarySession, "_publish_while_live", reject_publication
        )
        unbound = MetadataRepository(conn)
        with pytest.raises(RuntimeError, match="closing LibrarySession"):
            unbound._bind_session(first)
        assert unbound._session is None
        assert unbound._library_root is None
    finally:
        bootstrap.library_service.close()


def test_metadata_repository_cannot_bind_after_raw_operation_started(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        conn = session.connection_for(session.root)
        repository = MetadataRepository(conn)
        assert repository.list_file_metadata() == []

        with pytest.raises(RuntimeError, match="raw operations have started"):
            repository._bind_session(session)
        assert repository._session is None
    finally:
        bootstrap.library_service.close()


def test_metadata_repository_close_rejects_read_write_and_delete_before_sql(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        repo = MetadataRepository.for_session(session)
        asset = _asset(session.root)
        repo.set_notes(asset, "before-close")
        statements: list[str] = []
        repo._conn.set_trace_callback(statements.append)
        statements.clear()

        session.close()

        for operation in (
            lambda: repo.get_notes(asset),
            lambda: repo.set_notes(asset, "after-close"),
            lambda: repo.delete_path(asset, commit=False),
            repo.list_file_metadata,
        ):
            with pytest.raises(RuntimeError, match="closed LibrarySession"):
                operation()
        assert statements == []
    finally:
        bootstrap.library_service.close()


def test_in_flight_metadata_repository_read_holds_close_lease(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    release_operation = threading.Event()
    worker: threading.Thread | None = None
    closer: threading.Thread | None = None
    worker_errors: list[BaseException] = []
    close_errors: list[BaseException] = []
    try:
        repo = MetadataRepository.for_session(session)
        asset = _asset(session.root)
        repo.set_notes(asset, "note")
        operation_entered = threading.Event()
        begin_close = threading.Event()
        close_done = threading.Event()

        def trace(statement: str) -> None:
            if operation_entered.is_set() or not statement.lstrip().upper().startswith("SELECT"):
                return
            operation_entered.set()
            if not release_operation.wait(timeout=5):
                worker_errors.append(TimeoutError("metadata read was not released"))

        original_begin_close = session._begin_close

        def instrumented_begin_close() -> None:
            original_begin_close()
            begin_close.set()

        object.__setattr__(session, "_begin_close", instrumented_begin_close)
        repo._conn.set_trace_callback(trace)

        def run_read() -> None:
            try:
                repo.get_notes(asset)
            except BaseException as exc:  # pragma: no cover - asserted below
                worker_errors.append(exc)

        def close_session() -> None:
            try:
                session.close()
            except BaseException as exc:  # pragma: no cover - asserted below
                close_errors.append(exc)
            finally:
                close_done.set()

        worker = threading.Thread(target=run_read)
        worker.start()
        assert operation_entered.wait(timeout=5)
        closer = threading.Thread(target=close_session)
        closer.start()
        assert begin_close.wait(timeout=5)
        assert close_done.wait(timeout=0.1) is False

        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            repo.get_notes(asset)

        release_operation.set()
        worker.join(timeout=5)
        closer.join(timeout=5)
        assert not worker.is_alive()
        assert not closer.is_alive()
        assert worker_errors == []
        assert close_errors == []
    finally:
        release_operation.set()
        if worker is not None:
            worker.join(timeout=5)
        if closer is not None:
            closer.join(timeout=5)
        bootstrap.library_service.close()


def test_same_root_reopen_invalidates_old_metadata_repository(tmp_path):
    bootstrap = ApplicationBootstrap()
    root = tmp_path / "library"
    first = bootstrap.library_service.open_session(root)
    try:
        asset = _asset(root)
        old_repo = MetadataRepository.for_session(first)
        old_repo.set_notes(asset, "persisted")
        old_conn = old_repo._conn
        first.close()

        second = bootstrap.library_service.open_session(root)
        try:
            new_repo = MetadataRepository.for_session(second)
            assert new_repo._conn is not old_conn
            assert new_repo.get_notes(asset) == "persisted"
            new_repo.set_notes(asset, "new-session")
            with pytest.raises(RuntimeError, match="closed LibrarySession"):
                old_repo.get_notes(asset)
        finally:
            second.close()
    finally:
        bootstrap.library_service.close()


def test_bound_metadata_delete_without_commit_preserves_outer_transaction(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        repo = MetadataRepository.for_session(session)
        asset = _asset(session.root)
        repo.set_notes(asset, "keep-on-rollback")
        conn = repo._conn
        conn.execute("CREATE TABLE caller_data (value TEXT NOT NULL)")
        conn.commit()

        conn.execute("BEGIN")
        conn.execute("INSERT INTO caller_data VALUES ('keep-me')")
        assert repo.delete_path(asset, commit=False) == 1
        assert conn.in_transaction is True
        assert repo.get_notes(asset) == ""

        conn.rollback()
        assert repo.get_notes(asset) == "keep-on-rollback"
        assert conn.execute("SELECT * FROM caller_data").fetchall() == []
    finally:
        bootstrap.library_service.close()


def test_bound_metadata_writes_preserve_caller_outer_transaction(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        repo = MetadataRepository.for_session(session)
        asset = _asset(session.root)
        repo.set_notes(asset, "original")
        conn = repo._conn
        conn.execute("CREATE TABLE caller_data (value TEXT NOT NULL)")
        conn.commit()

        conn.execute("BEGIN")
        conn.execute("INSERT INTO caller_data VALUES ('keep-me')")
        repo.set_notes(asset, "inside-outer")

        assert conn.in_transaction is True
        assert repo.get_notes(asset) == "inside-outer"
        assert conn.execute("SELECT * FROM caller_data").fetchall() == [("keep-me",)]

        conn.rollback()
        assert repo.get_notes(asset) == "original"
        assert conn.execute("SELECT * FROM caller_data").fetchall() == []
    finally:
        bootstrap.library_service.close()


def test_metadata_migrate_guards_overlap_and_rolls_back_partial_failure(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        repo = MetadataRepository.for_session(session)
        source = session.root / "source"
        child = source / "child.txt"
        source.mkdir(parents=True)
        child.write_text("child", encoding="utf-8")
        repo.set_notes(source, "root")
        repo.set_notes(child, "child")

        assert repo.migrate_path(source, source) == 0
        assert repo.get_notes(source) == "root"
        with pytest.raises(ValueError, match="inside source subtree"):
            repo.migrate_path(source, source / "nested")
        assert repo.get_notes(source) == "root"
        assert repo.get_notes(child) == "child"

        conn = repo._conn
        conn.execute(
            "CREATE TRIGGER fail_metadata_migrate BEFORE INSERT ON file_meta "
            "WHEN NEW.file_path LIKE '%blocked-target%' "
            "AND NEW.file_path LIKE '%child.txt' "
            "BEGIN SELECT RAISE(ABORT, 'blocked metadata migrate'); END"
        )
        conn.execute("CREATE TABLE caller_data (value TEXT NOT NULL)")
        conn.commit()
        conn.execute("BEGIN")
        conn.execute("INSERT INTO caller_data VALUES ('keep-me')")

        with pytest.raises(sqlite3.IntegrityError, match="blocked metadata migrate"):
            repo.migrate_path(source, session.root / "blocked-target")

        assert conn.in_transaction is True
        assert repo.get_notes(source) == "root"
        assert repo.get_notes(child) == "child"
        assert repo.get_notes(session.root / "blocked-target") == ""
        assert conn.execute("SELECT * FROM caller_data").fetchall() == [("keep-me",)]
        conn.rollback()
    finally:
        bootstrap.library_service.close()


def test_cached_file_count_zero_is_a_valid_cached_value(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        repo = MetadataRepository.for_session(session)
        empty = session.root / "empty"
        empty.mkdir(parents=True)
        repo.set_cached_file_count(empty, 0)

        # A count written without a directory mtime is a permanent miss.
        assert repo.get_cached_file_count(empty) is None
        assert repo.batch_get_cached_file_counts([str(empty)]) == {}

        repo.set_cached_file_count(empty, 0, empty.stat().st_mtime)
        assert repo.get_cached_file_count(empty) == 0
        assert repo.batch_get_cached_file_counts([str(empty)]) == {
            str(empty.resolve()): 0
        }
    finally:
        bootstrap.library_service.close()


def test_metadata_service_uses_bound_repository_and_rejects_foreign_provider(tmp_path):
    bootstrap = ApplicationBootstrap()
    first = bootstrap.library_service.open_session(tmp_path / "first")
    second = bootstrap.library_service.open_session(tmp_path / "second")
    try:
        first_asset = _asset(first.root)
        service = MetadataService(
            connection_provider=first.connection_for,
            session=first,
        )
        repository = service._repo(first.root)
        assert repository._session is first
        service.set_notes(first.root, first_asset, "bound")
        assert service.get_notes(first.root, first_asset) == "bound"

        foreign_conn = second.connection_for(second.root)
        # Binding mismatches now raise the domain type so the LAN error
        # contract maps them (minimal ValueError migration); message preserved.
        with pytest.raises(OperationNotPermitted, match=r"(?i)(provider|LibrarySession)"):
            MetadataService(
                connection_provider=lambda _root: foreign_conn,
                session=first,
            )

        with pytest.raises(OperationNotPermitted, match=r"(?i)(library_root|LibrarySession)"):
            service.get_notes(second.root, _asset(second.root))
    finally:
        bootstrap.library_service.close()


def test_bound_metadata_event_mutations_reject_caller_owned_transactions(
    tmp_path, monkeypatch
):
    import AssetsManager.domain.event_bus as event_bus_module

    bus = EventBus()
    events: list[object] = []
    for event_type in (AssetNotesChanged, AssetUrlsChanged):
        bus.subscribe(event_type, events.append)
    monkeypatch.setattr(event_bus_module, "_instance", bus)

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        service = bootstrap.runtime_for(session).services.metadata_service
        asset = _asset(session.root)
        conn = session.connection_for(session.root)

        conn.execute("BEGIN")
        with pytest.raises(RuntimeError, match="clean transaction boundary"):
            service.set_notes(session.root, asset, "must-not-publish")
        assert conn.in_transaction is True
        assert service.get_notes(session.root, asset) == ""
        assert events == []
        conn.rollback()

        conn.execute("BEGIN")
        with pytest.raises(RuntimeError, match="clean transaction boundary"):
            service.add_url(session.root, asset, "https://example.test")
        assert conn.in_transaction is True
        assert service.get_urls(session.root, asset) == []
        assert events == []
        conn.rollback()
    finally:
        bootstrap.library_service.close()


def test_metadata_service_close_prevents_mutation_and_event_publication(
    tmp_path, monkeypatch
):
    import AssetsManager.domain.event_bus as event_bus_module

    bus = EventBus()
    scoped_events: list[object] = []
    bus.subscribe(AssetNotesChanged, scoped_events.append)
    monkeypatch.setattr(event_bus_module, "_instance", bus)

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        service = bootstrap.runtime_for(session).services.metadata_service
        asset = _asset(session.root)
        service.set_notes(session.root, asset, "before-close")
        scoped_events.clear()
        conn = session.connection_for(session.root)
        statements: list[str] = []
        conn.set_trace_callback(statements.append)
        statements.clear()

        session.close()

        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            service.set_notes(session.root, asset, "after-close")
        assert statements == []
        assert scoped_events == []
    finally:
        bootstrap.library_service.close()
