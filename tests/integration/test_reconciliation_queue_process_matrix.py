"""Windows-spawn-safe process matrix for the SQLite reconciliation queue."""

from __future__ import annotations

from multiprocessing import context as mp_context
import multiprocessing
from pathlib import Path
import queue as queue_module
import sqlite3
import traceback

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


# These child targets must remain module-level: multiprocessing.get_context("spawn")
# imports this test module in a fresh interpreter on Windows.
def _child_error(results: object, phase: str, error: BaseException) -> None:
    results.put(
        {
            "kind": "error",
            "phase": phase,
            "type": type(error).__name__,
            "message": str(error),
            "traceback": traceback.format_exc(),
        }
    )


def _open_queue(
    database: str,
    library_root: str,
    *,
    monotonic_now: float,
    wallclock_now: float,
):
    from AssetsManager.application import ReconciliationQueue, SQLiteReconciliationQueueStore

    monotonic_value = [float(monotonic_now)]
    wallclock_value = [float(wallclock_now)]
    connection = sqlite3.connect(
        database,
        check_same_thread=False,
        timeout=10.0,
    )
    connection.execute("PRAGMA busy_timeout=10000")
    # This is a temporary file/schema owned by this test.  The production
    # bootstrap uses a DatabaseManager-owned connection; allow_unmanaged keeps
    # this process matrix on the same SQLite store contract without changing
    # production assembly.
    store = SQLiteReconciliationQueueStore(
        connection=connection,
        library_root=library_root,
        allow_unmanaged=True,
        clock=lambda: monotonic_value[0],
        wall_clock=lambda: wallclock_value[0],
        busy_retry_attempts=5,
        busy_retry_backoff=0.01,
    )
    queue = ReconciliationQueue(
        library_root=library_root,
        persistence_store=store,
        clock=lambda: monotonic_value[0],
        wall_clock=lambda: wallclock_value[0],
    )
    return connection, queue, monotonic_value, wallclock_value


def _claim_competitor(
    database: str,
    library_root: str,
    start_event: mp_context.BaseContext.Event,
    results: mp_context.BaseContext.Queue,
    label: str,
) -> None:
    connection = None
    try:
        connection, queue, monotonic_value, wallclock_value = _open_queue(
            database,
            library_root,
            monotonic_now=10.0,
            wallclock_now=1000.0,
        )
        results.put({"kind": "ready", "label": label})
        if not start_event.wait(10.0):
            raise TimeoutError(f"claim competitor {label} did not receive start signal")

        claimed = queue.claim_next(now=10.0, lease_seconds=30.0)
        if claimed is None:
            results.put({"kind": "claim", "label": label, "claimed": False})
            return

        monotonic_value[0] = 10.5
        wallclock_value[0] = 1000.5
        renewed = queue.renew_lease(
            claimed.task_id,
            expected_attempts=claimed.attempts,
            lease_token=claimed.lease_token,
            lease_seconds=30.0,
            now=10.5,
        )
        results.put(
            {
                "kind": "claim",
                "label": label,
                "claimed": True,
                "task_id": claimed.task_id,
                "attempts": claimed.attempts,
                "lease_token": claimed.lease_token,
                "claimed_expiry": claimed.lease_expires_at,
                "renewed_expiry": renewed.lease_expires_at,
            }
        )
    except BaseException as error:
        _child_error(results, f"claim:{label}", error)
    finally:
        if connection is not None:
            connection.close()


def _old_worker_completion(
    database: str,
    library_root: str,
    allow_completion: mp_context.BaseContext.Event,
    old_done: mp_context.BaseContext.Event,
    results: mp_context.BaseContext.Queue,
) -> None:
    connection = None
    try:
        connection, queue, _monotonic_value, _wallclock_value = _open_queue(
            database,
            library_root,
            monotonic_now=0.0,
            wallclock_now=1000.0,
        )
        claimed = queue.claim_next(now=0.0, lease_seconds=1.0)
        if claimed is None:
            raise AssertionError("old worker failed to claim the seeded task")
        results.put(
            {
                "kind": "old_claim",
                "task_id": claimed.task_id,
                "attempts": claimed.attempts,
                "lease_token": claimed.lease_token,
            }
        )
        if not allow_completion.wait(10.0):
            raise TimeoutError("old worker did not receive completion signal")

        try:
            queue.mark_succeeded(
                claimed.task_id,
                expected_attempts=claimed.attempts,
                lease_token=claimed.lease_token,
                revision=111,
                now=0.0,
            )
        except Exception as error:
            results.put(
                {
                    "kind": "old_completion",
                    "accepted": False,
                    "type": type(error).__name__,
                    "message": str(error),
                    "stale_worker_completion": getattr(
                        error, "stale_worker_completion", False
                    ),
                    "operation": getattr(error, "operation", None),
                }
            )
        else:
            results.put({"kind": "old_completion", "accepted": True})
    except BaseException as error:
        _child_error(results, "old-worker", error)
    finally:
        old_done.set()
        if connection is not None:
            connection.close()


