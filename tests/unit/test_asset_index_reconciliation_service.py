from contextlib import contextmanager

import pytest


def _service(tmp_path, results, **service_kwargs):
    from AssetsManager.application import (
        AssetIndexReconciliationService,
        ReconciliationQueue,
    )

    class Session:
        root = tmp_path / "library"
        root_str = str(root)
        event_token = "session-token"

        @contextmanager
        def operation(self):
            yield

        def connection_for(self, _root):
            return object()

    class AssetIndex:
        def __init__(self):
            self.calls = []
            self.current_revision_value = 10

        def index_directory_tree_result(self, conn, root, path):
            self.calls.append((conn, root, path))
            current = results.pop(0)
            if isinstance(current, BaseException):
                raise current
            return current

        def current_revision(self, conn, root):
            return self.current_revision_value

    session = Session()
    index = AssetIndex()
    queue = ReconciliationQueue(library_root=session.root, clock=lambda: 0.0)
    service = AssetIndexReconciliationService(
        session=session,
        asset_index_service=index,
        reconciliation_queue=queue,
        clock=lambda: 0.0,
        **service_kwargs,
    )
    return service, queue, index


def test_worker_callbacks_defer_to_durable_transition_outbox(tmp_path):
    """v44 delivery owns manifest writes after the queue mutation commits."""
    from types import SimpleNamespace

    from AssetsManager.application import AssetIndexReconciliationService

    calls: list[str] = []
    service = object.__new__(AssetIndexReconciliationService)
    service.reconciliation_queue = SimpleNamespace(
        durable_transition_outbox_enabled=True
    )
    service.import_manifest_recovery = SimpleNamespace(
        acknowledge_task=lambda _task: calls.append("acknowledge"),
        mark_task_running=lambda _task: calls.append("running"),
    )
    task = SimpleNamespace(task_id="durable-outbox-task")

    service._mark_import_recovery_running(task)
    service._acknowledge_import_recovery(task)

    assert calls == []


def test_reconciliation_worker_completes_filesystem_projection_repair(tmp_path):
    from AssetsManager.application import ReconciliationKind, ReconciliationState

    class RepairService:
        def __init__(self):
            self.tasks = []

        def repair(self, task):
            self.tasks.append(task)

    repair = RepairService()
    service, queue, _index = _service(
        tmp_path,
        [],
        projection_repair_service=repair,
    )
    library = tmp_path / "library"
    library.mkdir()
    payload = {
        "payload_version": 1,
        "operation_kind": "delete",
        "operation_id": "repair-1",
        "projection_set": [
            "asset_index", "tags", "metadata", "favorites",
            "thumbnail_rows", "thumbnail_bytes",
        ],
        "scope_path": str(library),
        "target_path": str(library / "gone.txt"),
        "delete_mode": "permanent",
        "expected_state": {"target_absent": True},
    }
    task = queue.enqueue_or_merge(
        path=library,
        reason="projection_cleanup_failed",
        kind=ReconciliationKind.FILESYSTEM_PROJECTION_REPAIR,
        payload=payload,
        now=0.0,
    )

    outcome = service.process_once(now=0.0)

    assert outcome is not None
    assert outcome.state is ReconciliationState.SUCCEEDED
    assert len(repair.tasks) == 1
    assert repair.tasks[0].task_id == task.task_id


def test_reconciliation_worker_terminals_invalid_filesystem_repair(tmp_path):
    from AssetsManager.application import ReconciliationKind

    service, queue, _index = _service(tmp_path, [])
    library = tmp_path / "library"
    library.mkdir()
    payload = {
        "payload_version": 1,
        "operation_kind": "delete",
        "operation_id": "repair-2",
        "projection_set": [
            "asset_index", "tags", "metadata", "favorites",
            "thumbnail_rows", "thumbnail_bytes",
        ],
        "scope_path": str(library),
        "target_path": str(tmp_path / "outside.txt"),
        "delete_mode": "permanent",
        "expected_state": {"target_absent": True},
    }
    with pytest.raises(ValueError, match="escapes library root"):
        queue.enqueue_or_merge(
            path=library,
            reason="projection_cleanup_failed",
            kind=ReconciliationKind.FILESYSTEM_PROJECTION_REPAIR,
            payload=payload,
            now=0.0,
        )


