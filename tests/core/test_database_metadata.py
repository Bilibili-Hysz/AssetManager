

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


def test_validate_connection_owner_distinguishes_managed_and_unmanaged(tmp_path):
    from AssetsManager.core import database

    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    manager = database.DatabaseManager()
    unmanaged = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        managed = manager.connection_for(root_a)

        assert manager.validate_connection_owner(root_a, managed) is managed
        assert (
            manager.validate_connection_owner(
                root_b,
                unmanaged,
                allow_unmanaged=True,
            )
            is unmanaged
        )
        with pytest.raises(RuntimeError, match="not managed by DatabaseManager"):
            manager.validate_connection_owner(
                root_a,
                unmanaged,
                allow_unmanaged=False,
            )
        with pytest.raises(ValueError, match="different library root"):
            manager.validate_connection_owner(root_b, managed)

    finally:
        unmanaged.close()
        manager.close()

def test_require_managed_connection_owner_is_strict_about_registration_and_root(
    tmp_path,
):
    from AssetsManager.core import database

    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    manager = database.DatabaseManager()
    unmanaged = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        managed = manager.connection_for(root_a)

        assert manager.require_managed_connection_owner(root_a, managed) is managed
        with pytest.raises(ValueError, match="different library root"):
            manager.require_managed_connection_owner(root_b, managed)
        with pytest.raises(RuntimeError, match="unmanaged connection"):
            manager.require_managed_connection_owner(root_a, unmanaged)
    finally:
        unmanaged.close()
        manager.close()


def test_database_module_does_not_expose_removed_update_library_stats_helper():
    from AssetsManager.core import database

    assert not hasattr(database, "update_library_stats")


def test_legacy_library_dir_helper_does_not_construct_database_manager(tmp_path, monkeypatch):
    from AssetsManager.core import database, path_resolver

    def fail_singleton(_type):
        raise AssertionError("path-only lookup must not construct DatabaseManager")

    def fail_open(*_args, **_kwargs):
        raise AssertionError("path-only lookup must not open a database")

    monkeypatch.setattr(database.ThreadSafeSingleton, "get", fail_singleton)
    monkeypatch.setattr(database.DatabaseManager, "open_library", fail_open)
    monkeypatch.setattr(database.DatabaseManager, "__init__", fail_open)
    monkeypatch.setattr(database.DatabaseManager, "connection_for", fail_open)
    monkeypatch.setattr(database.sqlite3, "connect", fail_open)

    library = tmp_path / "library"
    directory = database.get_library_dir(str(library))

    assert directory.is_dir()
    marker = path_resolver.library_data_identity_path(library)
    assert marker.read_text(encoding="utf-8") == path_resolver.root_identity(
        library, strict=False
    ).map_key


def test_legacy_library_dir_helper_migrates_legacy_data_before_preparing_hashed_dir(
    tmp_path, monkeypatch
):
    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    library = tmp_path / "Source" / "Assets"
    library.parent.mkdir()
    legacy = runtime / "Assets"
    legacy.mkdir(parents=True)
    (legacy / "marker.txt").write_text("legacy", encoding="utf-8")
    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)

    directory = database.get_library_dir(str(library))

    assert directory == path_resolver.library_data_dir(library)
    assert (directory / "marker.txt").read_text(encoding="utf-8") == "legacy"
    assert not legacy.exists()
    marker = path_resolver.library_data_identity_path(library)
    assert marker.read_text(encoding="utf-8") == path_resolver.root_identity(
        library, strict=False
    ).map_key


def test_legacy_library_dir_helper_rejects_formal_identity_collision(
    tmp_path, monkeypatch
):
    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    library = tmp_path / "Source" / "Assets"
    library.parent.mkdir()
    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)

    marker = path_resolver.library_data_identity_path(library)
    marker.parent.mkdir(parents=True)
    marker.write_text("different-root", encoding="utf-8")

    with pytest.raises(RuntimeError, match="identity collision"):
        database.get_library_dir(str(library))

    assert marker.read_text(encoding="utf-8") == "different-root"
    assert not path_resolver.library_data_dir(library).exists()


def test_legacy_library_dir_helper_rejects_reserved_legacy_directory(
    tmp_path, monkeypatch
):
    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    library = tmp_path / "Source" / "_orphaned"
    library.parent.mkdir()
    legacy = runtime / "_orphaned"
    legacy.mkdir(parents=True)
    (legacy / "keep.txt").write_text("keep", encoding="utf-8")
    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)

    with pytest.raises(RuntimeError, match="Reserved RuntimeData directory"):
        database.get_library_dir(str(library))

    assert legacy.exists()
    assert (legacy / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert not path_resolver.library_data_dir(library).exists()
    assert path_resolver.library_data_identity_path(library).exists()


def test_legacy_library_dir_helper_rejects_legacy_and_hashed_double_directory(
    tmp_path, monkeypatch
):
    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    library = tmp_path / "Source" / "Assets"
    library.parent.mkdir()
    legacy = runtime / "Assets"
    legacy.mkdir(parents=True)
    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)
    hashed = path_resolver.library_data_dir(library)
    hashed.mkdir(parents=True)
    (hashed / "hashed.txt").write_text("hashed", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Legacy and hashed RuntimeData directories"):
        database.get_library_dir(str(library))

    assert legacy.exists()
    assert (hashed / "hashed.txt").read_text(encoding="utf-8") == "hashed"
    assert path_resolver.library_data_identity_path(library).exists()


def test_legacy_library_dir_helper_retains_marker_when_migration_fails(
    tmp_path, monkeypatch
):
    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    library = tmp_path / "Source" / "Assets"
    library.parent.mkdir()
    legacy = runtime / "Assets"
    legacy.mkdir(parents=True)
    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)

    def fail_move(*_args, **_kwargs):
        raise OSError("injected migration failure")

    monkeypatch.setattr(database.shutil, "move", fail_move)

    with pytest.raises(RuntimeError, match="Legacy RuntimeData migration failed"):
        database.get_library_dir(str(library))

    assert legacy.exists()
    assert not path_resolver.library_data_dir(library).exists()
    assert path_resolver.library_data_identity_path(library).exists()


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


