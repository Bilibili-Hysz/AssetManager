"""Tests for runtime data path resolution."""


def test_same_basename_libraries_get_distinct_dirs(tmp_path, monkeypatch):
    from AssetsManager.core import path_resolver

    monkeypatch.setattr(path_resolver, "runtime_root", lambda: tmp_path / "RuntimeData")
    lib_a = tmp_path / "A" / "Assets"
    lib_b = tmp_path / "B" / "Assets"
    lib_a.parent.mkdir()
    lib_b.parent.mkdir()

    dir_a = path_resolver.library_data_dir(str(lib_a))
    dir_b = path_resolver.library_data_dir(str(lib_b))

    assert dir_a != dir_b
    assert dir_a.name.startswith("Assets_")
    assert dir_b.name.startswith("Assets_")


def test_library_data_name_is_stable(tmp_path):
    from AssetsManager.core.path_resolver import library_data_name

    lib = tmp_path / "Library"

    assert library_data_name(str(lib)) == library_data_name(str(lib))


def test_library_lock_path_is_stable_and_per_library(tmp_path, monkeypatch):
    from AssetsManager.core import path_resolver

    runtime = tmp_path / "RuntimeData"
    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)
    lib_a = tmp_path / "A" / "Assets"
    lib_b = tmp_path / "B" / "Assets"
    lib_a.parent.mkdir()
    lib_b.parent.mkdir()

    lock_a = path_resolver.library_lock_path(lib_a)
    lock_a_again = path_resolver.library_lock_path(str(lib_a))
    lock_b = path_resolver.library_lock_path(lib_b)

    assert lock_a == lock_a_again
    assert lock_a != lock_b
    assert lock_a.parent == runtime / "Shared"
    assert not lock_a.parent.exists()


def test_database_rejects_hashed_runtime_data_identity_collision(tmp_path, monkeypatch):
    import pytest
    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    root_a = tmp_path / "A" / "Assets"
    root_b = tmp_path / "B" / "Assets"
    root_a.mkdir(parents=True)
    root_b.mkdir(parents=True)
    shared_data = runtime / "Assets_legacy-hash"
    marker = runtime / "Shared" / "library-data-collision.identity"

    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)
    monkeypatch.setattr(database, "library_data_dir", lambda _identity: shared_data)
    monkeypatch.setattr(database, "db_path", lambda _identity: shared_data / "assetmanager.db")
    monkeypatch.setattr(database, "library_data_identity_path", lambda _identity: marker)
    monkeypatch.setattr(
        database,
        "legacy_library_data_dir",
        lambda identity: runtime / f"legacy-{identity.display_path.name}",
    )
    monkeypatch.setattr(database, "thumb_dir", lambda _identity: shared_data / ".thumbnails")

    first = database.DatabaseManager()
    second = database.DatabaseManager()
    first.open_library(root_a)
    try:
        with pytest.raises(RuntimeError, match="identity collision"):
            second.open_library(root_b)
    finally:
        first.close()
        second.close()


def test_database_recovers_matching_stale_pending_marker(tmp_path, monkeypatch):
    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    root = tmp_path / "library"
    root.mkdir()
    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)

    identity = path_resolver.root_identity(root, strict=False)
    marker = path_resolver.library_data_identity_path(identity)
    pending = marker.with_name(marker.name + ".pending")
    pending.parent.mkdir(parents=True)
    pending.write_text(identity.map_key, encoding="utf-8")

    manager = database.DatabaseManager()
    try:
        manager.connection_for(root)
        assert marker.read_text(encoding="utf-8") == identity.map_key
        # Recovery publishes the existing pending marker without deleting a
        # file that may belong to another crashed or concurrent claimant.
        assert pending.read_text(encoding="utf-8") == identity.map_key
    finally:
        manager.close()


def test_matching_pending_recovery_does_not_alias_formal_marker(
    tmp_path, monkeypatch
):
    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    root = tmp_path / "library"
    root.mkdir()
    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)

    identity = path_resolver.root_identity(root, strict=False)
    marker = path_resolver.library_data_identity_path(identity)
    pending = marker.with_name(marker.name + ".pending")
    pending.parent.mkdir(parents=True)
    pending.write_text(identity.map_key, encoding="utf-8")

    manager = database.DatabaseManager()
    try:
        manager.connection_for(root)
        assert marker.read_text(encoding="utf-8") == identity.map_key
        pending.write_text("rewritten-pending", encoding="utf-8")
        assert marker.read_text(encoding="utf-8") == identity.map_key
    finally:
        manager.close()


