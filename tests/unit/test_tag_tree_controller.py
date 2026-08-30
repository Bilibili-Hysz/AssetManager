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
    assert ctrl.get_all_tags(source="ai") == []
    assert ctrl.get_all_tags(source="plugin") == []


def test_get_all_tags_source_partitions(lib_env):
    """AI/plugin partitions stay isolated from the human catalog."""
    lib_root, conn = lib_env
    ctrl = _make_controller(lib_root)
    file_path = str(os.path.join(lib_root, "file.txt"))
    open(file_path, "w").close()
    svc = ctrl._tag_svc
    svc.add_tag(lib_root, file_path, "human_tag")
    svc.add_tag(lib_root, file_path, "ai_guess", source="ai")
    svc.add_tag(lib_root, file_path, "plugin_hint", source="plugin")

    assert "human_tag" in ctrl.get_all_tags()
    assert "ai_guess" not in ctrl.get_all_tags()
    assert "ai_guess" in ctrl.get_all_tags(source="ai")
    assert "plugin_hint" in ctrl.get_all_tags(source="plugin")
    assert "human_tag" not in ctrl.get_all_tags(source="ai")


def test_get_files_by_tag_source(lib_env):
    lib_root, _ = lib_env
    ctrl = _make_controller(lib_root)
    file_path = str(os.path.join(lib_root, "file.txt"))
    open(file_path, "w").close()
    svc = ctrl._tag_svc
    svc.add_tag(lib_root, file_path, "hero", source="ai")
    assert file_path in ctrl.get_files_by_tag("hero", source="ai")
    assert file_path not in ctrl.get_files_by_tag("hero")


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


def test_get_tag_with_files_aggregates_sources(lib_env):
    """AI/plugin tags appear in the tree with their source recorded."""
    lib_root, _ = lib_env
    ctrl = _make_controller(lib_root)
    file_path = str(os.path.join(lib_root, "file.txt"))
    open(file_path, "w").close()
    svc = ctrl._tag_svc
    svc.add_tag(lib_root, file_path, "hero")
    svc.add_tag(lib_root, file_path, "ai_guess", source="ai")
    svc.add_tag(lib_root, file_path, "plugin_hint", source="plugin")

    # Human-only metadata lookup must not crash the aggregation.
    by_tag = {entry["tag"]: entry for entry in ctrl.get_tag_with_files()}
    assert by_tag["hero"]["source"] == "human"
    assert by_tag["ai_guess"]["source"] == "ai"
    assert by_tag["plugin_hint"]["source"] == "plugin"
    assert by_tag["hero"]["files"] == [file_path]
    assert by_tag["ai_guess"]["files"] == [file_path]
    # Human tags expose metadata fields; non-human ones stay empty.
    assert by_tag["ai_guess"]["icon"] == ""
    assert by_tag["ai_guess"]["color"] == ""


def test_library_root_property(lib_env):
    lib_root, _ = lib_env
    ctrl = _make_controller(lib_root)
    assert ctrl.library_root == lib_root


def test_set_and_get_tag_metadata(lib_env):
    lib_root, _ = lib_env
    ctrl = _make_controller(lib_root)
    assert ctrl.get_tag_metadata("hero") is None

    ctrl.set_tag_metadata("hero", color="#ff0000", icon="star", category="character")
    assert ctrl.get_tag_metadata("hero") == {
        "color": "#ff0000",
        "icon": "star",
        "category": "character",
    }


def test_get_tag_with_files_includes_color_icon_and_category(lib_env):
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

    ctrl.set_tag_metadata("hero", color="#00ff00", icon="heart", category="work")

    entries = {entry["tag"]: entry for entry in ctrl.get_tag_with_files()}
    assert entries["hero"]["color"] == "#00ff00"
    assert entries["hero"]["icon"] == "heart"
    assert entries["hero"]["category"] == "work"