def test_migrate_path_metadata_preserves_caller_outer_transaction(tmp_path):
    from AssetsManager.core.database import DatabaseManager, migrate_path_metadata

    library = tmp_path / "library"
    old = library / "old.txt"
    new = library / "new.txt"
    library.mkdir()
    old.write_text("old", encoding="utf-8")
    new.write_text("new", encoding="utf-8")
    manager = DatabaseManager()
    try:
        conn = manager.connection_for(library)
        old_key = str(old.resolve())
        new_key = str(new.resolve())
        conn.execute("INSERT INTO file_tags (file_path, tag) VALUES (?, ?)", (old_key, "hero"))
        conn.execute("CREATE TABLE caller_data (value TEXT NOT NULL)")
        conn.commit()
        conn.execute("BEGIN")
        conn.execute("INSERT INTO caller_data VALUES ('keep-me')")

        migrate_path_metadata(conn, manager.thumb_dir_for(library), old, new)

        assert conn.in_transaction is True
        assert conn.execute("SELECT tag FROM file_tags WHERE file_path=?", (new_key,)).fetchone() == ("hero",)
        assert conn.execute("SELECT * FROM caller_data").fetchall() == [("keep-me",)]
        conn.rollback()
        assert conn.execute("SELECT tag FROM file_tags WHERE file_path=?", (old_key,)).fetchone() == ("hero",)
        assert conn.execute("SELECT tag FROM file_tags WHERE file_path=?", (new_key,)).fetchone() is None
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


def test_migrate_path_metadata_does_not_move_same_prefix_sibling(tmp_path, monkeypatch):
    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    lib = tmp_path / "Library"
    old_dir = lib / "folder"
    new_dir = lib / "renamed"
    sibling_child = lib / "folder-copy" / "child.txt"
    old_child = old_dir / "child.txt"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    sibling_child.parent.mkdir(parents=True)
    old_child.write_text("old", encoding="utf-8")
    sibling_child.write_text("sibling", encoding="utf-8")

    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)
    monkeypatch.setattr(database, "RUNTIME_ROOT", runtime)
    manager = database.DatabaseManager()
    try:
        conn = manager.connection_for(lib)
        old_key = str(old_child.resolve())
        sibling_key = str(sibling_child.resolve())
        conn.execute("INSERT INTO file_tags (file_path, tag) VALUES (?,?)", (old_key, "old"))
        conn.execute("INSERT INTO file_tags (file_path, tag) VALUES (?,?)", (sibling_key, "sibling"))
        conn.execute("INSERT INTO file_meta (file_path, notes) VALUES (?,?)", (old_key, "old"))
        conn.execute("INSERT INTO file_meta (file_path, notes) VALUES (?,?)", (sibling_key, "sibling"))
        conn.commit()

        database.migrate_path_metadata(conn, manager.thumb_dir_for(lib), old_dir, new_dir)

        assert conn.execute(
            "SELECT tag FROM file_tags WHERE file_path=?",
            (str((new_dir / "child.txt").resolve()),),
        ).fetchone() == ("old",)
        assert conn.execute(
            "SELECT tag FROM file_tags WHERE file_path=?",
            (sibling_key,),
        ).fetchone() == ("sibling",)
        assert conn.execute(
            "SELECT notes FROM file_meta WHERE file_path=?",
            (sibling_key,),
        ).fetchone() == ("sibling",)
    finally:
        manager.close()



def test_thumb_directory_failure_does_not_publish_managed_connection(tmp_path, monkeypatch):
    from AssetsManager.core import database

    root = tmp_path / "library"
    root.mkdir()
    manager = database.DatabaseManager()

    class FailingThumbDir:
        def mkdir(self, *args, **kwargs):
            raise OSError("thumbnail directory unavailable")

    monkeypatch.setattr(database, "thumb_dir", lambda _identity: FailingThumbDir())
    try:
        with pytest.raises(OSError, match="thumbnail directory unavailable"):
            manager.connection_for(root)
        assert manager._connections == {}
        assert manager._connection_locks == {}
        # The formal identity reservation must survive preparation failure.
        assert database.library_data_identity_path(root).exists()
    finally:
        manager.close()



def test_owner_validation_rejects_managed_connection_marked_for_cleanup(tmp_path):
    from AssetsManager.core import database

    root = tmp_path / "library"
    root.mkdir()
    manager = database.DatabaseManager()
    conn = manager.connection_for(root)
    state = database._connection_locks[id(conn)]
    state.closed = True
    try:
        with pytest.raises(RuntimeError, match="cleanup is pending"):
            manager.validate_connection_owner(root, conn)
        with pytest.raises(RuntimeError, match="cleanup is pending"):
            manager.require_managed_connection_owner(root, conn)
    finally:
        state.closed = False
        manager.close()
