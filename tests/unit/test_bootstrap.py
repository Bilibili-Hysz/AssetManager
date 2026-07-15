"""Tests for ApplicationBootstrap."""
import pytest

from AssetsManager.application.bootstrap import ApplicationBootstrap
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
        assert isinstance(scoped.metadata_service, MetadataService)
        assert isinstance(scoped.tag_service, TagService)
        assert isinstance(scoped.project_service, ProjectService)
        assert isinstance(scoped.thumbnail_service, ThumbnailService)
        assert isinstance(scoped.search_service, SearchService)
        assert isinstance(scoped.file_operation_service, FileOperationService)
        assert isinstance(scoped.undo_service, UndoService)
        assert isinstance(scoped.plugin_service, PluginService)
        assert isinstance(scoped.asset_index_service, AssetIndexService)

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

    def test_for_library_binds_provider_to_context_connection(self, tmp_path):
        root = tmp_path / "library"
        root.mkdir()

        bootstrap = ApplicationBootstrap()
        session = bootstrap.library_service.open_session(root)
        scoped = bootstrap.for_library(session)

        assert scoped.metadata_service._connection(root) is session.db_conn
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
        assert session.db_conn is context.db_conn
        assert session.tag_store is context.tag_store
        assert session.project_data is context.project_data
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
        assert scoped.metadata_service._connection(root) is session.db_conn
        with pytest.raises(ValueError):
            scoped.metadata_service._connection(other)

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
        assert scoped.metadata_service._repo(root)._conn is session.db_conn
        assert scoped.tag_service._connection_provider(root) is session.db_conn
        assert scoped.project_service._metadata_svc._repo(root)._conn is session.db_conn
        assert scoped.project_service._tag_svc._connection_provider(root) is session.db_conn
        assert scoped.file_operation_service._library_root is session.root
        with pytest.raises(ValueError):
            scoped.metadata_service._connection(other)