def test_restore_payload_is_accepted_and_canonicalized(tmp_path):
    from AssetsManager.application import ReconciliationKind, ReconciliationQueue

    library = tmp_path / "library"
    library.mkdir()
    target = library / "restored.txt"
    payload = {
        "payload_version": 1,
        "operation_kind": "restore",
        "operation_id": "restore-1",
        "projection_set": ["asset_index", "tags", "metadata", "favorites"],
        "scope_path": str(library),
        "target_path": str(target),
        "is_directory": False,
        "expected_state": {"target_present": True},
        "snapshot": {
            "format": "assetsmanager.undo-projection",
            "version": 1,
            "base": str(library / "old.txt"),
            "file_tags": [[str(library / "old.txt"), "hero"]],
            "file_meta": [],
            "library_favorites": [],
        },
    }
    queue = ReconciliationQueue(library_root=library, clock=lambda: 0.0)
    task = queue.enqueue_or_merge(
        path=library,
        reason="projection_restore_failed",
        kind=ReconciliationKind.FILESYSTEM_PROJECTION_REPAIR,
        payload=payload,
        now=0.0,
    )
    assert '"operation_kind":"restore"' in task.payload
    assert '"file_tags"' in task.payload


def test_restore_payload_rejects_snapshot_outside_root(tmp_path):
    from AssetsManager.application import ReconciliationKind, ReconciliationQueue

    library = tmp_path / "library"
    library.mkdir()
    payload = {
        "payload_version": 1,
        "operation_kind": "restore",
        "operation_id": "restore-2",
        "projection_set": ["asset_index", "tags", "metadata", "favorites"],
        "scope_path": str(library),
        "target_path": str(library / "restored.txt"),
        "is_directory": False,
        "expected_state": {"target_present": True},
        "snapshot": {
            "format": "assetsmanager.undo-projection",
            "version": 1,
            "base": str(tmp_path / "outside.txt"),
            "file_tags": [],
            "file_meta": [],
            "library_favorites": [],
        },
    }
    queue = ReconciliationQueue(library_root=library, clock=lambda: 0.0)
    with pytest.raises(ValueError, match="base escapes"):
        queue.enqueue_or_merge(
            path=library,
            reason="projection_restore_failed",
            kind=ReconciliationKind.FILESYSTEM_PROJECTION_REPAIR,
            payload=payload,
            now=0.0,
        )


def test_reconciliation_worker_requires_durable_publish(tmp_path):
    from AssetsManager.application import (
        AssetIndexPublishResult,
        AssetIndexPublishStatus,
        ReconciliationState,
    )

    service, queue, _index = _service(
        tmp_path,
        [AssetIndexPublishResult(AssetIndexPublishStatus.PUBLISHED, committed=False)],
    )
    task = queue.enqueue_or_merge(path=tmp_path / "library", reason="staged", now=0.0)

    outcome = service.process_once(now=0.0)

    assert outcome is not None
    assert outcome.ok is False
    assert outcome.state is ReconciliationState.RETRYABLE
    assert outcome.task.task_id == task.task_id
    assert outcome.task.reason == "staged"
    assert outcome.task.next_attempt_at == pytest.approx(1.0)


