"""Tests for InfoController."""
import os
import sqlite3

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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


def test_get_file_info_basic(lib_env):
    from AssetsManager.controllers.info_controller import InfoController

    lib_root, conn = lib_env
    (lib_root + "/file.txt") and open(lib_root + "/file.txt", "w").close()

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

    summary = InfoController.classify_dir(str(tmp_path))

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
