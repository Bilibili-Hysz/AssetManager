"""Tests for InfoController."""

import os
import sqlite3
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture
def lib_env(tmp_path):
    """Create a temporary library with DB and return (lib_root, conn)."""
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        conn.executescript(database._SCHEMA)
        migrate(conn)
        from AssetsManager.application.library_service import LibraryService
        LibraryService().open_session(str(tmp_path))
        yield str(tmp_path), conn
    finally:
        conn.close()


def test_managed_connection_same_root_is_accepted(tmp_path):
    from AssetsManager.controllers.info_controller import InfoController
    from AssetsManager.core.database import DatabaseManager

    manager = DatabaseManager()
    try:
        conn = manager.connection_for(tmp_path)
        ctrl = InfoController(str(tmp_path), conn)
        assert ctrl._db_conn is conn
    finally:
        manager.close()


def test_managed_connection_foreign_root_is_rejected(tmp_path):
    from AssetsManager.controllers.info_controller import InfoController
    from AssetsManager.core.database import DatabaseManager

    root = tmp_path / "root"
    foreign_root = tmp_path / "foreign"
    root.mkdir()
    foreign_root.mkdir()
    manager = DatabaseManager()
    try:
        conn = manager.connection_for(foreign_root)
        with pytest.raises(ValueError, match="different library root"):
            InfoController(str(root), conn)
    finally:
        manager.close()


def test_unmanaged_raw_connection_remains_compatible(lib_env):
    from AssetsManager.controllers.info_controller import InfoController

    lib_root, conn = lib_env
    ctrl = InfoController(lib_root, conn)
    assert ctrl._db_conn is conn
    assert ctrl.get_plugin_fields(lib_root + "/file.txt") == ([], [])


def test_none_connection_supports_filesystem_only_plugin_queries(tmp_path):
    from AssetsManager.controllers.info_controller import InfoController

    ctrl = InfoController(str(tmp_path), None)
    assert ctrl.get_plugin_fields(str(tmp_path / "file.txt")) == ([], [])
    assert ctrl.discover_urls_in_dir(str(tmp_path)) == []


def test_get_file_info_basic(lib_env):
    from AssetsManager.controllers.info_controller import InfoController

    lib_root, conn = lib_env
    open(lib_root + "/file.txt", "w").close()

    ctrl = InfoController(lib_root, conn)
    info = ctrl.get_file_info(
        lib_root + "/file.txt",
        is_dir=False,
        file_type="File (TXT)",
        size_display="0 B",
        modified_display="2026-01-01",
        parent_path=lib_root,
    )

    assert info.name == "file.txt"
    assert info.is_dir is False
    assert info.file_type == "File (TXT)"
    assert info.urls == ()
    assert info.tags == ()


def test_tag_operations(lib_env):
    from AssetsManager.controllers.info_controller import InfoController

    lib_root, conn = lib_env
    file_path = lib_root + "/file.txt"
    open(file_path, "w").close()

    ctrl = InfoController(lib_root, conn)

    tags = ctrl.add_tag(file_path, "hero")
    assert "hero" in tags

    tags2 = ctrl.add_tag(file_path, "villain")
    assert set(tags2) == {"hero", "villain"}

    tags3 = ctrl.get_tags(file_path)
    assert set(tags3) == {"hero", "villain"}

    tags4 = ctrl.remove_tag(file_path, "hero")
    assert tags4 == ["villain"]


def test_url_operations(lib_env):
    from AssetsManager.controllers.info_controller import InfoController

    lib_root, conn = lib_env
    file_path = lib_root + "/file.txt"
    open(file_path, "w").close()

    ctrl = InfoController(lib_root, conn)

    ctrl.add_url(file_path, "https://example.com")
    urls = ctrl.get_urls(file_path)
    assert "https://example.com" in urls

    ctrl.remove_url(file_path, "https://example.com")
    urls2 = ctrl.get_urls(file_path)
    assert "https://example.com" not in urls2


def test_notes_operations(lib_env):
    from AssetsManager.controllers.info_controller import InfoController

    lib_root, conn = lib_env
    file_path = lib_root + "/file.txt"
    open(file_path, "w").close()

    ctrl = InfoController(lib_root, conn)

    ctrl.save_notes(file_path, "hello world")
    info = ctrl.get_file_info(
        file_path,
        is_dir=False,
        file_type="File",
        size_display="0 B",
        modified_display="",
        parent_path=lib_root,
    )
    assert info.notes == "hello world"


