"""Deterministic heartbeat/lease races for reconciliation workers."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import threading

import pytest

from AssetsManager.application.asset_index_reconciliation_service import (
    AssetIndexReconciliationService,
)
from AssetsManager.application.asset_index_service import (
    AssetIndexPublishResult,
    AssetIndexPublishStatus,
)
from AssetsManager.application.reconciliation_queue import (
    ReconciliationKind,
    ReconciliationQueuePersistenceConflict,
    ReconciliationState,
    ReconciliationTask,
)


_WAIT_TIMEOUT = 2.0


class _Session:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root_str = str(root)
        self.event_token = "heartbeat-test-session"

    @contextmanager
    def operation(self):
        yield

    def connection_for(self, _root: Path):
        return object()


class _BlockingAssetIndex:
    def __init__(
        self,
        result: AssetIndexPublishResult,
        *,
        started: threading.Event,
        release: threading.Event | None = None,
        completed: threading.Event | None = None,
    ) -> None:
        self._result = result
        self._started = started
        self._release = release
        self._completed = completed

    def index_directory_tree_result(self, _connection, _root, _path):
        self._started.set()
        if self._release is not None and not self._release.wait(_WAIT_TIMEOUT):
            raise AssertionError("controlled reconciliation operation was not released")
        if self._completed is not None:
            self._completed.set()
        return self._result


def _task(root: Path) -> ReconciliationTask:
    return ReconciliationTask(
        task_id="heartbeat-task",
        library_root=str(root),
        path=str(root / "asset"),
        kind=ReconciliationKind.ASSET_INDEX_ROOT_RESCAN,
        reason="busy",
        state=ReconciliationState.PENDING,
        attempts=0,
        next_attempt_at=0.0,
        created_at=0.0,
        updated_at=0.0,
        max_attempts=5,
    )


class _LeaseState:
    """Small shared state model with explicit old/new ownership transitions."""

    def __init__(self, task: ReconciliationTask) -> None:
        self._lock = threading.Lock()
        self.owned_task = task
        self.claimed: ReconciliationTask | None = None
        self.renew_entered = threading.Event()
        self.renew_release = threading.Event()
        self.completion_entered = threading.Event()
        self.completion_release = threading.Event()
        self.renew_calls: list[tuple[str, int, str | None]] = []
        self.completion_calls: list[tuple[str, int, str | None]] = []
        self.accepted_completions: list[ReconciliationTask] = []

    def recover_and_claim_new_owner(self, *, now: float) -> ReconciliationTask:
        with self._lock:
            old = self.owned_task
            recovered = replace(
                old,
                state=ReconciliationState.RETRYABLE,
                next_attempt_at=now,
                lease_expires_at=None,
                lease_token=None,
                updated_at=now,
            )
            self.owned_task = replace(
                recovered,
                state=ReconciliationState.RUNNING,
                attempts=old.attempts + 1,
                next_attempt_at=now,
                lease_expires_at=now + 10.0,
                lease_token="new-owner-token",
                updated_at=now,
            )
            return self.owned_task


class _ControlledQueue:
    def __init__(
        self,
        state: _LeaseState,
        *,
        block_renew: bool = False,
        renew_error: BaseException | None = None,
        block_completion: bool = False,
    ) -> None:
        self.state = state
        self.block_renew = block_renew
        self.renew_error = renew_error
        self.block_completion = block_completion

    def claim_next(self, *, now: float, lease_seconds: float) -> ReconciliationTask:
        with self.state._lock:
            claimed = replace(
                self.state.owned_task,
                state=ReconciliationState.RUNNING,
                attempts=self.state.owned_task.attempts + 1,
                lease_expires_at=now + lease_seconds,
                lease_token="old-owner-token",
                updated_at=now,
            )
            self.state.owned_task = claimed
            self.state.claimed = claimed
            return claimed

    def renew_lease(
        self,
        task_id: str,
        *,
        expected_attempts: int,
        lease_token: str | None,
        lease_seconds: float,
        now: float,
    ) -> ReconciliationTask:
        with self.state._lock:
            self.state.renew_calls.append((task_id, expected_attempts, lease_token))
        self.state.renew_entered.set()
        if self.block_renew and not self.state.renew_release.wait(_WAIT_TIMEOUT):
            raise AssertionError("controlled lease renewal was not released")
        if self.renew_error is not None:
            raise self.renew_error
        with self.state._lock:
            current = self.state.owned_task
            if (
                current.task_id != task_id
                or current.state is not ReconciliationState.RUNNING
                or current.attempts != expected_attempts
                or current.lease_token != lease_token
            ):
                raise ReconciliationQueuePersistenceConflict(
                    "old worker renewal lost ownership",
                    stale_worker_completion=True,
                    operation="renew",
                )
            renewed = replace(
                current,
                lease_expires_at=now + lease_seconds,
                updated_at=now,
            )
            self.state.owned_task = renewed
            return renewed

    def mark_succeeded(
        self,
        task_id: str,
        *,
        revision: int | None,
        expected_attempts: int,
        lease_token: str | None,
        now: float,
    ) -> ReconciliationTask:
        with self.state._lock:
            self.state.completion_calls.append((task_id, expected_attempts, lease_token))
        self.state.completion_entered.set()
        if self.block_completion and not self.state.completion_release.wait(_WAIT_TIMEOUT):
            raise AssertionError("controlled completion mutation was not released")
        with self.state._lock:
            current = self.state.owned_task
            if (
                current.task_id != task_id
                or current.state is not ReconciliationState.RUNNING
                or current.attempts != expected_attempts
                or current.lease_token != lease_token
            ):
                raise ReconciliationQueuePersistenceConflict(
                    "old worker completion lost ownership",
                    stale_worker_completion=True,
                    operation="completion",
                )
            completed = replace(
                current,
                state=ReconciliationState.SUCCEEDED,
                observed_revision=revision,
                lease_expires_at=None,
                lease_token=None,
                updated_at=now,
            )
            self.state.owned_task = completed
            self.state.accepted_completions.append(completed)
            return completed

    def get(self, task_id: str) -> ReconciliationTask | None:
        with self.state._lock:
            if self.state.owned_task.task_id != task_id:
                return None
            return self.state.owned_task

    def refresh(self):
        """Model a durable refresh that has already been reflected in state."""
        return None

    def wake(self) -> None:
        return None


def _service(
    root: Path,
    queue: _ControlledQueue,
    asset_index: _BlockingAssetIndex,
) -> AssetIndexReconciliationService:
    return AssetIndexReconciliationService(
        session=_Session(root),
        asset_index_service=asset_index,
        reconciliation_queue=queue,
        clock=lambda: 0.0,
        max_persistence_conflict_retries=0,
        persistence_conflict_backoff=0.0,
        worker_max_operation_age=60.0,
    )


def _join(thread: threading.Thread) -> None:
    thread.join(_WAIT_TIMEOUT)
    assert not thread.is_alive(), "reconciliation worker thread did not finish"


def test_inflight_renew_is_joined_before_completion_and_cannot_touch_new_owner(tmp_path):
    """An old renewal in flight must not permit an old completion after recovery."""
    root = tmp_path / "library"
    state = _LeaseState(_task(root))
    queue = _ControlledQueue(state, block_renew=True)
    operation_started = threading.Event()
    operation_release = threading.Event()
    operation_completed = threading.Event()
    asset_index = _BlockingAssetIndex(
        AssetIndexPublishResult(
            AssetIndexPublishStatus.PUBLISHED,
            committed=True,
            revision=17,
        ),
        started=operation_started,
        release=operation_release,
        completed=operation_completed,
    )
    service = _service(root, queue, asset_index)
    outcome: list[object] = []
    worker = threading.Thread(
        target=lambda: outcome.append(service.process_once(now=0.0, lease_seconds=0.03)),
        daemon=True,
    )
    worker.start()
    try:
        assert operation_started.wait(_WAIT_TIMEOUT)
        assert state.renew_entered.wait(_WAIT_TIMEOUT)

        operation_release.set()
        assert operation_completed.wait(_WAIT_TIMEOUT)
        # process_once must wait for the in-flight renew before attempting the
        # completion mutation; the old worker cannot race past heartbeat.join().
        assert not state.completion_calls
        assert worker.is_alive()

        state.recover_and_claim_new_owner(now=1.0)
        state.renew_release.set()
        _join(worker)
    finally:
        operation_release.set()
        state.renew_release.set()
        if worker.is_alive():
            worker.join(_WAIT_TIMEOUT)

    assert outcome and outcome[0] is not None
    result = outcome[0]
    assert result.state is ReconciliationState.RUNNING
    assert result.ok is False
    assert result.error_type == "StaleWorkerCompletion"
    assert len(state.renew_calls) == 1
    assert len(state.completion_calls) == 1
    assert not state.accepted_completions
    current = queue.get("heartbeat-task")
    assert current is not None
    assert current.attempts == 2
    assert current.lease_token == "new-owner-token"
    assert current.state is ReconciliationState.RUNNING


@pytest.mark.parametrize("stop_kind", ("heartbeat_stop", "worker_stop"))
def test_stop_signal_suppresses_inflight_renew_error_without_late_renew(
    tmp_path, stop_kind
):
    """Both stop gates terminate an in-flight heartbeat without a stale retry."""
    root = tmp_path / f"library-{stop_kind}"
    state = _LeaseState(_task(root))
    queue = _ControlledQueue(
        state,
        block_renew=True,
        renew_error=RuntimeError("controlled renew interruption"),
    )
    asset_index = _BlockingAssetIndex(
        AssetIndexPublishResult(AssetIndexPublishStatus.EMPTY, committed=True),
        started=threading.Event(),
    )
    service = _service(root, queue, asset_index)
    heartbeat_stop = threading.Event()
    worker_stop = threading.Event()
    errors: list[BaseException] = []
    heartbeat = threading.Thread(
        target=service._lease_heartbeat,
        args=(
            state.owned_task,
            0.03,
            60.0,
            heartbeat_stop,
            worker_stop,
            errors,
        ),
        daemon=True,
    )
    heartbeat.start()
    try:
        assert state.renew_entered.wait(_WAIT_TIMEOUT)
        if stop_kind == "heartbeat_stop":
            heartbeat_stop.set()
        else:
            worker_stop.set()
        state.renew_release.set()
        _join(heartbeat)
    finally:
        heartbeat_stop.set()
        worker_stop.set()
        state.renew_release.set()
        if heartbeat.is_alive():
            heartbeat.join(_WAIT_TIMEOUT)

    assert errors == []
    assert len(state.renew_calls) == 1


def test_completion_mutation_cas_fails_closed_when_recovery_wins_after_heartbeat_stop(
    tmp_path,
):
    """Recovery between heartbeat cleanup and completion cannot be overwritten."""
    root = tmp_path / "library"
    state = _LeaseState(_task(root))
    queue = _ControlledQueue(state, block_completion=True)
    operation_started = threading.Event()
    operation_release = threading.Event()
    asset_index = _BlockingAssetIndex(
        AssetIndexPublishResult(
            AssetIndexPublishStatus.EMPTY,
            committed=True,
            revision=23,
        ),
        started=operation_started,
        release=operation_release,
    )
    service = _service(root, queue, asset_index)
    outcome: list[object] = []
    worker = threading.Thread(
        target=lambda: outcome.append(service.process_once(now=0.0, lease_seconds=30.0)),
        daemon=True,
    )
    worker.start()
    try:
        assert operation_started.wait(_WAIT_TIMEOUT)
        operation_release.set()
        assert state.completion_entered.wait(_WAIT_TIMEOUT)

        state.recover_and_claim_new_owner(now=2.0)
        state.completion_release.set()
        _join(worker)
    finally:
        operation_release.set()
        state.completion_release.set()
        if worker.is_alive():
            worker.join(_WAIT_TIMEOUT)

    assert outcome and outcome[0] is not None
    result = outcome[0]
    assert result.state is ReconciliationState.RUNNING
    assert result.ok is False
    assert result.error_type == "StaleWorkerCompletion"
    assert len(state.completion_calls) == 1
    assert not state.accepted_completions
    current = queue.get("heartbeat-task")
    assert current is not None
    assert current.attempts == 2
    assert current.lease_token == "new-owner-token"
    assert current.state is ReconciliationState.RUNNING