def _recovery_worker(
    database: str,
    library_root: str,
    old_done: mp_context.BaseContext.Event,
    results: mp_context.BaseContext.Queue,
) -> None:
    connection = None
    try:
        # Start before expiry so queue construction does not perform its
        # automatic startup recovery.  Advance the independent process clock
        # only for the explicit recovery step below.
        connection, queue, monotonic_value, wallclock_value = _open_queue(
            database,
            library_root,
            monotonic_now=0.5,
            wallclock_now=1000.5,
        )
        monotonic_value[0] = 2.0
        wallclock_value[0] = 1002.0
        recovered = queue.recover_expired_running(now=2.0)
        if len(recovered) != 1:
            raise AssertionError(f"expected one recovered task, got {recovered!r}")
        if recovered[0].state.value != "retryable":
            raise AssertionError(f"unexpected recovery state: {recovered[0]!r}")

        monotonic_value[0] = 3.0
        wallclock_value[0] = 1003.0
        claimed = queue.claim_next(now=3.0, lease_seconds=5.0)
        if claimed is None:
            raise AssertionError("new worker failed to claim the recovered task")
        results.put(
            {
                "kind": "new_claim",
                "task_id": claimed.task_id,
                "attempts": claimed.attempts,
                "lease_token": claimed.lease_token,
                "recovered_count": len(recovered),
            }
        )

        if not old_done.wait(10.0):
            raise TimeoutError("new worker did not observe old worker completion")
        completed = queue.mark_succeeded(
            claimed.task_id,
            expected_attempts=claimed.attempts,
            lease_token=claimed.lease_token,
            revision=222,
            now=3.0,
        )
        results.put(
            {
                "kind": "new_completion",
                "state": completed.state.value,
                "attempts": completed.attempts,
                "observed_revision": completed.observed_revision,
                "lease_token": completed.lease_token,
            }
        )
    except BaseException as error:
        _child_error(results, "recovery-worker", error)
    finally:
        if connection is not None:
            connection.close()


def _initialize_database(database: Path) -> None:
    connection = sqlite3.connect(str(database), timeout=10.0)
    try:
        connection.executescript(_SCHEMA)
        connection.commit()
    finally:
        connection.close()


def _seed_task(database: Path, library_root: Path) -> str:
    connection, queue, _monotonic_value, _wallclock_value = _open_queue(
        str(database),
        str(library_root),
        monotonic_now=0.0,
        wallclock_now=1000.0,
    )
    try:
        task = queue.enqueue_or_merge(
            path=library_root,
            reason="busy",
            now=0.0,
        )
        return task.task_id
    finally:
        connection.close()


def _next_message(results: mp_context.BaseContext.Queue, timeout: float = 10.0):
    try:
        message = results.get(timeout=timeout)
    except queue_module.Empty as error:
        raise AssertionError("timed out waiting for spawned queue worker") from error
    if message.get("kind") == "error":
        raise AssertionError(
            f"spawned worker failed during {message['phase']}: "
            f"{message['type']}: {message['message']}\n{message['traceback']}"
        )
    return message


def _join_children(processes: list[multiprocessing.Process]) -> None:
    for process in processes:
        process.join(15.0)
    lingering = [process for process in processes if process.is_alive()]
    for process in lingering:
        process.terminate()
    for process in lingering:
        process.join(5.0)
    assert not lingering, "spawned queue worker did not terminate"
    for process in processes:
        assert process.exitcode == 0, f"spawned worker exit code: {process.exitcode}"


