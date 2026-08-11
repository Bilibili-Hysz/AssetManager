"""SQLite connection-close fault injection for reconciliation ownership."""

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


def _open_queue(database, library_root, *, now, wallclock):
    from AssetsManager.application import ReconciliationQueue, SQLiteReconciliationQueueStore

    connection = sqlite3.connect(str(database), check_same_thread=False, timeout=5.0)
    connection.execute("PRAGMA busy_timeout=5000")
    clock_value = [float(now)]
    wallclock_value = [float(wallclock)]
    store = SQLiteReconciliationQueueStore(
        connection=connection,
        library_root=library_root,
        allow_unmanaged=True,
        clock=lambda: clock_value[0],
        wall_clock=lambda: wallclock_value[0],
        busy_retry_attempts=2,
        busy_retry_backoff=0.01,
    )
    queue = ReconciliationQueue(
        library_root=library_root,
        persistence_store=store,
        clock=lambda: clock_value[0],
        wall_clock=lambda: wallclock_value[0],
    )
    return connection, queue, clock_value, wallclock_value


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


def test_closed_claim_connection_fails_renew_and_other_connection_recovers(tmp_path):
    from AssetsManager.application import (
        ReconciliationQueuePersistenceError,
        ReconciliationState,
    )

    database = tmp_path / "reconciliation-renew-close.sqlite3"
    library_root = tmp_path / "library"
    library_root.mkdir()
    connection = sqlite3.connect(str(database))
    try:
        connection.executescript(_SCHEMA)
        connection.commit()
    finally:
        connection.close()

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
    try:
        claimed = old_queue.claim_next(now=0.0, lease_seconds=1.0)
        assert claimed is not None
        old_connection.close()

        with pytest.raises(ReconciliationQueuePersistenceError):
            old_queue.renew_lease(
                task_id,
                expected_attempts=claimed.attempts,
                lease_token=claimed.lease_token,
                lease_seconds=1.0,
                now=0.5,
            )

        recovered = new_queue.recover_expired_running(now=2.0)
        assert len(recovered) == 1
        assert recovered[0].state is ReconciliationState.RETRYABLE

        new_clock[0] = 2.25
        new_wallclock[0] = 1002.25
        replacement = new_queue.claim_next(now=2.25, lease_seconds=5.0)
        assert replacement is not None
        assert replacement.attempts == claimed.attempts + 1
        assert replacement.lease_token != claimed.lease_token
    finally:
        if old_connection is not None:
            try:
                old_connection.close()
            except Exception:
                pass
        new_connection.close()


def test_closed_claim_connection_cannot_report_completion_and_recovery_succeeds(tmp_path):
    from AssetsManager.application import (
        ReconciliationQueuePersistenceError,
        ReconciliationState,
    )

    database = tmp_path / "reconciliation-completion-close.sqlite3"
    library_root = tmp_path / "library"
    library_root.mkdir()
    connection = sqlite3.connect(str(database))
    try:
        connection.executescript(_SCHEMA)
        connection.commit()
    finally:
        connection.close()

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
    try:
        claimed = old_queue.claim_next(now=0.0, lease_seconds=1.0)
        assert claimed is not None
        old_connection.close()

        with pytest.raises(ReconciliationQueuePersistenceError):
            old_queue.mark_succeeded(
                task_id,
                expected_attempts=claimed.attempts,
                lease_token=claimed.lease_token,
                revision=111,
                now=0.5,
            )

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
        try:
            old_connection.close()
        except Exception:
            pass
        new_connection.close()
