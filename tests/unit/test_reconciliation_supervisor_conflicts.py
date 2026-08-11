from contextlib import contextmanager
from dataclasses import replace

import pytest


def _service(tmp_path, results, **kwargs):
    from AssetsManager.application import AssetIndexReconciliationService, ReconciliationQueue

    class Session:
        root = tmp_path / "library"
        root_str = str(root)

        @contextmanager
        def operation(self):
            yield

        def connection_for(self, _root):
            return object()

    class Index:
        def __init__(self):
            self.calls = 0

        def index_directory_tree_result(self, *_args):
            self.calls += 1
            value = results.pop(0)
            if isinstance(value, BaseException):
                raise value
            return value

    session = Session()
    queue = ReconciliationQueue(library_root=session.root, clock=lambda: 0.0)
    index = Index()
    service = AssetIndexReconciliationService(
        session=session,
        asset_index_service=index,
        reconciliation_queue=queue,
        clock=lambda: 0.0,
        **kwargs,
    )
    return service, queue, index


def _conflict(message, **metadata):
    from AssetsManager.application import ReconciliationQueuePersistenceConflict

    return ReconciliationQueuePersistenceConflict(message, **metadata)


def _published():
    from AssetsManager.application import AssetIndexPublishResult, AssetIndexPublishStatus

    return AssetIndexPublishResult(AssetIndexPublishStatus.PUBLISHED, committed=True, revision=3)


def test_retryable_persistence_conflict_is_reloaded_and_bounded_then_continues(tmp_path, monkeypatch):
    service, queue, index = _service(
        tmp_path,
        [_published()],
        max_persistence_conflict_retries=2,
        persistence_conflict_backoff=0.0,
    )
    task = queue.enqueue_or_merge(path=tmp_path / "library", reason="scan", now=0.0)
    original_claim = queue.claim_next
    calls = 0

    def conflict_once(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _conflict("new generation", retryable=True)
        return original_claim(**kwargs)

    monkeypatch.setattr(queue, "claim_next", conflict_once)

    outcome = service.process_once(now=0.0)

    assert outcome is not None and outcome.ok
    assert outcome.task.task_id == task.task_id
    assert calls == 2
    assert index.calls == 1


def test_persistence_conflict_retry_budget_exhaustion_reaches_worker_fault(tmp_path, monkeypatch):
    service, queue, _index = _service(
        tmp_path,
        [],
        max_consecutive_errors=1,
        max_worker_restarts=0,
        max_persistence_conflict_retries=1,
        persistence_conflict_backoff=0.0,
    )
    calls = 0

    def always_conflict(**_kwargs):
        nonlocal calls
        calls += 1
        raise _conflict("generation changed", retry_after_refresh=True)

    monkeypatch.setattr(queue, "claim_next", always_conflict)
    assert service.start()
    service._worker.join(2.0)

    assert not service.is_running
    assert service.worker_faulted
    assert calls == 2
    assert service.last_worker_error is not None
    assert "ReconciliationQueuePersistenceConflict" in service.last_worker_error


def test_stale_worker_completion_is_benign_without_replaying_completion_or_restart(tmp_path, monkeypatch):
    from AssetsManager.application import ReconciliationState

    service, queue, index = _service(
        tmp_path,
        [_published()],
        max_consecutive_errors=1,
        max_worker_restarts=1,
        max_persistence_conflict_retries=1,
        persistence_conflict_backoff=0.0,
    )
    task = queue.enqueue_or_merge(path=tmp_path / "library", reason="scan", now=0.0)
    original_mark = queue.mark_succeeded
    calls = 0

    def stale_completion(
        task_id,
        *,
        revision=None,
        expected_attempts=None,
        lease_token=None,
        now=None,
    ):
        nonlocal calls
        calls += 1
        if calls == 1:
            current = queue.get(task_id)
            assert current is not None
            queue._tasks[current.repair_key] = replace(
                current,
                state=ReconciliationState.SUCCEEDED,
                lease_expires_at=None,
            )
            raise _conflict("old completion", stale_worker_completion=True)
        return original_mark(
            task_id,
            revision=revision,
            expected_attempts=expected_attempts,
            lease_token=lease_token,
            now=now,
        )

    monkeypatch.setattr(queue, "mark_succeeded", stale_completion)
    outcome = service.process_once(now=0.0)

    assert outcome is not None and outcome.ok
    assert outcome.task.task_id == task.task_id
    assert calls == 1
    assert index.calls == 1
    assert service.worker_restart_count == 0
    assert not service.worker_faulted


def test_unknown_persistence_conflict_fails_closed_without_retry(tmp_path, monkeypatch):
    service, queue, _index = _service(tmp_path, [], max_persistence_conflict_retries=3)
    calls = 0

    def unknown_conflict(**_kwargs):
        nonlocal calls
        calls += 1
        raise _conflict("unclassified conflict")

    monkeypatch.setattr(queue, "claim_next", unknown_conflict)

    with pytest.raises(Exception) as raised:
        service.process_once(now=0.0)

    assert type(raised.value).__name__ == "ReconciliationQueuePersistenceConflict"
    assert calls == 1


def test_worker_refresh_failure_is_recorded_and_faulted(tmp_path, monkeypatch):
    service, queue, _index = _service(
        tmp_path,
        [],
        max_consecutive_errors=1,
        max_worker_restarts=0,
    )

    def fail_wait(**_kwargs):
        raise RuntimeError("queue refresh failed")

    monkeypatch.setattr(queue, "wait_for_ready", fail_wait)
    assert service.start()
    service._worker.join(2.0)

    assert not service.is_running
    assert service.worker_faulted
    assert service.last_worker_error == "RuntimeError: queue refresh failed"