def test_plugin_fields_from_db(lib_env, tmp_path):
    from AssetsManager.controllers.info_controller import InfoController
    from AssetsManager.repositories.plugin_metadata_repository import PluginMetadataRepository

    lib_root, conn = lib_env
    file_path = lib_root + "/file.txt"

    # Pre-populate plugin metadata
    repo = PluginMetadataRepository(conn)
    repo.upsert_batch(file_path, "test_plugin", {"name": "Test", "author": "Author"})

    ctrl = InfoController(lib_root, conn)
    info = ctrl.get_file_info(
        file_path,
        is_dir=False,
        file_type="File",
        size_display="0 B",
        modified_display="",
        parent_path=lib_root,
    )

    keys = {f.key for f in info.plugin_fields}
    assert "name" in keys
    assert "author" in keys
    assert all(f.plugin_id == "test_plugin" for f in info.plugin_fields)


def test_discover_urls_in_dir(tmp_path):
    from AssetsManager.controllers.info_controller import InfoController

    # Create a .url file
    url_file = tmp_path / "product.url"
    url_file.write_text("[InternetShortcut]\nURL=https://example.com/product\n")

    # Create an .html file
    html_file = tmp_path / "page.html"
    html_file.write_text('<html><a href="https://example.com/page">Link</a></html>')

    ctrl = InfoController(str(tmp_path), None)
    urls = ctrl.discover_urls_in_dir(str(tmp_path))

    assert "https://example.com/product" in urls
    assert any("https://example.com/page" in u for u in urls)


def test_classify_dir_uses_text_categories_without_double_counting_blend(tmp_path):
    from AssetsManager.controllers.info_controller import InfoController

    (tmp_path / "texture.png").write_bytes(b"")
    (tmp_path / "scene.blend").write_bytes(b"")

    ctrl = InfoController(str(tmp_path), None)
    summary = ctrl.classify_dir(str(tmp_path))

    assert "Images 1" in summary
    assert "3D Models 1" in summary
    assert "3D Models 2" not in summary


def test_get_file_info_preserves_existing_urls(lib_env):
    from AssetsManager.controllers.info_controller import InfoController

    lib_root, conn = lib_env
    file_path = lib_root + "/file.txt"
    open(file_path, "w").close()

    ctrl = InfoController(lib_root, conn)

    # Add a URL manually
    ctrl.add_url(file_path, "https://manual.com")

    info = ctrl.get_file_info(
        file_path,
        is_dir=False,
        file_type="File",
        size_display="0 B",
        modified_display="",
        parent_path=lib_root,
    )

    assert "https://manual.com" in info.urls


@pytest.mark.parametrize(
    "operation",
    ["get_file_info", "add_tag", "remove_tag", "get_tags", "save_notes", "add_url",
     "remove_url", "get_urls", "get_notes", "get_plugin_fields", "discover_urls_in_dir"],
)
def test_info_controller_rejects_paths_outside_library_root(lib_env, tmp_path, operation):
    from AssetsManager.controllers.info_controller import InfoController

    lib_root, conn = lib_env
    outside = Path(lib_root).parent / f"{Path(lib_root).name}-outside"
    outside.mkdir()
    outside_file = str(outside / "asset.txt")
    ctrl = InfoController(lib_root, conn)

    with pytest.raises(ValueError, match="under library_root"):
        if operation == "get_file_info":
            ctrl.get_file_info(
                outside_file,
                is_dir=False,
                file_type="File",
                size_display="0 B",
                modified_display="",
                parent_path=str(outside),
            )
        elif operation == "add_tag":
            ctrl.add_tag(outside_file, "blocked")
        elif operation == "remove_tag":
            ctrl.remove_tag(outside_file, "blocked")
        elif operation == "get_tags":
            ctrl.get_tags(outside_file)
        elif operation == "save_notes":
            ctrl.save_notes(outside_file, "blocked")
        elif operation == "add_url":
            ctrl.add_url(outside_file, "https://example.com")
        elif operation == "remove_url":
            ctrl.remove_url(outside_file, "https://example.com")
        elif operation == "get_urls":
            ctrl.get_urls(outside_file)
        elif operation == "get_notes":
            ctrl.get_notes(outside_file)
        elif operation == "get_plugin_fields":
            ctrl.get_plugin_fields(outside_file)
        else:
            ctrl.discover_urls_in_dir(str(outside))


