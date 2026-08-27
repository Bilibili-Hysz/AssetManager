"""Tests for repositories/revoked_token_repository.py."""
import sqlite3

import pytest

from AssetsManager.core import database
from AssetsManager.core.db_migrations import migrate
from AssetsManager.repositories.revoked_token_repository import RevokedTokenRepository


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.executescript(database._SCHEMA)
    migrate(c)
    yield c
    c.close()


@pytest.fixture
def repo(conn):
    return RevokedTokenRepository(conn)


class TestRevokedTokenRepository:

    def test_is_revoked_empty(self, repo):
        assert repo.is_revoked("a" * 64) is False

    def test_add_and_is_revoked_roundtrip(self, repo):
        repo.add("a" * 64, expires_at=200.0, revoked_at=100.0)
        assert repo.is_revoked("a" * 64, now=150.0) is True
        assert repo.is_revoked("b" * 64, now=150.0) is False

    def test_expired_revocation_is_not_revoked(self, repo):
        repo.add("a" * 64, expires_at=200.0, revoked_at=100.0)
        assert repo.is_revoked("a" * 64, now=250.0) is False

    def test_load_active_filters_expired_rows(self, repo):
        repo.add("a" * 64, expires_at=200.0, revoked_at=100.0)
        repo.add("b" * 64, expires_at=300.0, revoked_at=100.0)
        assert repo.load_active(now=150.0) == {"a" * 64: 200.0, "b" * 64: 300.0}
        assert repo.load_active(now=250.0) == {"b" * 64: 300.0}

    def test_prune_expired_removes_only_expired_rows(self, repo):
        repo.add("a" * 64, expires_at=200.0, revoked_at=100.0)
        repo.add("b" * 64, expires_at=300.0, revoked_at=100.0)
        assert repo.prune_expired(now=250.0) == 1
        assert repo.load_active(now=250.0) == {"b" * 64: 300.0}

    def test_add_without_commit_leaves_caller_transaction_authoritative(self, conn, repo):
        """A caller-owned transaction is never committed by the repository."""
        conn.execute("CREATE TABLE marker (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.execute("INSERT INTO marker (id) VALUES (1)")
        repo.add("a" * 64, expires_at=200.0, commit=False)
        assert conn.in_transaction
        conn.rollback()
        assert conn.execute("SELECT 1 FROM marker").fetchone() is None
        assert repo.is_revoked("a" * 64) is False

    def test_schema_check_does_not_commit_caller_transaction(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        repo = RevokedTokenRepository(conn)
        try:
            conn.execute("CREATE TABLE marker (id INTEGER PRIMARY KEY)")
            conn.commit()
            conn.execute("BEGIN")
            conn.execute("INSERT INTO marker (id) VALUES (1)")
            assert repo.is_revoked("a" * 64) is False
            assert conn.in_transaction
            conn.rollback()
            assert conn.execute("SELECT 1 FROM marker").fetchone() is None
            assert conn.execute(
                "SELECT name FROM sqlite_master WHERE name = 'revoked_tokens'"
            ).fetchone() is None
        finally:
            conn.close()
