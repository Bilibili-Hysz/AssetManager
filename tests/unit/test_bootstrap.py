"""Tests for ApplicationBootstrap."""
import os
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.application.context import LibraryContext, LibrarySession
from AssetsManager.application.library_export_service import LibraryExportService
from AssetsManager.application.library_service import LibraryService
from AssetsManager.application.asset_service import AssetService
from AssetsManager.application.metadata_service import MetadataService
from AssetsManager.application.tag_service import TagService
from AssetsManager.application.file_operation_service import FileOperationService
from AssetsManager.application.thumbnail_service import ThumbnailService
from AssetsManager.application.search_service import SearchService
from AssetsManager.application.project_service import ProjectService
from AssetsManager.application.plugin_service import PluginService
from AssetsManager.application.undo_service import UndoService
from AssetsManager.application.asset_index_service import AssetIndexService
from AssetsManager.core.project_data import ProjectData
from AssetsManager.domain.errors import OperationNotPermitted
from AssetsManager.core.tag_store import TagStore


class TestApplicationBootstrap:

    def test_build_services_uses_context_identity_when_root_key_is_omitted(
        self, opened_session
    ):
        bootstrap, canonical = opened_session
        root = canonical.root
        conn = canonical.context.db_conn
        context = LibraryContext(
            root=root,
            data_dir=canonical.context.data_dir,
            thumb_dir=canonical.context.thumb_dir,
            db_conn=conn,
            tag_store=TagStore(str(root), db_conn=conn),
            project_data=ProjectData(str(root), db_conn=conn),
        )
        manual = LibrarySession.from_context(context)
        try:
            services = bootstrap._build_services(manual)
            assert services.session is manual
            assert context.root_identity.map_key
        finally:
            manual.close()
            bootstrap.library_service.close()


    @pytest.mark.parametrize("direct_close", [True, False], ids=["callback", "service"])
    def test_same_thread_close_rejects_before_lifecycle_mutation(
        self, opened_session, direct_close
    ):
        bootstrap, session = opened_session
        root = session.root
        scoped = bootstrap.runtime_for(session).services
        scoped.undo_service.record_rename("old", "new")
        notifications = []
        bootstrap.library_service.add_session_close_listener(notifications.append)
        close = (
            session.close
            if direct_close
            else lambda: bootstrap.library_service.close_session(session)
        )

        with session.operation():
            with pytest.raises(RuntimeError, match="active operation"):
                close()

            assert bootstrap.library_service.current_session is session
            assert bootstrap.library_service.owns_live_session(session)
            assert not session.is_closed
            assert session.connection_for(root).execute("SELECT 1").fetchone() == (1,)
            assert notifications == []
            assert bootstrap.runtime_for(session).services.undo_service is scoped.undo_service
            assert scoped.undo_service.can_undo()

    def test_global_close_serializes_with_selective_close_teardown(
        self, opened_session, monkeypatch
    ):
        bootstrap, session = opened_session
        root = session.root
        service = bootstrap.library_service
        scoped = bootstrap.runtime_for(session).services
        scoped.undo_service.record_rename("old", "new")
        operation_entered = threading.Event()
        release_operation = threading.Event()
        operation_exited = threading.Event()
        selective_done = threading.Event()
        global_done = threading.Event()
        notifications = []
        db_close_calls = []
        reopened = []
        operation_errors = []
        original_db_close = service._db.close
        service.add_session_close_listener(notifications.append)

        def tracked_db_close():
            db_close_calls.append("close")
            original_db_close()

        monkeypatch.setattr(service._db, "close", tracked_db_close)

        def operation():
            try:
                with session.operation():
                    operation_entered.set()
                    assert release_operation.wait(5)
                    assert session.connection_for(root).execute("SELECT 1").fetchone() == (1,)
            except Exception as exc:
                operation_errors.append(exc)
            finally:
                operation_exited.set()

        worker = threading.Thread(target=operation)
        selective = threading.Thread(
            target=lambda: (service.close_session(session), selective_done.set())
        )
        global_close = threading.Thread(target=lambda: (service.close(), global_done.set()))
        reopen = threading.Thread(target=lambda: reopened.append(service.open_session(root)))

        worker.start()
        assert operation_entered.wait(5)
        selective.start()
        for _ in range(100):
            if session.is_closed:
                break
            threading.Event().wait(0.01)
        assert session.is_closed
        global_close.start()
        reopen.start()
        try:
            assert not global_done.wait(0.2)
            assert not reopened
            assert db_close_calls == []
            assert notifications == []
            assert id(session) in bootstrap._runtimes
            assert session.context.db_conn.execute("SELECT 1").fetchone() == (1,)
        finally:
            release_operation.set()

        assert operation_exited.wait(5)
        assert selective_done.wait(5)
        assert global_done.wait(5)
        worker.join(5)
        selective.join(5)
        global_close.join(5)
        reopen.join(5)

        assert notifications.count(session) == 1
        assert operation_errors == []
        assert id(session) not in bootstrap._runtimes
        assert not scoped.undo_service.undo_dir.exists()
        assert db_close_calls == ["close"]
        assert len(reopened) == 1
        assert reopened[0] is not session
        reopened[0].connection_for(root).execute("SELECT 1")

    def test_global_close_inside_operation_rejects_before_mutation(
        self, opened_session, monkeypatch
    ):
        bootstrap, session = opened_session
        root = session.root
        service = bootstrap.library_service
        scoped = bootstrap.runtime_for(session).services
        scoped.undo_service.record_rename("old", "new")
        notifications = []
        db_close_calls = []
        service.add_session_close_listener(notifications.append)
        monkeypatch.setattr(service._db, "close", lambda: db_close_calls.append("close"))

        with session.operation():
            with pytest.raises(RuntimeError, match="active operation"):
                service.close()

            assert service.current_session is session
            assert service.owns_live_session(session)
            assert not session.is_closed
            assert session.connection_for(root).execute("SELECT 1").fetchone() == (1,)
            assert notifications == []
            assert db_close_calls == []
            assert bootstrap.runtime_for(session).services.undo_service is scoped.undo_service
            assert scoped.undo_service.can_undo()

    def test_global_close_inside_draining_operation_rejects_without_deadlock(
        self, opened_session
    ):
        bootstrap, session = opened_session
        service = bootstrap.library_service
        selective_done = threading.Event()

        with session.operation():
            selective = threading.Thread(
                target=lambda: (service.close_session(session), selective_done.set())
            )
            selective.start()
            for _ in range(100):
                if session.is_closed:
                    break
                threading.Event().wait(0.01)
            assert session.is_closed

            with pytest.raises(RuntimeError, match="active operation"):
                service.close()
            assert not selective_done.is_set()
            assert session.context.db_conn.execute("SELECT 1").fetchone() == (1,)

        assert selective_done.wait(5)
        selective.join(5)

    def test_bootstrap_registers_only_lifecycle_services(self):
        """The container registers only application-lifetime services.

        Per-session services require a live ``LibrarySession`` and are
        constructed in ``_build_services`` / the lazy LAN projection, so the
        container never registers or resolves them.
        """
        from AssetsManager.core.database import DatabaseManager

        bootstrap = ApplicationBootstrap()
        container = bootstrap.container

        assert container.has(DatabaseManager)
        assert container.has(LibraryService)
        assert container.has(PluginService)
        assert set(container.registered_types()) == {
            DatabaseManager,
            LibraryService,
            PluginService,
        }

    def test_container_rejects_session_scoped_service_resolution(self):
        """Resolving a session-scoped service from the container fails closed."""
        bootstrap = ApplicationBootstrap()
        container = bootstrap.container

        for service_type in (
            AssetService,
            MetadataService,
            TagService,
            FileOperationService,
            ThumbnailService,
            SearchService,
            AssetIndexService,
            UndoService,
        ):
            assert not container.has(service_type)
            with pytest.raises(KeyError, match="Service not registered"):
                container.resolve(service_type)

    def test_auth_share_not_registered(self):
        """AuthService/ShareService require db_conn+token_secret and are NOT in bootstrap."""
        from AssetsManager.application.auth_service import AuthService
        from AssetsManager.application.share_service import ShareService
        bootstrap = ApplicationBootstrap()
        assert not bootstrap.container.has(AuthService)
        assert not bootstrap.container.has(ShareService)

    def test_resolve_returns_singleton(self):
        bootstrap = ApplicationBootstrap()
        a = bootstrap.resolve(LibraryService)
        b = bootstrap.resolve(LibraryService)
        assert a is b

    def test_library_service_accessor(self):
        bootstrap = ApplicationBootstrap()
        assert isinstance(bootstrap.library_service, LibraryService)

    def test_custom_container(self):
        from AssetsManager.di import ServiceContainer
        custom = ServiceContainer()
        bootstrap = ApplicationBootstrap(container=custom)
        assert bootstrap.container is custom
        assert custom.has(LibraryService)

    def test_discover_plugins_returns_empty_for_no_plugins(self, tmp_path):
        bootstrap = ApplicationBootstrap()
        # Override search paths to empty so no plugins are found
        svc = bootstrap.resolve(PluginService)
        result = svc.discover(search_paths=[tmp_path / "nonexistent"])
        assert result == []

    def test_plugin_host_context_initially_none(self):
        bootstrap = ApplicationBootstrap()
        assert bootstrap.plugin_host_context is None
        assert bootstrap.plugin_service is None

    def test_discover_plugins_sets_properties(self, tmp_path):
        bootstrap = ApplicationBootstrap()
        bootstrap.discover_plugins()
        # After discovery, plugin_service should be set (even if no plugins found)
        assert bootstrap.plugin_service is not None

    def test_runtime_for_returns_scoped_services(self, opened_session):
        bootstrap, session = opened_session
        scoped = bootstrap.runtime_for(session).services
        lan_services = scoped.lan_services

        assert scoped.session is session
        assert isinstance(lan_services.asset_service, AssetService)
        assert lan_services.asset_service._session_token == session.event_token
        assert lan_services.asset_service._directory_cache._conn is session.connection_for(session.root)
        assert isinstance(scoped.metadata_service, MetadataService)
        assert isinstance(scoped.tag_service, TagService)
        assert isinstance(lan_services.project_service, ProjectService)
        assert isinstance(scoped.thumbnail_service, ThumbnailService)
        assert isinstance(lan_services.search_service, SearchService)
        assert isinstance(scoped.file_operation_service, FileOperationService)
        assert isinstance(scoped.undo_service, UndoService)
        assert isinstance(scoped.plugin_service, PluginService)
        assert isinstance(scoped.asset_index_service, AssetIndexService)

    def test_runtime_for_injects_explicit_performance_recorder(self, tmp_path):
        from AssetsManager.core.performance import PerformanceRecorder

        root = tmp_path / "library"
        root.mkdir()
        recorder = PerformanceRecorder(enabled=True)
        bootstrap = ApplicationBootstrap(performance_recorder=recorder)
        session = bootstrap.library_service.open_session(root)

        scoped = bootstrap.runtime_for(session).services
        lan_services = scoped.lan_services

        assert lan_services.asset_service._performance_recorder is recorder
        assert lan_services.asset_service._session_token == session.event_token

    def test_runtime_for_asset_service_reuses_session_directory_summary_cache(self, tmp_path):
        from AssetsManager.core.performance import PerformanceRecorder

        root = tmp_path / "library"
        child = root / "child"
        child.mkdir(parents=True)
        (child / "asset.png").write_bytes(b"data")
        recorder = PerformanceRecorder(enabled=True)
        bootstrap = ApplicationBootstrap(performance_recorder=recorder)
        session = bootstrap.library_service.open_session(root)
        scoped = bootstrap.runtime_for(session).services
        asset_service = scoped.lan_services.asset_service

        asset_service.list_directory(root, root)
        asset_service.list_directory(root, root)

        summaries = [event for event in recorder.recent() if event.name == "directory.summary"]
        assert [event.attributes["cache_hit"] for event in summaries] == [False, True]

    def test_runtime_for_creates_library_scoped_undo_service(self, tmp_path):
        first_root = tmp_path / "first"
        second_root = tmp_path / "second"
        first_root.mkdir()
        second_root.mkdir()

        bootstrap = ApplicationBootstrap()
        first = bootstrap.runtime_for(bootstrap.library_service.open_session(first_root)).services
        second = bootstrap.runtime_for(bootstrap.library_service.open_session(second_root)).services

        try:
            assert first.undo_service is not second.undo_service
            first.undo_service.record_rename("/tmp/a", "/tmp/b")
            assert first.undo_service.can_undo()
            assert not second.undo_service.can_undo()
        finally:
            first.undo_service.cleanup()
            second.undo_service.cleanup()

    def test_closing_session_discards_only_its_undo_service(self, tmp_path):
        first_root = tmp_path / "first"
        second_root = tmp_path / "second"
        first_root.mkdir()
        second_root.mkdir()
        bootstrap = ApplicationBootstrap()
        first_session = bootstrap.library_service.open_session(first_root)
        second_session = bootstrap.library_service.open_session(second_root)
        first = bootstrap.runtime_for(first_session).services
        second = bootstrap.runtime_for(second_session).services
        first.undo_service.record_rename(str(first_root / "a"), str(first_root / "b"))
        second.undo_service.record_rename(str(second_root / "a"), str(second_root / "b"))

        first_session.close()

        with pytest.raises(RuntimeError, match="closed"):
            first.undo_service.can_undo()
        with pytest.raises(RuntimeError, match="closed"):
            first.undo_service.record_rename("old", "new")
        assert not first.undo_service.undo_dir.exists()
        assert second.undo_service.can_undo()
        assert second.undo_service.undo_dir.exists()

    def test_close_session_cleans_scoped_undo_when_session_cleanup_raises(
        self, tmp_path, monkeypatch
    ):
        first_root = tmp_path / "first"
        second_root = tmp_path / "second"
        first_root.mkdir()
        second_root.mkdir()
        bootstrap = ApplicationBootstrap()
        first_session = bootstrap.library_service.open_session(first_root)
        second_session = bootstrap.library_service.open_session(second_root)
        first = bootstrap.runtime_for(first_session).services
        second = bootstrap.runtime_for(second_session).services
        first.undo_service.record_rename("old-a", "new-a")
        second.undo_service.record_rename("old-b", "new-b")
        notifications = []
        bootstrap.library_service.add_session_close_listener(notifications.append)

        def fail_clear_cache():
            raise RuntimeError("tag cache cleanup failed")

        monkeypatch.setattr(first_session.context.tag_store, "clear_cache", fail_clear_cache)

        with pytest.raises(RuntimeError, match="tag cache cleanup failed"):
            bootstrap.library_service.close_session(first_session)

        assert first_session.is_closed
        assert id(first_session) not in bootstrap._runtimes
        assert not first.undo_service.undo_dir.exists()
        assert notifications == [first_session]
        assert bootstrap.library_service.owns_live_session(second_session)
        assert bootstrap._runtimes[id(second_session)].services.undo_service is second.undo_service
        assert second.undo_service.can_undo()
        assert second.undo_service.undo_dir.exists()

    def test_global_close_notifies_once_when_session_cleanup_raises(
        self, tmp_path, monkeypatch
    ):
        first_root = tmp_path / "first"
        second_root = tmp_path / "second"
        first_root.mkdir()
        second_root.mkdir()
        bootstrap = ApplicationBootstrap()
        contender = ApplicationBootstrap()
        first_session = bootstrap.library_service.open_session(first_root)
        second_session = bootstrap.library_service.open_session(second_root)
        first = bootstrap.runtime_for(first_session).services
        second = bootstrap.runtime_for(second_session).services
        notifications = []
        cleanup_calls = []
        bootstrap.library_service.add_session_close_listener(notifications.append)

        def fail_clear_cache_once():
            cleanup_calls.append("clear_cache")
            if len(cleanup_calls) == 1:
                raise RuntimeError("tag cache cleanup failed")

        monkeypatch.setattr(
            first_session.context.tag_store, "clear_cache", fail_clear_cache_once
        )

        with pytest.raises(RuntimeError, match="tag cache cleanup failed"):
            bootstrap.library_service.close()

        first_key = str(first_session.root)
        assert first_session.is_closed
        assert second_session.is_closed
        assert bootstrap.library_service._sessions[first_key] is first_session
        assert bootstrap.library_service._closing_sessions[first_key] is first_session
        assert first_session.context.db_conn.execute("SELECT 1").fetchone() == (1,)
        with pytest.raises(RuntimeError, match="owned by another LibraryService"):
            contender.library_service.open_session(first_root)
        assert bootstrap._runtimes == {}
        assert not first.undo_service.undo_dir.exists()
        assert not second.undo_service.undo_dir.exists()
        assert notifications.count(first_session) == 1
        assert notifications.count(second_session) == 1

        bootstrap.library_service.close()

        assert cleanup_calls == ["clear_cache", "clear_cache"]
        assert first_key not in bootstrap.library_service._sessions
        assert first_key not in bootstrap.library_service._closing_sessions
        assert notifications.count(first_session) == 1
        assert notifications.count(second_session) == 1
        replacement = contender.library_service.open_session(first_root)
        contender.library_service.close_session(replacement)

    def test_global_close_retains_session_when_runtime_cleanup_fails(
        self, opened_session, monkeypatch
    ):
        bootstrap, session = opened_session
        runtime = bootstrap.runtime_for(session)
        cleanup_calls = []

        def flaky_cleanup():
            cleanup_calls.append("cleanup")
            if len(cleanup_calls) == 1:
                raise RuntimeError("undo cleanup failed")

        monkeypatch.setattr(runtime.services.undo_service, "cleanup", flaky_cleanup)

        with pytest.raises(RuntimeError, match="undo cleanup failed"):
            bootstrap.library_service.close()

        assert bootstrap.library_service.current_session is session
        assert bootstrap._runtimes[id(session)] is runtime
        assert session.context.db_conn.execute("SELECT 1").fetchone() == (1,)

        bootstrap.library_service.close()

        assert cleanup_calls == ["cleanup", "cleanup"]
        assert bootstrap._runtimes == {}

    def test_reopening_same_root_gets_fresh_undo_service(self, opened_session):
        bootstrap, old_session = opened_session
        root = old_session.root
        old = bootstrap.runtime_for(old_session).services
        old.undo_service.record_rename(str(root / "a"), str(root / "b"))

        old_session.close()
        new_session = bootstrap.library_service.open_session(root)
        new = bootstrap.runtime_for(new_session).services

        assert new_session is not old_session
        assert new.undo_service is not old.undo_service
        assert not new.undo_service.can_undo()

    def test_runtime_for_rejects_unmanaged_canonical_provider(self, opened_session, monkeypatch):
        bootstrap, session = opened_session
        unmanaged = sqlite3.connect(":memory:", check_same_thread=False)

        monkeypatch.setattr(
            LibrarySession,
            "connection_for",
            lambda _session, _root=None: unmanaged,
        )
        try:
            with pytest.raises(RuntimeError, match="unmanaged connection"):
                bootstrap.runtime_for(session)
        finally:
            unmanaged.close()

    def test_runtime_for_binds_provider_to_context_connection(self, opened_session):
        bootstrap, session = opened_session
        root = session.root
        scoped = bootstrap.runtime_for(session).services

        assert scoped.metadata_service._connection(root) is session.connection_for(root)
        assert scoped.thumbnail_service._session is session
        assert scoped.thumbnail_service._connection(root) is session.connection_for(root)
        assert scoped.tag_service.list_tags(root) == []

    def test_runtime_for_binds_file_operations_to_session(self, opened_session):
        bootstrap, session = opened_session

        assert bootstrap.runtime_for(session).services.file_operation_service.session is session

    def test_library_session_delegates_context_resources(self, opened_session):
        bootstrap, session = opened_session
        root = session.root
        context = session.context

        assert session.context is context
        assert session.root is context.root
        assert session.root_str == context.root_str
        assert session.data_dir is context.data_dir
        assert session.data_dir_str == context.data_dir_str
        assert session.thumb_dir is context.thumb_dir
        assert session.thumb_dir_str == context.thumb_dir_str
        assert session.connection_for(root) is context.db_conn

    def test_runtime_for_accepts_library_session(self, opened_session, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        bootstrap, session = opened_session
        root = session.root
        scoped = bootstrap.runtime_for(session).services

        assert scoped.session is session
        assert scoped.metadata_service._connection(root) is session.connection_for(root)
        # Binding-mismatch now raises the domain type so the LAN error
        # contract maps it (minimal ValueError migration).
        with pytest.raises(OperationNotPermitted):
            scoped.metadata_service._connection(other)

    def test_runtime_for_rejects_closed_canonical_session(self, opened_session):
        bootstrap, session = opened_session

        session.close()

        with pytest.raises(ValueError, match="live canonical"):
            bootstrap.runtime_for(session).services

    def test_runtime_for_rejects_stale_session_after_reopen(self, opened_session):
        bootstrap, stale = opened_session
        root = stale.root
        stale.close()
        canonical = bootstrap.library_service.open_session(root)

        with pytest.raises(ValueError, match="live canonical"):
            bootstrap.runtime_for(stale).services
        assert bootstrap.runtime_for(canonical).services.session is canonical

    def test_runtime_for_rejects_reconstructed_session(self, opened_session):
        bootstrap, canonical = opened_session
        reconstructed = LibrarySession.from_context(canonical.context)

        with pytest.raises(ValueError, match="live canonical"):
            bootstrap.runtime_for(reconstructed).services

    def test_runtime_for_rejects_session_from_another_service(self, tmp_path):
        root = tmp_path / "library"
        root.mkdir()
        bootstrap = ApplicationBootstrap()
        foreign = LibraryService().open_session(root)

        with pytest.raises(ValueError, match="live canonical"):
            bootstrap.runtime_for(foreign).services

    def test_runtime_for_accepts_exact_live_canonical_session(self, opened_session):
        bootstrap, canonical = opened_session

        assert bootstrap.runtime_for(canonical).services.session is canonical

    def test_repeated_runtime_for_uses_the_exact_canonical_session(self, opened_session):
        bootstrap, canonical = opened_session

        first = bootstrap.runtime_for(canonical).services
        second = bootstrap.runtime_for(canonical).services

        assert first.session is canonical
        assert second.session is canonical

    def test_runtime_for_preserves_session_identity_and_resources(self, opened_session, tmp_path, monkeypatch):
        other = tmp_path / "other"
        other.mkdir()
        bootstrap, session = opened_session
        root = session.root

        def reject_session_reconstruction(cls, context):
            raise AssertionError("runtime_for must not reconstruct a LibrarySession")

        monkeypatch.setattr(type(session), "from_context", classmethod(reject_session_reconstruction))
        scoped = bootstrap.runtime_for(session).services
        lan_services = scoped.lan_services

        assert scoped.session is session
        assert scoped.file_operation_service.session is session
        assert scoped.metadata_service._repo(root)._conn is session.connection_for(root)
        assert scoped.tag_service._connection_provider(root) is session.connection_for(root)
        assert lan_services.project_service._metadata_svc._repo(root)._conn is session.connection_for(root)
        assert lan_services.project_service._tag_svc._connection_provider(root) is session.connection_for(root)
        assert scoped.file_operation_service._library_root is session.root
        # Binding-mismatch now raises the domain type so the LAN error
        # contract maps it (minimal ValueError migration).
        with pytest.raises(OperationNotPermitted):
            scoped.metadata_service._connection(other)


def test_runtime_for_keeps_lan_only_services_lazy_and_thumbnail_eager(opened_session, monkeypatch):
    import AssetsManager.application.bootstrap as bootstrap_module

    calls = {name: 0 for name in ("asset", "project", "search", "thumbnail")}
    original_thumbnail = bootstrap_module.ThumbnailService

    def forbidden_asset(*args, **kwargs):
        calls["asset"] += 1
        raise AssertionError("AssetService must be lazy for Desktop runtime creation")

    def forbidden_project(*args, **kwargs):
        calls["project"] += 1
        raise AssertionError("ProjectService must be lazy for Desktop runtime creation")

    def forbidden_search(*args, **kwargs):
        calls["search"] += 1
        raise AssertionError("SearchService must be lazy for Desktop runtime creation")

    def counted_thumbnail(*args, **kwargs):
        calls["thumbnail"] += 1
        return original_thumbnail(*args, **kwargs)

    monkeypatch.setattr(bootstrap_module, "AssetService", forbidden_asset)
    monkeypatch.setattr(bootstrap_module, "ProjectService", forbidden_project)
    monkeypatch.setattr(bootstrap_module, "SearchService", forbidden_search)
    monkeypatch.setattr(bootstrap_module, "ThumbnailService", counted_thumbnail)

    bootstrap, session = opened_session
    runtime = bootstrap.runtime_for(session)

    assert calls == {"asset": 0, "project": 0, "search": 0, "thumbnail": 1}
    assert runtime.services_snapshot is runtime.services
    assert repr(runtime.services_snapshot)
    assert runtime.services_snapshot == runtime.services_snapshot
    assert calls == {"asset": 0, "project": 0, "search": 0, "thumbnail": 1}


def test_lan_services_success_is_single_flight_and_legacy_properties_share_identity(
    opened_session, monkeypatch
):
    bootstrap, session = opened_session
    calls = []
    entered = threading.Event()
    release = threading.Event()
    bundle = SimpleNamespace(
        asset_service=object(), project_service=object(), search_service=object()
    )

    def build_lan_services(session, *, connection_provider=None):
        calls.append(session)
        entered.set()
        assert release.wait(5)
        return bundle

    monkeypatch.setattr(bootstrap, "_build_lan_services", build_lan_services, raising=False)
    scoped = bootstrap.runtime_for(session).services
    results = []
    errors = []

    def read_bundle():
        try:
            results.append(scoped.lan_services)
        except Exception as exc:  # pragma: no cover - assertion below reports it
            errors.append(exc)

    workers = [threading.Thread(target=read_bundle) for _ in range(8)]
    for worker in workers:
        worker.start()
    assert entered.wait(5)
    release.set()
    for worker in workers:
        worker.join(5)

    assert errors == []
    assert calls == [session]
    assert results and all(result is bundle for result in results)
    assert scoped.lan_services is bundle
    assert scoped.asset_service is bundle.asset_service
    assert scoped.project_service is bundle.project_service
    assert scoped.search_service is bundle.search_service


def test_lan_services_failed_attempt_is_single_flight_and_can_retry(
    opened_session, monkeypatch
):
    import time

    bootstrap, session = opened_session
    first_entered = threading.Event()
    first_release = threading.Event()
    retry_entered = threading.Event()
    retry_release = threading.Event()
    calls = []
    bundle = SimpleNamespace(
        asset_service=object(), project_service=object(), search_service=object()
    )

    def build_lan_services(session, *, connection_provider=None):
        calls.append(session)
        if len(calls) == 1:
            first_entered.set()
            assert first_release.wait(5)
            raise ValueError("first LAN construction failed")
        retry_entered.set()
        assert retry_release.wait(5)
        return bundle

    monkeypatch.setattr(bootstrap, "_build_lan_services", build_lan_services)
    scoped = bootstrap.runtime_for(session).services
    holder = scoped._lan_holder
    snapshot_hash = hash(scoped)
    worker_count = 6

    def wait_for_joined_waiters(expected):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with holder._condition:
                joined = holder._waiters.get(holder._generation, 0)
            if joined == expected:
                return
            time.sleep(0.005)
        pytest.fail(f"only {joined} of {expected} waiters joined the generation")

    first_barrier = threading.Barrier(worker_count + 1)
    first_errors = []

    def read_first_attempt():
        first_barrier.wait()
        try:
            scoped.lan_services
        except Exception as exc:
            first_errors.append(exc)

    first_workers = [
        threading.Thread(target=read_first_attempt) for _ in range(worker_count)
    ]
    for worker in first_workers:
        worker.start()
    first_barrier.wait()
    assert first_entered.wait(5)
    wait_for_joined_waiters(worker_count - 1)
    first_release.set()
    for worker in first_workers:
        worker.join(5)

    assert all(not worker.is_alive() for worker in first_workers)
    assert calls == [session]
    assert len(first_errors) == worker_count
    assert all(isinstance(error, ValueError) for error in first_errors)
    assert hash(scoped) == snapshot_hash

    retry_barrier = threading.Barrier(worker_count + 1)
    retry_results = []
    retry_errors = []

    def read_retry():
        retry_barrier.wait()
        try:
            retry_results.append(scoped.lan_services)
        except Exception as exc:
            retry_errors.append(exc)

    retry_workers = [threading.Thread(target=read_retry) for _ in range(worker_count)]
    for worker in retry_workers:
        worker.start()
    retry_barrier.wait()
    assert retry_entered.wait(5)
    wait_for_joined_waiters(worker_count - 1)
    retry_release.set()
    for worker in retry_workers:
        worker.join(5)

    assert all(not worker.is_alive() for worker in retry_workers)
    assert retry_errors == []
    assert calls == [session, session]
    assert retry_results and all(result is bundle for result in retry_results)
    assert scoped.lan_services is bundle
    assert hash(scoped) == snapshot_hash

def test_lan_services_rejects_recursive_access_and_closed_or_closing_session(
    tmp_path, monkeypatch
):
    bootstrap = ApplicationBootstrap()
    recursive_scoped = {}

    def recursive_factory(_session, *, connection_provider=None):
        return recursive_scoped["scoped"].lan_services

    monkeypatch.setattr(bootstrap, "_build_lan_services", recursive_factory, raising=False)
    session = bootstrap.library_service.open_session(tmp_path / "recursive")
    recursive_scoped["scoped"] = bootstrap.runtime_for(session).services
    with pytest.raises(RuntimeError, match="(?i)recurs|reentr|building"):
        recursive_scoped["scoped"].lan_services

    closed_bootstrap = ApplicationBootstrap()
    closed_session = closed_bootstrap.library_service.open_session(tmp_path / "closed")
    closed_scoped = closed_bootstrap.runtime_for(closed_session).services
    closed_session.close()
    with pytest.raises(RuntimeError, match="closed|closing"):
        closed_scoped.lan_services

    closing_bootstrap = ApplicationBootstrap()
    closing_session = closing_bootstrap.library_service.open_session(tmp_path / "closing")
    closing_scoped = closing_bootstrap.runtime_for(closing_session).services
    closing_session._begin_close()
    with pytest.raises(RuntimeError, match="closed|closing"):
        closing_scoped.lan_services


def test_lan_services_are_isolated_per_library_and_runtime_close_does_not_materialize(
    tmp_path, monkeypatch
):
    bootstrap = ApplicationBootstrap()
    calls = []

    def build_lan_services(session, *, connection_provider=None):
        calls.append(session)
        return SimpleNamespace(
            asset_service=object(), project_service=object(), search_service=object()
        )

    monkeypatch.setattr(bootstrap, "_build_lan_services", build_lan_services, raising=False)
    first_session = bootstrap.library_service.open_session(tmp_path / "first")
    second_session = bootstrap.library_service.open_session(tmp_path / "second")
    first_runtime = bootstrap.runtime_for(first_session)
    second_runtime = bootstrap.runtime_for(second_session)

    assert first_runtime.services.lan_services is not second_runtime.services.lan_services
    assert first_runtime.services.lan_services.asset_service is not second_runtime.services.lan_services.asset_service
    assert first_runtime.services.lan_services.project_service is not second_runtime.services.lan_services.project_service
    assert first_runtime.services.lan_services.search_service is not second_runtime.services.lan_services.search_service
    assert calls == [first_session, second_session]

    untouched_bootstrap = ApplicationBootstrap()
    untouched_session = untouched_bootstrap.library_service.open_session(tmp_path / "untouched")
    untouched_calls = []
    monkeypatch.setattr(
        untouched_bootstrap,
        "_build_lan_services",
        lambda session, connection_provider=None: untouched_calls.append(session),
        raising=False,
    )
    untouched_runtime = untouched_bootstrap.runtime_for(untouched_session)
    untouched_runtime.close()
    assert untouched_calls == []


def test_runtime_bundle_owns_auth_and_share_services(opened_session):
    from AssetsManager.application.auth_service import AuthService
    from AssetsManager.application.share_service import ShareService

    bootstrap, session = opened_session
    scoped = bootstrap.runtime_for(session).services

    assert isinstance(scoped.sharing_services.auth_service, AuthService)
    assert isinstance(scoped.sharing_services.share_service, ShareService)
    assert scoped.sharing_services.auth_service._conn is session.context.db_conn
    assert scoped.sharing_services.share_service._conn is session.context.db_conn
    assert scoped.sharing_services.auth_service is not scoped.sharing_services.share_service
    assert "token_secret" not in repr(scoped.sharing_services)
    assert scoped.sharing_services.token_secret not in repr(scoped.sharing_services)


def test_runtime_bundle_initializes_auth_and_share_tables(opened_session):
    bootstrap, session = opened_session
    bootstrap.runtime_for(session)

    tables = {
        row[0]
        for row in session.context.db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }

    assert "users" in tables
    assert "share_links" in tables


def test_runtime_bundle_services_reject_calls_after_session_close(opened_session):
    bootstrap, session = opened_session
    sharing = bootstrap.runtime_for(session).sharing_services
    session.close()

    with pytest.raises(RuntimeError, match="closed"):
        sharing.auth_service.has_active_users()
    with pytest.raises(RuntimeError, match="closed"):
        sharing.auth_service.generate_user_token(1, "user", "user")
    with pytest.raises(RuntimeError, match="closed"):
        sharing.share_service.list_shares()
    with pytest.raises(RuntimeError, match="closed"):
        sharing.share_service.generate_token("share")

def test_lan_services_close_race_rejects_publication_and_retry(opened_session, monkeypatch):
    bootstrap, session = opened_session
    factory_entered = threading.Event()
    release_factory = threading.Event()
    closing_started = threading.Event()
    close_done = threading.Event()
    calls = []
    read_results = []
    read_errors = []
    close_errors = []

    def build_lan_services(session, *, connection_provider=None):
        calls.append(session)
        factory_entered.set()
        assert release_factory.wait(5)
        return SimpleNamespace(
            asset_service=object(), project_service=object(), search_service=object()
        )

    monkeypatch.setattr(bootstrap, "_build_lan_services", build_lan_services)
    scoped = bootstrap.runtime_for(session).services
    bootstrap.library_service.add_session_closing_listener(
        lambda closing_session: closing_started.set()
    )

    def read_bundle():
        try:
            read_results.append(scoped.lan_services)
        except Exception as exc:
            read_errors.append(exc)

    def close_session():
        try:
            session.close()
        except Exception as exc:
            close_errors.append(exc)
        finally:
            close_done.set()

    reader = threading.Thread(target=read_bundle)
    reader.start()
    assert factory_entered.wait(5)
    closer = threading.Thread(target=close_session)
    closer.start()
    assert closing_started.wait(5)
    assert session.is_closed
    assert not close_done.wait(0.05)

    release_factory.set()
    reader.join(5)
    closer.join(5)

    assert not reader.is_alive()
    assert not closer.is_alive()
    assert read_results == []
    assert len(read_errors) == 1
    assert isinstance(read_errors[0], RuntimeError)
    assert close_errors == []
    assert calls == [session]
    with pytest.raises(RuntimeError, match="closed|closing"):
        scoped.lan_services
    assert calls == [session]


def test_lan_holder_is_excluded_from_snapshot_value_semantics(opened_session, monkeypatch):
    from dataclasses import fields, replace

    bootstrap, session = opened_session
    calls = []
    bundle = SimpleNamespace(
        asset_service=object(), project_service=object(), search_service=object()
    )

    def build_lan_services(session, *, connection_provider=None):
        calls.append(session)
        return bundle

    monkeypatch.setattr(bootstrap, "_build_lan_services", build_lan_services)
    snapshot = bootstrap.runtime_for(session).services_snapshot
    comparison_peer = replace(snapshot, _lan_holder=object())
    holder_field = next(field for field in fields(snapshot) if field.name == "_lan_holder")
    repr_before = repr(snapshot)
    snapshot_hash = hash(snapshot)
    session_hash = hash(session)
    snapshot_lookup = {snapshot: "snapshot"}
    session_lookup = {session: "session"}

    assert holder_field.repr is False
    assert holder_field.compare is False
    assert holder_field.hash is False
    assert "_lan_holder=" not in repr_before
    assert "lan_services=" not in repr_before
    assert snapshot == comparison_peer
    assert snapshot_lookup[comparison_peer] == "snapshot"
    assert calls == []

    assert snapshot.lan_services is bundle

    assert repr(snapshot) == repr_before
    assert snapshot == comparison_peer
    assert hash(snapshot) == snapshot_hash
    assert hash(session) == session_hash
    assert snapshot_lookup[snapshot] == "snapshot"
    assert session_lookup[session] == "session"
    assert calls == [session]

    session.close()

    assert hash(snapshot) == snapshot_hash
    assert hash(session) == session_hash
    assert snapshot_lookup[snapshot] == "snapshot"
    assert session_lookup[session] == "session"
    assert calls == [session]


def test_maintenance_service_construction_failure_does_not_publish_or_block_retry(
    opened_session, monkeypatch
):
    import AssetsManager.application.bootstrap as bootstrap_module
    from AssetsManager.application.database_maintenance_service import (
        DatabaseMaintenanceService,
    )

    bootstrap, session = opened_session

    def fail_construction(**_kwargs):
        raise RuntimeError("maintenance construction failed")

    monkeypatch.setattr(
        bootstrap_module, "DatabaseMaintenanceService", fail_construction, raising=False
    )

    with pytest.raises(RuntimeError, match="maintenance construction failed"):
        bootstrap.runtime_for(session)

    assert bootstrap._runtimes == {}
    assert bootstrap._runtime_creation == {}

    monkeypatch.setattr(
        bootstrap_module, "DatabaseMaintenanceService", DatabaseMaintenanceService
    )
    runtime = bootstrap.runtime_for(session)

    assert runtime.services.maintenance_service._session is session


def test_deferred_runtime_cleanup_keeps_bootstrap_ownership_until_retry(
    opened_session, monkeypatch
):
    owner, session = opened_session
    root = session.root
    contender = ApplicationBootstrap()
    runtime = owner.runtime_for(session)
    real_close = runtime.close
    calls = 0

    def defer_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            return
        return real_close()

    monkeypatch.setattr(runtime, "close", defer_once)

    with pytest.raises(RuntimeError, match="cleanup is pending"):
        owner.library_service.close_session(session)

    assert owner._runtimes[id(session)] is runtime
    with pytest.raises(RuntimeError, match="owned by another LibraryService"):
        contender.library_service.open_session(root)

    owner.library_service.close_session(session)
    replacement = contender.library_service.open_session(root)
    contender.library_service.close_session(replacement)


def test_bootstrap_export_restore_failure_blocks_cross_bootstrap_admission_until_ack(
    tmp_path, monkeypatch
):
    root = tmp_path / "MiXeDLibrary"
    root.mkdir()
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(root)
    export_service = bootstrap.runtime_for(session).services.export_service
    bootstrap.library_service.close_session(session)

    def fail_restore(*_args, **_kwargs):
        error = ValueError("unsafe restore install")
        error.restore_recovery_required = True
        raise error

    monkeypatch.setattr(export_service, "_preflight_archive_path", lambda _path: None)
    monkeypatch.setattr(export_service, "_restore_under_reservation", fail_restore)
    with pytest.raises(ValueError, match="unsafe restore install"):
        export_service.restore_backup(
            tmp_path / "backup.zip", root, overwrite_existing=True
        )

    assert bootstrap.library_service.restore_failure_state(root) is not None

    other = ApplicationBootstrap()
    with pytest.raises(RuntimeError, match="Restore admission is blocked"):
        # Mixed-case alias only folds onto the same library where the
        # filesystem is case-insensitive; on POSIX use the same spelling.
        alias = tmp_path / ("MIXEDLIBRARY" if os.path.normcase("A") == "a" else "MiXeDLibrary")
        other.library_service.open_session(alias)

    new_export_service = LibraryExportService(
        connection_provider=session.connection_for,
        session=session,
        restore_coordinator=bootstrap.library_service.restore_reservation,
        restore_state_provider=bootstrap.library_service.restore_state_provider,
        restore_acknowledger=bootstrap.library_service.restore_acknowledger,
    )
    with pytest.raises(RuntimeError, match="Restore admission is blocked"):
        new_export_service.restore_backup(tmp_path / "new-backup.zip", root)

    recovery_state = bootstrap.library_service.restore_failure_state(root)
    assert recovery_state is not None
    export_service.acknowledge_restore_failure(recovery_state.token)
    assert bootstrap.library_service.restore_failure_state(root) is None
    assert export_service.restore_failure_state is None
    export_service._ensure_restore_admission()
    replacement = bootstrap.library_service.open_session(root)
    bootstrap.library_service.close_session(replacement)


def test_materialized_lan_services_reject_access_after_session_close(opened_session):
    bootstrap, session = opened_session
    runtime = bootstrap.runtime_for(session)
    scoped = runtime.services

    assert scoped.lan_services is runtime.services.lan_services
    session.close()

    with pytest.raises(RuntimeError, match="retained LAN services"):
        _ = scoped.lan_services


def test_reconciliation_start_failure_cleans_temporary_runtime(opened_session, monkeypatch):
    from AssetsManager.application.asset_index_reconciliation_service import (
        AssetIndexReconciliationService,
    )

    bootstrap, session = opened_session
    original_start = AssetIndexReconciliationService.start

    def fail_start(_service):
        raise RuntimeError("reconciliation start failed")

    monkeypatch.setattr(AssetIndexReconciliationService, "start", fail_start)
    with pytest.raises(RuntimeError, match="reconciliation start failed"):
        bootstrap.runtime_for(session)

    assert bootstrap._runtimes == {}
    assert bootstrap._runtime_creation == {}
    assert not session.is_closed

    monkeypatch.setattr(AssetIndexReconciliationService, "start", original_start)
    runtime = bootstrap.runtime_for(session)
    assert runtime.session is session