def test_database_rejects_mismatched_stale_pending_marker(tmp_path, monkeypatch):
    import pytest
    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    root = tmp_path / "library"
    root.mkdir()
    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)
    monkeypatch.setattr(database.time, "sleep", lambda _seconds: None)

    identity = path_resolver.root_identity(root, strict=False)
    marker = path_resolver.library_data_identity_path(identity)
    pending = marker.with_name(marker.name + ".pending")
    pending.parent.mkdir(parents=True)
    pending.write_text("different-root", encoding="utf-8")

    manager = database.DatabaseManager()
    try:
        with pytest.raises(RuntimeError, match="identity collision"):
            manager.connection_for(root)
        assert pending.read_text(encoding="utf-8") == "different-root"
        assert not marker.exists()
    finally:
        manager.close()


def test_database_migrates_legacy_library_dir(tmp_path, monkeypatch):
    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    lib = tmp_path / "Source" / "Assets"
    lib.parent.mkdir()
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


def test_database_fails_closed_when_legacy_migration_fails(tmp_path, monkeypatch):
    import pytest
    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    lib = tmp_path / "Source" / "Assets"
    lib.parent.mkdir()
    legacy = runtime / "Assets"
    legacy.mkdir(parents=True)
    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)
    monkeypatch.setattr(database, "RUNTIME_ROOT", runtime)

    def fail_move(*_args, **_kwargs):
        raise OSError("injected migration failure")

    monkeypatch.setattr(database.shutil, "move", fail_move)
    manager = database.DatabaseManager()
    with pytest.raises(RuntimeError, match="Legacy RuntimeData migration failed"):
        manager.connection_for(lib)

    assert legacy.exists()
    assert not path_resolver.library_data_dir(lib).exists()
    # Keep the formal identity reservation so a later opener cannot claim a
    # partially prepared slot for a different root identity.
    assert path_resolver.library_data_identity_path(lib).exists()


def test_legacy_migration_fails_closed_for_reserved_runtime_dirs(tmp_path, monkeypatch):
    import pytest
    from AssetsManager.core import database, path_resolver

    reserved_names = ("Shared", "shared", "SHARED", "_orphaned", "_ORPHANED")

    def fail_move(*_args, **_kwargs):
        raise AssertionError("reserved RuntimeData directory must not be migrated")

    monkeypatch.setattr(database.shutil, "move", fail_move)
    for index, name in enumerate(reserved_names):
        runtime = tmp_path / str(index) / "RuntimeData"
        lib = tmp_path / str(index) / "library" / name
        lib.parent.mkdir(parents=True)
        legacy = runtime / name
        legacy.mkdir(parents=True)
        sentinel = legacy / "keep.txt"
        sentinel.write_text(name, encoding="utf-8")

        monkeypatch.setattr(path_resolver, "runtime_root", lambda runtime=runtime: runtime)
        monkeypatch.setattr(database, "RUNTIME_ROOT", runtime)

        manager = database.DatabaseManager()
        try:
            with pytest.raises(RuntimeError, match="Reserved RuntimeData directory cannot be migrated"):
                manager.open_library(lib)
            hashed = path_resolver.library_data_dir(lib)
            assert not hashed.exists()
            assert sentinel.read_text(encoding="utf-8") == name
            assert legacy.exists()
            # A reserved RuntimeData basename still owns its identity marker;
            # do not release the collision guard on a failed open.
            assert path_resolver.library_data_identity_path(lib).exists()
        finally:
            manager.close()


def test_clean_orphan_dirs_preserves_marked_non_current_hashed_data(tmp_path, monkeypatch):
    import os
    import time
    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    current = tmp_path / "Current" / "Assets"
    other = tmp_path / "Other" / "Assets"
    current.mkdir(parents=True)
    other.mkdir(parents=True)
    current_name = path_resolver.library_data_name(current)
    other_name = path_resolver.library_data_name(other)
    current_data = runtime / current_name
    other_data = runtime / other_name
    current_data.mkdir(parents=True)
    other_data.mkdir(parents=True)
    (other_data / "metadata.json").write_text("must survive", encoding="utf-8")
    shared = runtime / "Shared"
    shared.mkdir(parents=True)
    (shared / f"{other_name}.identity").write_text(
        path_resolver.root_identity(other, strict=False).map_key,
        encoding="utf-8",
    )
    old_time = time.time() - 8 * 86400
    os.utime(str(other_data), (old_time, old_time))

    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)
    monkeypatch.setattr(database, "RUNTIME_ROOT", runtime)

    database.DatabaseManager.clean_orphan_dirs([str(current)])

    assert current_data.exists()
    assert other_data.exists()
    assert (other_data / "metadata.json").read_text(encoding="utf-8") == "must survive"
    assert not (runtime / "_orphaned" / other_name).exists()


