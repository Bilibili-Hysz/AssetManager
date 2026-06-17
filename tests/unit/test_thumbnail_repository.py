"""Tests for repositories/thumbnail_repository.py."""
import sqlite3

import pytest

from AssetsManager.core import database
from AssetsManager.core.db_migrations import migrate
from AssetsManager.repositories.thumbnail_repository import ThumbnailRepository


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.executescript(database._SCHEMA)
    migrate(c)
    yield c
    c.close()


@pytest.fixture
def repo(conn):
    return ThumbnailRepository(conn)


class TestThumbnailRepository:

    def test_get_source_mtime_empty(self, repo, conn):
        assert repo.get_source_mtime("nonexistent") is None

    def test_upsert_and_get(self, repo, conn):
        repo.upsert_entry("key1", "/path/img.png", 1234.0, 1024, 800, 500)
        mtime = repo.get_source_mtime("key1")
        assert mtime == 1234.0

    def test_delete_entry(self, repo, conn):
        repo.upsert_entry("key1", "/path/img.png", 1234.0, 1024, 800, 500)
        repo.delete_entry("key1")
        assert repo.get_source_mtime("key1") is None

    def test_list_all(self, repo, conn):
        repo.upsert_entry("key1", "/a.png", 1.0, 100, 80, 50)
        repo.upsert_entry("key2", "/b.png", 2.0, 200, 160, 100)
        entries = repo.list_all()
        assert len(entries) == 2
        paths = {e[1] for e in entries}
        assert "/a.png" in paths
        assert "/b.png" in paths

    def test_clear_all(self, repo, conn):
        repo.upsert_entry("key1", "/a.png", 1.0, 100, 80, 50)
        repo.upsert_entry("key2", "/b.png", 2.0, 200, 160, 100)
        repo.clear_all()
        assert repo.list_all() == []

    def test_delete_by_key(self, repo, conn):
        repo.upsert_entry("key1", "/a.png", 1.0, 100, 80, 50)
        repo.delete_by_key("key1")
        assert repo.get_source_mtime("key1") is None

    def test_touch_access(self, repo, conn):
        repo.upsert_entry("key1", "/a.png", 1.0, 100, 80, 50)
        # touch_access should not raise
        repo.touch_access("key1")

    def test_upsert_overwrites(self, repo, conn):
        repo.upsert_entry("key1", "/a.png", 1.0, 100, 80, 50)
        repo.upsert_entry("key1", "/a.png", 2.0, 200, 160, 100)
        mtime = repo.get_source_mtime("key1")
        assert mtime == 2.0
