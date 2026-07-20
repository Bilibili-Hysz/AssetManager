"""Tests for runtime data path resolution."""


def test_same_basename_libraries_get_distinct_dirs(tmp_path, monkeypatch):
    from AssetsManager.core import path_resolver

    monkeypatch.setattr(path_resolver, "runtime_root", lambda: tmp_path / "RuntimeData")
    lib_a = tmp_path / "A" / "Assets"
    lib_b = tmp_path / "B" / "Assets"

    dir_a = path_resolver.library_data_dir(str(lib_a))
    dir_b = path_resolver.library_data_dir(str(lib_b))

    assert dir_a != dir_b
    assert dir_a.name.startswith("Assets_")
    assert dir_b.name.startswith("Assets_")


def test_library_data_name_is_stable(tmp_path):
    from AssetsManager.core.path_resolver import library_data_name

    lib = tmp_path / "Library"

    assert library_data_name(str(lib)) == library_data_name(str(lib))


def test_database_migrates_legacy_library_dir(tmp_path, monkeypatch):
    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    lib = tmp_path / "Source" / "Assets"
    legacy = runtime / "Assets"
    legacy.mkdir(parents=True)
    marker = legacy / "marker.txt"
    marker.write_text("legacy", encoding="utf-8")

    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)
    monkeypatch.setattr(database, "RUNTIME_ROOT", runtime)

    manager = database.DatabaseManager()
    manager.open_library(str(lib))
    try:
        new_dir = path_resolver.library_data_dir(str(lib))
        assert new_dir != legacy
        assert (new_dir / "marker.txt").read_text(encoding="utf-8") == "legacy"
        assert not legacy.exists()
    finally:
        manager.close()


def test_clean_orphan_dirs_keeps_hashed_and_legacy_dirs(tmp_path, monkeypatch):
    import os
    import time
    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    lib = tmp_path / "Source" / "Assets"
    lib.mkdir(parents=True)
    hashed = runtime / path_resolver.library_data_name(str(lib))
    legacy = runtime / "Assets"
    orphan = runtime / "Old"
    shared = runtime / "Shared"
    for path in (hashed, legacy, orphan, shared):
        path.mkdir(parents=True)

    old_time = time.time() - 8 * 86400
    os.utime(str(orphan), (old_time, old_time))

    monkeypatch.setattr(database, "RUNTIME_ROOT", runtime)

    database.DatabaseManager.clean_orphan_dirs([str(lib)])

    assert hashed.exists()
    assert legacy.exists()
    assert shared.exists()
    assert not orphan.exists()


def test_legacy_db_write_lock_is_reentrant_without_a_manager(monkeypatch):
    from AssetsManager.core import database

    monkeypatch.setattr(
        database.ThreadSafeSingleton,
        "get",
        lambda _type: (_ for _ in ()).throw(AssertionError("manager lookup")),
    )
    with database.db_write_lock():
        with database.db_write_lock():
            assert True
