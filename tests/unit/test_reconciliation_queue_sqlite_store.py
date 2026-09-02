import sqlite3
import threading
import time

import pytest

from AssetsManager.core.db_migrations import migrate


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
    payload TEXT NOT NULL DEFAULT '{}',
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


def _outbox_schema_connection():
    from AssetsManager.core import database

    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.executescript(database._SCHEMA)
    connection.commit()
    migrate(connection)
    return connection


def _store(tmp_path):
    from AssetsManager.application import SQLiteReconciliationQueueStore

    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.executescript(_SCHEMA)
    connection.commit()
    store = SQLiteReconciliationQueueStore(
        connection=connection,
        library_root=tmp_path / "library",
        allow_unmanaged=True,
        clock=lambda: 10.0,
        wall_clock=lambda: 1000.0,
    )
    return connection, store


def _outbox_store(tmp_path, **store_kwargs):
    from AssetsManager.application import SQLiteReconciliationQueueStore

    wall_clock = [1000.0]
    connection = _outbox_schema_connection()
    store = SQLiteReconciliationQueueStore(
        connection=connection,
        library_root=tmp_path / "library",
        allow_unmanaged=True,
        clock=lambda: 10.0,
        wall_clock=lambda: wall_clock[0],
        **store_kwargs,
    )
    assert store.transition_outbox_enabled
    return connection, store, wall_clock


def _outbox_file_stores(tmp_path, *, wall_clock=None, **store_kwargs):
    from AssetsManager.application import SQLiteReconciliationQueueStore
    from AssetsManager.core import database

    db_path = tmp_path / "outbox-queue.db"
    initializer = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        initializer.executescript(database._SCHEMA)
        initializer.commit()
        migrate(initializer)
    finally:
        initializer.close()
    first_connection = sqlite3.connect(str(db_path), check_same_thread=False)
    second_connection = sqlite3.connect(str(db_path), check_same_thread=False)
    first_wall_clock = [1000.0]
    second_wall_clock = [1000.0]
    first_wall_clock_fn = wall_clock or (lambda: first_wall_clock[0])
    second_wall_clock_fn = wall_clock or (lambda: second_wall_clock[0])
    kwargs = {
        "library_root": tmp_path / "library",
        "allow_unmanaged": True,
        "clock": lambda: 10.0,
    }
    kwargs.update(store_kwargs)
    return (
        first_connection,
        second_connection,
        SQLiteReconciliationQueueStore(
            connection=first_connection,
            wall_clock=first_wall_clock_fn,
            **kwargs,
        ),
        SQLiteReconciliationQueueStore(
            connection=second_connection,
            wall_clock=second_wall_clock_fn,
            **kwargs,
        ),
        first_wall_clock,
        second_wall_clock,
    )


def _register_manifest_transition_consumer(queue, listener):
    """Register a test consumer that treats an omitted result as APPLIED."""
    from AssetsManager.application.reconciliation_queue import (
        IMPORT_MANIFEST_RECOVERY_CONSUMER_ID,
        ReconciliationTransitionDisposition,
    )

    def consumer(transition):
        result = listener(transition)
        return (
            ReconciliationTransitionDisposition.APPLIED
            if result is None
            else result
        )

    queue.set_durable_transition_consumer(
        IMPORT_MANIFEST_RECOVERY_CONSUMER_ID,
        consumer,
    )
    return consumer


def test_sqlite_store_round_trips_queue_state(tmp_path):
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
        )
        task = queue.enqueue_or_merge(
            path=tmp_path / "library" / "assets",
            reason="busy",
            operation_id="op-1",
            now=10.0,
        )
        claimed = queue.claim_next(now=10.0, lease_seconds=5.0)
        assert claimed is not None
        retryable = queue.mark_retryable(
            task.task_id, reason="busy", lease_token=claimed.lease_token, now=10.0
        )
        assert retryable.state is ReconciliationState.RETRYABLE

        restored = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
        )
        current = restored.get(task.task_id)
        assert current is not None
        assert current.state is ReconciliationState.RETRYABLE
        assert current.operation_ids == ("op-1",)
        assert current.next_attempt_at == pytest.approx(retryable.next_attempt_at)
    finally:
        connection.close()


def test_sqlite_store_preserves_outer_transaction_ownership(tmp_path):
    connection, store = _store(tmp_path)
    connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
    connection.commit()
    try:
        from AssetsManager.application import ReconciliationQueue

        connection.execute("BEGIN")
        connection.execute("INSERT INTO sentinel(value) VALUES ('caller')")
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 0.0,
        )
        queue.enqueue_or_merge(
            path=tmp_path / "library",
            reason="scan_failed",
            now=0.0,
        )
        assert connection.in_transaction
        connection.rollback()

        assert connection.execute("SELECT COUNT(*) FROM sentinel").fetchone()[0] == 0
        assert store.load() == ()
    finally:
        connection.close()


def test_sqlite_store_requires_managed_connection_by_default(tmp_path):
    from AssetsManager.application import SQLiteReconciliationQueueStore

    connection = sqlite3.connect(":memory:")
    try:
        with pytest.raises(RuntimeError, match="not managed"):
            SQLiteReconciliationQueueStore(
                connection=connection,
                library_root=tmp_path / "library",
            )
    finally:
        connection.close()


def test_sqlite_store_fails_closed_on_invalid_row(tmp_path):
    from AssetsManager.application import ReconciliationQueuePersistenceError

    connection, store = _store(tmp_path)
    try:
        connection.execute(
            "INSERT INTO reconciliation_tasks ("
            "task_id, library_root, path, kind, reason, state, attempts, "
            "next_attempt_at_wallclock, operation_ids, created_at, updated_at, max_attempts"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "bad",
                store.library_root,
                store.library_root,
                "unknown_kind",
                "busy",
                "pending",
                0,
                0.0,
                "[]",
                0.0,
                0.0,
                5,
            ),
        )
        connection.commit()
        with pytest.raises(ReconciliationQueuePersistenceError):
            store.load()
    finally:
        connection.close()


def _file_stores(tmp_path):
    from AssetsManager.application import SQLiteReconciliationQueueStore

    db_path = tmp_path / "queue.db"
    first_connection = sqlite3.connect(str(db_path), check_same_thread=False)
    first_connection.executescript(_SCHEMA)
    first_connection.commit()
    second_connection = sqlite3.connect(str(db_path), check_same_thread=False)
    kwargs = {
        "library_root": tmp_path / "library",
        "allow_unmanaged": True,
        "clock": lambda: 10.0,
        "wall_clock": lambda: 1000.0,
    }
    return (
        first_connection,
        second_connection,
        SQLiteReconciliationQueueStore(connection=first_connection, **kwargs),
        SQLiteReconciliationQueueStore(connection=second_connection, **kwargs),
    )


def test_sqlite_store_generation_increments_on_each_snapshot_replace(tmp_path):
    from AssetsManager.application import ReconciliationQueue

    connection, store = _store(tmp_path)
    try:
        assert store.load_snapshot().generation == 0
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=10.0)
        assert queue.persistence_generation == 1
        assert store.load_snapshot().generation == 1
    finally:
        connection.close()


def test_sqlite_store_rejects_stale_snapshot_without_losing_durable_tasks(tmp_path):
    from AssetsManager.application import ReconciliationQueue

    first_connection, second_connection, first_store, second_store = _file_stores(tmp_path)
    try:
        first_queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=first_store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        second_queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=second_store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        first_task = first_queue.enqueue_or_merge(
            path=tmp_path / "library" / "first",
            reason="busy",
            now=10.0,
        )

        second_task = second_queue.enqueue_or_merge(
            path=tmp_path / "library" / "second",
            reason="stale",
            now=10.0,
        )
        assert second_queue.get(first_task.task_id) is not None
        assert second_queue.get(second_task.task_id) is not None
        durable = second_store.load_snapshot()
        assert durable.generation == 2
        assert {item.path for item in durable.tasks} == {
            str(tmp_path / "library" / "first").lower(),
            str(tmp_path / "library" / "second").lower(),
        }
    finally:
        first_connection.close()
        second_connection.close()


def test_sqlite_store_generation_prevents_double_claim_across_connections(tmp_path):
    from AssetsManager.application import (
        ReconciliationQueue,
        ReconciliationState,
    )

    first_connection, second_connection, first_store, second_store = _file_stores(tmp_path)
    try:
        seed = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=first_store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        task = seed.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=10.0)
        first_queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=first_store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        second_queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=second_store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        claimed = first_queue.claim_next(now=10.0, lease_seconds=30.0)
        assert claimed is not None
        assert claimed.task_id == task.task_id
        assert claimed.lease_token is not None

        assert second_queue.claim_next(now=10.0, lease_seconds=30.0) is None
        restored = second_queue.get(task.task_id)
        assert restored is not None
        assert restored.state is ReconciliationState.RUNNING
        assert restored.attempts == 1
    finally:
        first_connection.close()
        second_connection.close()


def test_sqlite_claim_recovers_expired_lease_without_double_claiming(tmp_path):
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
        claimed = queue.claim_next(now=10.0, lease_seconds=5.0)
        assert claimed is not None
        connection.execute(
            "UPDATE reconciliation_tasks SET lease_expires_at_wallclock=? "
            "WHERE task_id=?",
            (999.0, task.task_id),
        )
        connection.commit()

        recovered = store.claim_next(now=20.0, lease_seconds=5.0)
        assert recovered.claimed is None
        current = next(
            item for item in recovered.snapshot.tasks if item.task_id == task.task_id
        )
        assert current.state is ReconciliationState.RETRYABLE
        assert current.last_error_type == "LeaseExpired"
        assert current.lease_token is None
        assert recovered.snapshot.generation == 3
    finally:
        connection.close()


def test_sqlite_completion_cas_rejects_stale_worker_and_refreshes_snapshot(tmp_path):
    from AssetsManager.application import (
        ReconciliationQueue,
        ReconciliationQueuePersistenceConflict,
        ReconciliationState,
    )

    first_connection, second_connection, first_store, second_store = _file_stores(tmp_path)
    try:
        seed = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=first_store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        task = seed.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=10.0)
        first_queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=first_store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        second_queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=second_store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        claimed = first_queue.claim_next(now=10.0, lease_seconds=30.0)
        assert claimed is not None
        assert second_queue.claim_next(now=10.0, lease_seconds=30.0) is None
        completed = first_queue.mark_succeeded(
            task.task_id, revision=7, lease_token=claimed.lease_token, now=10.0
        )
        assert completed.state is ReconciliationState.SUCCEEDED

        with pytest.raises(ReconciliationQueuePersistenceConflict) as raised:
            second_queue.mark_succeeded(
                task.task_id,
                revision=8,
                lease_token=claimed.lease_token,
                now=10.0,
            )
        assert raised.value.stale_worker_completion is True
        assert raised.value.retryable is False
        assert raised.value.operation == "completion"
        refreshed = second_queue.get(task.task_id)
        assert refreshed is not None
        assert refreshed.state is ReconciliationState.SUCCEEDED
        assert refreshed.observed_revision == 7
    finally:
        first_connection.close()
        second_connection.close()


