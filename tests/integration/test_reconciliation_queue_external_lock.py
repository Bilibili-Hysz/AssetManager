"""Deterministic external-lock fault injection for reconciliation ownership."""

from __future__ import annotations

import sqlite3

import pytest


_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE reconciliation_tasks (
    task_id TEXT PRIMARY KEY NOT NULL,
    library_root TEXT NOT NULL,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    reason TEXT NOT NULL,
    state TEXT NOT NULL,
    attempts INTEGER NOT NULL CHECK (attempts >= 0),
    next_attempt_at_wallclock REAL NOT NULL,
    operation_ids TEXT NOT NULL DEFAULT '[]',
    last_error_type TEXT,
    last_error TEXT,
    expected_revision INTEGER,
    observed_revision INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    lease_expires_at_wallclock REAL,
    lease_token TEXT,
    max_attempts INTEGER NOT NULL CHECK (max_attempts >= 1),
    UNIQUE (library_root, path, kind)
);
CREATE INDEX idx_reconciliation_tasks_due
    ON reconciliation_tasks(library_root, state, next_attempt_at_wallclock);
CREATE TABLE reconciliation_queue_state (
    library_root TEXT PRIMARY KEY NOT NULL,
    generation INTEGER NOT NULL DEFAULT 0 CHECK (generation >= 0),
    updated_at REAL NOT NULL
);
"""


def _open_queue(database, library_root, *, now: float, wallclock: float):
    from AssetsManager.application import ReconciliationQueue, SQLiteReconciliationQueueStore

    connection = sqlite3.connect(
        str(database),
        check_same_thread=False,
        timeout=0.0,
    )
    clock_value = [float(now)]
    wallclock_value = [float(wallclock)]
    store = SQLiteReconciliationQueueStore(
        connection=connection,
        library_root=library_root,
        allow_unmanaged=True,
        clock=lambda: clock_value[0],
        wall_clock=lambda: wallclock_value[0],
        busy_retry_attempts=0,
        busy_retry_backoff=0.0,
    )
    queue = ReconciliationQueue(
        library_root=library_root,
        persistence_store=store,
        clock=lambda: clock_value[0],
        wall_clock=lambda: wallclock_value[0],
    )
    return connection, queue, clock_value, wallclock_value


def _initialize_database(database):
    connection = sqlite3.connect(str(database), timeout=0.0)
    try:
        connection.executescript(_SCHEMA)
        connection.commit()
    finally:
        connection.close()


def _seed(database, library_root):
    connection, queue, _clock, _wallclock = _open_queue(
        database,
        library_root,
        now=0.0,
        wallclock=1000.0,
    )
    try:
        return queue.enqueue_or_merge(path=library_root, reason="busy", now=0.0).task_id
    finally:
        connection.close()


def _hold_external_write_lock(database):
    lock_connection = sqlite3.connect(
        str(database),
        check_same_thread=False,
        timeout=0.0,
    )
    lock_connection.execute("BEGIN IMMEDIATE")
    return lock_connection


def test_external_write_lock_makes_heartbeat_fail_closed_then_recover(tmp_path):
    from AssetsManager.application import (
        ReconciliationQueuePersistenceError,
        ReconciliationState,
    )

    database = tmp_path / "reconciliation-external-lock-renew.sqlite3"
    library_root = tmp_path / "library"
    library_root.mkdir()
    _initialize_database(database)
    task_id = _seed(database, library_root)

    old_connection, old_queue, _old_clock, _old_wallclock = _open_queue(
        database,
        library_root,
        now=0.0,
        wallclock=1000.0,
    )
    new_connection, new_queue, new_clock, new_wallclock = _open_queue(
        database,
        library_root,
        now=2.0,
        wallclock=1002.0,
    )
    lock_connection = None
    try:
        claimed = old_queue.claim_next(now=0.0, lease_seconds=1.0)
        assert claimed is not None

        lock_connection = _hold_external_write_lock(database)
        with pytest.raises(ReconciliationQueuePersistenceError):
            old_queue.renew_lease(
                task_id,
                expected_attempts=claimed.attempts,
                lease_token=claimed.lease_token,
                lease_seconds=1.0,
                now=0.5,
            )

        lock_connection.rollback()
        lock_connection.close()
        lock_connection = None

        recovered = new_queue.recover_expired_running(now=2.0)
        assert len(recovered) == 1
        assert recovered[0].state is ReconciliationState.RETRYABLE

        new_clock[0] = 2.25
        new_wallclock[0] = 1002.25
        replacement = new_queue.claim_next(now=2.25, lease_seconds=5.0)
        assert replacement is not None
        assert replacement.attempts == claimed.attempts + 1
        assert replacement.lease_token != claimed.lease_token

        completed = new_queue.mark_succeeded(
            task_id,
            expected_attempts=replacement.attempts,
            lease_token=replacement.lease_token,
            revision=222,
            now=2.25,
        )
        assert completed.state is ReconciliationState.SUCCEEDED
        assert completed.observed_revision == 222
    finally:
        if lock_connection is not None:
            lock_connection.rollback()
            lock_connection.close()
        old_connection.close()
        new_connection.close()


def test_external_write_lock_prevents_old_completion_then_new_worker_completes(tmp_path):
    from AssetsManager.application import (
        ReconciliationQueuePersistenceError,
        ReconciliationState,
    )

    database = tmp_path / "reconciliation-external-lock-completion.sqlite3"
    library_root = tmp_path / "library"
    library_root.mkdir()
    _initialize_database(database)
    task_id = _seed(database, library_root)

    old_connection, old_queue, _old_clock, _old_wallclock = _open_queue(
        database,
        library_root,
        now=0.0,
        wallclock=1000.0,
    )
    new_connection, new_queue, new_clock, new_wallclock = _open_queue(
        database,
        library_root,
        now=2.0,
        wallclock=1002.0,
    )
    lock_connection = None
    try:
        claimed = old_queue.claim_next(now=0.0, lease_seconds=1.0)
        assert claimed is not None

        lock_connection = _hold_external_write_lock(database)
        with pytest.raises(ReconciliationQueuePersistenceError):
            old_queue.mark_succeeded(
                task_id,
                expected_attempts=claimed.attempts,
                lease_token=claimed.lease_token,
                revision=111,
                now=0.5,
            )

        lock_connection.rollback()
        lock_connection.close()
        lock_connection = None

        recovered = new_queue.recover_expired_running(now=2.0)
        assert len(recovered) == 1
        assert recovered[0].state is ReconciliationState.RETRYABLE

        new_clock[0] = 2.25
        new_wallclock[0] = 1002.25
        replacement = new_queue.claim_next(now=2.25, lease_seconds=5.0)
        assert replacement is not None
        completed = new_queue.mark_succeeded(
            task_id,
            expected_attempts=replacement.attempts,
            lease_token=replacement.lease_token,
            revision=222,
            now=2.25,
        )
        assert completed.state is ReconciliationState.SUCCEEDED
        assert completed.observed_revision == 222
        assert completed.lease_token is None
    finally:
        if lock_connection is not None:
            lock_connection.rollback()
            lock_connection.close()
        old_connection.close()
        new_connection.close()
