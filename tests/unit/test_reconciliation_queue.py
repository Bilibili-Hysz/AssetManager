import json

import pytest


def test_enqueue_deduplicates_active_scope_and_merges_operation_ids(tmp_path):
    from AssetsManager.application import ReconciliationQueue, ReconciliationState

    queue = ReconciliationQueue(
        library_root=tmp_path / "library",
        persistence_path=tmp_path / "queue.json",
        clock=lambda: 10.0,
    )

    first = queue.enqueue_or_merge(
        path=tmp_path / "library" / "assets",
        reason="busy",
        operation_id="file-op-1",
        now=10.0,
    )
    merged = queue.enqueue_or_merge(
        path=tmp_path / "library" / "assets" / ".",
        reason="stale",
        operation_id="file-op-2",
        now=11.0,
    )

    assert merged.task_id == first.task_id
    assert merged.state is ReconciliationState.PENDING
    assert merged.reason == "stale"
    assert merged.operation_ids == ("file-op-1", "file-op-2")
    assert len(queue) == 1


def test_claim_retry_and_success_are_durable(tmp_path):
    from AssetsManager.application import ReconciliationQueue, ReconciliationState

    marker = tmp_path / "queue.json"
    queue = ReconciliationQueue(
        library_root=tmp_path / "library",
        persistence_path=marker,
        clock=lambda: 100.0,
    )
    task = queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=100.0)

    claimed = queue.claim_next(now=100.0, lease_seconds=10.0)
    assert claimed is not None
    assert claimed.task_id == task.task_id
    assert claimed.state is ReconciliationState.RUNNING
    assert claimed.attempts == 1
    assert claimed.lease_expires_at == 110.0
    assert claimed.lease_token is not None

    retryable = queue.mark_retryable(
        task.task_id,
        error_type="OperationalError",
        error="database is locked",
        lease_token=claimed.lease_token,
        now=100.0,
    )
    assert retryable.state is ReconciliationState.RETRYABLE
    assert retryable.next_attempt_at == pytest.approx(100.25)

    assert queue.claim_next(now=100.24) is None
    claimed_again = queue.claim_next(now=100.25, lease_seconds=10.0)
    assert claimed_again is not None
    succeeded = queue.mark_succeeded(
        task.task_id, revision=7, lease_token=claimed_again.lease_token, now=101.0
    )
    assert succeeded.state is ReconciliationState.SUCCEEDED
    assert succeeded.observed_revision == 7

    restored = ReconciliationQueue(
        library_root=tmp_path / "library",
        persistence_path=marker,
        clock=lambda: 101.0,
    )
    restored_task = restored.get(task.task_id)
    assert restored_task is not None
    assert restored_task.state is ReconciliationState.SUCCEEDED
    assert restored_task.observed_revision == 7


def test_expired_running_task_is_recovered_with_backoff(tmp_path):
    from AssetsManager.application import ReconciliationQueue, ReconciliationState

    queue = ReconciliationQueue(
        library_root=tmp_path / "library",
        clock=lambda: 0.0,
        max_attempts=3,
    )
    task = queue.enqueue_or_merge(path=tmp_path / "library" / "assets", reason="stale", now=0.0)
    queue.claim_next(now=0.0, lease_seconds=1.0)

    recovered = queue.recover_expired_running(now=1.0)
    assert len(recovered) == 1
    assert recovered[0].task_id == task.task_id
    assert recovered[0].state is ReconciliationState.RETRYABLE
    assert recovered[0].next_attempt_at == pytest.approx(1.5)
    assert recovered[0].last_error_type == "LeaseExpired"
    assert recovered[0].lease_token is None


def test_bounded_queue_evicts_finished_but_not_active_tasks(tmp_path):
    from AssetsManager.application import ReconciliationQueue, ReconciliationQueueFull

    queue = ReconciliationQueue(
        library_root=tmp_path / "library",
        max_tasks=1,
        clock=lambda: 0.0,
    )
    first = queue.enqueue_or_merge(path=tmp_path / "library" / "a", reason="busy", now=0.0)
    claimed = queue.claim_next(now=0.0)
    assert claimed is not None
    queue.mark_succeeded(first.task_id, lease_token=claimed.lease_token, now=1.0)

    second = queue.enqueue_or_merge(path=tmp_path / "library" / "b", reason="scan_failed", now=2.0)
    assert second.path.endswith("b")
    assert queue.get(first.task_id) is None

    with pytest.raises(ReconciliationQueueFull):
        queue.enqueue_or_merge(path=tmp_path / "library" / "c", reason="stale", now=3.0)


def test_corrupt_marker_fails_closed(tmp_path):
    from AssetsManager.application import ReconciliationQueue, ReconciliationQueuePersistenceError

    marker = tmp_path / "queue.json"
    marker.write_text(json.dumps({"version": 999, "tasks": []}), encoding="utf-8")

    with pytest.raises(ReconciliationQueuePersistenceError):
        ReconciliationQueue(library_root=tmp_path / "library", persistence_path=marker)