def test_sqlite_stale_worker_terminal_cannot_override_recovered_retryable_task(tmp_path):
    from AssetsManager.application import (
        ReconciliationQueue,
        ReconciliationQueuePersistenceConflict,
        ReconciliationState,
        SQLiteReconciliationQueueStore,
    )

    first_connection, second_connection, first_store, _second_store = _file_stores(tmp_path)
    second_store = SQLiteReconciliationQueueStore(
        connection=second_connection,
        library_root=tmp_path / "library",
        allow_unmanaged=True,
        clock=lambda: 20.0,
        wall_clock=lambda: 1002.0,
    )
    try:
        first_queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=first_store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        second_queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=second_store,
            clock=lambda: 20.0,
            wall_clock=lambda: 1002.0,
        )
        task = first_queue.enqueue_or_merge(
            path=tmp_path / "library",
            reason="scan_failed",
            now=10.0,
        )
        claimed = first_queue.claim_next(now=10.0, lease_seconds=1.0)
        assert claimed is not None

        recovered = second_queue.recover_expired_running(now=20.0)
        assert recovered[0].state is ReconciliationState.RETRYABLE

        with pytest.raises(ReconciliationQueuePersistenceConflict) as raised:
            first_queue.mark_terminal(
                task.task_id,
                error_type="OldWorker",
                error="late failure",
                lease_token=claimed.lease_token,
                now=10.0,
            )
        assert raised.value.stale_worker_completion is True
        assert raised.value.operation == "state_mutation"
        current = second_store.load_snapshot().tasks[0]
        assert current.state is ReconciliationState.RETRYABLE
    finally:
        first_connection.close()
        second_connection.close()


def test_sqlite_per_task_retry_and_terminal_mutations_preserve_generation(tmp_path):
    from AssetsManager.application import ReconciliationQueue, ReconciliationState

    connection, store = _store(tmp_path)
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        retry_task = queue.enqueue_or_merge(
            path=tmp_path / "library" / "retry",
            reason="busy",
            now=10.0,
        )
        claimed = queue.claim_next(now=10.0, lease_seconds=30.0)
        assert claimed is not None
        retryable = queue.mark_retryable(
            retry_task.task_id,
            error_type="OperationalError",
            error="locked",
            reason="busy",
            lease_token=claimed.lease_token,
            now=10.0,
        )
        assert retryable.state is ReconciliationState.RETRYABLE
        assert retryable.last_error_type == "OperationalError"
        generation_after_retry = queue.persistence_generation

        terminal_task = queue.enqueue_or_merge(
            path=tmp_path / "library" / "terminal",
            reason="scan_failed",
            now=10.0,
        )
        terminal = queue.mark_terminal(
            terminal_task.task_id,
            error_type="FileNotFoundError",
            error="missing",
            now=10.0,
        )
        assert terminal.state is ReconciliationState.TERMINAL
        assert queue.persistence_generation == generation_after_retry + 2
    finally:
        connection.close()


def test_sqlite_enqueue_merges_operation_ids_and_revisions_per_task(tmp_path):
    from AssetsManager.application import ReconciliationQueue

    connection, store = _store(tmp_path)
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        first = queue.enqueue_or_merge(
            path=tmp_path / "library" / "asset",
            reason="busy",
            operation_id="op-1",
            expected_revision=1,
            observed_revision=2,
            now=10.0,
        )
        merged = queue.enqueue_or_merge(
            path=tmp_path / "library" / "asset",
            reason="stale",
            operation_id="op-2",
            expected_revision=3,
            observed_revision=4,
            now=10.0,
        )
        duplicate = queue.enqueue_or_merge(
            path=tmp_path / "library" / "asset",
            reason="scan_failed",
            operation_id="op-2",
            now=10.0,
        )
        assert merged.task_id == first.task_id == duplicate.task_id
        assert duplicate.operation_ids == ("op-1", "op-2")
        assert duplicate.reason == "scan_failed"
        assert duplicate.expected_revision == 3
        assert duplicate.observed_revision == 4
    finally:
        connection.close()


def test_sqlite_enqueue_replaces_finished_task_with_new_task_id(tmp_path):
    from AssetsManager.application import ReconciliationQueue, ReconciliationState

    connection, store = _store(tmp_path)
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        first = queue.enqueue_or_merge(
            path=tmp_path / "library" / "asset",
            reason="busy",
            now=10.0,
        )
        terminal = queue.mark_terminal(first.task_id, error_type="missing", error="gone", now=10.0)
        assert terminal.state is ReconciliationState.TERMINAL
        replacement = queue.enqueue_or_merge(
            path=tmp_path / "library" / "asset",
            reason="busy",
            now=10.0,
        )
        assert replacement.task_id != first.task_id
        assert replacement.state is ReconciliationState.PENDING
        assert queue.get(first.task_id) is None
    finally:
        connection.close()


def test_sqlite_enqueue_applies_bounded_finished_eviction_and_active_full_guard(tmp_path):
    from AssetsManager.application import ReconciliationQueue, ReconciliationQueueFull

    connection, store = _store(tmp_path)
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            max_tasks=1,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        active = queue.enqueue_or_merge(
            path=tmp_path / "library" / "active",
            reason="busy",
            now=10.0,
        )
        with pytest.raises(ReconciliationQueueFull):
            queue.enqueue_or_merge(
                path=tmp_path / "library" / "blocked",
                reason="stale",
                now=10.0,
            )
        assert queue.get(active.task_id) is not None

        queue.mark_terminal(active.task_id, error_type="done", error="done", now=10.0)
        evicted = queue.enqueue_or_merge(
            path=tmp_path / "library" / "new",
            reason="busy",
            now=10.0,
        )
        assert queue.get(active.task_id) is None
        assert queue.get(evicted.task_id) is not None
        assert len(store.load()) == 1
    finally:
        connection.close()


def test_sqlite_public_recover_expired_running_is_per_task_and_generation_safe(tmp_path):
    from AssetsManager.application import ReconciliationQueue, ReconciliationState

    connection, store = _store(tmp_path)
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        task = queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=10.0)
        assert queue.claim_next(now=10.0, lease_seconds=30.0) is not None
        connection.execute(
            "UPDATE reconciliation_tasks SET lease_expires_at_wallclock=? WHERE task_id=?",
            (999.0, task.task_id),
        )
        connection.commit()

        recovered = queue.recover_expired_running(now=20.0)
        assert len(recovered) == 1
        assert recovered[0].task_id == task.task_id
        assert recovered[0].state is ReconciliationState.RETRYABLE
        assert recovered[0].last_error_type == "LeaseExpired"
        assert queue.persistence_generation == 3
    finally:
        connection.close()


def test_sqlite_public_recovery_does_not_double_recover_across_connections(tmp_path):
    from AssetsManager.application import ReconciliationQueue, ReconciliationState

    first_connection, second_connection, first_store, second_store = _file_stores(tmp_path)
    try:
        seed = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=first_store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        task = seed.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=10.0)
        first_queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=first_store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        second_queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=second_store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        assert first_queue.claim_next(now=10.0, lease_seconds=30.0) is not None
        assert second_queue.claim_next(now=10.0, lease_seconds=30.0) is None
        first_connection.execute(
            "UPDATE reconciliation_tasks SET lease_expires_at_wallclock=? WHERE task_id=?",
            (999.0, task.task_id),
        )
        first_connection.commit()

        first_recovered = first_queue.recover_expired_running(now=20.0)
        second_recovered = second_queue.recover_expired_running(now=20.0)
        assert len(first_recovered) == 1
        assert second_recovered == ()
        current = second_queue.get(task.task_id)
        assert current is not None
        assert current.state is ReconciliationState.RETRYABLE
        assert current.last_error_type == "LeaseExpired"
        assert current.lease_token is None
    finally:
        first_connection.close()
        second_connection.close()


def test_sqlite_store_retries_transient_busy_operation_with_bounded_budget(tmp_path, monkeypatch):
    import sqlite3

    connection, store = _store(tmp_path)
    store._busy_retry_attempts = 2
    store._busy_retry_backoff = 0.0
    calls = 0
    original = store._read_generation_unlocked

    def fail_once_then_read():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise sqlite3.OperationalError("database is locked")
        return original()

    monkeypatch.setattr(store, "_read_generation_unlocked", fail_once_then_read)
    try:
        snapshot = store.load_snapshot()
        assert snapshot.generation == 0
        assert calls == 2
    finally:
        connection.close()


def test_sqlite_store_round_trips_lease_token(tmp_path):
    from AssetsManager.application import (
        ReconciliationKind,
        ReconciliationState,
        ReconciliationTask,
    )

    connection, store = _store(tmp_path)
    try:
        library_root = store.library_root
        task = ReconciliationTask(
            task_id="task-with-token",
            library_root=library_root,
            path=str(tmp_path / "library" / "asset"),
            kind=ReconciliationKind.ASSET_INDEX_ROOT_RESCAN,
            reason="busy",
            state=ReconciliationState.RUNNING,
            attempts=1,
            next_attempt_at=10.0,
            created_at=10.0,
            updated_at=10.0,
            lease_expires_at=20.0,
            lease_token="lease-token-1",
        )
        store.replace((task,), expected_generation=0)

        restored = store.load()[0]
        assert restored.lease_token == "lease-token-1"
        assert restored.state is ReconciliationState.RUNNING
        assert restored.attempts == 1
    finally:
        connection.close()


def test_sqlite_missing_lease_token_recovers_even_before_expiry(tmp_path):
    from AssetsManager.application import ReconciliationQueue, ReconciliationState

    connection, store = _store(tmp_path)
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        task = queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=10.0)
        claimed = queue.claim_next(now=10.0, lease_seconds=30.0)
        assert claimed is not None
        connection.execute(
            "UPDATE reconciliation_tasks SET lease_token=NULL, "
            "lease_expires_at_wallclock=? WHERE task_id=?",
            (9999.0, task.task_id),
        )
        connection.commit()

        recovered = store.recover_expired_running(now=20.0)
        assert len(recovered.recovered) == 1
        assert recovered.recovered[0].state is ReconciliationState.RETRYABLE
        assert recovered.recovered[0].lease_token is None
    finally:
        connection.close()