def test_reconciliation_worker_marks_durable_publish_succeeded(tmp_path):
    from AssetsManager.application import (
        AssetIndexPublishResult,
        AssetIndexPublishStatus,
        ReconciliationState,
    )

    service, queue, index = _service(
        tmp_path,
        [AssetIndexPublishResult(AssetIndexPublishStatus.EMPTY, committed=True, revision=9)],
    )
    task = queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=0.0)

    outcome = service.process_once(now=0.0)

    assert outcome is not None
    assert outcome.ok
    assert outcome.state is ReconciliationState.SUCCEEDED
    assert outcome.task.observed_revision == 9
    assert queue.get(task.task_id) == outcome.task
    assert index.calls[0][1] == tmp_path / "library"
    assert index.calls[0][2] == tmp_path / "library"


def test_reconciliation_worker_retries_operational_errors_then_succeeds(tmp_path):
    from sqlite3 import OperationalError

    from AssetsManager.application import (
        AssetIndexPublishResult,
        AssetIndexPublishStatus,
        ReconciliationState,
    )

    service, queue, _index = _service(
        tmp_path,
        [
            OperationalError("database is locked"),
            AssetIndexPublishResult(AssetIndexPublishStatus.PUBLISHED, committed=True, revision=4),
        ],
    )
    task = queue.enqueue_or_merge(path=tmp_path / "library", reason="scan_failed", now=0.0)

    first = service.process_once(now=0.0)
    assert first is not None
    assert first.state is ReconciliationState.RETRYABLE
    assert first.task.reason == "busy"
    assert first.task.next_attempt_at == pytest.approx(0.25)

    second = service.process_once(now=0.25)
    assert second is not None
    assert second.state is ReconciliationState.SUCCEEDED
    assert second.task.task_id == task.task_id


def test_missing_reconciliation_path_is_terminal(tmp_path):
    from AssetsManager.application import ReconciliationState

    service, queue, _index = _service(tmp_path, [FileNotFoundError("missing")])
    task = queue.enqueue_or_merge(path=tmp_path / "library" / "gone", reason="scan_failed", now=0.0)

    outcome = service.process_once(now=0.0)

    assert outcome is not None
    assert outcome.state is ReconciliationState.TERMINAL
    assert outcome.task.task_id == task.task_id
    assert outcome.error_type == "FileNotFoundError"


def test_background_worker_wakes_on_enqueue_and_stops_cleanly(tmp_path):
    import time

    from AssetsManager.application import (
        AssetIndexPublishResult,
        AssetIndexPublishStatus,
        ReconciliationState,
    )

    service, queue, _index = _service(
        tmp_path,
        [AssetIndexPublishResult(AssetIndexPublishStatus.PUBLISHED, committed=True, revision=12)],
    )

    assert service.start()
    assert not service.start()
    assert service.is_running
    task = queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=0.0)

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        current = queue.get(task.task_id)
        if current is not None and current.state is ReconciliationState.SUCCEEDED:
            break
        time.sleep(0.01)
    else:
        pytest.fail(f"worker did not complete task: {queue.get(task.task_id)!r}")

    service.stop()
    assert not service.is_running
    service.stop()


def test_sweeper_prunes_outbox_history_on_retention_schedule(tmp_path, monkeypatch):
    """Retention uses wall-clock cutoffs and remains bounded between sweeps."""
    service, queue, _index = _service(
        tmp_path,
        [],
        wall_clock=iter((1_000.0, 1_005.0)).__next__,
        transition_outbox_prune_interval=10.0,
        transition_outbox_ack_retention_seconds=20.0,
        transition_outbox_dead_letter_retention_seconds=40.0,
        transition_outbox_prune_limit=7,
    )
    prune_calls = []
    monkeypatch.setattr(
        queue,
        "prune_transition_outbox",
        lambda **kwargs: prune_calls.append(kwargs),
    )

    class StopAfterTwoSweeps:
        def __init__(self):
            self.calls = 0

        def wait(self, _timeout):
            self.calls += 1
            return self.calls > 2

    service._run_sweeper(StopAfterTwoSweeps())

    assert prune_calls == [
        {
            "acknowledged_before": 980.0,
            "dead_letter_before": 960.0,
            "limit": 7,
        }
    ]


