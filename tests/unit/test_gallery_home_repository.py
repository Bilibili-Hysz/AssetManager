"""Tests for repositories/gallery_home_repository.py."""
import sqlite3

import pytest

from AssetsManager.core import database
from AssetsManager.core.db_migrations import migrate
from AssetsManager.repositories.gallery_home_repository import GalleryHomeRepository


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.executescript(database._SCHEMA)
    migrate(c)
    yield c
    c.close()


@pytest.fixture
def repo(conn):
    return GalleryHomeRepository(conn)


class TestGalleryHomeRepository:

    def test_get_empty(self, repo):
        assert repo.get() is None

    def test_save_and_get_roundtrip(self, repo):
        repo.save(1234.5, '{"featured": null}')
        assert repo.get() == (1234.5, '{"featured": null}')

    def test_save_replaces_previous_projection(self, repo):
        repo.save(1.0, '{"projects": [1]}')
        repo.save(2.0, '{"projects": [2]}')
        assert repo.get() == (2.0, '{"projects": [2]}')

    def test_delete_removes_projection(self, repo):
        repo.save(1.0, "{}")
        repo.delete()
        assert repo.get() is None

    def test_delete_on_missing_row_is_a_noop(self, repo):
        repo.delete()
        assert repo.get() is None

    def test_save_without_commit_leaves_caller_transaction_authoritative(self, conn, repo):
        """A caller-owned transaction is never committed by the repository."""
        conn.execute("CREATE TABLE marker (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.execute("INSERT INTO marker (id) VALUES (1)")
        repo.save(1.0, "{}", commit=False)
        assert conn.in_transaction
        conn.rollback()
        assert conn.execute("SELECT 1 FROM marker").fetchone() is None
        # The save itself was rolled back with the caller transaction.
        assert repo.get() is None