def test_backoff_is_bounded_and_reason_specific():
    from AssetsManager.application import reconciliation_backoff

    assert reconciliation_backoff("busy", 1) == 0.25
    assert reconciliation_backoff("stale", 2) == 1.0
    assert reconciliation_backoff("scan_failed", 10) == 60.0
    assert reconciliation_backoff("staged", 10) == 30.0


def test_running_task_without_lease_is_recovered_on_reload(tmp_path):
    from AssetsManager.application import ReconciliationQueue, ReconciliationState

    marker = tmp_path / "queue.json"
    queue = ReconciliationQueue(
        library_root=tmp_path / "library",
        persistence_path=marker,
        clock=lambda: 10.0,
    )
    task = queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=10.0)
    queue.claim_next(now=10.0, lease_seconds=30.0)

    payload = json.loads(marker.read_text(encoding="utf-8"))
    payload["tasks"][0]["lease_expires_at_wallclock"] = None
    marker.write_text(json.dumps(payload), encoding="utf-8")

    restored = ReconciliationQueue(
        library_root=tmp_path / "library",
        persistence_path=marker,
        clock=lambda: 10.0,
    )
    recovered = restored.get(task.task_id)
    assert recovered is not None
    assert recovered.state is ReconciliationState.RETRYABLE
    assert recovered.last_error_type == "LeaseExpired"


def test_retry_deadline_is_rebased_across_process_restart(tmp_path):
    from AssetsManager.application import ReconciliationQueue, ReconciliationState

    marker = tmp_path / "queue.json"
    monotonic_now = [100.0]
    wall_now = [1000.0]
    queue = ReconciliationQueue(
        library_root=tmp_path / "library",
        persistence_path=marker,
        clock=lambda: monotonic_now[0],
        wall_clock=lambda: wall_now[0],
    )
    task = queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=100.0)
    claimed = queue.claim_next(now=100.0, lease_seconds=10.0)
    assert claimed is not None
    retryable = queue.mark_retryable(
        task.task_id, lease_token=claimed.lease_token, now=100.0
    )
    assert retryable.next_attempt_at == pytest.approx(100.25)

    restarted = ReconciliationQueue(
        library_root=tmp_path / "library",
        persistence_path=marker,
        clock=lambda: 0.0,
        wall_clock=lambda: 1000.10,
    )
    restored = restarted.get(task.task_id)
    assert restored is not None
    assert restored.state is ReconciliationState.RETRYABLE
    assert restored.next_attempt_at == pytest.approx(0.15)

    elapsed = ReconciliationQueue(
        library_root=tmp_path / "library",
        persistence_path=marker,
        clock=lambda: 0.0,
        wall_clock=lambda: 1000.30,
    )
    due = elapsed.get(task.task_id)
    assert due is not None
    assert due.next_attempt_at == pytest.approx(0.0)


def test_old_json_marker_without_lease_token_loads(tmp_path):
    from AssetsManager.application import ReconciliationQueue

    marker = tmp_path / "queue.json"
    queue = ReconciliationQueue(
        library_root=tmp_path / "library",
        persistence_path=marker,
        clock=lambda: 10.0,
        wall_clock=lambda: 1000.0,
    )
    task = queue.enqueue_or_merge(
        path=tmp_path / "library",
        reason="busy",
        now=10.0,
    )
    payload = json.loads(marker.read_text(encoding="utf-8"))
    payload["tasks"][0].pop("lease_token", None)
    marker.write_text(json.dumps(payload), encoding="utf-8")

    restored = ReconciliationQueue(
        library_root=tmp_path / "library",
        persistence_path=marker,
        clock=lambda: 10.0,
        wall_clock=lambda: 1000.0,
    )
    restored_task = restored.get(task.task_id)
    assert restored_task is not None
    assert restored_task.lease_token is None


def test_running_json_task_without_lease_token_recovers_immediately(tmp_path):
    from AssetsManager.application import ReconciliationQueue, ReconciliationState

    marker = tmp_path / "queue.json"
    queue = ReconciliationQueue(
        library_root=tmp_path / "library",
        persistence_path=marker,
        clock=lambda: 10.0,
        wall_clock=lambda: 1000.0,
    )
    task = queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=10.0)
    claimed = queue.claim_next(now=10.0, lease_seconds=30.0)
    assert claimed is not None
    payload = json.loads(marker.read_text(encoding="utf-8"))
    payload["tasks"][0].pop("lease_token", None)
    payload["tasks"][0]["lease_expires_at_wallclock"] = 9999.0
    marker.write_text(json.dumps(payload), encoding="utf-8")

    restored = ReconciliationQueue(
        library_root=tmp_path / "library",
        persistence_path=marker,
        clock=lambda: 10.0,
        wall_clock=lambda: 1000.0,
    )
    recovered = restored.get(task.task_id)
    assert recovered is not None
    assert recovered.state is ReconciliationState.RETRYABLE
    assert recovered.lease_token is None