def test_sweeper_retries_outbox_prune_after_failure(tmp_path, monkeypatch):
    """Retention failure is advisory and retries before its regular interval."""
    service, queue, _index = _service(
        tmp_path,
        [],
        wall_clock=iter((1_000.0, 1_001.0)).__next__,
        transition_outbox_prune_interval=60.0,
    )
    prune_calls = []

    def flaky_prune(**kwargs):
        prune_calls.append(kwargs)
        if len(prune_calls) == 1:
            raise RuntimeError("temporary prune failure")

    monkeypatch.setattr(queue, "prune_transition_outbox", flaky_prune)

    class StopAfterTwoSweeps:
        def __init__(self):
            self.calls = 0

        def wait(self, _timeout):
            self.calls += 1
            return self.calls > 2

    service._run_sweeper(StopAfterTwoSweeps())

    assert len(prune_calls) == 2
    assert prune_calls[0]["limit"] == prune_calls[1]["limit"] == 1000
    assert (
        prune_calls[1]["acknowledged_before"]
        == prune_calls[0]["acknowledged_before"] + 1.0
    )
    assert (
        prune_calls[1]["dead_letter_before"]
        == prune_calls[0]["dead_letter_before"] + 1.0
    )


def test_sweeper_emits_edge_triggered_outbox_capacity_alerts(
    tmp_path, caplog, monkeypatch
):
    from types import SimpleNamespace

    service, queue, _index = _service(
        tmp_path,
        [],
        transition_outbox_pending_alert_threshold=3,
        transition_outbox_dead_letter_alert_threshold=2,
        transition_outbox_oldest_pending_alert_age_seconds=30.0,
    )
    snapshots = iter(
        (
            SimpleNamespace(
                pending_count=3,
                dead_letter_count=2,
                oldest_pending_age_seconds=30.0,
            ),
            SimpleNamespace(
                pending_count=4,
                dead_letter_count=5,
                oldest_pending_age_seconds=45.0,
            ),
            SimpleNamespace(
                pending_count=0,
                dead_letter_count=0,
                oldest_pending_age_seconds=None,
            ),
        )
    )
    monkeypatch.setattr(queue, "transition_outbox_metrics", lambda **_kwargs: next(snapshots))
    caplog.set_level("WARNING")

    for snapshot in (1, 2, 3):
        service._observe_transition_outbox_metrics(
            queue.transition_outbox_metrics(now=float(snapshot))
        )

    warnings = [record for record in caplog.records if record.levelname == "WARNING"]
    assert len(warnings) == 3
    assert {record.args[1] for record in warnings} == {
        "pending transition outbox rows",
        "transition outbox dead-letter rows",
        "oldest pending transition outbox age",
    }
    assert service._outbox_alert_state == set()


def test_sweeper_alert_threshold_zero_disables_metric(tmp_path, caplog):
    from types import SimpleNamespace

    service, _queue, _index = _service(
        tmp_path,
        [],
        transition_outbox_pending_alert_threshold=0,
        transition_outbox_dead_letter_alert_threshold=0,
        transition_outbox_oldest_pending_alert_age_seconds=0,
    )
    caplog.set_level("WARNING")
    service._observe_transition_outbox_metrics(
        SimpleNamespace(
            pending_count=100,
            dead_letter_count=100,
            oldest_pending_age_seconds=100.0,
        )
    )

    assert not caplog.records
    assert service._outbox_alert_state == set()


def test_worker_start_failure_resets_lifecycle_state(tmp_path, monkeypatch):
    import threading

    service, _queue, _index = _service(tmp_path, [])

    def fail_start(_thread):
        raise RuntimeError("thread start failed")

    monkeypatch.setattr(threading.Thread, "start", fail_start)

    with pytest.raises(RuntimeError, match="thread start failed"):
        service.start()

    assert not service.is_running
    assert service.last_worker_error == "RuntimeError: thread start failed"