def test_clean_orphan_dirs_keeps_known_and_quarantines_old_dirs(tmp_path, monkeypatch):
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
    (orphan / "marker.txt").write_text("recoverable", encoding="utf-8")

    old_time = time.time() - 8 * 86400
    os.utime(str(orphan), (old_time, old_time))

    monkeypatch.setattr(database, "RUNTIME_ROOT", runtime)

    database.DatabaseManager.clean_orphan_dirs([str(lib)])

    assert hashed.exists()
    assert legacy.exists()
    assert shared.exists()
    assert not orphan.exists()
    quarantine = runtime / "_orphaned"
    moved = tuple(quarantine.glob("Old*"))
    assert len(moved) == 1
    assert (moved[0] / "marker.txt").read_text(encoding="utf-8") == "recoverable"


def test_clean_orphan_dirs_preserves_quarantine_collisions_and_recent_dirs(
    tmp_path, monkeypatch
):
    import os
    import time
    from AssetsManager.core import database

    runtime = tmp_path / "RuntimeData"
    runtime.mkdir(parents=True)
    quarantine = runtime / "_orphaned"
    existing = quarantine / "Old"
    existing.mkdir(parents=True)
    (existing / "keep.txt").write_text("existing", encoding="utf-8")

    old_orphan = runtime / "Old"
    old_orphan.mkdir()
    (old_orphan / "move.txt").write_text("move", encoding="utf-8")
    old_time = time.time() - 8 * 86400
    os.utime(str(old_orphan), (old_time, old_time))

    recent = runtime / "Recent"
    recent.mkdir()

    monkeypatch.setattr(database, "RUNTIME_ROOT", runtime)

    database.DatabaseManager.clean_orphan_dirs([])

    assert not old_orphan.exists()
    assert (existing / "keep.txt").read_text(encoding="utf-8") == "existing"
    moved = tuple(path for path in quarantine.glob("Old*") if path != existing)
    assert len(moved) == 1
    assert (moved[0] / "move.txt").read_text(encoding="utf-8") == "move"
    assert recent.exists()


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


def test_sql_like_helpers_escape_wildcards_and_preserve_path_separator():
    from AssetsManager.core.path_resolver import (
        escape_sql_like,
        path_key_separator,
        sql_like_descendant_pattern,
    )

    windows = r"C:\library\100%_files"
    portable = "C:/library/100%_files"

    assert path_key_separator(windows) == "\\"
    assert path_key_separator(portable) == "/"
    assert escape_sql_like(windows) == r"C:\\library\\100\%\_files"
    assert sql_like_descendant_pattern(windows).endswith(r"\\%")
    assert sql_like_descendant_pattern(portable).endswith("/%")


def test_sql_like_descendant_pattern_does_not_match_same_prefix_sibling():
    import sqlite3

    from AssetsManager.core.path_resolver import sql_like_descendant_pattern

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE paths (file_path TEXT)")
    conn.executemany(
        "INSERT INTO paths(file_path) VALUES (?)",
        [
            (r"C:\library\folder",),
            (r"C:\library\folder\asset.png",),
            (r"C:\library\folder-copy\asset.png",),
        ],
    )

    root = r"C:\library\folder"
    pattern = sql_like_descendant_pattern(root)
    rows = conn.execute(
        "SELECT file_path FROM paths WHERE file_path=? OR file_path LIKE ? ESCAPE '\\' ORDER BY file_path",
        (root, pattern),
    ).fetchall()

    assert [row[0] for row in rows] == [
        r"C:\library\folder",
        r"C:\library\folder\asset.png",
    ]


def test_remap_path_subtree_respects_windows_and_portable_boundaries():
    from AssetsManager.core.path_resolver import remap_path_subtree

    assert remap_path_subtree(
        r"C:\library\folder",
        r"D:\archive\folder",
        r"C:\library\folder\asset.png",
    ) == r"D:\archive\folder\asset.png"
    assert remap_path_subtree(
        "C:/library/folder",
        "D:/archive/folder",
        "C:/library/folder/asset.png",
    ) == "D:/archive/folder/asset.png"
    assert remap_path_subtree(
        r"C:\library\folder",
        r"D:\archive\folder",
        r"C:\library\folder-copy\asset.png",
    ) == r"C:\library\folder-copy\asset.png"