def test_sqlite_completion_rejects_wrong_lease_token(tmp_path):
    from AssetsManager.application import (
        ReconciliationQueue,
        ReconciliationQueuePersistenceConflict,
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
        task = queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=10.0)
        claimed = queue.claim_next(now=10.0, lease_seconds=30.0)
        assert claimed is not None

        with pytest.raises(ReconciliationQueuePersistenceConflict) as raised:
            queue.mark_succeeded(task.task_id, lease_token="wrong-token", now=10.0)
        assert raised.value.stale_worker_completion is True

        current = queue.get(task.task_id)
        assert current is not None
        assert current.state is ReconciliationState.RUNNING
        assert current.lease_token == claimed.lease_token

        completed = queue.mark_succeeded(
            task.task_id, lease_token=claimed.lease_token, now=10.0
        )
        assert completed.state is ReconciliationState.SUCCEEDED
        assert completed.lease_token is None
    finally:
        connection.close()



def test_sqlite_refreshed_snapshot_cannot_downgrade_old_worker_state_mutation(tmp_path):
    from AssetsManager.application import (
        ReconciliationQueue,
        ReconciliationQueuePersistenceConflict,
        ReconciliationState,
    )

    first_connection, second_connection, first_store, second_store = _file_stores(tmp_path)
    second_store._clock = lambda: 20.0
    second_store._wall_clock = lambda: 1002.0
    try:
        first_queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=first_store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        second_queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=second_store,
            clock=lambda: 20.0,
            wall_clock=lambda: 1002.0,
        )
        task = first_queue.enqueue_or_merge(
            path=tmp_path / "library",
            reason="scan_failed",
            now=10.0,
        )
        claimed = first_queue.claim_next(now=10.0, lease_seconds=1.0)
        assert claimed is not None
        recovered = second_queue.recover_expired_running(now=20.0)
        assert recovered[0].state is ReconciliationState.RETRYABLE

        with pytest.raises(ReconciliationQueuePersistenceConflict):
            first_queue.renew_lease(
                task.task_id,
                expected_attempts=claimed.attempts,
                lease_token=claimed.lease_token,
                lease_seconds=1.0,
                now=20.0,
            )
        refreshed = first_queue.get(task.task_id)
        assert refreshed is not None
        assert refreshed.state is ReconciliationState.RETRYABLE

        for mutation in (first_queue.mark_terminal, first_queue.cancel):
            with pytest.raises(ReconciliationQueuePersistenceConflict) as raised:
                mutation(
                    task.task_id,
                    expected_attempts=claimed.attempts,
                    lease_token=claimed.lease_token,
                    now=20.0,
                )
            assert raised.value.stale_worker_completion is True
            assert raised.value.operation == "state_mutation"

        current = second_store.load_snapshot().tasks[0]
        assert current.state is ReconciliationState.RETRYABLE
        assert current.lease_token is None
    finally:
        first_connection.close()
        second_connection.close()


def test_sqlite_transition_outbox_records_every_committed_queue_transition(tmp_path):
    from AssetsManager.application import ReconciliationQueue

    connection, store, wall_clock = _outbox_store(tmp_path)
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        first = queue.enqueue_or_merge(
            path=tmp_path / "library" / "first",
            reason="busy",
            operation_id="op-outbox",
            now=10.0,
        )
        claimed = queue.claim_next(now=10.0, lease_seconds=30.0)
        assert claimed is not None
        queue.mark_retryable(
            first.task_id,
            error_type="TemporaryError",
            error="try again",
            lease_token=claimed.lease_token,
            now=10.0,
        )
        wall_clock[0] = 1000.25
        claimed_again = queue.claim_next(now=10.25, lease_seconds=30.0)
        assert claimed_again is not None
        queue.mark_succeeded(
            first.task_id,
            lease_token=claimed_again.lease_token,
            now=10.25,
        )
        queue.cancel(first.task_id, now=10.5)

        rows = connection.execute(
            "SELECT reason, previous_task, current_task, operation_ids "
            "FROM reconciliation_transition_outbox ORDER BY id"
        ).fetchall()
        assert [row[0] for row in rows] == [
            "enqueue",
            "claim",
            "retryable",
            "claim",
            "succeeded",
        ]
        for _reason, previous, current, operation_ids in rows:
            assert previous is None or '"task_id"' in previous
            assert current is None or '"task_id"' in current
            assert operation_ids == '["op-outbox"]'
    finally:
        connection.close()


def test_sqlite_transition_outbox_replays_failed_listener_then_acknowledges(tmp_path):
    from AssetsManager.application import ReconciliationQueue

    connection, store, wall_clock = _outbox_store(tmp_path)
    calls: list[tuple[str, str]] = []
    fail = {"value": True}

    def listener(transition):
        calls.append((transition.task_id, transition.reason))
        if fail["value"]:
            fail["value"] = False
            raise RuntimeError("manifest database unavailable")

    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        _register_manifest_transition_consumer(queue, listener)
        task = queue.enqueue_or_merge(
            path=tmp_path / "library" / "asset",
            reason="busy",
            operation_id="op-replay",
            now=10.0,
        )
        pending = connection.execute(
            "SELECT delivery_attempts, delivered_at, last_error_type, next_delivery_at "
            "FROM reconciliation_transition_outbox"
        ).fetchone()
        assert pending[:3] == (1, None, "RuntimeError")
        assert 1015.0 <= pending[3] <= 1018.0

        assert queue.drain_transition_outbox() == 0
        assert calls == [(task.task_id, "enqueue")]
        wall_clock[0] = pending[3]
        assert queue.drain_transition_outbox() == 1
        delivered = connection.execute(
            "SELECT delivery_attempts, delivered_at, delivery_token, last_error_type, "
            "next_delivery_at "
            "FROM reconciliation_transition_outbox"
        ).fetchone()
        assert delivered[0] == 2
        assert delivered[1] is not None
        assert delivered[2] is None
        assert delivered[3] is None
        assert delivered[4] == 0.0
        assert calls == [(task.task_id, "enqueue"), (task.task_id, "enqueue")]
    finally:
        connection.close()


def test_sqlite_transition_outbox_requires_canonical_consumer_before_claiming(tmp_path):
    """Observers cannot claim or ACK a transition without the manifest consumer."""
    from AssetsManager.application import ReconciliationQueue
    from AssetsManager.application.reconciliation_queue import (
        IMPORT_MANIFEST_RECOVERY_CONSUMER_ID,
        ReconciliationTransitionDisposition,
    )

    connection, store, _wall_clock = _outbox_store(tmp_path)
    observer_calls: list[str] = []
    durable_calls: list[str] = []
    observer_fails = {"value": True}

    def observer(transition):
        observer_calls.append(transition.task_id)
        if observer_fails["value"]:
            observer_fails["value"] = False
            raise RuntimeError("observer unavailable")

    def consumer(transition):
        durable_calls.append(transition.task_id)
        return ReconciliationTransitionDisposition.APPLIED

    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        queue.add_transition_listener(observer)
        task = queue.enqueue_or_merge(
            path=tmp_path / "library" / "asset",
            reason="busy",
            operation_id="op-observer-only",
            now=10.0,
        )

        assert observer_calls == []
        assert connection.execute(
            "SELECT delivery_attempts, delivered_at FROM reconciliation_transition_outbox"
        ).fetchone() == (0, None)

        queue.set_durable_transition_consumer(
            IMPORT_MANIFEST_RECOVERY_CONSUMER_ID,
            consumer,
        )

        assert durable_calls == [task.task_id]
        assert observer_calls == [task.task_id]
        assert connection.execute(
            "SELECT delivered_at, last_error_type FROM reconciliation_transition_outbox"
        ).fetchone()[0] is not None
        assert queue.transition_backlog_size == 1

        assert queue.retry_transition_backlog() == 1
        assert durable_calls == [task.task_id]
        assert observer_calls == [task.task_id, task.task_id]
        assert queue.transition_backlog_size == 0
    finally:
        connection.close()


def test_sqlite_transition_outbox_rejects_implicit_or_conflicting_durable_consumers(
    tmp_path,
):
    """Only the canonical consumer with an explicit disposition may ACK."""
    from AssetsManager.application import ReconciliationQueue
    from AssetsManager.application.reconciliation_queue import (
        IMPORT_MANIFEST_RECOVERY_CONSUMER_ID,
    )

    connection, store, _wall_clock = _outbox_store(tmp_path)

    def implicit_consumer(_transition):
        return None

    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        with pytest.raises(ValueError, match="only supports"):
            queue.set_durable_transition_consumer("another_consumer", implicit_consumer)
        queue.set_durable_transition_consumer(
            IMPORT_MANIFEST_RECOVERY_CONSUMER_ID,
            implicit_consumer,
        )
        queue.set_durable_transition_consumer(
            IMPORT_MANIFEST_RECOVERY_CONSUMER_ID,
            implicit_consumer,
        )
        with pytest.raises(ValueError, match="already registered"):
            queue.set_durable_transition_consumer(
                IMPORT_MANIFEST_RECOVERY_CONSUMER_ID,
                lambda _transition: None,
            )

        queue.enqueue_or_merge(
            path=tmp_path / "library" / "asset",
            reason="busy",
            operation_id="op-implicit-consumer",
            now=10.0,
        )

        pending = connection.execute(
            "SELECT delivery_attempts, delivered_at, last_error_type, next_delivery_at "
            "FROM reconciliation_transition_outbox"
        ).fetchone()
        assert pending[:3] == (1, None, "TypeError")
        assert pending[3] > 1000.0
    finally:
        connection.close()


