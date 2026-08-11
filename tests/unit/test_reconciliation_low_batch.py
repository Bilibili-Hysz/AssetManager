"""Low-severity batch fixes for the reconciliation queue.

Covers:
- Bug 6: startup recovery must degrade to a read-only snapshot load when a
  cross-process generation conflict is detected, instead of failing the
  library open.
- Bug 7: ``wait_for_ready`` must refresh the due clock from the queue's own
  clock so a stale caller-supplied ``now`` cannot delay an already-due task
  by one full poll round.
- Bug 8: administrative terminal/cancel of a RUNNING task must be allowed
  without a lease token (forced stop), while worker-scoped mutations keep
  their strict lease CAS.
"""
import logging
import sqlite3
import time

import pytest


_SCHEMA = """
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


def _store(tmp_path, *, clock=10.0, wall_clock=1000.0):
    from AssetsManager.application import SQLiteReconciliationQueueStore

    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.executescript(_SCHEMA)
    connection.commit()
    store = SQLiteReconciliationQueueStore(
        connection=connection,
        library_root=tmp_path / "library",
        allow_unmanaged=True,
        clock=lambda: clock,
        wall_clock=lambda: wall_clock,
    )
    return connection, store


class _ConflictOnFirstReplace:
    """Store wrapper raising one cross-process generation conflict on replace.

    ``load_snapshot`` always reflects the durable truth, which simulates
    another process having taken over the queue between this process's
    snapshot load and its recovery persist.
    """

    def __init__(self, inner):
        from AssetsManager.application import ReconciliationQueuePersistenceConflict

        self._inner = inner
        self.replace_calls = 0
        self._conflict_type = ReconciliationQueuePersistenceConflict

    def load_snapshot(self):
        return self._inner.load_snapshot()

    def replace(self, tasks, *, expected_generation=None):
        self.replace_calls += 1
        if self.replace_calls == 1:
            raise self._conflict_type(
                "Reconciliation queue generation conflict: expected 2, found 3",
                retryable=True,
                operation="replace",
            )
        return self._inner.replace(tasks, expected_generation=expected_generation)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _file_stores(tmp_path):
    """Two stores over one file-backed database (cross-connection view)."""
    from AssetsManager.application import SQLiteReconciliationQueueStore

    db_path = tmp_path / "queue.db"
    first_connection = sqlite3.connect(str(db_path), check_same_thread=False)
    first_connection.executescript(_SCHEMA)
    first_connection.commit()
    second_connection = sqlite3.connect(str(db_path), check_same_thread=False)
    kwargs = {
        "library_root": tmp_path / "library",
        "allow_unmanaged": True,
        "clock": lambda: 100.0,
        "wall_clock": lambda: 1000.0,
    }
    return (
        first_connection,
        second_connection,
        SQLiteReconciliationQueueStore(connection=first_connection, **kwargs),
        SQLiteReconciliationQueueStore(connection=second_connection, **kwargs),
    )


def test_startup_recovery_generation_conflict_degrades_to_readonly_snapshot(tmp_path, caplog):
    from AssetsManager.application import ReconciliationQueue, ReconciliationState

    first_connection, second_connection, store_a, store_b = _file_stores(tmp_path)
    try:
        owner = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store_a,
            clock=lambda: 100.0,
            wall_clock=lambda: 1000.0,
        )
        task = owner.enqueue_or_merge(
            path=tmp_path / "library",
            reason="busy",
            now=100.0,
        )
        claimed = owner.claim_next(now=100.0, lease_seconds=1.0)
        assert claimed is not None
        assert claimed.state is ReconciliationState.RUNNING
        durable = store_a.load_snapshot()
        assert durable.generation == 2

        # A second process starts with a clock past the lease expiry so
        # startup lease recovery fires, then loses the generation race when
        # it tries to persist the recovery.
        store_b._clock = lambda: 200.0
        store_b._wall_clock = lambda: 2000.0
        wrapped = _ConflictOnFirstReplace(store_b)
        with caplog.at_level(logging.WARNING):
            restarted = ReconciliationQueue(
                library_root=tmp_path / "library",
                persistence_store=wrapped,
                clock=lambda: 200.0,
                wall_clock=lambda: 2000.0,
            )
        # The queue opens and degrades to the newer durable snapshot: the
        # running task is untouched (no unpersisted local recovery leaked).
        assert wrapped.replace_calls == 1
        current = restarted.get(task.task_id)
        assert current is not None
        assert current.state is ReconciliationState.RUNNING
        assert current.lease_token == claimed.lease_token
        assert restarted.persistence_generation == 2
        assert any(
            "generation race" in record.getMessage() for record in caplog.records
        )
    finally:
        first_connection.close()
        second_connection.close()


def test_wait_for_ready_uses_queue_clock_not_stale_caller_now(tmp_path):
    from AssetsManager.application import ReconciliationQueue

    now = [100.0]
    queue = ReconciliationQueue(
        library_root=tmp_path / "library",
        clock=lambda: now[0],
    )
    queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=100.0)

    # The task is due per the queue clock (100.0), but the caller passes a
    # stale ``now`` (99.0).  The queue clock must win inside the wait loop.
    started = time.monotonic()
    assert queue.wait_for_ready(now=99.0, timeout=1.0) is True
    assert time.monotonic() - started < 0.5


def test_wait_for_ready_stale_now_recognizes_due_task_with_real_clock(tmp_path):
    from AssetsManager.application import ReconciliationQueue

    queue = ReconciliationQueue(library_root=tmp_path / "library")
    queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=time.monotonic())

    stale = time.monotonic() - 1.0
    started = time.monotonic()
    assert queue.wait_for_ready(now=stale, timeout=0.5) is True
    assert time.monotonic() - started < 0.3


def test_wait_for_ready_zero_timeout_keeps_caller_now_compat(tmp_path):
    from AssetsManager.application import ReconciliationQueue

    queue = ReconciliationQueue(
        library_root=tmp_path / "library",
        clock=lambda: 100.0,
    )
    queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=100.0)

    # The non-blocking zero-timeout check remains a snapshot with the
    # caller's clock: a stale now sees the task as not yet due.
    assert queue.wait_for_ready(now=99.0, timeout=0) is False
    assert queue.wait_for_ready(now=100.0, timeout=0) is True


def test_admin_mark_terminal_without_lease_token_forces_running_task(tmp_path):
    from AssetsManager.application import ReconciliationQueue, ReconciliationState

    queue = ReconciliationQueue(library_root=tmp_path / "library", clock=lambda: 0.0)
    task = queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=0.0)
    claimed = queue.claim_next(now=0.0, lease_seconds=10.0)
    assert claimed is not None
    assert claimed.state is ReconciliationState.RUNNING

    terminal = queue.mark_terminal(
        task.task_id,
        error_type="AdminStopped",
        error="forced stop",
        now=1.0,
    )
    assert terminal.state is ReconciliationState.TERMINAL
    assert terminal.lease_token is None
    assert terminal.lease_expires_at is None
    assert terminal.last_error_type == "AdminStopped"


def test_admin_cancel_without_lease_token_forces_running_task(tmp_path):
    from AssetsManager.application import ReconciliationQueue, ReconciliationState

    queue = ReconciliationQueue(library_root=tmp_path / "library", clock=lambda: 0.0)
    task = queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=0.0)
    claimed = queue.claim_next(now=0.0, lease_seconds=10.0)
    assert claimed is not None

    cancelled = queue.cancel(task.task_id, now=1.0)
    assert cancelled.state is ReconciliationState.CANCELLED
    assert cancelled.lease_token is None
    assert cancelled.lease_expires_at is None


def test_admin_forced_terminal_on_running_task_is_durable_in_store(tmp_path):
    from AssetsManager.application import (
        ReconciliationQueue,
        ReconciliationState,
    )

    connection, store = _store(tmp_path)
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        task = queue.enqueue_or_merge(
            path=tmp_path / "library",
            reason="busy",
            now=10.0,
        )
        claimed = queue.claim_next(now=10.0, lease_seconds=30.0)
        assert claimed is not None
        assert claimed.state is ReconciliationState.RUNNING

        terminal = queue.mark_terminal(
            task.task_id,
            error_type="AdminStopped",
            error="forced stop",
            now=10.0,
        )
        assert terminal.state is ReconciliationState.TERMINAL

        durable = store.load()[0]
        assert durable.state is ReconciliationState.TERMINAL
        assert durable.lease_token is None
        assert durable.lease_expires_at is None
        # The store snapshot is at least as new as the terminal mutation.
        assert store.load_snapshot().generation >= 3
    finally:
        connection.close()


def test_worker_scoped_termination_still_requires_valid_lease(tmp_path):
    from AssetsManager.application import (
        ReconciliationQueue,
        ReconciliationQueuePersistenceConflict,
        ReconciliationState,
    )

    queue = ReconciliationQueue(library_root=tmp_path / "library", clock=lambda: 0.0)
    task = queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=0.0)
    claimed = queue.claim_next(now=0.0, lease_seconds=10.0)
    assert claimed is not None

    # A worker with a mismatched token must still be rejected.
    with pytest.raises(ReconciliationQueuePersistenceConflict):
        queue.mark_terminal(
            task.task_id,
            expected_attempts=claimed.attempts,
            lease_token="wrong-token",
            now=0.5,
        )
    current = queue.get(task.task_id)
    assert current is not None
    assert current.state is ReconciliationState.RUNNING
    assert current.lease_token == claimed.lease_token
