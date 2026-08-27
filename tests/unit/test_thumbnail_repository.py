"""Tests for repositories/thumbnail_repository.py."""
import os
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

    def test_list_all_with_metadata_returns_stably_sorted_rows(self, repo):
        repo.upsert_entry("key-b", "/b.png", 2.0, 100, 80, 50)
        repo.upsert_entry("key-a", "/a.png", 2.0, 100, 80, 50)
        repo.upsert_entry("key-c", "/c.png", 1.0, 100, 80, 50)

        assert repo.list_all_with_metadata() == [
            ("key-a", "/a.png", 2.0),
            ("key-b", "/b.png", 2.0),
            ("key-c", "/c.png", 1.0),
        ]

    def test_clear_all(self, repo, conn):
        repo.upsert_entry("key1", "/a.png", 1.0, 100, 80, 50)
        repo.upsert_entry("key2", "/b.png", 2.0, 200, 160, 100)
        repo.clear_all()
        assert repo.list_all() == []

    def test_delete_by_key(self, repo, conn):
        repo.upsert_entry("key1", "/a.png", 1.0, 100, 80, 50)
        repo.delete_by_key("key1")
        assert repo.get_source_mtime("key1") is None

    def test_delete_path_removes_path_and_descendants(self, repo, conn):
        folder = os.path.join(os.sep, "library", "folder")
        repo.upsert_entry("root", folder, 1.0, 1, 1, 1)
        repo.upsert_entry("child", os.path.join(folder, "image.png"), 1.0, 1, 1, 1)
        repo.upsert_entry("other", os.path.join(os.sep, "library", "other.png"), 1.0, 1, 1, 1)

        assert repo.delete_path(folder) == ["root", "child"]
        assert repo.list_all() == [("other", os.path.join(os.sep, "library", "other.png"))]

    def test_delete_path_escapes_wildcards_in_source_path(self, repo, conn):
        repo.upsert_entry("root", "/lib/my_dir", 1.0, 1, 1, 1)
        repo.upsert_entry("child", "/lib/my_dir/img.png", 1.0, 1, 1, 1)
        repo.upsert_entry("wildcard-sibling", "/lib/myXdir/img.png", 1.0, 1, 1, 1)
        repo.upsert_entry("percent-dir", "/lib/50%_off/img.png", 1.0, 1, 1, 1)

        assert repo.delete_path("/lib/my_dir") == ["root", "child"]
        assert repo.list_all() == [
            ("wildcard-sibling", "/lib/myXdir/img.png"),
            ("percent-dir", "/lib/50%_off/img.png"),
        ]

    def test_delete_path_matches_stored_separator_style(self, repo, conn):
        # Keys stored with "/" must be cleaned even when os.sep differs.
        repo.upsert_entry("root", r"C:\lib\folder", 1.0, 1, 1, 1)
        repo.upsert_entry("child", r"C:\lib\folder\img.png", 1.0, 1, 1, 1)
        repo.upsert_entry("sibling", r"C:\lib\folder-extra.png", 1.0, 1, 1, 1)

        assert repo.delete_path(r"C:\lib\folder") == ["root", "child"]
        assert repo.list_all() == [("sibling", r"C:\lib\folder-extra.png")]

    def test_touch_access(self, repo, conn):
        repo.upsert_entry("key1", "/a.png", 1.0, 100, 80, 50)
        # touch_access should not raise
        repo.touch_access("key1")

    def test_touch_access_commit_false_preserves_outer_transaction(self, repo, conn):
        repo.upsert_entry("key1", "/a.png", 1.0, 100, 80, 50)
        conn.execute("BEGIN")
        repo.touch_access("key1", commit=False)
        assert conn.in_transaction
        conn.rollback()
        assert repo.get_entry("key1") is not None

    def test_upsert_overwrites(self, repo, conn):
        repo.upsert_entry("key1", "/a.png", 1.0, 100, 80, 50)
        repo.upsert_entry("key1", "/a.png", 2.0, 200, 160, 100)
        mtime = repo.get_source_mtime("key1")
        assert mtime == 2.0

    def test_metadata_round_trip_and_kind(self, repo):
        repo.upsert_entry(
            "video-key", "/video.mp4", 12.5, 1200, 512, 99,
            source_mtime_ns=12500000001, artifact_kind="jpg",
        )
        entry = repo.get_entry("video-key")
        assert entry is not None
        assert entry.source_mtime_ns == 12500000001
        assert entry.artifact_kind == "jpg"
        assert entry.cache_size == 99

    def test_upsert_preserves_created_at(self, repo):
        repo.upsert_entry("key", "/a.png", 1.0, 1, 1, 1)
        created = repo.get_entry("key").created_at
        repo.upsert_entry("key", "/a.png", 2.0, 2, 2, 2)
        assert repo.get_entry("key").created_at == created

    def test_eviction_candidates_are_stable_and_batch_delete(self, repo):
        repo.upsert_entry("b", "/b.png", 1.0, 1, 1, 20)
        repo.upsert_entry("a", "/a.png", 1.0, 1, 1, 20)
        repo.upsert_entry("c", "/c.png", 1.0, 1, 1, 20)
        candidates = repo.list_eviction_candidates()
        assert [item.cache_key for item in candidates] == ["a", "b", "c"]
        assert repo.delete_entries(["a", "c"]) == 2
        assert [item.cache_key for item in repo.list_metadata()] == ["b"]

    def test_delete_entries_commit_false_preserves_outer_transaction(self, repo, conn):
        repo.upsert_entry("key", "/a.png", 1.0, 1, 1, 1)
        conn.execute("BEGIN")
        assert repo.delete_entries(["key"], commit=False) == 1
        assert conn.in_transaction
        conn.rollback()
        assert repo.get_entry("key") is not None

    def test_upsert_commit_false_preserves_outer_transaction(self, repo, conn):
        conn.execute("BEGIN")
        repo.upsert_entry("key", "/a.png", 1.0, 1, 1, 1, commit=False)
        assert conn.in_transaction
        conn.rollback()
        assert repo.get_entry("key") is None

    def test_delete_if_matches_preserves_newer_row(self, repo):
        repo.upsert_entry("key", "/a.png", 1.0, 1, 1, 1)
        observed = repo.get_entry("key")
        repo.upsert_entry("key", "/a.png", 2.0, 2, 1, 2)
        assert observed is not None
        assert repo.delete_if_matches(observed) is False
        assert repo.get_entry("key").source_mtime == 2.0