def test_sqlite_transition_outbox_retries_manifest_write_before_ack(tmp_path, monkeypatch):
    """A manifest DB failure leaves the successful queue event deliverable."""
    from AssetsManager.application import ReconciliationQueue
    from AssetsManager.application.import_manifest_store import (
        ImportManifestRecoveryService,
        ImportManifestStore,
    )

    connection, store, wall_clock = _outbox_store(tmp_path)
    root = tmp_path / "library"
    destination = root / "dest"
    operation_id = "outbox-manifest-write-retry"
    try:
        manifest_store = ImportManifestStore(connection, root)
        manifest_store.create(
            operation_id=operation_id,
            destination=destination,
            payload={
                "payload_version": 1,
                "destination": str(destination.resolve()),
                "items": [
                    {
                        "source": str((tmp_path / "source.txt").resolve()),
                        "target": str((destination / "source.txt").resolve()),
                        "state": "pending",
                    }
                ],
            },
            state="running",
        )
        queue = ReconciliationQueue(
            library_root=root,
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        ImportManifestRecoveryService(manifest_store, queue)
        task = queue.enqueue_or_merge(
            path=root,
            reason="import_manifest_recovery",
            operation_id=operation_id,
            now=10.0,
        )
        record = manifest_store.get(operation_id, include_items=False)
        assert record is not None
        assert manifest_store.bind_recovery_task(record, task.task_id)
        claimed = queue.claim_next(now=10.0, lease_seconds=30.0)
        assert claimed is not None

        original_record_transition = manifest_store.record_recovery_task_transition
        fail = {"value": True}

        def fail_success(*args, **kwargs):
            if fail["value"]:
                raise sqlite3.OperationalError("manifest database unavailable")
            return original_record_transition(*args, **kwargs)

        monkeypatch.setattr(
            manifest_store,
            "record_recovery_task_transition",
            fail_success,
        )
        queue.mark_succeeded(
            task.task_id,
            expected_attempts=claimed.attempts,
            lease_token=claimed.lease_token,
            now=10.0,
        )

        pending = connection.execute(
            "SELECT delivery_attempts, delivered_at, last_error_type, next_delivery_at "
            "FROM reconciliation_transition_outbox ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert pending[0] == 1
        assert pending[1] is None
        assert pending[2] is not None
        assert manifest_store.get(operation_id)["state"] == "recovery_pending"

        fail["value"] = False
        assert queue.drain_transition_outbox() == 0
        wall_clock[0] = pending[3]
        assert queue.drain_transition_outbox() == 1
        delivered = connection.execute(
            "SELECT delivery_attempts, delivered_at, last_error_type, next_delivery_at "
            "FROM reconciliation_transition_outbox ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert delivered[0] == 2
        assert delivered[1] is not None
        assert delivered[2] is None
        assert delivered[3] == 0.0
        assert manifest_store.get(operation_id)["state"] == "completed"
    finally:
        connection.close()


def test_sqlite_transition_outbox_idle_sweeper_drains_past_batch_limit(tmp_path):
    """A full synchronous batch cannot strand later events while idle."""
    from AssetsManager.application import (
        AssetIndexReconciliationService,
        ReconciliationQueue,
    )

    connection, store, _wall_clock = _outbox_store(tmp_path)
    calls: list[str] = []
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            max_tasks=100,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        for index in range(65):
            queue.enqueue_or_merge(
                path=tmp_path / "library" / str(index),
                reason="busy",
                operation_id=f"op-idle-{index}",
                now=10.0,
            )

        _register_manifest_transition_consumer(
            queue,
            lambda transition: calls.append(transition.task_id),
        )
        assert len(calls) == 64
        assert connection.execute(
            "SELECT COUNT(*) FROM reconciliation_transition_outbox "
            "WHERE delivered_at IS NULL"
        ).fetchone() == (1,)

        class OneSweep:
            calls = 0

            def wait(self, _timeout):
                self.calls += 1
                return self.calls > 1

        service = object.__new__(AssetIndexReconciliationService)
        service.reconciliation_queue = queue
        service._clock = lambda: 10.0
        service._run_sweeper(OneSweep())

        assert len(calls) == 65
        assert connection.execute(
            "SELECT COUNT(*) FROM reconciliation_transition_outbox "
            "WHERE delivered_at IS NULL"
        ).fetchone() == (0,)
    finally:
        connection.close()


def test_sqlite_transition_outbox_leases_one_head_event_across_connections(tmp_path):
    from AssetsManager.application import ReconciliationQueue

    (
        first_connection,
        second_connection,
        first_store,
        second_store,
        _first_wall_clock,
        _second_wall_clock,
    ) = _outbox_file_stores(tmp_path)
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=first_store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        queue.enqueue_or_merge(
            path=tmp_path / "library" / "asset",
            reason="busy",
            operation_id="op-lease",
            now=10.0,
        )
        first = first_store.claim_transition_outbox(limit=1, lease_seconds=30.0)
        second = second_store.claim_transition_outbox(limit=1, lease_seconds=30.0)
        assert len(first) == 1
        assert second == ()
        assert first_store.acknowledge_transition_outbox(
            first[0].event_id,
            delivery_token=first[0].delivery_token,
        )
        assert second_store.claim_transition_outbox(limit=1, lease_seconds=30.0) == ()
    finally:
        first_connection.close()
        second_connection.close()


def test_sqlite_transition_outbox_expired_delivery_lease_is_reclaimed(tmp_path):
    from AssetsManager.application import ReconciliationQueue

    connection, store, wall_clock = _outbox_store(tmp_path)
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: wall_clock[0],
        )
        queue.enqueue_or_merge(
            path=tmp_path / "library" / "asset",
            reason="busy",
            operation_id="op-expired-delivery",
            now=10.0,
        )
        first = store.claim_transition_outbox(limit=1, lease_seconds=1.0)
        assert len(first) == 1
        wall_clock[0] = 1002.0
        second = store.claim_transition_outbox(limit=1, lease_seconds=1.0)
        assert len(second) == 1
        assert second[0].event_id == first[0].event_id
        assert second[0].delivery_token != first[0].delivery_token
        assert second[0].delivery_attempts == 2
        assert not store.acknowledge_transition_outbox(
            first[0].event_id,
            delivery_token=first[0].delivery_token,
        )
    finally:
        connection.close()


def test_sqlite_transition_outbox_renewal_preserves_current_owner(tmp_path):
    """A delivery owner can extend its lease, while a stale token cannot."""
    from AssetsManager.application import ReconciliationQueue

    (
        first_connection,
        second_connection,
        first_store,
        second_store,
        first_wall_clock,
        second_wall_clock,
    ) = _outbox_file_stores(tmp_path)
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=first_store,
            clock=lambda: 10.0,
            wall_clock=lambda: first_wall_clock[0],
        )
        queue.enqueue_or_merge(
            path=tmp_path / "library" / "asset",
            reason="busy",
            operation_id="op-renew-delivery",
            now=10.0,
        )
        first = first_store.claim_transition_outbox(limit=1, lease_seconds=1.0)[0]

        assert first_store.renew_transition_outbox_lease(
            first.event_id,
            delivery_token=first.delivery_token,
            lease_seconds=10.0,
        )
        assert first_connection.execute(
            "SELECT delivery_lease_expires_at FROM reconciliation_transition_outbox "
            "WHERE id=?",
            (first.event_id,),
        ).fetchone() == (1010.0,)

        second_wall_clock[0] = 1002.0
        assert second_store.claim_transition_outbox(limit=1, lease_seconds=1.0) == ()

        first_wall_clock[0] = 1011.0
        second_wall_clock[0] = 1011.0
        second = second_store.claim_transition_outbox(limit=1, lease_seconds=1.0)[0]
        assert second.delivery_token != first.delivery_token
        assert not first_store.renew_transition_outbox_lease(
            first.event_id,
            delivery_token=first.delivery_token,
            lease_seconds=1.0,
        )
        assert second_store.acknowledge_transition_outbox(
            second.event_id,
            delivery_token=second.delivery_token,
        )
    finally:
        first_connection.close()
        second_connection.close()


def test_sqlite_transition_outbox_heartbeats_slow_durable_consumer(tmp_path, monkeypatch):
    """An active slow consumer retains its delivery lease across connections."""
    from AssetsManager.application import ReconciliationQueue
    from AssetsManager.application.reconciliation_queue import (
        IMPORT_MANIFEST_RECOVERY_CONSUMER_ID,
        ReconciliationTransitionDisposition,
    )

    (
        first_connection,
        second_connection,
        first_store,
        second_store,
        _first_wall_clock,
        _second_wall_clock,
    ) = _outbox_file_stores(tmp_path, wall_clock=time.time)
    entered = threading.Event()
    release = threading.Event()
    results: list[int] = []
    failures: list[BaseException] = []

    def consumer(_transition):
        entered.set()
        if not release.wait(3.0):
            raise AssertionError("slow consumer was not released")
        return ReconciliationTransitionDisposition.APPLIED

    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=first_store,
            clock=lambda: 10.0,
            wall_clock=time.time,
        )
        queue.enqueue_or_merge(
            path=tmp_path / "library" / "asset",
            reason="busy",
            operation_id="op-slow-consumer",
            now=10.0,
        )
        original_drain = queue.drain_transition_outbox
        monkeypatch.setattr(queue, "drain_transition_outbox", lambda *_args, **_kwargs: 0)
        queue.set_durable_transition_consumer(
            IMPORT_MANIFEST_RECOVERY_CONSUMER_ID,
            consumer,
        )
        monkeypatch.setattr(queue, "drain_transition_outbox", original_drain)

        def drain() -> None:
            try:
                results.append(
                    original_drain(lease_seconds=0.12, callback_max_age=2.0)
                )
            except BaseException as exc:
                failures.append(exc)

        worker = threading.Thread(target=drain, daemon=True)
        worker.start()
        assert entered.wait(2.0)
        time.sleep(0.30)
        assert second_store.claim_transition_outbox(limit=1, lease_seconds=0.12) == ()

        release.set()
        worker.join(3.0)
        assert not worker.is_alive()
        assert failures == []
        assert results == [1]
        assert first_connection.execute(
            "SELECT delivery_attempts, delivered_at FROM reconciliation_transition_outbox"
        ).fetchone()[0] == 1
        assert first_connection.execute(
            "SELECT delivered_at FROM reconciliation_transition_outbox"
        ).fetchone()[0] is not None
    finally:
        release.set()
        first_connection.close()
        second_connection.close()


def test_sqlite_transition_outbox_callback_age_releases_stuck_consumer(
    tmp_path,
    monkeypatch,
):
    """A stuck callback stops renewing so another process can replay the head."""
    from AssetsManager.application import ReconciliationQueue
    from AssetsManager.application.reconciliation_queue import (
        IMPORT_MANIFEST_RECOVERY_CONSUMER_ID,
        ReconciliationTransitionDisposition,
    )

    (
        first_connection,
        second_connection,
        first_store,
        second_store,
        _first_wall_clock,
        _second_wall_clock,
    ) = _outbox_file_stores(tmp_path, wall_clock=time.time)
    entered = threading.Event()
    release = threading.Event()
    results: list[int] = []
    failures: list[BaseException] = []

    def consumer(_transition):
        entered.set()
        if not release.wait(3.0):
            raise AssertionError("stuck consumer was not released")
        return ReconciliationTransitionDisposition.APPLIED

    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=first_store,
            clock=lambda: 10.0,
            wall_clock=time.time,
        )
        queue.enqueue_or_merge(
            path=tmp_path / "library" / "asset",
            reason="busy",
            operation_id="op-callback-age",
            now=10.0,
        )
        original_drain = queue.drain_transition_outbox
        monkeypatch.setattr(queue, "drain_transition_outbox", lambda *_args, **_kwargs: 0)
        queue.set_durable_transition_consumer(
            IMPORT_MANIFEST_RECOVERY_CONSUMER_ID,
            consumer,
        )
        monkeypatch.setattr(queue, "drain_transition_outbox", original_drain)

        def drain() -> None:
            try:
                results.append(
                    original_drain(lease_seconds=0.12, callback_max_age=0.20)
                )
            except BaseException as exc:
                failures.append(exc)

        worker = threading.Thread(target=drain, daemon=True)
        worker.start()
        assert entered.wait(2.0)
        time.sleep(0.60)
        takeover = second_store.claim_transition_outbox(limit=1, lease_seconds=1.0)
        assert len(takeover) == 1

        release.set()
        worker.join(3.0)
        assert not worker.is_alive()
        assert failures == []
        assert results == [0]
        assert second_store.acknowledge_transition_outbox(
            takeover[0].event_id,
            delivery_token=takeover[0].delivery_token,
        )
    finally:
        release.set()
        first_connection.close()
        second_connection.close()