def test_spawn_two_processes_compete_for_claim_and_renew(tmp_path):
    """Two independent Windows-spawn workers share one durable claim."""
    database = tmp_path / "reconciliation-process-matrix.sqlite3"
    library_root = tmp_path / "library"
    library_root.mkdir()
    _initialize_database(database)
    task_id = _seed_task(database, library_root)

    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_claim_competitor,
            args=(str(database), str(library_root), start_event, results, label),
        )
        for label in ("worker-a", "worker-b")
    ]
    try:
        for process in processes:
            process.start()
        ready = {_next_message(results)["label"] for _ in processes}
        assert ready == {"worker-a", "worker-b"}
        start_event.set()

        outcomes = [_next_message(results) for _ in processes]
        claimed = [outcome for outcome in outcomes if outcome["claimed"]]
        not_claimed = [outcome for outcome in outcomes if not outcome["claimed"]]
        assert len(claimed) == 1
        assert len(not_claimed) == 1

        winner = claimed[0]
        assert winner["task_id"] == task_id
        assert winner["attempts"] == 1
        assert winner["lease_token"]
        assert winner["renewed_expiry"] > winner["claimed_expiry"]
    finally:
        start_event.set()
        _join_children(processes)

    connection, queue, _monotonic_value, _wallclock_value = _open_queue(
        str(database),
        str(library_root),
        monotonic_now=10.5,
        wallclock_now=1000.5,
    )
    try:
        current = queue.get(task_id)
        assert current is not None
        assert current.state.value == "running"
        assert current.attempts == 1
        assert current.lease_token == winner["lease_token"]
        assert current.lease_expires_at == pytest.approx(winner["renewed_expiry"])
    finally:
        connection.close()


def test_spawn_old_worker_completion_cannot_overwrite_recovered_owner(tmp_path):
    """An old process token cannot complete a task after recovery and re-claim."""
    database = tmp_path / "reconciliation-recovery-matrix.sqlite3"
    library_root = tmp_path / "library"
    library_root.mkdir()
    _initialize_database(database)
    task_id = _seed_task(database, library_root)

    context = multiprocessing.get_context("spawn")
    allow_old_completion = context.Event()
    old_done = context.Event()
    old_results = context.Queue()
    new_results = context.Queue()
    old_process = context.Process(
        target=_old_worker_completion,
        args=(
            str(database),
            str(library_root),
            allow_old_completion,
            old_done,
            old_results,
        ),
    )
    new_process = None
    processes = [old_process]
    try:
        old_process.start()
        old_claim = _next_message(old_results)
        assert old_claim["kind"] == "old_claim"
        assert old_claim["task_id"] == task_id
        assert old_claim["attempts"] == 1
        assert old_claim["lease_token"]

        new_process = context.Process(
            target=_recovery_worker,
            args=(str(database), str(library_root), old_done, new_results),
        )
        processes.append(new_process)
        new_process.start()
        new_claim = _next_message(new_results)
        assert new_claim["kind"] == "new_claim"
        assert new_claim["task_id"] == task_id
        assert new_claim["recovered_count"] == 1
        assert new_claim["attempts"] == 2
        assert new_claim["lease_token"]
        assert new_claim["lease_token"] != old_claim["lease_token"]

        allow_old_completion.set()
        old_completion = _next_message(old_results)
        assert old_completion["kind"] == "old_completion"
        assert old_completion["accepted"] is False
        assert old_completion["type"] == "ReconciliationQueuePersistenceConflict"
        assert old_completion["stale_worker_completion"] is True
        assert old_completion["operation"] == "completion"

        new_completion = _next_message(new_results)
        assert new_completion["kind"] == "new_completion"
        assert new_completion["state"] == "succeeded"
        assert new_completion["attempts"] == 2
        assert new_completion["observed_revision"] == 222
        assert new_completion["lease_token"] is None
    finally:
        allow_old_completion.set()
        _join_children(processes)

    connection, queue, _monotonic_value, _wallclock_value = _open_queue(
        str(database),
        str(library_root),
        monotonic_now=3.0,
        wallclock_now=1003.0,
    )
    try:
        current = queue.get(task_id)
        assert current is not None
        assert current.state.value == "succeeded"
        assert current.attempts == 2
        assert current.observed_revision == 222
        assert current.lease_token is None
    finally:
        connection.close()

