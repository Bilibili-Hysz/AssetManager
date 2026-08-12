"""Tests for TagTreeController."""
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


def _make_controller(lib_root: str):
    from AssetsManager.application.tag_service import TagService
    from AssetsManager.core.database import DatabaseManager
    from AssetsManager.core.singleton import ThreadSafeSingleton
    from AssetsManager.controllers.tag_tree_controller import TagTreeController
    svc = TagService(
        connection_provider=lambda root: ThreadSafeSingleton.get(DatabaseManager).connection_for(root)
    )
    return TagTreeController(lib_root, tag_svc=svc)


def test_get_all_tags_empty(lib_env):
    lib_root, _ = lib_env
    ctrl = _make_controller(lib_root)
    assert ctrl.get_all_tags() == []


def test_add_tag(lib_env):
    lib_root, _ = lib_env
    ctrl = _make_controller(lib_root)
    ctrl.add_tag("hero")
    from AssetsManager.core.tag_library import get_library
    assert get_library().canonical("hero") == "hero"


def test_rename_tag(lib_env):
    from AssetsManager.core.database import DatabaseManager
    from AssetsManager.core.singleton import ThreadSafeSingleton
    lib_root, _ = lib_env
    conn = ThreadSafeSingleton.get(DatabaseManager).connection_for(lib_root)
    ctrl = _make_controller(lib_root)
    file_path = str(os.path.join(lib_root, "file.txt"))
    open(file_path, "w").close()
    from AssetsManager.core.tag_store import TagStore
    store = TagStore(lib_root, db_conn=conn)
    store.add_tag(file_path, "old_name")
    ctrl.rename_tag("old_name", "new_name")
    tags = ctrl.get_all_tags()
    assert "new_name" in tags
    assert "old_name" not in tags


def test_delete_tag(lib_env):
    from AssetsManager.core.database import DatabaseManager
    from AssetsManager.core.singleton import ThreadSafeSingleton
    lib_root, _ = lib_env
    conn = ThreadSafeSingleton.get(DatabaseManager).connection_for(lib_root)
    ctrl = _make_controller(lib_root)
    file_path = str(os.path.join(lib_root, "file.txt"))
    open(file_path, "w").close()
    from AssetsManager.core.tag_store import TagStore
    store = TagStore(lib_root, db_conn=conn)
    store.add_tag(file_path, "temp")
    count = ctrl.delete_tag("temp")
    assert count >= 0
    tags = ctrl.get_all_tags()
    assert "temp" not in tags


def test_remove_tag_from_file(lib_env):
    lib_root, _ = lib_env
    ctrl = _make_controller(lib_root)
    file_path = str(os.path.join(lib_root, "file.txt"))
    open(file_path, "w").close()
    ctrl.add_tag("hero")
    ctrl.remove_tag_from_file(file_path, "hero")
    files = ctrl.get_files_for_tag("hero")
    assert file_path not in files


def test_get_tag_with_files(lib_env):
    from AssetsManager.core.database import DatabaseManager
    from AssetsManager.core.singleton import ThreadSafeSingleton
    lib_root, _ = lib_env
    conn = ThreadSafeSingleton.get(DatabaseManager).connection_for(lib_root)
    ctrl = _make_controller(lib_root)
    file_path = str(os.path.join(lib_root, "file.txt"))
    open(file_path, "w").close()
    from AssetsManager.core.tag_store import TagStore
    store = TagStore(lib_root, db_conn=conn)
    store.add_tag(file_path, "hero")
    store.add_tag(file_path, "villain")
    result = ctrl.get_tag_with_files()
    tags = [entry["tag"] for entry in result]
    assert "hero" in tags
    assert "villain" in tags


def test_library_root_property(lib_env):
    lib_root, _ = lib_env
    ctrl = _make_controller(lib_root)
    assert ctrl.library_root == lib_root
