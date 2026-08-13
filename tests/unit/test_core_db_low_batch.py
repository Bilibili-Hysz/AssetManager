"""Low-batch regression tests for AssetsManager/core/database.py fixes.

Covers:
- Bug 1: ``migrate_path_metadata`` never deletes rows whose path the
  case-sensitive remap did not change (LIKE-collected case variants survive).
- Bug 6: ``db_write_lock`` rejects read-holder -> write and write-holder ->
  read nesting instead of deadlocking.
- Bug 10: a failed legacy directory move is treated as already done when the
  hashed destination already carries the database payload (idempotent TOCTOU
  recovery).
- Bug 11: ``clean_orphan_dirs`` protects RuntimeData slots of libraries that
  are recorded in settings but currently offline (their roots do not exist).
- Bug 16: thumbnail migration keeps the old thumbnail file when the
  destination key already exists (no silent delete without regeneration).
"""
import os
import sqlite3
import time

import pytest

from AssetsManager.core import database as database_module
from AssetsManager.core import path_resolver


def test_migrate_path_metadata_preserves_case_variant_rows(tmp_path, monkeypatch):
    """LIKE-collected rows that the case-sensitive remap leaves alone survive."""
    runtime = tmp_path / "RuntimeData"
    lib = tmp_path / "Library"
    lib.mkdir()
    # Non-existent subtree names: resolve() preserves the caller's case, which
    # keeps the test deterministic on case-insensitive filesystems too.
    old_dir = lib / "OldSub"
    new_dir = lib / "NewSub"
    exact_child = str((old_dir / "child.txt").resolve())
    variant_child = str((lib / "oldsub" / "child.txt").resolve())
    assert variant_child != exact_child

    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)
    monkeypatch.setattr(database_module, "RUNTIME_ROOT", runtime)
    manager = database_module.DatabaseManager()
    try:
        conn = manager.connection_for(lib)
        conn.execute(
            "INSERT INTO file_tags (file_path, tag) VALUES (?,?)",
            (exact_child, "exact"),
        )
        conn.execute(
            "INSERT INTO file_tags (file_path, tag) VALUES (?,?)",
            (variant_child, "variant"),
        )
        conn.execute(
            "INSERT INTO file_meta (file_path, notes) VALUES (?,?)",
            (exact_child, "exact"),
        )
        conn.execute(
            "INSERT INTO file_meta (file_path, notes) VALUES (?,?)",
            (variant_child, "variant"),
        )
        conn.commit()

        database_module.migrate_path_metadata(
            conn, manager.thumb_dir_for(lib), old_dir, new_dir
        )

        moved_child = str((new_dir / "child.txt").resolve())
        # The exact-case row is migrated to the new subtree...
        assert conn.execute(
            "SELECT tag FROM file_tags WHERE file_path=?", (moved_child,)
        ).fetchone() == ("exact",)
        assert conn.execute(
            "SELECT notes FROM file_meta WHERE file_path=?", (moved_child,)
        ).fetchone() == ("exact",)
        # ...its old exact key is removed...
        assert conn.execute(
            "SELECT 1 FROM file_tags WHERE file_path=?", (exact_child,)
        ).fetchone() is None
        # ...and the LIKE-collected case variant is preserved untouched.
        assert conn.execute(
            "SELECT tag FROM file_tags WHERE file_path=?", (variant_child,)
        ).fetchone() == ("variant",)
        assert conn.execute(
            "SELECT notes FROM file_meta WHERE file_path=?", (variant_child,)
        ).fetchone() == ("variant",)
    finally:
        manager.close()


def test_db_write_lock_rejects_read_holder_acquiring_global_write(tmp_path):
    """Read-holder -> no-argument write nesting must fail fast, not deadlock."""
    manager = database_module.DatabaseManager()
    try:
        conn = manager.connection_for(tmp_path / "library")
        with database_module.db_write_lock(conn):
            with pytest.raises(RuntimeError, match="this would deadlock"):
                with database_module.db_write_lock():
                    pass
    finally:
        manager.close()


def test_db_write_lock_rejects_global_writer_acquiring_connection_read(tmp_path):
    """Global-write-holder -> connection read nesting must fail fast."""
    manager = database_module.DatabaseManager()
    try:
        conn = manager.connection_for(tmp_path / "library")
        with database_module.db_write_lock():
            with pytest.raises(RuntimeError, match="this would deadlock"):
                with database_module.db_write_lock(conn):
                    pass
    finally:
        manager.close()


def test_open_library_idempotent_when_legacy_move_failed_after_destination_ready(
    tmp_path, monkeypatch
):
    """A failed legacy move with an already-populated hashed dir must not fail."""
    runtime = tmp_path / "RuntimeData"
    lib = tmp_path / "Source" / "Assets"
    lib.parent.mkdir(parents=True)
    legacy = runtime / "Assets"
    legacy.mkdir(parents=True)
    (legacy / "legacy.txt").write_text("legacy", encoding="utf-8")

    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)
    monkeypatch.setattr(database_module, "RUNTIME_ROOT", runtime)

    hashed = path_resolver.library_data_dir(lib)

    def losing_move(*_args, **_kwargs):
        # A concurrent opener wins the race between our exists() check and our
        # move call: it publishes the hashed destination with its database
        # payload, removes the legacy source, and our own move call fails.
        hashed.mkdir(parents=True)
        sqlite3.connect(str(database_module.db_path(lib))).close()
        (legacy / "legacy.txt").unlink()
        legacy.rmdir()
        raise OSError("injected migration failure")

    monkeypatch.setattr(database_module.shutil, "move", losing_move)

    manager = database_module.DatabaseManager()
    try:
        conn = manager.connection_for(lib)
        assert conn.execute("SELECT 1").fetchone() == (1,)
        assert hashed.exists()
    finally:
        manager.close()


