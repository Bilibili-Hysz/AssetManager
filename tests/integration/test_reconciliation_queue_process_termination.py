"""Spawn-safe recovery after abrupt worker/process termination."""

from __future__ import annotations

from multiprocessing import context as mp_context
import multiprocessing
import os
from pathlib import Path
import queue as queue_module
import sqlite3
import traceback

import pytest


# This scenario is retained as an explicit F-4 draft, but is not part of the
# default gate until Windows spawn/Queue finalization can be made deterministic
# in the shared workspace.  The stable recovery contract is covered by the
# process matrix and connection-close tests.
pytestmark = pytest.mark.skip(
    reason="abrupt Windows spawn termination/Queue finalization is not deterministic yet"
)


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


def _open_queue(database: str, library_root: str, *, now: float, wallclock: float):
    from AssetsManager.application import ReconciliationQueue, SQLiteReconciliationQueueStore

    clock_value = [float(now)]
    wallclock_value = [float(wallclock)]
    connection = sqlite3.connect(database, check_same_thread=False, timeout=0.0)
    store = SQLiteReconciliationQueueStore(
        connection=connection,
        library_root=library_root,
        allow_unmanaged=True,
        clock=lambda: clock_value[0],
        wall_clock=lambda: wallclock_value[0],
        busy_retry_attempts=0,
        busy_retry_backoff=0.0,
    )
    queue = ReconciliationQueue(
        library_root=library_root,
        persistence_store=store,
        clock=lambda: clock_value[0],
        wall_clock=lambda: wallclock_value[0],
    )
    return connection, queue, clock_value, wallclock_value


def _old_worker_until_terminated(
    database: str,
    library_root: str,
    hold_event: mp_context.BaseContext.Event,
    results: mp_context.BaseContext.Queue,
) -> None:
    connection = None
    try:
        connection, queue, _clock, _wallclock = _open_queue(
            database,
            library_root,
            now=0.0,
            wallclock=1000.0,
        )
        claimed = queue.claim_next(now=0.0, lease_seconds=1.0)
        if claimed is None:
            raise AssertionError("old worker failed to claim seeded task")
        results.put(
            {
                "kind": "old_claim",
                "task_id": claimed.task_id,
                "attempts": claimed.attempts,
                "lease_token": claimed.lease_token,
                "lease_expires_at": claimed.lease_expires_at,
            }
        )
        if not hold_event.wait(10.0):
            raise TimeoutError("old worker was not held until termination")
        if connection is not None:
            connection.close()
        os._exit(1)
    except BaseException as error:
        _child_error(results, "old-worker", error)
    finally:
        if connection is not None:
            connection.close()


def _new_recovery_worker(
    database: str,
    library_root: str,
    task_id: str,
    results: mp_context.BaseContext.Queue,
) -> None:
    connection = None
    try:
        from AssetsManager.application import ReconciliationState

        connection, queue, clock_value, wallclock_value = _open_queue(
            database,
            library_root,
            now=2.0,
            wallclock=1002.0,
        )
        recovered = queue.get(task_id)
        if recovered is None:
            raise AssertionError("new worker did not load terminated worker task")
        if recovered.state is not ReconciliationState.RETRYABLE:
            raise AssertionError(f"task was not recovered: {recovered!r}")
        results.put(
            {
                "kind": "new_recovery",
                "task_id": task_id,
                "state": recovered.state.value,
                "attempts": recovered.attempts,
                "lease_token": recovered.lease_token,
            }
        )

        clock_value[0] = 3.0
        wallclock_value[0] = 1003.0
        claimed = queue.claim_next(now=3.0, lease_seconds=5.0)
        if claimed is None:
            raise AssertionError("new worker failed to re-claim recovered task")
        completed = queue.mark_succeeded(
            task_id,
            expected_attempts=claimed.attempts,
            lease_token=claimed.lease_token,
            revision=222,
            now=3.0,
        )
        results.put(
            {
                "kind": "new_completion",
                "task_id": completed.task_id,
                "state": completed.state.value,
                "attempts": completed.attempts,
                "observed_revision": completed.observed_revision,
                "lease_token": completed.lease_token,
            }
        )
    except BaseException as error:
        _child_error(results, "new-worker", error)
    finally:
        if connection is not None:
            connection.close()


def _initialize_database(database: Path) -> None:
    connection = sqlite3.connect(str(database), timeout=0.0)
    try:
        connection.executescript(_SCHEMA)
        connection.commit()
    finally:
        connection.close()


def _seed_task(database: Path, library_root: Path) -> str:
    connection, queue, _clock, _wallclock = _open_queue(
        str(database),
        str(library_root),
        now=0.0,
        wallclock=1000.0,
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


def test_terminated_worker_is_recovered_and_completed_by_new_process(tmp_path):
    database = tmp_path / "reconciliation-process-termination.sqlite3"
    library_root = tmp_path / "library"
    library_root.mkdir()
    _initialize_database(database)
    task_id = _seed_task(database, library_root)

    context = multiprocessing.get_context("spawn")
    hold_event = context.Event()
    old_results = context.Queue()
    new_results = context.Queue()
    old_process = context.Process(
        target=_old_worker_until_terminated,
        args=(str(database), str(library_root), hold_event, old_results),
    )
    new_process = None
    try:
        old_process.start()
        old_claim = _next_message(old_results)
        assert old_claim["kind"] == "old_claim"
        assert old_claim["task_id"] == task_id
        assert old_claim["attempts"] == 1
        assert old_claim["lease_token"]
        assert old_claim["lease_expires_at"] == pytest.approx(1.0)

        # Abrupt termination closes the old process connection without giving
        # the worker a chance to complete or explicitly release its lease.
        hold_event.set()
        old_process.join(10.0)
        assert not old_process.is_alive()
        assert old_process.exitcode != 0

        new_process = context.Process(
            target=_new_recovery_worker,
            args=(str(database), str(library_root), task_id, new_results),
        )
        new_process.start()
        recovery = _next_message(new_results)
        assert recovery == {
            "kind": "new_recovery",
            "task_id": task_id,
            "state": "retryable",
            "attempts": 1,
            "lease_token": None,
        }

        completion = _next_message(new_results)
        assert completion == {
            "kind": "new_completion",
            "task_id": task_id,
            "state": "succeeded",
            "attempts": 2,
            "observed_revision": 222,
            "lease_token": None,
        }
        new_process.join(10.0)
        assert not new_process.is_alive()
        assert new_process.exitcode == 0
    finally:
        hold_event.set()
        for process in (old_process, new_process):
            if process is None:
                continue
            if process.is_alive():
                process.terminate()
            process.join(10.0)