def test_worker_stops_after_bounded_unexpected_errors(tmp_path):
    import time

    service, _queue, _index = _service(
        tmp_path,
        [],
        max_consecutive_errors=2,
        stop_timeout=1.0,
    )

    def fail_process_once(**_kwargs):
        raise RuntimeError("unexpected worker failure")

    service.process_once = fail_process_once
    assert service.start()

    deadline = time.monotonic() + 2.0
    while service.is_running and time.monotonic() < deadline:
        time.sleep(0.01)

    assert not service.is_running
    assert service.worker_faulted
    assert service.consecutive_worker_errors == 2
    assert service.last_worker_error == "RuntimeError: unexpected worker failure"
    service.stop()


def test_worker_supervisor_restarts_after_exhausting_one_error_epoch(tmp_path):
    import threading

    service, _queue, _index = _service(
        tmp_path,
        [],
        max_consecutive_errors=1,
        max_worker_restarts=1,
        worker_restart_backoff=0.0,
    )
    recovered = threading.Event()
    calls = 0

    def fail_once_then_idle(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient worker failure")
        recovered.set()
        return None

    service.process_once = fail_once_then_idle
    assert service.start()
    assert recovered.wait(2.0)
    assert service.is_running
    assert service.worker_restart_count == 1
    assert service.consecutive_worker_errors == 0
    assert not service.worker_faulted

    service.stop()


def test_worker_supervisor_faults_after_restart_budget_is_exhausted(tmp_path):
    import time

    service, _queue, _index = _service(
        tmp_path,
        [],
        max_consecutive_errors=1,
        max_worker_restarts=1,
        worker_restart_backoff=0.0,
    )
    calls = 0

    def always_fail(**_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("persistent worker failure")

    service.process_once = always_fail
    assert service.start()

    deadline = time.monotonic() + 2.0
    while service.is_running and time.monotonic() < deadline:
        time.sleep(0.01)

    assert not service.is_running
    assert service.worker_faulted
    assert service.worker_restart_count == 1
    assert calls >= 2
    assert service.last_worker_error == "RuntimeError: persistent worker failure"
    service.stop()


def test_worker_stop_timeout_preserves_running_state_until_retry(tmp_path):
    import threading

    from AssetsManager.application import ReconciliationWorkerStopTimeout

    service, _queue, _index = _service(tmp_path, [], stop_timeout=0.01)
    entered = threading.Event()
    release = threading.Event()

    def blocked_process_once(**_kwargs):
        entered.set()
        release.wait(2.0)
        return None

    service.process_once = blocked_process_once
    assert service.start()
    assert entered.wait(1.0)

    with pytest.raises(ReconciliationWorkerStopTimeout):
        service.stop()
    assert service.is_running

    release.set()
    service.stop(timeout=1.0)
    assert not service.is_running



def test_reconciliation_worker_renews_long_running_claim(tmp_path):
    import threading
    import time

    from AssetsManager.application import (
        AssetIndexPublishResult,
        AssetIndexPublishStatus,
        ReconciliationState,
    )

    service, queue, index = _service(
        tmp_path,
        [AssetIndexPublishResult(AssetIndexPublishStatus.PUBLISHED, committed=True)],
    )
    service._clock = time.monotonic
    started = threading.Event()
    release = threading.Event()

    def slow_index(_conn, _root, _path):
        started.set()
        assert release.wait(2.0)
        return AssetIndexPublishResult(
            AssetIndexPublishStatus.PUBLISHED, committed=True, revision=8
        )

    index.index_directory_tree_result = slow_index
    task = queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=0.0)
    outcome_holder = []

    worker = threading.Thread(
        target=lambda: outcome_holder.append(
            service.process_once(lease_seconds=0.5)
        ),
        daemon=True,
    )
    worker.start()
    assert started.wait(1.0)

    # A fixed sleep is load-dependent: under CPU contention the heartbeat
    # thread can be starved for longer than any chosen wall-clock window.
    # Poll for the observable renewal instead — the stored lease deadline
    # advancing — which is exactly what this test needs to prove.
    current = queue.get(task.task_id)
    assert current is not None
    assert current.lease_expires_at is not None
    initial_lease_expires_at = current.lease_expires_at

    deadline = time.monotonic() + 5.0
    while True:
        current = queue.get(task.task_id)
        assert current is not None
        assert current.lease_expires_at is not None
        if current.lease_expires_at > initial_lease_expires_at:
            break
        if time.monotonic() >= deadline:
            pytest.fail(
                "worker did not renew the running claim within 5.0s: "
                f"lease_expires_at stayed at {current.lease_expires_at!r}"
            )
        time.sleep(0.01)

    assert current.state is ReconciliationState.RUNNING
    assert current.lease_token is not None
    assert current.lease_expires_at is not None
    assert current.lease_expires_at > initial_lease_expires_at

    release.set()
    worker.join(2.0)
    assert not worker.is_alive()
    assert outcome_holder[0] is not None
    assert outcome_holder[0].state is ReconciliationState.SUCCEEDED



def test_worker_stop_after_lease_expiry_does_not_commit_old_completion(tmp_path):
    import threading
    import time

    from AssetsManager.application import (
        AssetIndexPublishResult,
        AssetIndexPublishStatus,
        ReconciliationState,
        ReconciliationWorkerStopTimeout,
    )

    service, queue, index = _service(
        tmp_path,
        [],
        worker_lease_seconds=0.1,
        max_consecutive_errors=1,
        max_worker_restarts=0,
    )
    service._clock = time.monotonic
    started = threading.Event()
    release = threading.Event()

    def slow_index(_conn, _root, _path):
        started.set()
        assert release.wait(2.0)
        return AssetIndexPublishResult(
            AssetIndexPublishStatus.PUBLISHED, committed=True, revision=9
        )

    index.index_directory_tree_result = slow_index
    task = queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=0.0)
    assert service.start()
    assert started.wait(1.0)
    time.sleep(0.18)

    with pytest.raises(ReconciliationWorkerStopTimeout):
        service.stop(timeout=0.01)
    time.sleep(0.12)
    recovered = queue.recover_expired_running(now=time.monotonic())
    assert len(recovered) == 1
    assert recovered[0].state is ReconciliationState.RETRYABLE

    release.set()
    service.stop(timeout=2.0)
    current = queue.get(task.task_id)
    assert current is not None
    assert current.state is ReconciliationState.RETRYABLE
    assert service.worker_faulted