def test_open_library_still_fails_when_legacy_move_failed_without_destination(
    tmp_path, monkeypatch
):
    """A failed move without a ready destination keeps the hard failure."""
    runtime = tmp_path / "RuntimeData"
    lib = tmp_path / "Source" / "Assets"
    lib.parent.mkdir(parents=True)
    legacy = runtime / "Assets"
    legacy.mkdir(parents=True)
    (legacy / "legacy.txt").write_text("legacy", encoding="utf-8")

    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)
    monkeypatch.setattr(database_module, "RUNTIME_ROOT", runtime)

    def fail_move(*_args, **_kwargs):
        raise OSError("injected migration failure")

    monkeypatch.setattr(database_module.shutil, "move", fail_move)

    manager = database_module.DatabaseManager()
    try:
        with pytest.raises(RuntimeError, match="Legacy RuntimeData migration failed"):
            manager.connection_for(lib)
        assert legacy.exists()
        assert not path_resolver.library_data_dir(lib).exists()
    finally:
        manager.close()


def test_clean_orphan_dirs_protects_persisted_offline_library_slots(
    tmp_path, monkeypatch
):
    """Settings-recorded roots keep their slots even while offline (>7 days)."""
    runtime = tmp_path / "RuntimeData"
    # The library root is deliberately never created: it models a library on a
    # currently disconnected drive that is still recorded in settings.
    offline = tmp_path / "Detached" / "Assets"
    legacy = runtime / "Assets"
    hashed = runtime / database_module.library_data_name(str(offline))
    orphan = runtime / "Old"
    for path in (legacy, hashed, orphan):
        path.mkdir(parents=True)
    (legacy / "legacy.db").write_text("legacy", encoding="utf-8")
    (hashed / "metadata.json").write_text("hashed", encoding="utf-8")
    (orphan / "recoverable.txt").write_text("recoverable", encoding="utf-8")
    old_time = time.time() - 8 * 86400
    os.utime(str(legacy), (old_time, old_time))
    os.utime(str(hashed), (old_time, old_time))
    os.utime(str(orphan), (old_time, old_time))

    monkeypatch.setattr(database_module, "RUNTIME_ROOT", runtime)
    monkeypatch.setattr(
        database_module, "_persisted_library_roots", lambda: [str(offline)]
    )

    database_module.DatabaseManager.clean_orphan_dirs([])

    assert legacy.exists()
    assert hashed.exists()
    assert (legacy / "legacy.db").read_text(encoding="utf-8") == "legacy"
    assert (hashed / "metadata.json").read_text(encoding="utf-8") == "hashed"
    assert not orphan.exists()
    quarantine = runtime / "_orphaned"
    assert tuple(quarantine.glob("Old*"))


def test_clean_orphan_dirs_ignores_settings_failure(tmp_path, monkeypatch):
    """A broken settings lookup must not turn cleanup into a destructive sweep."""
    runtime = tmp_path / "RuntimeData"
    old_orphan = runtime / "Old"
    old_orphan.mkdir(parents=True)
    (old_orphan / "recoverable.txt").write_text("recoverable", encoding="utf-8")
    old_time = time.time() - 8 * 86400
    os.utime(str(old_orphan), (old_time, old_time))

    from AssetsManager.core.singleton import ThreadSafeSingleton

    monkeypatch.setattr(database_module, "RUNTIME_ROOT", runtime)

    def broken_settings(_type):
        raise RuntimeError("settings unavailable")

    monkeypatch.setattr(ThreadSafeSingleton, "get", broken_settings)

    # The registry lookup degrades to an empty list instead of raising, and
    # cleanup proceeds with the marker-based protection only.
    assert database_module._persisted_library_roots() == []
    database_module.DatabaseManager.clean_orphan_dirs([])
    assert not old_orphan.exists()


def test_migrate_path_metadata_keeps_old_thumbnail_when_new_key_exists(
    tmp_path, monkeypatch
):
    """A pre-existing destination thumbnail is kept, not silently deleted."""
    runtime = tmp_path / "RuntimeData"
    lib = tmp_path / "Library"
    old = lib / "old.png"
    new = lib / "new.png"
    lib.mkdir()
    old.write_text("old", encoding="utf-8")
    new.write_text("new", encoding="utf-8")

    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)
    monkeypatch.setattr(database_module, "RUNTIME_ROOT", runtime)
    manager = database_module.DatabaseManager()
    try:
        conn = manager.connection_for(lib)
        old_key = database_module._thumbnail_cache_key(str(old.resolve()))
        new_key = database_module._thumbnail_cache_key(str(new.resolve()))
        assert old_key != new_key
        thumb_dir = manager.thumb_dir_for(lib)
        thumb_dir.mkdir(parents=True, exist_ok=True)
        old_file = thumb_dir / f"{old_key}.webp"
        new_file = thumb_dir / f"{new_key}.webp"
        old_file.write_bytes(b"old-thumb")
        new_file.write_bytes(b"new-thumb")
        conn.execute(
            "INSERT INTO thumbnail_cache (cache_key, source_path, source_mtime) "
            "VALUES (?,?,?)",
            (old_key, str(old.resolve()), 1.0),
        )
        conn.commit()

        database_module.migrate_path_metadata(conn, thumb_dir, old, new)

        # The cache row is repointed at the destination key...
        row = conn.execute(
            "SELECT source_path FROM thumbnail_cache WHERE cache_key=?",
            (new_key,),
        ).fetchone()
        assert row == (str(new.resolve()),)
        # ...the pre-existing destination thumbnail is untouched...
        assert new_file.read_bytes() == b"new-thumb"
        # ...and the old file is preserved instead of being deleted.
        assert old_file.exists()
    finally:
        manager.close()
