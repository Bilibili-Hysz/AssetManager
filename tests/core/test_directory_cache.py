"""Tests for directory_cache schema and migration."""
import sqlite3

from AssetsManager.core.db_migrations import migrate, current_version


def test_migration_v5_creates_directory_cache(memory_db: sqlite3.Connection):
    migrate(memory_db)
    rows = memory_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='directory_cache'"
    ).fetchall()
    assert len(rows) == 1


def test_directory_cache_columns(memory_db: sqlite3.Connection):
    migrate(memory_db)
    info = memory_db.execute("PRAGMA table_info(directory_cache)").fetchall()
    col_names = [row[1] for row in info]
    assert "dir_path" in col_names
    assert "item_count" in col_names
    assert "preview_path" in col_names
    assert "mtime" in col_names
    assert "scanned_at" in col_names


def test_directory_cache_primary_key(memory_db: sqlite3.Connection):
    migrate(memory_db)
    info = memory_db.execute("PRAGMA table_info(directory_cache)").fetchall()
    pk_cols = [row[1] for row in info if row[5] > 0]
    assert pk_cols == ["dir_path"]


def test_schema_version_after_v5(memory_db: sqlite3.Connection):
    migrate(memory_db)
    assert current_version(memory_db) == 5


def test_directory_cache_insert_and_query(memory_db: sqlite3.Connection):
    migrate(memory_db)
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
    migrate(memory_db)
    from AssetsManager.core.directory_cache import DirectoryCache
    cache = DirectoryCache(memory_db)
    cache.set('/lib/subdir', item_count=42, preview_path='/lib/subdir/preview.jpg', mtime=1000.0)
    result = cache.get('/lib/subdir')
    assert result is not None
    assert result.item_count == 42
    assert result.preview_path == '/lib/subdir/preview.jpg'


def test_directory_cache_returns_none_for_missing(memory_db: sqlite3.Connection):
    migrate(memory_db)
    from AssetsManager.core.directory_cache import DirectoryCache
    cache = DirectoryCache(memory_db)
    assert cache.get('/nonexistent') is None


def test_directory_cache_invalidates_on_mtime_change(memory_db: sqlite3.Connection):
    migrate(memory_db)
    from AssetsManager.core.directory_cache import DirectoryCache
    cache = DirectoryCache(memory_db)
    cache.set('/lib/sub', item_count=10, preview_path=None, mtime=1000.0)
    result = cache.get('/lib/sub', mtime=1000.0)
    assert result is not None
    result = cache.get('/lib/sub', mtime=2000.0)
    assert result is None


def test_directory_cache_batch_set(memory_db: sqlite3.Connection):
    migrate(memory_db)
    from AssetsManager.core.directory_cache import DirectoryCache
    cache = DirectoryCache(memory_db)
    entries = [
        ('/lib/a', 5, None, 1000.0),
        ('/lib/b', 10, '/lib/b/img.jpg', 2000.0),
    ]
    cache.set_batch(entries)
    assert cache.get('/lib/a').item_count == 5
    assert cache.get('/lib/b').item_count == 10


def test_directory_cache_invalidate(memory_db: sqlite3.Connection):
    migrate(memory_db)
    from AssetsManager.core.directory_cache import DirectoryCache
    cache = DirectoryCache(memory_db)
    cache.set('/lib/x', item_count=1, preview_path=None, mtime=100.0)
    assert cache.get('/lib/x') is not None
    cache.invalidate('/lib/x')
    assert cache.get('/lib/x') is None


def test_directory_cache_clear(memory_db: sqlite3.Connection):
    migrate(memory_db)
    from AssetsManager.core.directory_cache import DirectoryCache
    cache = DirectoryCache(memory_db)
    cache.set('/lib/a', 1, None, 100.0)
    cache.set('/lib/b', 2, None, 200.0)
    cache.clear()
    assert cache.get('/lib/a') is None
    assert cache.get('/lib/b') is None
