"""Tests for directory_cache schema and migration."""
import sqlite3

import pytest

from AssetsManager.core import database
from AssetsManager.core.db_migrations import CURRENT_SCHEMA_VERSION, current_version, migrate


def _migrate_with_baseline(conn: sqlite3.Connection) -> int:
    conn.executescript(database._SCHEMA)
    return migrate(conn)


def test_migration_v5_creates_directory_cache(memory_db: sqlite3.Connection):
    _migrate_with_baseline(memory_db)
    rows = memory_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='directory_cache'"
    ).fetchall()
    assert len(rows) == 1


def test_directory_cache_columns(memory_db: sqlite3.Connection):
    _migrate_with_baseline(memory_db)
    info = memory_db.execute("PRAGMA table_info(directory_cache)").fetchall()
    col_names = [row[1] for row in info]
    assert "dir_path" in col_names
    assert "item_count" in col_names
    assert "preview_path" in col_names
    assert "mtime" in col_names
    assert "scanned_at" in col_names


def test_directory_cache_primary_key(memory_db: sqlite3.Connection):
    _migrate_with_baseline(memory_db)
    info = memory_db.execute("PRAGMA table_info(directory_cache)").fetchall()
    pk_cols = [row[1] for row in info if row[5] > 0]
    assert pk_cols == ["dir_path"]


def test_schema_version_after_latest_migration(memory_db: sqlite3.Connection):
    _migrate_with_baseline(memory_db)
    assert current_version(memory_db) == CURRENT_SCHEMA_VERSION


def test_directory_cache_insert_and_query(memory_db: sqlite3.Connection):
    _migrate_with_baseline(memory_db)
    memory_db.execute(
        "INSERT INTO directory_cache (dir_path, item_count, preview_path, mtime) "
        "VALUES (?, ?, ?, ?)",
        ("/some/dir", 42, "/some/dir/preview.webp", 1700000000.0),
    )
    memory_db.commit()
    row = memory_db.execute(
        "SELECT dir_path, item_count, preview_path, mtime FROM directory_cache WHERE dir_path = ?",
        ("/some/dir",),
    ).fetchone()
    assert row == ("/some/dir", 42, "/some/dir/preview.webp", 1700000000.0)


def test_directory_cache_set_and_get(memory_db: sqlite3.Connection):
    _migrate_with_baseline(memory_db)
    from AssetsManager.core.directory_cache import DirectoryCache
    cache = DirectoryCache(memory_db)
    cache.set('/lib/subdir', item_count=42, preview_path='/lib/subdir/preview.jpg', mtime=1000.0)
    result = cache.get('/lib/subdir')
    assert result is not None
    assert result.item_count == 42
    assert result.preview_path == '/lib/subdir/preview.jpg'


def test_directory_cache_returns_none_for_missing(memory_db: sqlite3.Connection):
    _migrate_with_baseline(memory_db)
    from AssetsManager.core.directory_cache import DirectoryCache
    cache = DirectoryCache(memory_db)
    assert cache.get('/nonexistent') is None


def test_directory_cache_invalidates_on_mtime_change(memory_db: sqlite3.Connection):
    _migrate_with_baseline(memory_db)
    from AssetsManager.core.directory_cache import DirectoryCache
    cache = DirectoryCache(memory_db)
    cache.set('/lib/sub', item_count=10, preview_path=None, mtime=1000.0)
    result = cache.get('/lib/sub', mtime=1000.0)
    assert result is not None
    result = cache.get('/lib/sub', mtime=2000.0)
    assert result is None


def test_directory_cache_batch_set(memory_db: sqlite3.Connection):
    _migrate_with_baseline(memory_db)
    from AssetsManager.core.directory_cache import DirectoryCache
    cache = DirectoryCache(memory_db)
    entries = [
        ('/lib/a', 5, None, 1000.0),
        ('/lib/b', 10, '/lib/b/img.jpg', 2000.0),
    ]
    cache.set_batch(entries)
    first = cache.get('/lib/a')
    second = cache.get('/lib/b')
    assert first is not None
    assert second is not None
    assert first.item_count == 5
    assert second.item_count == 10


def test_directory_cache_batch_get(memory_db: sqlite3.Connection):
    _migrate_with_baseline(memory_db)
    from AssetsManager.core.directory_cache import DirectoryCache
    cache = DirectoryCache(memory_db)
    cache.set_batch([
        ('/lib/a', 5, None, 1000.0),
        ('/lib/b', 10, '/lib/b/img.jpg', 2000.0),
    ])

    entries = cache.get_batch(['/lib/a', '/lib/missing', '/lib/b'])

    assert set(entries) == {'/lib/a', '/lib/b'}
    assert entries['/lib/b'].preview_path == '/lib/b/img.jpg'


def test_directory_cache_batch_get_chunks_over_500_paths(memory_db: sqlite3.Connection):
    _migrate_with_baseline(memory_db)
    from AssetsManager.core.directory_cache import DirectoryCache
    cache = DirectoryCache(memory_db)
    paths = [f'/lib/{index}' for index in range(501)]
    cache.set_batch([(path, index, None, float(index)) for index, path in enumerate(paths)])

    entries = cache.get_batch(paths)

    assert len(entries) == 501
    assert entries[paths[0]].item_count == 0
    assert entries[paths[-1]].item_count == 500


def test_directory_cache_does_not_commit_outer_transaction(memory_db: sqlite3.Connection):
    _migrate_with_baseline(memory_db)
    from AssetsManager.core.directory_cache import DirectoryCache
    cache = DirectoryCache(memory_db)
    memory_db.execute("BEGIN")
    cache.set('/lib/outer', 1, None, 100.0)
    # The caller-owned transaction must still be open: the cache write must
    # not have committed it early.
    assert memory_db.in_transaction
    memory_db.rollback()
    assert cache.get('/lib/outer') is None


def test_directory_cache_invalidate(memory_db: sqlite3.Connection):
    _migrate_with_baseline(memory_db)
    from AssetsManager.core.directory_cache import DirectoryCache
    cache = DirectoryCache(memory_db)
    cache.set('/lib/x', item_count=1, preview_path=None, mtime=100.0)
    assert cache.get('/lib/x') is not None
    cache.invalidate('/lib/x')
    assert cache.get('/lib/x') is None


def test_directory_cache_clear(memory_db: sqlite3.Connection):
    _migrate_with_baseline(memory_db)
    from AssetsManager.core.directory_cache import DirectoryCache
    cache = DirectoryCache(memory_db)
    cache.set('/lib/a', 1, None, 100.0)
    cache.set('/lib/b', 2, None, 200.0)
    cache.clear()
    assert cache.get('/lib/a') is None
    assert cache.get('/lib/b') is None


def test_directory_cache_rejects_managed_connection_for_foreign_root(tmp_path):
    from AssetsManager.core.database import DatabaseManager
    from AssetsManager.core.directory_cache import DirectoryCache

    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    manager = DatabaseManager()
    try:
        cache = DirectoryCache(manager.connection_for(root_b))

        with pytest.raises(ValueError, match="different library root"):
            cache.validate_for(root_a)
    finally:
        manager.close()


def test_directory_cache_raw_connection_compatibility_can_be_root_bound(memory_db, tmp_path):
    from AssetsManager.core.directory_cache import DirectoryCache

    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    cache = DirectoryCache(memory_db, library_root=root_a)

    cache.validate_for(root_a)
    with pytest.raises(ValueError, match="different library root"):
        cache.validate_for(root_b)