def test_sqlite_transition_outbox_backoff_blocks_later_events_until_head_replays(
    tmp_path,
):
    """A deferred head remains a strict delivery-order barrier for its library."""
    from AssetsManager.application import ReconciliationQueue

    connection, store, wall_clock = _outbox_store(tmp_path)
    received: list[str] = []
    fail_first = {"value": True}

    def listener(transition):
        received.append(transition.task_id)
        if fail_first["value"]:
            fail_first["value"] = False
            raise RuntimeError("dependent store temporarily unavailable")

    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: wall_clock[0],
        )
        _register_manifest_transition_consumer(queue, listener)
        first = queue.enqueue_or_merge(
            path=tmp_path / "library" / "first",
            reason="busy",
            operation_id="op-backoff-first",
            now=10.0,
        )
        second = queue.enqueue_or_merge(
            path=tmp_path / "library" / "second",
            reason="busy",
            operation_id="op-backoff-second",
            now=10.0,
        )
        first_deadline = connection.execute(
            "SELECT next_delivery_at FROM reconciliation_transition_outbox "
            "WHERE task_id=?",
            (first.task_id,),
        ).fetchone()[0]

        assert first_deadline > wall_clock[0]
        assert received == [first.task_id]
        assert queue.drain_transition_outbox() == 0
        assert received == [first.task_id]
        assert connection.execute(
            "SELECT delivered_at FROM reconciliation_transition_outbox WHERE task_id=?",
            (second.task_id,),
        ).fetchone() == (None,)

        wall_clock[0] = first_deadline
        assert queue.drain_transition_outbox() == 2
        assert received == [first.task_id, first.task_id, second.task_id]
        assert connection.execute(
            "SELECT delivery_attempts, next_delivery_at FROM reconciliation_transition_outbox "
            "WHERE task_id=?",
            (first.task_id,),
        ).fetchone() == (2, 0.0)
    finally:
        connection.close()


def test_sqlite_transition_outbox_backoff_is_stable_and_finally_capped(tmp_path):
    """Deterministic jitter cannot raise a retry past the public 300-second cap."""
    from AssetsManager.application.reconciliation_queue_store import (
        _outbox_delivery_backoff,
    )

    kwargs = {
        "library_root": str(tmp_path / "library"),
        "event_id": 1,
        "delivery_attempts": 6,
    }

    delay = _outbox_delivery_backoff(**kwargs)

    assert delay == 300.0
    assert _outbox_delivery_backoff(**kwargs) == delay


def test_sqlite_transition_outbox_backoff_token_cas_preserves_new_owner(tmp_path):
    """A stale claimant cannot schedule a retry after the lease was reclaimed."""
    from AssetsManager.application import ReconciliationQueue

    connection, store, wall_clock = _outbox_store(tmp_path)
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: wall_clock[0],
        )
        queue.enqueue_or_merge(
            path=tmp_path / "library" / "asset",
            reason="busy",
            operation_id="op-backoff-token",
            now=10.0,
        )
        first = store.claim_transition_outbox(limit=1, lease_seconds=1.0)[0]
        wall_clock[0] = 1002.0
        second = store.claim_transition_outbox(limit=1, lease_seconds=30.0)[0]

        assert not store.fail_transition_outbox(
            first.event_id,
            delivery_token=first.delivery_token,
            error=RuntimeError("stale owner"),
        )
        row = connection.execute(
            "SELECT delivery_token, next_delivery_at FROM reconciliation_transition_outbox "
            "WHERE id=?",
            (second.event_id,),
        ).fetchone()
        assert row == (second.delivery_token, 0.0)

        assert store.fail_transition_outbox(
            second.event_id,
            delivery_token=second.delivery_token,
            error=RuntimeError("current owner"),
        )
        row = connection.execute(
            "SELECT delivery_token, delivery_attempts, next_delivery_at "
            "FROM reconciliation_transition_outbox WHERE id=?",
            (second.event_id,),
        ).fetchone()
        assert row[0] is None
        assert row[1] == 2
        assert row[2] > wall_clock[0]
    finally:
        connection.close()


def test_sqlite_transition_outbox_delivery_exhaustion_dead_letters_head(
    tmp_path,
):
    """A valid repeatedly failing head becomes auditable without blocking later work."""
    from AssetsManager.application import ReconciliationQueue

    connection, store, wall_clock = _outbox_store(
        tmp_path,
        transition_outbox_max_delivery_attempts=2,
    )
    received: list[str] = []
    fail_first = {"value": True}

    def listener(transition):
        received.append(transition.task_id)
        if fail_first["value"]:
            raise RuntimeError("manifest database remains unavailable")

    try:
        assert store.transition_outbox_max_delivery_attempts == 2
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: wall_clock[0],
        )
        _register_manifest_transition_consumer(queue, listener)
        first = queue.enqueue_or_merge(
            path=tmp_path / "library" / "first",
            reason="busy",
            operation_id="op-delivery-exhausted-first",
            now=10.0,
        )
        second = queue.enqueue_or_merge(
            path=tmp_path / "library" / "second",
            reason="busy",
            operation_id="op-delivery-exhausted-second",
            now=10.0,
        )
        first_event = connection.execute(
            "SELECT id FROM reconciliation_transition_outbox WHERE task_id=?",
            (first.task_id,),
        ).fetchone()[0]
        retry_deadline = connection.execute(
            "SELECT next_delivery_at FROM reconciliation_transition_outbox WHERE id=?",
            (first_event,),
        ).fetchone()[0]
        assert retry_deadline > wall_clock[0]

        wall_clock[0] = retry_deadline
        assert queue.drain_transition_outbox() == 0
        dead_letter = connection.execute(
            "SELECT event_id, task_id, delivery_attempts, error_type, error "
            "FROM reconciliation_transition_outbox_dead_letters"
        ).fetchone()
        assert dead_letter[:4] == (
            first_event,
            first.task_id,
            2,
            "_TransitionOutboxDeliveryAttemptsExhausted",
        )
        assert "RuntimeError: manifest database remains unavailable" in dead_letter[4]
        assert connection.execute(
            "SELECT COUNT(*) FROM reconciliation_transition_outbox WHERE id=?",
            (first_event,),
        ).fetchone() == (0,)

        fail_first["value"] = False
        assert queue.drain_transition_outbox() == 1
        assert received == [first.task_id, first.task_id, second.task_id]
        assert connection.execute(
            "SELECT delivered_at FROM reconciliation_transition_outbox WHERE task_id=?",
            (second.task_id,),
        ).fetchone()[0] is not None
    finally:
        connection.close()


def test_sqlite_transition_outbox_delivery_exhaustion_keeps_v44_row(tmp_path):
    """A pre-v45 store cannot drop a failed event without dead-letter evidence."""
    from AssetsManager.application import ReconciliationQueue, SQLiteReconciliationQueueStore
    from AssetsManager.core.schema_defs import RECONCILIATION_TRANSITION_OUTBOX_SCHEMA_V44

    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.executescript(_SCHEMA)
    connection.executescript(RECONCILIATION_TRANSITION_OUTBOX_SCHEMA_V44)
    connection.commit()
    store = SQLiteReconciliationQueueStore(
        connection=connection,
        library_root=tmp_path / "library",
        allow_unmanaged=True,
        clock=lambda: 10.0,
        wall_clock=lambda: 1000.0,
        transition_outbox_max_delivery_attempts=1,
    )

    def listener(_transition):
        raise RuntimeError("legacy durable consumer unavailable")

    try:
        assert not store.transition_outbox_dead_letters_enabled
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        _register_manifest_transition_consumer(queue, listener)
        task = queue.enqueue_or_merge(
            path=tmp_path / "library" / "asset",
            reason="busy",
            operation_id="op-v44-delivery-exhaustion",
            now=10.0,
        )

        assert connection.execute(
            "SELECT delivery_attempts, delivered_at, delivery_token "
            "FROM reconciliation_transition_outbox WHERE task_id=?",
            (task.task_id,),
        ).fetchone() == (1, None, None)
    finally:
        connection.close()


def test_sqlite_transition_outbox_exhaustion_cannot_dead_letter_new_owner(tmp_path):
    """A stale delivery token cannot terminally remove a re-leased event."""
    from AssetsManager.application import ReconciliationQueue

    connection, store, wall_clock = _outbox_store(
        tmp_path,
        transition_outbox_max_delivery_attempts=2,
    )
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: wall_clock[0],
        )
        queue.enqueue_or_merge(
            path=tmp_path / "library" / "asset",
            reason="busy",
            operation_id="op-exhaustion-token-cas",
            now=10.0,
        )
        first = store.claim_transition_outbox(limit=1, lease_seconds=1.0)[0]
        wall_clock[0] = 1002.0
        second = store.claim_transition_outbox(limit=1, lease_seconds=30.0)[0]

        assert not store.fail_transition_outbox(
            first.event_id,
            delivery_token=first.delivery_token,
            error=RuntimeError("stale owner"),
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM reconciliation_transition_outbox_dead_letters"
        ).fetchone() == (0,)

        assert store.fail_transition_outbox(
            second.event_id,
            delivery_token=second.delivery_token,
            error=RuntimeError("current owner"),
        )
        assert connection.execute(
            "SELECT event_id, delivery_attempts FROM reconciliation_transition_outbox_dead_letters"
        ).fetchone() == (second.event_id, 2)
        assert connection.execute(
            "SELECT COUNT(*) FROM reconciliation_transition_outbox"
        ).fetchone() == (0,)
    finally:
        connection.close()