def test_database_identity_publish_is_no_clobber_and_cleans_only_own_temp(
    tmp_path, monkeypatch
):
    from pathlib import Path

    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    root = tmp_path / "library"
    root.mkdir()
    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)

    identity = path_resolver.root_identity(root, strict=False)
    marker = path_resolver.library_data_identity_path(identity)
    real_link = database.os.link
    calls = []

    def racing_link(source, destination):
        calls.append(Path(source))
        if len(calls) == 1:
            Path(destination).write_text("winner", encoding="utf-8")
            raise FileExistsError(17, "marker won by another claimant")
        return real_link(source, destination)

    monkeypatch.setattr(database.os, "link", racing_link)

    import pytest

    with pytest.raises(RuntimeError, match="identity collision"):
        database.DatabaseManager._ensure_library_data_identity(identity)

    assert marker.read_text(encoding="utf-8") == "winner"
    assert len(calls) == 1
    assert not tuple(marker.parent.glob(f".{marker.name}.*.tmp"))


def test_database_identity_rejects_corrupt_formal_marker_without_clobbering_it(
    tmp_path, monkeypatch
):
    import pytest
    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    root = tmp_path / "library"
    root.mkdir()
    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)

    identity = path_resolver.root_identity(root, strict=False)
    marker = path_resolver.library_data_identity_path(identity)
    marker.parent.mkdir(parents=True)
    marker.mkdir()

    with pytest.raises(RuntimeError, match="Invalid formal RuntimeData identity marker"):
        database.DatabaseManager._ensure_library_data_identity(identity)

    assert marker.is_dir()


def test_database_identity_rejects_corrupt_pending_marker_without_publishing(
    tmp_path, monkeypatch
):
    import pytest
    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    root = tmp_path / "library"
    root.mkdir()
    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)

    identity = path_resolver.root_identity(root, strict=False)
    marker = path_resolver.library_data_identity_path(identity)
    pending = marker.with_name(marker.name + ".pending")
    pending.parent.mkdir(parents=True)
    pending.mkdir()

    with pytest.raises(RuntimeError, match="Invalid pending RuntimeData identity marker"):
        database.DatabaseManager._ensure_library_data_identity(identity)

    assert not marker.exists()
    assert pending.is_dir()



def test_database_identity_flushes_published_marker_directory(tmp_path, monkeypatch):
    from pathlib import Path

    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    root = tmp_path / "library"
    root.mkdir()
    (runtime / "Shared").mkdir(parents=True)
    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)

    identity = path_resolver.root_identity(root, strict=False)
    calls = []
    monkeypatch.setattr(
        database,
        "_flush_directory_durable",
        lambda directory: calls.append(Path(directory)),
    )

    assert database.DatabaseManager._ensure_library_data_identity(identity) is True
    marker = path_resolver.library_data_identity_path(identity)
    assert calls == [marker.parent]
    assert marker.read_text(encoding="utf-8") == identity.map_key


def test_database_identity_flushes_new_directory_ancestors(tmp_path, monkeypatch):
    from pathlib import Path

    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "outer" / "RuntimeData"
    root = tmp_path / "library"
    root.mkdir()
    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)

    identity = path_resolver.root_identity(root, strict=False)
    calls = []
    monkeypatch.setattr(
        database,
        "_flush_directory_durable",
        lambda directory: calls.append(Path(directory)),
    )

    assert database.DatabaseManager._ensure_library_data_identity(identity) is True
    marker = path_resolver.library_data_identity_path(identity)
    assert calls == [
        marker.parent,
        runtime,
        runtime.parent,
        runtime.parent.parent,
    ]
    assert marker.read_text(encoding="utf-8") == identity.map_key


def test_database_identity_durability_failure_keeps_formal_marker_and_fails_closed(
    tmp_path, monkeypatch
):
    import pytest
    from AssetsManager.core import database, path_resolver

    runtime = tmp_path / "RuntimeData"
    root = tmp_path / "library"
    root.mkdir()
    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)

    identity = path_resolver.root_identity(root, strict=False)

    def fail_flush(_directory):
        raise OSError("directory flush unavailable")

    monkeypatch.setattr(database, "_flush_directory_durable", fail_flush)

    with pytest.raises(
        RuntimeError,
        match="published but directory durability could not be confirmed",
    ):
        database.DatabaseManager._ensure_library_data_identity(identity)

    marker = path_resolver.library_data_identity_path(identity)
    assert marker.read_text(encoding="utf-8") == identity.map_key
    assert not tuple(marker.parent.glob(f".{marker.name}.*.tmp"))


def test_flush_directory_durable_current_platform(tmp_path):
    from AssetsManager.core import database

    # This is the small platform integration check: POSIX exercises a
    # directory fd + fsync, while Windows exercises CreateFileW with
    # FILE_FLAG_BACKUP_SEMANTICS + FlushFileBuffers. Unsupported filesystems
    # must fail rather than being reported as durable.
    database._flush_directory_durable(tmp_path)
