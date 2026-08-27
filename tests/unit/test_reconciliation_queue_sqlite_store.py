import sqlite3

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



def test_sqlite_renew_lease_uses_token_and_attempt_cas(tmp_path):
    from AssetsManager.application import (
        ReconciliationQueue,
        ReconciliationQueuePersistenceConflict,
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
        claimed = queue.claim_next(now=10.0, lease_seconds=5.0)
        assert claimed is not None

        renewed = queue.renew_lease(
            task.task_id,
            lease_token=claimed.lease_token,
            lease_seconds=10.0,
            now=11.0,
        )
        assert renewed.lease_token == claimed.lease_token
        assert renewed.lease_expires_at == pytest.approx(21.0)

        with pytest.raises(ReconciliationQueuePersistenceConflict):
            queue.renew_lease(
                task.task_id,
                lease_token="wrong-token",
                lease_seconds=10.0,
                now=12.0,
            )
    finally:
        connection.close()


def test_sqlite_expired_lease_rejects_renewal_and_completion(tmp_path):
    from AssetsManager.application import (
        ReconciliationQueue,
        ReconciliationQueuePersistenceConflict,
        ReconciliationState,
    )

    connection, store = _store(tmp_path)
    wall_now = [1000.0]
    store._wall_clock = lambda: wall_now[0]
    try:
        queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: wall_now[0],
        )
        task = queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=10.0)
        claimed = queue.claim_next(now=10.0, lease_seconds=1.0)
        assert claimed is not None
        wall_now[0] = 1001.0

        with pytest.raises(ReconciliationQueuePersistenceConflict) as renewed:
            queue.renew_lease(
                task.task_id,
                expected_attempts=claimed.attempts,
                lease_token=claimed.lease_token,
                lease_seconds=1.0,
                now=11.0,
            )
        assert renewed.value.stale_worker_completion is True

        with pytest.raises(ReconciliationQueuePersistenceConflict) as completed:
            queue.mark_succeeded(
                task.task_id,
                expected_attempts=claimed.attempts,
                lease_token=claimed.lease_token,
                now=11.0,
            )
        assert completed.value.stale_worker_completion is True
        current = queue.get(task.task_id)
        assert current is not None
        assert current.state is ReconciliationState.RUNNING
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