def test_sqlite_v45_outbox_keeps_immediate_retry_compatibility(tmp_path):
    """A third-party v45 schema keeps its pre-v46 immediate retry behavior."""
    from AssetsManager.application import ReconciliationQueue, SQLiteReconciliationQueueStore
    from AssetsManager.core.schema_defs import (
        RECONCILIATION_TRANSITION_OUTBOX_DEAD_LETTERS_SCHEMA_V45,
        RECONCILIATION_TRANSITION_OUTBOX_SCHEMA_V44,
    )

    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.executescript(_SCHEMA)
    connection.executescript(RECONCILIATION_TRANSITION_OUTBOX_SCHEMA_V44)
    connection.executescript(RECONCILIATION_TRANSITION_OUTBOX_DEAD_LETTERS_SCHEMA_V45)
    connection.commit()
    store = SQLiteReconciliationQueueStore(
        connection=connection,
        library_root=tmp_path / "library",
        allow_unmanaged=True,
        clock=lambda: 10.0,
        wall_clock=lambda: 1000.0,
    )
    received: list[str] = []
    fail_once = {"value": True}

    def listener(transition):
        received.append(transition.task_id)
        if fail_once["value"]:
            fail_once["value"] = False
            raise RuntimeError("legacy retry")

    try:
        assert store.transition_outbox_enabled
        assert store.transition_outbox_dead_letters_enabled
        assert not store.transition_outbox_backoff_enabled
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        _register_manifest_transition_consumer(queue, listener)
        task = queue.enqueue_or_merge(
            path=tmp_path / "library" / "asset",
            reason="busy",
            operation_id="op-v45-retry",
            now=10.0,
        )

        assert queue.drain_transition_outbox() == 1
        assert received == [task.task_id, task.task_id]
        assert connection.execute(
            "SELECT delivery_attempts, delivered_at FROM reconciliation_transition_outbox"
        ).fetchone()[0] == 2
    finally:
        connection.close()


def test_sqlite_transition_outbox_quarantines_invalid_retry_deadline(tmp_path):
    """A corrupted v46 retry deadline cannot permanently block valid events."""
    from AssetsManager.application import ReconciliationQueue

    connection, store, _wall_clock = _outbox_store(tmp_path)
    received: list[str] = []
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        first = queue.enqueue_or_merge(
            path=tmp_path / "library" / "first",
            reason="busy",
            operation_id="op-invalid-deadline-first",
            now=10.0,
        )
        second = queue.enqueue_or_merge(
            path=tmp_path / "library" / "second",
            reason="busy",
            operation_id="op-invalid-deadline-second",
            now=10.0,
        )
        first_event = connection.execute(
            "SELECT id FROM reconciliation_transition_outbox WHERE task_id=?",
            (first.task_id,),
        ).fetchone()[0]
        connection.execute(
            "UPDATE reconciliation_transition_outbox SET next_delivery_at='not-a-deadline' "
            "WHERE id=?",
            (first_event,),
        )
        connection.commit()

        _register_manifest_transition_consumer(
            queue,
            lambda transition: received.append(transition.task_id),
        )

        assert received == [second.task_id]
        assert connection.execute(
            "SELECT error_type FROM reconciliation_transition_outbox_dead_letters "
            "WHERE event_id=?",
            (first_event,),
        ).fetchone() == ("ValueError",)
        assert connection.execute(
            "SELECT COUNT(*) FROM reconciliation_transition_outbox WHERE id=?",
            (first_event,),
        ).fetchone() == (0,)
    finally:
        connection.close()


