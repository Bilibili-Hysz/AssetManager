

import sqlite3

import pytest


def test_close_library_is_selective_and_idempotent(tmp_path):
    from AssetsManager.core.database import DatabaseManager

    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    manager = DatabaseManager()
    first_conn = manager.connection_for(first)
    second_conn = manager.connection_for(second)

    manager.close_library(first)
    manager.close_library(first)

    with pytest.raises(sqlite3.ProgrammingError):
        first_conn.execute("SELECT 1")
    second_conn.execute("SELECT 1")
    manager.close()


def test_database_manager_uses_only_explicit_library_resources(tmp_path):
    from AssetsManager.core.database import DatabaseManager

    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    manager = DatabaseManager()
    try:
        first_conn = manager.connection_for(first)
        first_data_dir = manager.data_dir_for(first)
        first_thumb_dir = manager.thumb_dir_for(first)
        second_conn = manager.connection_for(second)

        assert first_conn is manager.connection_for(first)
        assert second_conn is manager.connection_for(second)
        assert first_conn is not second_conn
        assert first_data_dir == manager.data_dir_for(first)
        assert first_thumb_dir == manager.thumb_dir_for(first)
        assert not hasattr(manager, "_current_root")
        assert not hasattr(manager, "_current_key")
        assert not hasattr(manager, "db_conn")
        assert not hasattr(manager, "data_dir")
        assert not hasattr(manager, "thumb_dir")
    finally:
        manager.close()


def test_database_module_does_not_expose_removed_get_manager_wrapper():
    from AssetsManager.core import database

    assert not hasattr(database, "get_manager")


def test_database_module_does_not_expose_removed_get_lib_db_helper():
    from AssetsManager.core import database

    assert not hasattr(database, "get_lib_db")


def test_database_module_does_not_expose_removed_update_library_stats_helper():
    from AssetsManager.core import database

    assert not hasattr(database, "update_library_stats")


def test_legacy_library_dir_helper_does_not_construct_database_manager(tmp_path, monkeypatch):
    from AssetsManager.core import database

    def fail_singleton(_type):
        raise AssertionError("path-only lookup must not construct DatabaseManager")

    monkeypatch.setattr(database.ThreadSafeSingleton, "get", fail_singleton)

    directory = database.get_library_dir(str(tmp_path / "library"))

    assert directory.is_dir()


def test_migrate_path_metadata_moves_file_rows(tmp_path, monkeypatch):
    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    lib = tmp_path / "Library"
    old = lib / "old.png"
    new = lib / "new.png"
    lib.mkdir()
    old.write_text("old", encoding="utf-8")
    new.write_text("new", encoding="utf-8")

    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)
    monkeypatch.setattr(database, "RUNTIME_ROOT", runtime)
    try:
        manager = database.DatabaseManager()
        conn = manager.connection_for(lib)
        old_key = database._thumbnail_cache_key(str(old.resolve()))
        thumb_dir = manager.thumb_dir_for(lib)
        thumb_dir.mkdir(parents=True, exist_ok=True)
        (thumb_dir / f"{old_key}.webp").write_bytes(b"thumb")
        conn.execute("INSERT INTO file_tags (file_path, tag) VALUES (?,?)", (str(old.resolve()), "hero"))
        conn.execute("INSERT INTO file_meta (file_path, notes, urls) VALUES (?,?,?)", (str(old.resolve()), "note", '["https://example.com"]'))
        conn.execute(
            "INSERT INTO thumbnail_cache (cache_key, source_path, source_mtime) VALUES (?,?,?)",
            (old_key, str(old.resolve()), 1.0),
        )
        conn.commit()

        database.migrate_path_metadata(conn, thumb_dir, old, new)

        assert conn.execute("SELECT tag FROM file_tags WHERE file_path=?", (str(new.resolve()),)).fetchone() == ("hero",)
        assert conn.execute("SELECT notes, urls FROM file_meta WHERE file_path=?", (str(new.resolve()),)).fetchone() == ("note", '["https://example.com"]')
        assert conn.execute("SELECT 1 FROM file_tags WHERE file_path=?", (str(old.resolve()),)).fetchone() is None
        new_key = database._thumbnail_cache_key(str(new.resolve()))
        assert conn.execute("SELECT source_path FROM thumbnail_cache WHERE cache_key=?", (new_key,)).fetchone() == (str(new.resolve()),)
        assert (thumb_dir / f"{new_key}.webp").exists()
    finally:
        manager.close()


def test_migrate_path_metadata_uses_target_library_thumb_dir(tmp_path, monkeypatch):
    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    first = tmp_path / "FirstLibrary"
    second = tmp_path / "SecondLibrary"
    old = first / "old.png"
    new = first / "new.png"
    first.mkdir()
    second.mkdir()
    old.write_text("old", encoding="utf-8")
    new.write_text("new", encoding="utf-8")

    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)
    monkeypatch.setattr(database, "RUNTIME_ROOT", runtime)
    try:
        manager = database.DatabaseManager()
        first_conn = manager.connection_for(first)
        old_key = database._thumbnail_cache_key(str(old.resolve()))
        first_thumb_dir = manager.thumb_dir_for(first)
        first_thumb_dir.mkdir(parents=True, exist_ok=True)
        old_thumb = first_thumb_dir / f"{old_key}.webp"
        old_thumb.write_bytes(b"thumb")
        first_conn.execute(
            "INSERT INTO thumbnail_cache (cache_key, source_path, source_mtime) VALUES (?,?,?)",
            (old_key, str(old.resolve()), 1.0),
        )
        first_conn.commit()

        # Opening another library must not alter the target library resources.
        manager.connection_for(second)

        database.migrate_path_metadata(first_conn, first_thumb_dir, old, new)

        new_key = database._thumbnail_cache_key(str(new.resolve()))
        assert not old_thumb.exists()
        assert (first_thumb_dir / f"{new_key}.webp").exists()
        assert not (manager.thumb_dir_for(second) / f"{new_key}.webp").exists()
    finally:
        manager.close()


def test_migrate_path_metadata_moves_directory_children(tmp_path, monkeypatch):
    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    lib = tmp_path / "Library"
    old_dir = lib / "old_dir"
    new_dir = lib / "new_dir"
    child = old_dir / "child.txt"
    new_child = new_dir / "child.txt"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    child.write_text("child", encoding="utf-8")
    new_child.write_text("child", encoding="utf-8")

    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)
    monkeypatch.setattr(database, "RUNTIME_ROOT", runtime)
    try:
        manager = database.DatabaseManager()
        conn = manager.connection_for(lib)
        conn.execute("INSERT INTO file_tags (file_path, tag) VALUES (?,?)", (str(child.resolve()), "nested"))
        conn.execute("INSERT INTO file_meta (file_path, notes) VALUES (?,?)", (str(child.resolve()), "nested note"))
        conn.commit()

        database.migrate_path_metadata(conn, manager.thumb_dir_for(lib), old_dir, new_dir)

        assert conn.execute("SELECT tag FROM file_tags WHERE file_path=?", (str(new_child.resolve()),)).fetchone() == ("nested",)
        assert conn.execute("SELECT notes FROM file_meta WHERE file_path=?", (str(new_child.resolve()),)).fetchone() == ("nested note",)
        assert conn.execute("SELECT 1 FROM file_meta WHERE file_path=?", (str(child.resolve()),)).fetchone() is None
    finally:
        manager.close()
