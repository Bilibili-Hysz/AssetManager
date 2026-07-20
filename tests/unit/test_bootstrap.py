"""Tests for ApplicationBootstrap."""
import threading

import pytest

from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.application.context import LibrarySession
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


class TestApplicationBootstrap:

    @pytest.mark.parametrize("direct_close", [True, False], ids=["callback", "service"])
    def test_same_thread_close_rejects_before_lifecycle_mutation(
        self, tmp_path, direct_close
    ):
        root = tmp_path / "library"
        root.mkdir()
        bootstrap = ApplicationBootstrap()
        session = bootstrap.library_service.open_session(root)
        scoped = bootstrap.for_library(session)
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
            assert bootstrap.for_library(session).undo_service is scoped.undo_service
            assert scoped.undo_service.can_undo()

    def test_global_close_serializes_with_selective_close_teardown(
        self, tmp_path, monkeypatch
    ):
        root = tmp_path / "library"
        root.mkdir()
        bootstrap = ApplicationBootstrap()
        service = bootstrap.library_service
        session = service.open_session(root)
        scoped = bootstrap.for_library(session)
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
            assert id(session) in bootstrap._undo_services
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
        assert id(session) not in bootstrap._undo_services
        assert not scoped.undo_service.undo_dir.exists()
        assert db_close_calls == ["close"]
        assert len(reopened) == 1
        assert reopened[0] is not session
        reopened[0].connection_for(root).execute("SELECT 1")

    def test_global_close_inside_operation_rejects_before_mutation(
        self, tmp_path, monkeypatch
    ):
        root = tmp_path / "library"
        root.mkdir()
        bootstrap = ApplicationBootstrap()
        service = bootstrap.library_service
        session = service.open_session(root)
        scoped = bootstrap.for_library(session)
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
            assert bootstrap.for_library(session).undo_service is scoped.undo_service
            assert scoped.undo_service.can_undo()

    def test_global_close_inside_draining_operation_rejects_without_deadlock(
        self, tmp_path
    ):
        root = tmp_path / "library"
        root.mkdir()
        bootstrap = ApplicationBootstrap()
        service = bootstrap.library_service
        session = service.open_session(root)
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

    def test_bootstrap_registers_all_services(self):
        bootstrap = ApplicationBootstrap()
        container = bootstrap.container

        assert container.has(LibraryService)
        assert container.has(AssetService)
        assert container.has(MetadataService)
        assert container.has(TagService)
        assert container.has(FileOperationService)
        assert container.has(ThumbnailService)
        assert container.has(SearchService)
        assert container.has(PluginService)
        assert container.has(UndoService)

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

    def test_for_library_returns_scoped_services(self, tmp_path):
        root = tmp_path / "library"
        root.mkdir()

        bootstrap = ApplicationBootstrap()
        session = bootstrap.library_service.open_session(root)
        scoped = bootstrap.for_library(session)

        assert scoped.session is session
        assert isinstance(scoped.asset_service, AssetService)
        assert scoped.asset_service._session_token == session.event_token
        assert scoped.asset_service._directory_cache._conn is session.connection_for(session.root)
        assert isinstance(scoped.metadata_service, MetadataService)
        assert isinstance(scoped.tag_service, TagService)
        assert isinstance(scoped.project_service, ProjectService)
        assert isinstance(scoped.thumbnail_service, ThumbnailService)
        assert isinstance(scoped.search_service, SearchService)
        assert isinstance(scoped.file_operation_service, FileOperationService)
        assert isinstance(scoped.undo_service, UndoService)
        assert isinstance(scoped.plugin_service, PluginService)
        assert isinstance(scoped.asset_index_service, AssetIndexService)

    def test_for_library_injects_explicit_performance_recorder(self, tmp_path):
        from AssetsManager.core.performance import PerformanceRecorder

        root = tmp_path / "library"
        root.mkdir()
        recorder = PerformanceRecorder(enabled=True)
        bootstrap = ApplicationBootstrap(performance_recorder=recorder)
        session = bootstrap.library_service.open_session(root)

        scoped = bootstrap.for_library(session)

        assert scoped.asset_service._performance_recorder is recorder
        assert scoped.asset_service._session_token == session.event_token

    def test_for_library_asset_service_reuses_session_directory_summary_cache(self, tmp_path):
        from AssetsManager.core.performance import PerformanceRecorder

        root = tmp_path / "library"
        child = root / "child"
        child.mkdir(parents=True)
        (child / "asset.png").write_bytes(b"data")
        recorder = PerformanceRecorder(enabled=True)
        bootstrap = ApplicationBootstrap(performance_recorder=recorder)
        session = bootstrap.library_service.open_session(root)
        scoped = bootstrap.for_library(session)

        scoped.asset_service.list_directory(root, root)
        scoped.asset_service.list_directory(root, root)

        summaries = [event for event in recorder.recent() if event.name == "directory.summary"]
        assert [event.attributes["cache_hit"] for event in summaries] == [False, True]

    def test_for_library_creates_library_scoped_undo_service(self, tmp_path):
        first_root = tmp_path / "first"
        second_root = tmp_path / "second"
        first_root.mkdir()
        second_root.mkdir()

        bootstrap = ApplicationBootstrap()
        first = bootstrap.for_library(bootstrap.library_service.open_session(first_root))
        second = bootstrap.for_library(bootstrap.library_service.open_session(second_root))

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
        first = bootstrap.for_library(first_session)
        second = bootstrap.for_library(second_session)
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
        first = bootstrap.for_library(first_session)
        second = bootstrap.for_library(second_session)
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
        assert id(first_session) not in bootstrap._undo_services
        assert not first.undo_service.undo_dir.exists()
        assert notifications == [first_session]
        assert bootstrap.library_service.owns_live_session(second_session)
        assert bootstrap._undo_services[id(second_session)][1] is second.undo_service
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
        first_session = bootstrap.library_service.open_session(first_root)
        second_session = bootstrap.library_service.open_session(second_root)
        first = bootstrap.for_library(first_session)
        second = bootstrap.for_library(second_session)
        notifications = []
        bootstrap.library_service.add_session_close_listener(notifications.append)

        def fail_clear_cache():
            raise RuntimeError("tag cache cleanup failed")

        monkeypatch.setattr(first_session.context.tag_store, "clear_cache", fail_clear_cache)

        bootstrap.library_service.close()

        assert first_session.is_closed
        assert second_session.is_closed
        assert bootstrap._undo_services == {}
        assert not first.undo_service.undo_dir.exists()
        assert not second.undo_service.undo_dir.exists()
        assert notifications.count(first_session) == 1
        assert notifications.count(second_session) == 1

    def test_reopening_same_root_gets_fresh_undo_service(self, tmp_path):
        root = tmp_path / "library"
        root.mkdir()
        bootstrap = ApplicationBootstrap()
        old_session = bootstrap.library_service.open_session(root)
        old = bootstrap.for_library(old_session)
        old.undo_service.record_rename(str(root / "a"), str(root / "b"))

        old_session.close()
        new_session = bootstrap.library_service.open_session(root)
        new = bootstrap.for_library(new_session)

        assert new_session is not old_session
        assert new.undo_service is not old.undo_service
        assert not new.undo_service.can_undo()

    def test_for_library_binds_provider_to_context_connection(self, tmp_path):
        root = tmp_path / "library"
        root.mkdir()

        bootstrap = ApplicationBootstrap()
        session = bootstrap.library_service.open_session(root)
        scoped = bootstrap.for_library(session)

        assert scoped.metadata_service._connection(root) is session.connection_for(root)
        assert scoped.tag_service.list_tags(root) == []

    def test_for_library_binds_file_operations_to_session(self, tmp_path):
        root = tmp_path / "library"
        root.mkdir()

        bootstrap = ApplicationBootstrap()
        session = bootstrap.library_service.open_session(root)

        assert bootstrap.for_library(session).file_operation_service.session is session

    def test_library_session_delegates_context_resources(self, tmp_path):
        root = tmp_path / "library"
        root.mkdir()

        bootstrap = ApplicationBootstrap()
        session = bootstrap.library_service.open_session(root)
        context = session.context

        assert session.context is context
        assert session.root is context.root
        assert session.root_str == context.root_str
        assert session.data_dir is context.data_dir
        assert session.data_dir_str == context.data_dir_str
        assert session.thumb_dir is context.thumb_dir
        assert session.thumb_dir_str == context.thumb_dir_str
        assert session.connection_for(root) is context.db_conn

    def test_for_library_accepts_library_session(self, tmp_path):
        root = tmp_path / "library"
        other = tmp_path / "other"
        root.mkdir()
        other.mkdir()

        bootstrap = ApplicationBootstrap()
        session = bootstrap.library_service.open_session(root)
        scoped = bootstrap.for_library(session)

        assert scoped.session is session
        assert scoped.metadata_service._connection(root) is session.connection_for(root)
        with pytest.raises(ValueError):
            scoped.metadata_service._connection(other)

    def test_for_library_rejects_closed_canonical_session(self, tmp_path):
        root = tmp_path / "library"
        root.mkdir()
        bootstrap = ApplicationBootstrap()
        session = bootstrap.library_service.open_session(root)

        session.close()

        with pytest.raises(ValueError, match="live canonical"):
            bootstrap.for_library(session)

    def test_for_library_rejects_stale_session_after_reopen(self, tmp_path):
        root = tmp_path / "library"
        root.mkdir()
        bootstrap = ApplicationBootstrap()
        stale = bootstrap.library_service.open_session(root)
        stale.close()
        canonical = bootstrap.library_service.open_session(root)

        with pytest.raises(ValueError, match="live canonical"):
            bootstrap.for_library(stale)
        assert bootstrap.for_library(canonical).session is canonical

    def test_for_library_rejects_reconstructed_session(self, tmp_path):
        root = tmp_path / "library"
        root.mkdir()
        bootstrap = ApplicationBootstrap()
        canonical = bootstrap.library_service.open_session(root)
        reconstructed = LibrarySession.from_context(canonical.context)

        with pytest.raises(ValueError, match="live canonical"):
            bootstrap.for_library(reconstructed)

    def test_for_library_rejects_session_from_another_service(self, tmp_path):
        root = tmp_path / "library"
        root.mkdir()
        bootstrap = ApplicationBootstrap()
        foreign = LibraryService().open_session(root)

        with pytest.raises(ValueError, match="live canonical"):
            bootstrap.for_library(foreign)

    def test_for_library_accepts_exact_live_canonical_session(self, tmp_path):
        root = tmp_path / "library"
        root.mkdir()
        bootstrap = ApplicationBootstrap()
        canonical = bootstrap.library_service.open_session(root)

        assert bootstrap.for_library(canonical).session is canonical

    def test_for_library_preserves_session_identity_and_resources(self, tmp_path, monkeypatch):
        root = tmp_path / "library"
        other = tmp_path / "other"
        root.mkdir()
        other.mkdir()

        bootstrap = ApplicationBootstrap()
        session = bootstrap.library_service.open_session(root)

        def reject_session_reconstruction(cls, context):
            raise AssertionError("for_library must not reconstruct a LibrarySession")

        monkeypatch.setattr(type(session), "from_context", classmethod(reject_session_reconstruction))
        scoped = bootstrap.for_library(session)

        assert scoped.session is session
        assert scoped.file_operation_service.session is session
        assert scoped.metadata_service._repo(root)._conn is session.connection_for(root)
        assert scoped.tag_service._connection_provider(root) is session.connection_for(root)
        assert scoped.project_service._metadata_svc._repo(root)._conn is session.connection_for(root)
        assert scoped.project_service._tag_svc._connection_provider(root) is session.connection_for(root)
        assert scoped.file_operation_service._library_root is session.root
        with pytest.raises(ValueError):
            scoped.metadata_service._connection(other)