@pytest.fixture(params=["memory", "sqlite"], ids=["memory", "sqlite"])
def make_queue(request, tmp_path):
    """Build a ReconciliationQueue over either persistence backend.

    Both backends use a monotonic clock frozen at 0.0 (the SQLite store adds
    a wall clock at 1000.0 because its leases are wall-clock based).  Yields
    ``(make, expire)`` where ``make(**kwargs)`` constructs the queue and
    ``expire()`` invalidates a claimed lease (a no-op for the in-memory
    backend, which expires via the caller-supplied ``now``).
    """
    from AssetsManager.application import ReconciliationQueue

    if request.param == "memory":
        def make(**kwargs):
            return ReconciliationQueue(
                library_root=tmp_path / "library",
                clock=lambda: 0.0,
                **kwargs,
            )

        def expire():
            pass

        yield make, expire
    else:
        from tests.unit.test_reconciliation_queue_sqlite_store import _SCHEMA
        import sqlite3

        from AssetsManager.application import SQLiteReconciliationQueueStore

        wall = [1000.0]
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        connection.executescript(_SCHEMA)
        connection.commit()
        store = SQLiteReconciliationQueueStore(
            connection=connection,
            library_root=tmp_path / "library",
            allow_unmanaged=True,
            clock=lambda: 0.0,
            wall_clock=lambda: wall[0],
        )

        def make(**kwargs):
            return ReconciliationQueue(
                library_root=tmp_path / "library",
                persistence_store=store,
                **kwargs,
            )

        def expire():
            wall[0] = 1001.0

        try:
            yield make, expire
        finally:
            connection.close()


def test_renew_lease_extends_current_token_only(make_queue, tmp_path):
    from AssetsManager.application import ReconciliationQueuePersistenceConflict

    make, _expire = make_queue
    queue = make()
    task = queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=0.0)
    claimed = queue.claim_next(now=0.0, lease_seconds=1.0)
    assert claimed is not None

    renewed = queue.renew_lease(
        task.task_id, lease_token=claimed.lease_token, lease_seconds=2.0, now=0.5
    )
    assert renewed.lease_token == claimed.lease_token
    assert renewed.lease_expires_at == pytest.approx(2.5)

    with pytest.raises(ReconciliationQueuePersistenceConflict):
        queue.renew_lease(
            task.task_id, lease_token="wrong-token", lease_seconds=2.0, now=0.6
        )


def test_expired_lease_rejects_renewal_and_completion(make_queue, tmp_path):
    from AssetsManager.application import (
        ReconciliationQueuePersistenceConflict,
        ReconciliationState,
    )

    make, expire = make_queue
    queue = make()
    task = queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=0.0)
    claimed = queue.claim_next(now=0.0, lease_seconds=1.0)
    assert claimed is not None
    expire()

    with pytest.raises(ReconciliationQueuePersistenceConflict) as renewed:
        queue.renew_lease(
            task.task_id,
            expected_attempts=claimed.attempts,
            lease_token=claimed.lease_token,
            lease_seconds=1.0,
            now=1.0,
        )
    assert renewed.value.stale_worker_completion is True

    with pytest.raises(ReconciliationQueuePersistenceConflict) as completed:
        queue.mark_succeeded(
            task.task_id,
            expected_attempts=claimed.attempts,
            lease_token=claimed.lease_token,
            now=1.0,
        )
    assert completed.value.stale_worker_completion is True
    current = queue.get(task.task_id)
    assert current is not None
    assert current.state is ReconciliationState.RUNNING


def test_in_memory_old_worker_cannot_terminalize_or_cancel_recovered_task(tmp_path):
    from AssetsManager.application import (
        ReconciliationQueue,
        ReconciliationQueuePersistenceConflict,
        ReconciliationState,
    )

    queue = ReconciliationQueue(library_root=tmp_path / "library", clock=lambda: 0.0)
    task = queue.enqueue_or_merge(path=tmp_path / "library", reason="scan_failed", now=0.0)
    claimed = queue.claim_next(now=0.0, lease_seconds=1.0)
    assert claimed is not None
    recovered = queue.recover_expired_running(now=1.0)
    assert recovered[0].state is ReconciliationState.RETRYABLE

    for mutation in (queue.mark_terminal, queue.cancel):
        with pytest.raises(ReconciliationQueuePersistenceConflict) as raised:
            mutation(
                task.task_id,
                expected_attempts=claimed.attempts,
                lease_token=claimed.lease_token,
                now=1.0,
            )
        assert raised.value.stale_worker_completion is True
        assert raised.value.operation == "state_mutation"

    current = queue.get(task.task_id)
    assert current is not None
    assert current.state is ReconciliationState.RETRYABLE
    assert current.lease_token is None