def test_committed_publish_past_operation_age_deadline_is_succeeded(tmp_path):
    import threading
    import time

    from AssetsManager.application import (
        AssetIndexPublishResult,
        AssetIndexPublishStatus,
        ReconciliationState,
    )

    service, queue, index = _service(
        tmp_path,
        [],
        worker_lease_seconds=0.1,
        worker_max_operation_age=0.2,
    )
    service._clock = time.monotonic
    started = threading.Event()
    release = threading.Event()
    outcome_holder = []

    def slow_index(_conn, _root, _path):
        started.set()
        assert release.wait(2.0)
        return AssetIndexPublishResult(
            AssetIndexPublishStatus.PUBLISHED,
            committed=True,
            revision=10,
        )

    index.index_directory_tree_result = slow_index
    task = queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=0.0)
    worker = threading.Thread(
        target=lambda: outcome_holder.append(service.process_once(lease_seconds=0.1)),
        daemon=True,
    )
    worker.start()
    assert started.wait(1.0)

    # The operation outlives the worker operation age budget (0.2s) while the
    # heartbeat keeps the lease alive for the running scan.
    time.sleep(0.3)

    release.set()
    worker.join(2.0)
    assert not worker.is_alive()
    assert outcome_holder[0] is not None
    # M6a-9: a durably committed publish is acknowledged even past the budget.
    assert outcome_holder[0].state is ReconciliationState.SUCCEEDED
    assert outcome_holder[0].task.observed_revision == 10
    current = queue.get(task.task_id)
    assert current is not None
    assert current.state is ReconciliationState.SUCCEEDED


