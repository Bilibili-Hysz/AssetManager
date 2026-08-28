"""Unit tests for repositories/_common.py shared write-safety plumbing.

Covers the two guarded-commit branches and the shared bounded SQLITE_BUSY
retry (fire once, then succeed) with discriminating negative cases: errors
that must NOT trigger a replay, and caller-owned transactions that must be
left untouched.
"""
from __future__ import annotations

import sqlite3

import pytest

from AssetsManager.core.database import SQLITE_BUSY_RETRY_ATTEMPTS
from AssetsManager.repositories._common import (
    _guarded_commit,
    _retry_sqlite_busy,
    _with_sqlite_busy_retry,
)


def _busy_error() -> sqlite3.OperationalError:
    return sqlite3.OperationalError("database is locked")


class TestGuardedCommit:
    def test_commits_and_returns_true_when_repository_owns_transaction(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE t (x)")
        # The flag must be sampled BEFORE the repository's own DML: managed
        # connections use deferred transaction control, so the INSERT below
        # opens an implicit transaction that must not be mistaken for a
        # caller-owned one.
        outer_transaction = conn.in_transaction
        assert outer_transaction is False

        conn.execute("INSERT INTO t VALUES (1)")
        assert conn.in_transaction is True

        performed = _guarded_commit(conn, outer_transaction=outer_transaction)

        assert performed is True
        assert conn.in_transaction is False
        assert conn.execute("SELECT x FROM t").fetchall() == [(1,)]

    def test_skips_commit_and_returns_false_inside_caller_transaction(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE t (x)")
        conn.commit()
        conn.execute("BEGIN")  # caller-owned outer transaction
        outer_transaction = conn.in_transaction
        assert outer_transaction is True

        conn.execute("INSERT INTO t VALUES (1)")
        performed = _guarded_commit(conn, outer_transaction=outer_transaction)

        # The caller transaction is still open and authoritative.
        assert performed is False
        assert conn.in_transaction is True
        conn.rollback()
        assert conn.execute("SELECT x FROM t").fetchall() == []


class _CountingConnection:
    """Forward every attribute to the real connection; count rollbacks."""

    def __init__(self, conn: sqlite3.Connection):
        self._inner = conn
        self.rollbacks = 0

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def rollback(self) -> None:
        self.rollbacks += 1
        self._inner.rollback()

    def execute(self, sql, parameters=()):
        return self._inner.execute(sql, parameters)


class _FlakyRepository:
    """Repository double whose first ``failures`` writes fail as instructed."""

    def __init__(self, conn: _CountingConnection, failures: int, error: Exception):
        self._conn = conn
        self._failures = failures
        self._error = error
        self.attempts = 0

    @_with_sqlite_busy_retry
    def write(self, value: str) -> str:
        self.attempts += 1
        if self.attempts <= self._failures:
            raise self._error
        self._conn.execute("CREATE TABLE IF NOT EXISTS t (x TEXT)")
        self._conn.execute("INSERT INTO t VALUES (?)", (value,))
        self._conn.commit()
        return value


@pytest.fixture
def sleeps(monkeypatch):
    """Capture the shared backoff sleeps instead of really sleeping."""
    seen: list[float] = []
    monkeypatch.setattr(
        "AssetsManager.repositories._common.time.sleep", seen.append
    )
    return seen


class TestSqliteBusyRetry:
    def test_busy_error_replays_once_then_succeeds(self, sleeps):
        conn = _CountingConnection(sqlite3.connect(":memory:"))
        repo = _FlakyRepository(conn, failures=1, error=_busy_error())

        assert repo.write("v") == "v"
        assert repo.attempts == 2  # exactly one replay after one busy failure
        assert conn.rollbacks == 1  # the failed attempt was rolled back
        assert len(sleeps) == 1  # one bounded backoff between the attempts
        assert conn.execute("SELECT x FROM t").fetchall() == [("v",)]

    def test_busy_replay_exhausts_the_bounded_attempts(self, sleeps):
        conn = _CountingConnection(sqlite3.connect(":memory:"))
        repo = _FlakyRepository(conn, failures=99, error=_busy_error())

        with pytest.raises(sqlite3.OperationalError, match="locked"):
            repo.write("v")
        assert repo.attempts == SQLITE_BUSY_RETRY_ATTEMPTS
        assert conn.rollbacks == SQLITE_BUSY_RETRY_ATTEMPTS - 1
        assert len(sleeps) == SQLITE_BUSY_RETRY_ATTEMPTS - 1

    def test_non_busy_operational_error_is_never_replayed(self, sleeps):
        conn = _CountingConnection(sqlite3.connect(":memory:"))
        repo = _FlakyRepository(
            conn, failures=99, error=sqlite3.OperationalError("no such table: t")
        )

        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            repo.write("v")
        assert repo.attempts == 1
        assert conn.rollbacks == 0
        assert sleeps == []

    def test_busy_error_inside_caller_transaction_is_never_replayed(self, sleeps):
        conn = _CountingConnection(sqlite3.connect(":memory:"))
        repo = _FlakyRepository(conn, failures=99, error=_busy_error())
        conn.execute("BEGIN")  # caller owns the transaction

        with pytest.raises(sqlite3.OperationalError, match="locked"):
            repo.write("v")
        assert repo.attempts == 1  # no replay underneath the caller
        assert conn.rollbacks == 0  # caller transaction left untouched
        assert sleeps == []

    def test_non_sqlite_error_is_never_replayed(self, sleeps):
        conn = _CountingConnection(sqlite3.connect(":memory:"))
        repo = _FlakyRepository(conn, failures=99, error=ValueError("boom"))

        with pytest.raises(ValueError, match="boom"):
            repo.write("v")
        assert repo.attempts == 1
        assert conn.rollbacks == 0
        assert sleeps == []

    def test_retry_runner_survives_a_failing_rollback_hook(self, monkeypatch):
        monkeypatch.setattr(
            "AssetsManager.repositories._common.time.sleep", lambda _delay: None
        )
        runs = {"count": 0}

        def run() -> str:
            runs["count"] += 1
            if runs["count"] == 1:
                raise _busy_error()
            return "ok"

        def broken_rollback() -> None:
            raise RuntimeError("rollback unavailable")

        assert (
            _retry_sqlite_busy(
                run,
                outer_transaction=False,
                attempts=SQLITE_BUSY_RETRY_ATTEMPTS,
                rollback=broken_rollback,
            )
            == "ok"
        )
        assert runs["count"] == 2

    def test_retry_runner_with_single_attempt_never_replays(self):
        runs = {"count": 0}

        def run() -> str:
            runs["count"] += 1
            raise _busy_error()

        with pytest.raises(sqlite3.OperationalError, match="locked"):
            _retry_sqlite_busy(run, outer_transaction=False, attempts=1)
        assert runs["count"] == 1