def test_sqlite_transition_outbox_quarantines_invalid_delivery_lease_deadline(
    tmp_path,
):
    """A corrupt queue-head lease cannot permanently block valid events."""
    from AssetsManager.application import ReconciliationQueue

    connection, store, _wall_clock = _outbox_store(tmp_path)
    received: list[str] = []
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        first = queue.enqueue_or_merge(
            path=tmp_path / "library" / "first",
            reason="busy",
            operation_id="op-invalid-lease-first",
            now=10.0,
        )
        second = queue.enqueue_or_merge(
            path=tmp_path / "library" / "second",
            reason="busy",
            operation_id="op-invalid-lease-second",
            now=10.0,
        )
        first_event = connection.execute(
            "SELECT id FROM reconciliation_transition_outbox WHERE task_id=?",
            (first.task_id,),
        ).fetchone()[0]
        connection.execute(
            "UPDATE reconciliation_transition_outbox SET "
            "delivery_token='broken-owner', "
            "delivery_lease_expires_at='not-a-lease-deadline' WHERE id=?",
            (first_event,),
        )
        connection.commit()

        _register_manifest_transition_consumer(
            queue,
            lambda transition: received.append(transition.task_id),
        )

        assert received == [second.task_id]
        assert connection.execute(
            "SELECT error_type FROM reconciliation_transition_outbox_dead_letters "
            "WHERE event_id=?",
            (first_event,),
        ).fetchone() == ("ValueError",)
        assert connection.execute(
            "SELECT COUNT(*) FROM reconciliation_transition_outbox WHERE id=?",
            (first_event,),
        ).fetchone() == (0,)
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("corruption", "expected_error_type"),
    (
        ("invalid_json", "JSONDecodeError"),
        ("mismatched_previous_task", "ValueError"),
        ("mismatched_operation_scope", "ValueError"),
    ),
)
def test_sqlite_transition_outbox_quarantines_poison_head_and_delivers_next(
    tmp_path,
    corruption,
    expected_error_type,
):
    """A malformed head moves to durable dead letter without blocking later work."""
    from AssetsManager.application import ReconciliationQueue

    connection, store, _wall_clock = _outbox_store(tmp_path)
    received: list[str] = []
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        first = queue.enqueue_or_merge(
            path=tmp_path / "library" / "first",
            reason="busy",
            operation_id="op-poison-first",
            now=10.0,
        )
        second = queue.enqueue_or_merge(
            path=tmp_path / "library" / "second",
            reason="busy",
            operation_id="op-poison-second",
            now=10.0,
        )
        first_event = connection.execute(
            "SELECT id FROM reconciliation_transition_outbox WHERE task_id=?",
            (first.task_id,),
        ).fetchone()[0]
        if corruption == "invalid_json":
            connection.execute(
                "UPDATE reconciliation_transition_outbox SET current_task='{bad' WHERE id=?",
                (first_event,),
            )
        elif corruption == "mismatched_previous_task":
            second_snapshot = connection.execute(
                "SELECT current_task FROM reconciliation_transition_outbox WHERE task_id=?",
                (second.task_id,),
            ).fetchone()[0]
            connection.execute(
                "UPDATE reconciliation_transition_outbox SET previous_task=? WHERE id=?",
                (second_snapshot, first_event),
            )
        else:
            connection.execute(
                "UPDATE reconciliation_transition_outbox SET operation_ids='[\"wrong-scope\"]' "
                "WHERE id=?",
                (first_event,),
            )
        connection.commit()

        _register_manifest_transition_consumer(
            queue,
            lambda transition: received.append(transition.task_id),
        )

        assert received == [second.task_id]
        dead_letter = connection.execute(
            "SELECT event_id, task_id, delivery_attempts, dead_lettered_at, "
            "error_type, error FROM reconciliation_transition_outbox_dead_letters"
        ).fetchone()
        assert dead_letter[0] == first_event
        assert dead_letter[1] == first.task_id
        assert dead_letter[2] == 1
        assert dead_letter[3] == 1000.0
        assert dead_letter[4] == expected_error_type
        assert dead_letter[5]
        assert connection.execute(
            "SELECT COUNT(*) FROM reconciliation_transition_outbox WHERE task_id=?",
            (first.task_id,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT delivered_at FROM reconciliation_transition_outbox WHERE task_id=?",
            (second.task_id,),
        ).fetchone()[0] is not None
    finally:
        connection.close()


def test_sqlite_transition_outbox_poison_isolation_rolls_back_on_dead_letter_failure(
    tmp_path,
):
    """A failed dead-letter copy must leave the live head intact and ordered."""
    from AssetsManager.application import ReconciliationQueue, ReconciliationQueuePersistenceError

    connection, store, _wall_clock = _outbox_store(tmp_path)
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        first = queue.enqueue_or_merge(
            path=tmp_path / "library" / "first",
            reason="busy",
            operation_id="op-poison-rollback-first",
            now=10.0,
        )
        second = queue.enqueue_or_merge(
            path=tmp_path / "library" / "second",
            reason="busy",
            operation_id="op-poison-rollback-second",
            now=10.0,
        )
        first_event = connection.execute(
            "SELECT id FROM reconciliation_transition_outbox WHERE task_id=?",
            (first.task_id,),
        ).fetchone()[0]
        connection.execute(
            "UPDATE reconciliation_transition_outbox SET current_task='{bad' WHERE id=?",
            (first_event,),
        )
        connection.execute(
            "CREATE TRIGGER fail_transition_dead_letter BEFORE INSERT ON "
            "reconciliation_transition_outbox_dead_letters BEGIN "
            "SELECT RAISE(FAIL, 'dead letter unavailable'); END"
        )
        connection.commit()

        with pytest.raises(ReconciliationQueuePersistenceError):
            store.claim_transition_outbox(limit=1, lease_seconds=30.0)

        assert connection.execute(
            "SELECT delivery_token, delivery_attempts FROM reconciliation_transition_outbox "
            "WHERE id=?",
            (first_event,),
        ).fetchone() == (None, 0)
        assert connection.execute(
            "SELECT COUNT(*) FROM reconciliation_transition_outbox_dead_letters"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT delivered_at FROM reconciliation_transition_outbox WHERE task_id=?",
            (second.task_id,),
        ).fetchone() == (None,)
    finally:
        connection.close()


def test_sqlite_transition_outbox_poison_isolation_rolls_back_on_source_delete_failure(
    tmp_path,
):
    """A failed source delete cannot commit the dead-letter copy alone."""
    from AssetsManager.application import ReconciliationQueue, ReconciliationQueuePersistenceError

    connection, store, _wall_clock = _outbox_store(tmp_path)
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        first = queue.enqueue_or_merge(
            path=tmp_path / "library" / "first",
            reason="busy",
            operation_id="op-poison-delete-first",
            now=10.0,
        )
        second = queue.enqueue_or_merge(
            path=tmp_path / "library" / "second",
            reason="busy",
            operation_id="op-poison-delete-second",
            now=10.0,
        )
        first_event = connection.execute(
            "SELECT id FROM reconciliation_transition_outbox WHERE task_id=?",
            (first.task_id,),
        ).fetchone()[0]
        connection.execute(
            "UPDATE reconciliation_transition_outbox SET current_task='{bad' WHERE id=?",
            (first_event,),
        )
        connection.execute(
            "CREATE TRIGGER fail_transition_source_delete BEFORE DELETE ON "
            "reconciliation_transition_outbox BEGIN "
            "SELECT RAISE(FAIL, 'source row unavailable'); END"
        )
        connection.commit()

        with pytest.raises(ReconciliationQueuePersistenceError):
            store.claim_transition_outbox(limit=1, lease_seconds=30.0)

        assert connection.execute(
            "SELECT delivery_token, delivery_attempts FROM reconciliation_transition_outbox "
            "WHERE id=?",
            (first_event,),
        ).fetchone() == (None, 0)
        assert connection.execute(
            "SELECT COUNT(*) FROM reconciliation_transition_outbox_dead_letters"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT delivered_at FROM reconciliation_transition_outbox WHERE task_id=?",
            (second.task_id,),
        ).fetchone() == (None,)
    finally:
        connection.close()


def test_sqlite_v44_outbox_poison_fails_closed_without_dead_letter_table(tmp_path):
    """A pre-v45 store never deletes a corrupt event without durable evidence."""
    from AssetsManager.application import (
        ReconciliationQueue,
        ReconciliationQueuePersistenceError,
        SQLiteReconciliationQueueStore,
    )
    from AssetsManager.core.schema_defs import RECONCILIATION_TRANSITION_OUTBOX_SCHEMA_V44

    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.executescript(_SCHEMA)
    connection.executescript(RECONCILIATION_TRANSITION_OUTBOX_SCHEMA_V44)
    connection.commit()
    store = SQLiteReconciliationQueueStore(
        connection=connection,
        library_root=tmp_path / "library",
        allow_unmanaged=True,
        clock=lambda: 10.0,
        wall_clock=lambda: 1000.0,
    )
    try:
        assert store.transition_outbox_enabled
        assert not store.transition_outbox_dead_letters_enabled
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        task = queue.enqueue_or_merge(
            path=tmp_path / "library" / "asset",
            reason="busy",
            operation_id="op-v44-poison",
            now=10.0,
        )
        event_id = connection.execute(
            "SELECT id FROM reconciliation_transition_outbox WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0]
        connection.execute(
            "UPDATE reconciliation_transition_outbox SET current_task='{bad' WHERE id=?",
            (event_id,),
        )
        connection.commit()

        with pytest.raises(ReconciliationQueuePersistenceError):
            store.claim_transition_outbox(limit=1, lease_seconds=30.0)

        assert connection.execute(
            "SELECT delivery_token, delivery_attempts FROM reconciliation_transition_outbox "
            "WHERE id=?",
            (event_id,),
        ).fetchone() == (None, 0)
        assert connection.execute(
            "SELECT COUNT(*) FROM reconciliation_transition_outbox WHERE id=?",
            (event_id,),
        ).fetchone() == (1,)
    finally:
        connection.close()


def test_sqlite_transition_outbox_records_terminal_cancelled_and_lease_recovery(tmp_path):
    from AssetsManager.application import ReconciliationQueue

    connection, store, _wall_clock = _outbox_store(tmp_path)
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        terminal = queue.enqueue_or_merge(
            path=tmp_path / "library" / "terminal",
            reason="busy",
            operation_id="op-terminal",
            now=10.0,
        )
        queue.mark_terminal(
            terminal.task_id,
            error_type="PermanentError",
            error="cannot repair",
            now=10.0,
        )
        cancelled = queue.enqueue_or_merge(
            path=tmp_path / "library" / "cancelled",
            reason="busy",
            operation_id="op-cancelled",
            now=10.0,
        )
        queue.cancel(cancelled.task_id, now=10.0)
        expiring = queue.enqueue_or_merge(
            path=tmp_path / "library" / "expiring",
            reason="busy",
            operation_id="op-expiring",
            now=10.0,
        )
        claim = queue.claim_next(now=10.0, lease_seconds=30.0)
        assert claim is not None and claim.task_id == expiring.task_id
        connection.execute(
            "UPDATE reconciliation_tasks SET lease_expires_at_wallclock=999.0 "
            "WHERE task_id=?",
            (expiring.task_id,),
        )
        connection.commit()
        queue.recover_expired_running(now=20.0)

        rows = connection.execute(
            "SELECT reason FROM reconciliation_transition_outbox ORDER BY id"
        ).fetchall()
        assert [row[0] for row in rows] == [
            "enqueue",
            "terminal",
            "enqueue",
            "cancelled",
            "enqueue",
            "claim",
            "lease_expired",
        ]
    finally:
        connection.close()


def test_sqlite_transition_outbox_rolls_back_with_failed_queue_mutation(tmp_path, monkeypatch):
    from AssetsManager.application import ReconciliationQueue, ReconciliationQueuePersistenceError

    connection, store, _wall_clock = _outbox_store(tmp_path)

    def fail_insert(**_kwargs):
        raise RuntimeError("outbox write failed")

    monkeypatch.setattr(store, "_insert_transition_outbox_unlocked", fail_insert)
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        with pytest.raises(ReconciliationQueuePersistenceError):
            queue.enqueue_or_merge(
                path=tmp_path / "library" / "asset",
                reason="busy",
                operation_id="op-rollback",
                now=10.0,
            )
        assert store.load() == ()
        assert connection.execute(
            "SELECT COUNT(*) FROM reconciliation_transition_outbox"
        ).fetchone() == (0,)
    finally:
        connection.close()


def test_sqlite_transition_outbox_dead_letter_replay_is_audited_and_idempotent(
    tmp_path,
):
    """An explicit replay restores the same event while retaining its audit row."""
    from AssetsManager.application import ReconciliationQueue

    connection, store, _wall_clock = _outbox_store(
        tmp_path,
        transition_outbox_max_delivery_attempts=1,
    )
    fail = {"value": True}

    def listener(_transition):
        if fail["value"]:
            raise RuntimeError("operator replay test failure")

    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        _register_manifest_transition_consumer(queue, listener)
        task = queue.enqueue_or_merge(
            path=tmp_path / "library" / "asset",
            reason="busy",
            operation_id="op-dead-letter-replay",
            now=10.0,
        )
        event_id = connection.execute(
            "SELECT event_id FROM reconciliation_transition_outbox_dead_letters "
            "WHERE task_id=?",
            (task.task_id,),
        ).fetchone()[0]
        dead_letter = store.list_transition_outbox_dead_letters(limit=10)[0]
        assert dead_letter.event_id == event_id
        assert dead_letter.transition.task_id == task.task_id
        assert dead_letter.delivery_attempts == 1
        assert (
            store.replay_transition_outbox_dead_letter(
                event_id,
                expected_dead_lettered_at=dead_letter.dead_lettered_at + 1,
            )
            is False
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM reconciliation_transition_outbox WHERE id=?",
            (event_id,),
        ).fetchone() == (0,)

        fail["value"] = False
        assert store.replay_transition_outbox_dead_letter(
            event_id,
            expected_dead_lettered_at=dead_letter.dead_lettered_at,
        )
        assert connection.execute(
            "SELECT id, delivery_attempts, delivered_at, next_delivery_at "
            "FROM reconciliation_transition_outbox WHERE id=?",
            (event_id,),
        ).fetchone() == (event_id, 1, None, 0.0)
        # The source is the immutable audit anchor and is never consumed by
        # replay itself.
        assert connection.execute(
            "SELECT COUNT(*) FROM reconciliation_transition_outbox_dead_letters "
            "WHERE event_id=?",
            (event_id,),
        ).fetchone() == (1,)
        assert (
            store.replay_transition_outbox_dead_letter(
                event_id,
                expected_dead_lettered_at=dead_letter.dead_lettered_at,
            )
            is False
        )
        assert queue.drain_transition_outbox() == 1
        assert connection.execute(
            "SELECT delivery_attempts, delivered_at FROM reconciliation_transition_outbox "
            "WHERE id=?",
            (event_id,),
        ).fetchone()[1] is not None
    finally:
        connection.close()


@pytest.mark.parametrize("later_progress", ("ack", "lease", "attempt"))
def test_sqlite_transition_outbox_dead_letter_replay_blocks_later_progress(
    tmp_path,
    later_progress,
):
    """An older dead letter cannot overtake a later event with progress."""
    from AssetsManager.application import (
        ReconciliationQueue,
        ReconciliationQueuePersistenceConflict,
    )

    connection, store, wall_clock = _outbox_store(
        tmp_path,
        transition_outbox_max_delivery_attempts=8,
    )
    try:
        # Keep the queue durable but without a consumer so the test can stage
        # the two event rows independently.
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: wall_clock[0],
        )
        queue.enqueue_or_merge(
            path=tmp_path / "library" / "first",
            reason="busy",
            operation_id="op-replay-order-first",
            now=10.0,
        )
        first_entry = store.claim_transition_outbox(limit=1, lease_seconds=30.0)[0]
        # Move the first event to the normal terminal dead-letter path without
        # requiring seven real callback failures.
        connection.execute(
            "UPDATE reconciliation_transition_outbox SET delivery_attempts=8 "
            "WHERE id=?",
            (first_entry.event_id,),
        )
        connection.commit()
        assert store.fail_transition_outbox(
            first_entry.event_id,
            delivery_token=first_entry.delivery_token,
            error=RuntimeError("first event failed"),
        )
        dead_letter = store.list_transition_outbox_dead_letters(limit=1)[0]
        assert dead_letter.event_id == first_entry.event_id

        queue.enqueue_or_merge(
            path=tmp_path / "library" / "second",
            reason="busy",
            operation_id="op-replay-order-second",
            now=10.0,
        )
        second_entry = store.claim_transition_outbox(limit=1, lease_seconds=30.0)[0]
        if later_progress == "ack":
            assert store.acknowledge_transition_outbox(
                second_entry.event_id,
                delivery_token=second_entry.delivery_token,
            )
        elif later_progress == "lease":
            # The claim itself is the later event's delivery progress; leave
            # its valid lease active to exercise the token/lease branch.
            assert second_entry.delivery_attempts == 1
        else:
            assert store.fail_transition_outbox(
                second_entry.event_id,
                delivery_token=second_entry.delivery_token,
                error=RuntimeError("later event retry"),
            )
            assert connection.execute(
                "SELECT delivery_token, delivery_attempts FROM "
                "reconciliation_transition_outbox WHERE id=?",
                (second_entry.event_id,),
            ).fetchone() == (None, 1)

        with pytest.raises(ReconciliationQueuePersistenceConflict) as raised:
            store.replay_transition_outbox_dead_letter(
                dead_letter.event_id,
                expected_dead_lettered_at=dead_letter.dead_lettered_at,
            )
        assert raised.value.operation == "transition_outbox_replay_order"
        assert connection.execute(
            "SELECT COUNT(*) FROM reconciliation_transition_outbox WHERE id=?",
            (first_entry.event_id,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM reconciliation_transition_outbox_dead_letters "
            "WHERE event_id=?",
            (first_entry.event_id,),
        ).fetchone() == (1,)
    finally:
        connection.close()


def test_sqlite_transition_outbox_dead_letter_replay_failure_is_idempotent(
    tmp_path,
):
    """A replay that exhausts again removes its live row despite the PK anchor."""
    from AssetsManager.application import ReconciliationQueue

    connection, store, wall_clock = _outbox_store(
        tmp_path,
        transition_outbox_max_delivery_attempts=1,
    )
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: wall_clock[0],
        )
        queue.enqueue_or_merge(
            path=tmp_path / "library" / "asset",
            reason="busy",
            operation_id="op-replay-again-fails",
            now=10.0,
        )
        first_entry = store.claim_transition_outbox(limit=1, lease_seconds=30.0)[0]
        assert store.fail_transition_outbox(
            first_entry.event_id,
            delivery_token=first_entry.delivery_token,
            error=RuntimeError("initial failure"),
        )
        dead_letter = store.list_transition_outbox_dead_letters(limit=1)[0]

        assert store.replay_transition_outbox_dead_letter(
            dead_letter.event_id,
            expected_dead_lettered_at=dead_letter.dead_lettered_at,
        )
        replay_entry = store.claim_transition_outbox(limit=1, lease_seconds=30.0)[0]
        assert replay_entry.delivery_attempts == dead_letter.delivery_attempts + 1
        # This used to raise UNIQUE(event_id) and roll back, leaving the live
        # row leased forever.  The copy now treats the existing audit anchor
        # as idempotent and atomically deletes the replayed source row.
        assert store.fail_transition_outbox(
            replay_entry.event_id,
            delivery_token=replay_entry.delivery_token,
            error=RuntimeError("replay failure"),
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM reconciliation_transition_outbox WHERE id=?",
            (first_entry.event_id,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT event_id, delivery_attempts FROM "
            "reconciliation_transition_outbox_dead_letters WHERE event_id=?",
            (dead_letter.event_id,),
        ).fetchone() == (dead_letter.event_id, dead_letter.delivery_attempts + 1)
    finally:
        connection.close()


def test_sqlite_transition_outbox_dead_letter_replay_has_cross_connection_cas(
    tmp_path,
):
    """Two SQLite owners can accept at most one restore of a dead letter."""
    from AssetsManager.application import ReconciliationQueue

    (
        first_connection,
        second_connection,
        first_store,
        second_store,
        _first_wall_clock,
        _second_wall_clock,
    ) = _outbox_file_stores(
        tmp_path,
        transition_outbox_max_delivery_attempts=1,
    )

    def listener(_transition):
        raise RuntimeError("cross-connection replay failure")

    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=first_store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        _register_manifest_transition_consumer(queue, listener)
        task = queue.enqueue_or_merge(
            path=tmp_path / "library" / "asset",
            reason="busy",
            operation_id="op-dead-letter-cross-connection",
            now=10.0,
        )
        dead_letter = second_store.list_transition_outbox_dead_letters(limit=1)[0]
        assert first_store.replay_transition_outbox_dead_letter(
            dead_letter.event_id,
            expected_dead_lettered_at=dead_letter.dead_lettered_at,
        )
        assert not second_store.replay_transition_outbox_dead_letter(
            dead_letter.event_id,
            expected_dead_lettered_at=dead_letter.dead_lettered_at,
        )
        assert second_connection.execute(
            "SELECT COUNT(*) FROM reconciliation_transition_outbox WHERE id=?",
            (dead_letter.event_id,),
        ).fetchone() == (1,)
        assert first_connection.execute(
            "SELECT task_id, delivery_attempts FROM reconciliation_transition_outbox "
            "WHERE id=?",
            (dead_letter.event_id,),
        ).fetchone() == (task.task_id, 1)
    finally:
        first_connection.close()
        second_connection.close()


def test_sqlite_transition_outbox_metrics_report_age_attempts_and_leases(tmp_path):
    """Metrics expose pending/ACK/dead-letter state without decoding payloads."""
    from AssetsManager.application import ReconciliationQueue
    from AssetsManager.application.reconciliation_queue import (
        ReconciliationTransitionDisposition,
    )

    connection, store, wall_clock = _outbox_store(
        tmp_path,
        transition_outbox_max_delivery_attempts=2,
    )

    def listener(transition):
        operation_id = transition.operation_ids[0]
        if operation_id == "op-metrics-ack":
            return ReconciliationTransitionDisposition.APPLIED
        if operation_id == "op-metrics-dead":
            raise RuntimeError("metrics dead-letter failure")
        return ReconciliationTransitionDisposition.RETRY

    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: wall_clock[0],
        )
        _register_manifest_transition_consumer(queue, listener)
        acknowledged = queue.enqueue_or_merge(
            path=tmp_path / "library" / "ack",
            reason="busy",
            operation_id="op-metrics-ack",
            now=10.0,
        )
        dead = queue.enqueue_or_merge(
            path=tmp_path / "library" / "dead",
            reason="busy",
            operation_id="op-metrics-dead",
            now=10.0,
        )
        retry = queue.enqueue_or_merge(
            path=tmp_path / "library" / "retry",
            reason="busy",
            operation_id="op-metrics-retry",
            now=10.0,
        )
        retry_deadline = connection.execute(
            "SELECT next_delivery_at FROM reconciliation_transition_outbox "
            "WHERE task_id=?",
            (dead.task_id,),
        ).fetchone()[0]
        # The dead-letter event is at the head after its first failed attempt;
        # move time to its not-before deadline and let the second failure
        # terminalize it, then claim the retry event to expose a live lease.
        wall_clock[0] = retry_deadline
        assert queue.drain_transition_outbox() == 0
        # The failed head stops the strict-order drain.  A second pass after
        # the dead letter is isolated reaches the following retry event.
        wall_clock[0] = 1000.0
        assert queue.drain_transition_outbox() == 0
        retry_deadline = connection.execute(
            "SELECT next_delivery_at FROM reconciliation_transition_outbox "
            "WHERE task_id=?",
            (retry.task_id,),
        ).fetchone()[0]
        wall_clock[0] = retry_deadline
        claimed = store.claim_transition_outbox(limit=1, lease_seconds=30.0)[0]
        connection.execute(
            "UPDATE reconciliation_transition_outbox SET created_at=1000, "
            "delivery_lease_expires_at=1200 WHERE id=?",
            (claimed.event_id,),
        )
        connection.execute(
            "UPDATE reconciliation_transition_outbox SET created_at=1000 "
            "WHERE delivered_at IS NOT NULL"
        )
        connection.execute(
            "UPDATE reconciliation_transition_outbox_dead_letters "
            "SET dead_lettered_at=1000"
        )
        connection.commit()
        metrics = store.transition_outbox_metrics(now=1100.0)
        assert metrics.pending_count == 1
        assert metrics.acknowledged_count == 1
        assert metrics.dead_letter_count == 1
        assert metrics.leased_count == 1
        assert metrics.expired_lease_count == 0
        assert metrics.delivery_attempts_total == 5
        assert metrics.max_delivery_attempts == 2
        assert metrics.oldest_pending_age_seconds == 100.0
        assert metrics.oldest_dead_letter_age_seconds == 100.0
        assert acknowledged.task_id != retry.task_id
        assert store.acknowledge_transition_outbox(
            claimed.event_id,
            delivery_token=claimed.delivery_token,
        )
    finally:
        connection.close()


def test_sqlite_transition_outbox_prune_applies_explicit_ack_and_dead_letter_retention(
    tmp_path,
):
    """Retention deletes only rows older than the supplied bounded cutoffs."""
    from AssetsManager.application import ReconciliationQueue

    connection, store, _wall_clock = _outbox_store(
        tmp_path,
        transition_outbox_max_delivery_attempts=1,
    )

    def listener(transition):
        if transition.operation_ids == ("op-retention-ack",):
            return None
        raise RuntimeError("retention dead-letter failure")

    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        _register_manifest_transition_consumer(queue, listener)
        acknowledged = queue.enqueue_or_merge(
            path=tmp_path / "library" / "ack",
            reason="busy",
            operation_id="op-retention-ack",
            now=10.0,
        )
        dead = queue.enqueue_or_merge(
            path=tmp_path / "library" / "dead",
            reason="busy",
            operation_id="op-retention-dead",
            now=10.0,
        )
        acknowledged_event = connection.execute(
            "SELECT id FROM reconciliation_transition_outbox WHERE task_id=?",
            (acknowledged.task_id,),
        ).fetchone()[0]
        dead_event = connection.execute(
            "SELECT event_id FROM reconciliation_transition_outbox_dead_letters "
            "WHERE task_id=?",
            (dead.task_id,),
        ).fetchone()[0]
        connection.execute(
            "UPDATE reconciliation_transition_outbox SET created_at=900, delivered_at=900 "
            "WHERE id=?",
            (acknowledged_event,),
        )
        connection.execute(
            "UPDATE reconciliation_transition_outbox_dead_letters "
            "SET created_at=900, dead_lettered_at=900 WHERE event_id=?",
            (dead_event,),
        )
        connection.commit()

        result = store.prune_transition_outbox(
            acknowledged_before=950,
            dead_letter_before=950,
            limit=10,
        )
        assert result.acknowledged_deleted == 1
        assert result.dead_letters_deleted == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM reconciliation_transition_outbox WHERE id=?",
            (acknowledged_event,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM reconciliation_transition_outbox_dead_letters "
            "WHERE event_id=?",
            (dead_event,),
        ).fetchone() == (0,)
    finally:
        connection.close()


def test_sqlite_transition_outbox_prune_never_removes_old_pending_or_leased_rows(
    tmp_path,
):
    """Retention only removes terminal rows, even when active rows are old."""
    from AssetsManager.application import ReconciliationQueue

    connection, store, _wall_clock = _outbox_store(tmp_path)
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        leased_task = queue.enqueue_or_merge(
            path=tmp_path / "library" / "leased",
            reason="busy",
            operation_id="op-retention-leased",
            now=10.0,
        )
        pending_task = queue.enqueue_or_merge(
            path=tmp_path / "library" / "pending",
            reason="busy",
            operation_id="op-retention-pending",
            now=10.0,
        )
        acknowledged_task = queue.enqueue_or_merge(
            path=tmp_path / "library" / "acknowledged",
            reason="busy",
            operation_id="op-retention-acknowledged",
            now=10.0,
        )
        leased_event = store.claim_transition_outbox(
            limit=1,
            lease_seconds=30.0,
        )[0]
        acknowledged_event = connection.execute(
            "SELECT id FROM reconciliation_transition_outbox WHERE task_id=?",
            (acknowledged_task.task_id,),
        ).fetchone()[0]
        connection.execute(
            "UPDATE reconciliation_transition_outbox SET created_at=900 "
            "WHERE library_root=?",
            (store.library_root,),
        )
        connection.execute(
            "UPDATE reconciliation_transition_outbox SET delivered_at=900 "
            "WHERE id=? AND library_root=?",
            (acknowledged_event, store.library_root),
        )
        connection.commit()

        result = store.prune_transition_outbox(
            acknowledged_before=950,
            limit=10,
        )
        assert result.acknowledged_deleted == 1
        assert result.dead_letters_deleted == 0
        remaining = connection.execute(
            "SELECT task_id, delivery_token, delivered_at "
            "FROM reconciliation_transition_outbox "
            "WHERE library_root=? ORDER BY id",
            (store.library_root,),
        ).fetchall()
        assert remaining == [
            (leased_task.task_id, leased_event.delivery_token, None),
            (pending_task.task_id, None, None),
        ]
    finally:
        connection.close()