def test_uncommitted_result_past_operation_age_deadline_is_not_acknowledged(tmp_path):
    import threading
    import time

    from AssetsManager.application import (
        AssetIndexPublishResult,
        AssetIndexPublishStatus,
        ReconciliationState,
    )

    service, queue, index = _service(
        tmp_path,
        [],
        worker_lease_seconds=0.1,
        worker_max_operation_age=0.2,
    )
    service._clock = time.monotonic
    started = threading.Event()
    release = threading.Event()
    outcome_holder = []

    def slow_index(_conn, _root, _path):
        started.set()
        assert release.wait(2.0)
        return AssetIndexPublishResult(AssetIndexPublishStatus.BUSY)

    index.index_directory_tree_result = slow_index
    queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=0.0)
    worker = threading.Thread(
        target=lambda: outcome_holder.append(service.process_once(lease_seconds=0.1)),
        daemon=True,
    )
    worker.start()
    assert started.wait(1.0)
    time.sleep(0.3)

    release.set()
    worker.join(2.0)
    assert not worker.is_alive()
    assert outcome_holder[0] is not None
    # The age deadline still guards uncommitted late results: the completion
    # is not acknowledged and the running task is left for lease recovery.
    assert outcome_holder[0].state is ReconciliationState.RUNNING
    assert outcome_holder[0].error_type == "StaleWorkerCompletion"


def test_lease_heartbeat_stops_renewing_after_renewal_deadline(tmp_path):
    """A stuck worker's heartbeat must stop at renew_until + lease_seconds."""
    import threading
    import time

    from AssetsManager.application import (
        AssetIndexPublishResult,
        AssetIndexPublishStatus,
    )

    service, queue, index = _service(
        tmp_path,
        [AssetIndexPublishResult(AssetIndexPublishStatus.PUBLISHED, committed=True)],
        worker_lease_seconds=0.1,
        worker_max_operation_age=0.2,
    )
    renewals = {"count": 0}
    real_renew = queue.renew_lease

    def counting_renew(*args, **kwargs):
        renewals["count"] += 1
        return real_renew(*args, **kwargs)

    queue.renew_lease = counting_renew
    task = queue.enqueue_or_merge(path=tmp_path / "library", reason="busy", now=0.0)
    claim = queue.claim_next(now=0.0, lease_seconds=0.1)
    assert claim is not None
    task = claim

    heartbeat_stop = threading.Event()
    errors: list = []
    service._clock = time.monotonic

    # renew_until is already in the past → the heartbeat must not renew at all.
    heartbeat = threading.Thread(
        target=service._lease_heartbeat,
        args=(task, 0.1, time.monotonic() - 1.0, heartbeat_stop, None, errors),
        daemon=True,
    )
    heartbeat.start()
    heartbeat.join(1.0)
    assert not heartbeat.is_alive()
    assert renewals["count"] == 0
    assert errors == []

    # A deadline in the future renews until it passes, then stops on its
    # own.  renew_lease is replaced with an unconditional counter so the
    # (already expired) claim cannot fail the CAS and pollute `errors`.
    renewals["count"] = 0
    queue.renew_lease = lambda *args, **kwargs: renewals.__setitem__(
        "count", renewals["count"] + 1
    ) or None
    heartbeat_stop.clear()
    heartbeat = threading.Thread(
        target=service._lease_heartbeat,
        args=(task, 0.6, time.monotonic() + 0.35, heartbeat_stop, None, errors),
        daemon=True,
    )
    heartbeat.start()
    heartbeat.join(3.0)
    assert not heartbeat.is_alive()
    assert renewals["count"] >= 1
    assert errors == []
