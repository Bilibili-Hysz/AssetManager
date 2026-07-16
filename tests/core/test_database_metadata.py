

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


def test_migrate_path_metadata_moves_file_rows(tmp_path, monkeypatch):
    from AssetsManager.core import database, path_resolver
    from AssetsManager.core.singleton import ThreadSafeSingleton

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
        conn = database.get_lib_db(str(lib))
        old_key = database._thumbnail_cache_key(str(old.resolve()))
        thumb_dir = ThreadSafeSingleton.get(database.DatabaseManager).thumb_dir
        thumb_dir.mkdir(parents=True, exist_ok=True)
        (thumb_dir / f"{old_key}.webp").write_bytes(b"thumb")
        conn.execute("INSERT INTO file_tags (file_path, tag) VALUES (?,?)", (str(old.resolve()), "hero"))
        conn.execute("INSERT INTO file_meta (file_path, notes, urls) VALUES (?,?,?)", (str(old.resolve()), "note", '["https://example.com"]'))
        conn.execute(
            "INSERT INTO thumbnail_cache (cache_key, source_path, source_mtime) VALUES (?,?,?)",
            (old_key, str(old.resolve()), 1.0),
        )
        conn.commit()

        database.migrate_path_metadata(str(lib), str(old), str(new))

        assert conn.execute("SELECT tag FROM file_tags WHERE file_path=?", (str(new.resolve()),)).fetchone() == ("hero",)
        assert conn.execute("SELECT notes, urls FROM file_meta WHERE file_path=?", (str(new.resolve()),)).fetchone() == ("note", '["https://example.com"]')
        assert conn.execute("SELECT 1 FROM file_tags WHERE file_path=?", (str(old.resolve()),)).fetchone() is None
        new_key = database._thumbnail_cache_key(str(new.resolve()))
        assert conn.execute("SELECT source_path FROM thumbnail_cache WHERE cache_key=?", (new_key,)).fetchone() == (str(new.resolve()),)
        assert (thumb_dir / f"{new_key}.webp").exists()
    finally:
        database.close_all_dbs()


def test_migrate_path_metadata_uses_target_library_thumb_dir(tmp_path, monkeypatch):
    from AssetsManager.core import database, path_resolver
    from AssetsManager.core.singleton import ThreadSafeSingleton

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
        first_conn = database.get_lib_db(str(first))
        old_key = database._thumbnail_cache_key(str(old.resolve()))
        first_thumb_dir = ThreadSafeSingleton.get(database.DatabaseManager).thumb_dir_for(first)
        first_thumb_dir.mkdir(parents=True, exist_ok=True)
        old_thumb = first_thumb_dir / f"{old_key}.webp"
        old_thumb.write_bytes(b"thumb")
        first_conn.execute(
            "INSERT INTO thumbnail_cache (cache_key, source_path, source_mtime) VALUES (?,?,?)",
            (old_key, str(old.resolve()), 1.0),
        )
        first_conn.commit()

        # Switch the manager's mutable current library before migrating first.
        database.get_lib_db(str(second))

        database.migrate_path_metadata(str(first), str(old), str(new))

        new_key = database._thumbnail_cache_key(str(new.resolve()))
        assert not old_thumb.exists()
        assert (first_thumb_dir / f"{new_key}.webp").exists()
        assert not (ThreadSafeSingleton.get(database.DatabaseManager).thumb_dir_for(second) / f"{new_key}.webp").exists()
    finally:
        database.close_all_dbs()


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
        conn = database.get_lib_db(str(lib))
        conn.execute("INSERT INTO file_tags (file_path, tag) VALUES (?,?)", (str(child.resolve()), "nested"))
        conn.execute("INSERT INTO file_meta (file_path, notes) VALUES (?,?)", (str(child.resolve()), "nested note"))
        conn.commit()

        database.migrate_path_metadata(str(lib), str(old_dir), str(new_dir))

        assert conn.execute("SELECT tag FROM file_tags WHERE file_path=?", (str(new_child.resolve()),)).fetchone() == ("nested",)
        assert conn.execute("SELECT notes FROM file_meta WHERE file_path=?", (str(new_child.resolve()),)).fetchone() == ("nested note",)
        assert conn.execute("SELECT 1 FROM file_meta WHERE file_path=?", (str(child.resolve()),)).fetchone() is None
    finally:
        database.close_all_dbs()