def test_info_controller_deepest_folder_rejects_foreign_root_path(tmp_path):
    from AssetsManager.controllers.info_controller import InfoController

    library = tmp_path / "library"
    outside = tmp_path / "outside"
    library.mkdir()
    outside.mkdir()

    assert InfoController.is_deepest_folder(str(outside), str(library), 1) is False


def test_info_controller_closed_session_error_is_not_converted_to_empty_metadata(tmp_path):
    from AssetsManager.application.library_service import LibraryService
    from AssetsManager.application.metadata_service import MetadataService
    from AssetsManager.controllers.info_controller import InfoController

    library = tmp_path / "library"
    library.mkdir()
    file_path = library / "asset.txt"
    file_path.write_text("asset", encoding="utf-8")
    library_service = LibraryService()
    session = library_service.open_session(library)
    metadata_svc = MetadataService(connection_provider=session.connection_for, session=session)
    ctrl = InfoController(
        str(library), session.context.db_conn, metadata_svc=metadata_svc
    )
    session.close()

    with pytest.raises(RuntimeError, match="closed LibrarySession"):
        ctrl.get_file_info(
            str(file_path),
            is_dir=False,
            file_type="File",
            size_display="0 B",
            modified_display="",
            parent_path=str(library),
        )


def test_info_controller_value_error_from_tag_service_is_not_converted_to_empty_tags(
    lib_env,
):
    from AssetsManager.controllers.info_controller import InfoController

    lib_root, conn = lib_env
    file_path = Path(lib_root) / "asset.txt"
    file_path.write_text("asset", encoding="utf-8")

    class RaisingTagService:
        def get_tags(self, *args, **kwargs):
            raise ValueError("path belongs to a different library root")

    ctrl = InfoController(lib_root, conn, tag_svc=RaisingTagService())

    with pytest.raises(ValueError, match="different library root"):
        ctrl.get_tags(str(file_path))


def test_info_controller_does_not_hide_closed_connection_during_plugin_url_persistence(
    lib_env,
):
    from AssetsManager.controllers.info_controller import InfoController
    from AssetsManager.application.metadata_service import AssetMetadata

    lib_root, conn = lib_env
    file_path = Path(lib_root) / "asset.txt"
    file_path.write_text("asset", encoding="utf-8")

    class RaisingMetadataService:
        def get_metadata(self, *args, **kwargs):
            return AssetMetadata(
                path=file_path,
                tags=(),
                notes="",
                urls=(),
            )

        def add_url(self, *args, **kwargs):
            raise sqlite3.ProgrammingError("Cannot operate on a closed database.")

    ctrl = InfoController(lib_root, conn, metadata_svc=RaisingMetadataService())
    ctrl._get_plugin_fields = lambda _path: ([], ["https://plugin.example"])

    with pytest.raises(sqlite3.ProgrammingError):
        ctrl.get_file_info(
            str(file_path),
            is_dir=False,
            file_type="File",
            size_display="0 B",
            modified_display="",
            parent_path=lib_root,
        )


def test_canonical_controller_binds_repository_to_session(tmp_path):
    from AssetsManager.application.library_service import LibraryService
    from AssetsManager.controllers.info_controller import InfoController

    library = tmp_path / "library"
    service = LibraryService()
    session = service.open_session(library)
    try:
        controller = InfoController(
            str(library),
            session.connection_for(library),
            session=session,
        )
        assert controller._session is session
        assert controller._metadata_svc._session is session
        assert controller._metadata_svc._repository is not None
        assert controller._metadata_svc._repository._session is session
        assert controller._tag_svc._session is session
        assert controller._plugin_repo is not None
        assert controller._plugin_repo._session is session
        assert controller._plugin_repo._library_root == library.resolve()

        session._begin_close()
        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            controller.get_plugin_fields(str(library / "asset.txt"))
        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            controller.get_notes(str(library / "asset.txt"))
    finally:
        if not session.is_closed:
            session.close()
        else:
            session._finish_close()

def test_canonical_controller_rejects_unbound_metadata_service(tmp_path):
    from AssetsManager.application.library_service import LibraryService
    from AssetsManager.application.metadata_service import MetadataService
    from AssetsManager.controllers.info_controller import InfoController

    library = tmp_path / "library"
    service = LibraryService()
    session = service.open_session(library)
    raw_metadata = MetadataService(
        connection_provider=lambda _root: session.connection_for(session.root)
    )
    try:
        with pytest.raises(ValueError, match="metadata_svc is not bound"):
            InfoController(
                str(library),
                session.connection_for(session.root),
                metadata_svc=raw_metadata,
                session=session,
            )
    finally:
        service.close()
