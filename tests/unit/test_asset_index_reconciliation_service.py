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
            service.process_once(lease_seconds=0.1)
        ),
        daemon=True,
    )
    worker.start()
    assert started.wait(1.0)
    time.sleep(0.18)

    current = queue.get(task.task_id)
    assert current is not None
    assert current.state is ReconciliationState.RUNNING
    assert current.lease_token is not None
    assert current.lease_expires_at is not None
    assert current.lease_expires_at > time.monotonic()

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
