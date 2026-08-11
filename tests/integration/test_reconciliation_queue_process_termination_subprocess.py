"""Subprocess-based recovery after abrupt reconciliation worker termination."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import textwrap
import time


_WAIT_TIMEOUT = 10.0
_POLL_INTERVAL = 0.01
_REPO_ROOT = Path(__file__).resolve().parents[2]

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

# The child scripts are passed to ``python -c`` instead of using a pytest or
# multiprocessing worker.  This keeps the process boundary Windows-safe and
# avoids inheriting pytest's in-process Queue/feeder-thread state.
_OLD_WORKER_SCRIPT = textwrap.dedent(
    r'''
    from __future__ import annotations

    import json
    from pathlib import Path
    import sqlite3
    import sys
    import time
    import traceback

    from AssetsManager.application import ReconciliationQueue, SQLiteReconciliationQueueStore


    def write_status(path_text, payload):
        path = Path(path_text)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.replace(path)


    def main():
        database, library_root, ready_path = sys.argv[1:4]
        connection = None
        try:
            connection = sqlite3.connect(
                database,
                check_same_thread=False,
                timeout=10.0,
            )
            store = SQLiteReconciliationQueueStore(
                connection=connection,
                library_root=library_root,
                allow_unmanaged=True,
                clock=lambda: 0.0,
                wall_clock=lambda: 1000.0,
                busy_retry_attempts=5,
                busy_retry_backoff=0.01,
            )
            queue = ReconciliationQueue(
                library_root=library_root,
                persistence_store=store,
                clock=lambda: 0.0,
                wall_clock=lambda: 1000.0,
            )
            claimed = queue.claim_next(now=0.0, lease_seconds=1.0)
            if claimed is None:
                raise AssertionError("old subprocess failed to claim seeded task")
            write_status(
                ready_path,
                {
                    "kind": "claimed",
                    "task_id": claimed.task_id,
                    "attempts": claimed.attempts,
                    "lease_token": claimed.lease_token,
                    "lease_expires_at": claimed.lease_expires_at,
                },
            )
            # The parent terminates this process after observing the claim.  The
            # fallback deadline keeps the child bounded if the parent fails.
            hold_deadline = time.monotonic() + 10.0
            while time.monotonic() < hold_deadline:
                time.sleep(min(0.05, hold_deadline - time.monotonic()))
            raise TimeoutError("parent did not terminate old worker in time")
        except BaseException as error:
            write_status(
                ready_path,
                {
                    "kind": "error",
                    "type": type(error).__name__,
                    "message": str(error),
                    "traceback": traceback.format_exc(),
                },
            )
            raise
        finally:
            if connection is not None:
                connection.close()


    if __name__ == "__main__":
        main()
    ''',
)

_NEW_WORKER_SCRIPT = textwrap.dedent(
    r'''
    from __future__ import annotations

    import json
    from pathlib import Path
    import sqlite3
    import sys
    import traceback

    from AssetsManager.application import (
        ReconciliationQueue,
        ReconciliationQueuePersistenceConflict,
        SQLiteReconciliationQueueStore,
    )


    def write_status(path_text, payload):
        path = Path(path_text)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.replace(path)


    def main():
        (
            database,
            library_root,
            recovery_path,
            old_completion_path,
            completion_path,
            task_id,
            old_attempts_text,
            old_token,
        ) = sys.argv[1:9]
        old_attempts = int(old_attempts_text)
        connection = None
        # Keep the lease valid while the queue loads its initial snapshot.  The
        # queue constructor performs an eager recovery pass, so the explicit
        # process-recovery boundary below must advance both clocks only after
        # construction has completed.
        clock_value = [0.0]
        wallclock_value = [1000.0]
        try:
            connection = sqlite3.connect(
                database,
                check_same_thread=False,
                timeout=10.0,
            )
            store = SQLiteReconciliationQueueStore(
                connection=connection,
                library_root=library_root,
                allow_unmanaged=True,
                clock=lambda: clock_value[0],
                wall_clock=lambda: wallclock_value[0],
                busy_retry_attempts=5,
                busy_retry_backoff=0.01,
            )
            queue = ReconciliationQueue(
                library_root=library_root,
                persistence_store=store,
                clock=lambda: clock_value[0],
                wall_clock=lambda: wallclock_value[0],
            )

            clock_value[0] = 2.0
            wallclock_value[0] = 1002.0
            recovered = queue.recover_expired_running(now=2.0)
            if len(recovered) != 1 or recovered[0].task_id != task_id:
                raise AssertionError(
                    f"unexpected recovery result: {recovered!r}"
                )
            recovered_task = queue.get(task_id)
            if recovered_task is None:
                raise AssertionError("recovered task disappeared")
            write_status(
                recovery_path,
                {
                    "kind": "recovery",
                    "now": 2.0,
                    "wallclock": 1002.0,
                    "task_id": recovered_task.task_id,
                    "state": recovered_task.state.value,
                    "attempts": recovered_task.attempts,
                    "lease_token": recovered_task.lease_token,
                    "next_attempt_at": recovered_task.next_attempt_at,
                },
            )

            # A busy task receives a bounded 0.25-second retry backoff during
            # recovery.  Reclaim therefore advances the deterministic test
            # clock to 3.0/1003.0 rather than using an unbounded sleep.
            clock_value[0] = 3.0
            wallclock_value[0] = 1003.0
            claimed = queue.claim_next(now=3.0, lease_seconds=5.0)
            if claimed is None:
                raise AssertionError("new subprocess failed to reclaim task")
            if claimed.attempts != old_attempts + 1:
                raise AssertionError(f"unexpected new attempt: {claimed!r}")
            if claimed.lease_token is None or claimed.lease_token == old_token:
                raise AssertionError("new claim did not receive a new lease token")

            try:
                queue.mark_succeeded(
                    task_id,
                    expected_attempts=old_attempts,
                    lease_token=old_token,
                    revision=111,
                    now=3.0,
                )
            except ReconciliationQueuePersistenceConflict as conflict:
                current = queue.get(task_id)
                if current is None:
                    raise AssertionError("task disappeared after stale completion")
                write_status(
                    old_completion_path,
                    {
                        "kind": "old_completion",
                        "accepted": False,
                        "stale_worker_completion": conflict.stale_worker_completion,
                        "operation": conflict.operation,
                        "current_state": current.state.value,
                        "current_attempts": current.attempts,
                        "current_lease_token": current.lease_token,
                    },
                )
            else:
                write_status(
                    old_completion_path,
                    {
                        "kind": "old_completion",
                        "accepted": True,
                    },
                )

            completed = queue.mark_succeeded(
                task_id,
                expected_attempts=claimed.attempts,
                lease_token=claimed.lease_token,
                revision=222,
                now=3.0,
            )
            write_status(
                completion_path,
                {
                    "kind": "new_completion",
                    "task_id": completed.task_id,
                    "state": completed.state.value,
                    "attempts": completed.attempts,
                    "observed_revision": completed.observed_revision,
                    "lease_token": completed.lease_token,
                },
            )
        except BaseException as error:
            error_status = {
                "kind": "error",
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            }
            for status_path in (recovery_path, old_completion_path, completion_path):
                write_status(status_path, error_status)
            raise
        finally:
            if connection is not None:
                connection.close()


    if __name__ == "__main__":
        main()
    ''',
)


def _write_schema(database: Path) -> None:
    connection = sqlite3.connect(str(database), timeout=10.0)
    try:
        connection.executescript(_SCHEMA)
        connection.commit()
    finally:
        connection.close()


def _open_queue(database: Path, library_root: Path, *, now: float, wallclock: float):
    from AssetsManager.application import ReconciliationQueue, SQLiteReconciliationQueueStore

    clock_value = [float(now)]
    wallclock_value = [float(wallclock)]
    connection = sqlite3.connect(
        str(database),
        check_same_thread=False,
        timeout=10.0,
    )
    store = SQLiteReconciliationQueueStore(
        connection=connection,
        library_root=str(library_root),
        allow_unmanaged=True,
        clock=lambda: clock_value[0],
        wall_clock=lambda: wallclock_value[0],
        busy_retry_attempts=5,
        busy_retry_backoff=0.01,
    )
    queue = ReconciliationQueue(
        library_root=str(library_root),
        persistence_store=store,
        clock=lambda: clock_value[0],
        wall_clock=lambda: wallclock_value[0],
    )
    return connection, queue


def _seed_task(database: Path, library_root: Path) -> object:
    connection, queue = _open_queue(database, library_root, now=0.0, wallclock=1000.0)
    try:
        return queue.enqueue_or_merge(
            path=library_root,
            reason="busy",
            now=0.0,
        )
    finally:
        connection.close()


def _wait_for_json(path: Path, *, timeout: float = _WAIT_TIMEOUT) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_decode_error: Exception | None = None
    while time.monotonic() < deadline:
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise AssertionError(f"status is not an object: {payload!r}")
                if payload.get("kind") == "error":
                    raise AssertionError(
                        f"child failed: {payload.get('type')}: {payload.get('message')}\n"
                        f"{payload.get('traceback', '')}"
                    )
                return payload
            except (OSError, json.JSONDecodeError, AssertionError) as error:
                last_decode_error = error
        time.sleep(_POLL_INTERVAL)
    raise AssertionError(
        f"timed out waiting for JSON handshake {path}; "
        f"last error={last_decode_error!r}"
    )


def _start_child(script: str, *arguments: object) -> subprocess.Popen:
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    pythonpath = str(_REPO_ROOT)
    if existing_pythonpath:
        pythonpath += os.pathsep + existing_pythonpath
    environment["PYTHONPATH"] = pythonpath
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            *(str(argument) for argument in arguments),
        ],
        cwd=str(_REPO_ROOT),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def _stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2.0)


def test_subprocess_termination_recovers_and_rejects_old_token(tmp_path):
    database = tmp_path / "reconciliation-process-termination.sqlite3"
    library_root = tmp_path / "library"
    library_root.mkdir()
    _write_schema(database)
    seeded = _seed_task(database, library_root)
    task_id = seeded.task_id

    old_ready = tmp_path / "old-ready.json"
    recovery_status = tmp_path / "new-recovery.json"
    old_completion_status = tmp_path / "old-completion.json"
    new_completion_status = tmp_path / "new-completion.json"

    old_process: subprocess.Popen | None = None
    new_process: subprocess.Popen | None = None
    try:
        old_process = _start_child(
            _OLD_WORKER_SCRIPT,
            database,
            library_root,
            old_ready,
        )
        old_claim = _wait_for_json(old_ready)
        assert old_claim["kind"] == "claimed"
        assert old_claim["task_id"] == task_id
        assert old_claim["attempts"] == 1
        old_token = old_claim["lease_token"]
        assert isinstance(old_token, str) and old_token
        assert old_claim["lease_expires_at"] == 1.0
        assert old_process.poll() is None

        old_process.terminate()
        try:
            old_process.wait(timeout=_WAIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            old_process.kill()
            old_process.wait(timeout=2.0)
        assert old_process.poll() is not None

        new_process = _start_child(
            _NEW_WORKER_SCRIPT,
            database,
            library_root,
            recovery_status,
            old_completion_status,
            new_completion_status,
            task_id,
            1,
            old_token,
        )
        recovery = _wait_for_json(recovery_status)
        assert recovery == {
            "kind": "recovery",
            "now": 2.0,
            "wallclock": 1002.0,
            "task_id": task_id,
            "state": "retryable",
            "attempts": 1,
            "lease_token": None,
            "next_attempt_at": 2.25,
        }

        old_completion = _wait_for_json(old_completion_status)
        assert old_completion["kind"] == "old_completion"
        assert old_completion["accepted"] is False
        assert old_completion["stale_worker_completion"] is True
        assert old_completion["operation"] == "completion"
        assert old_completion["current_state"] == "running"
        assert old_completion["current_attempts"] == 2
        current_token = old_completion["current_lease_token"]
        assert isinstance(current_token, str) and current_token
        # The exact new token is generated by the subprocess; assert ownership
        # separation rather than a UUID value.
        assert current_token != old_token

        completion = _wait_for_json(new_completion_status)
        assert completion == {
            "kind": "new_completion",
            "task_id": task_id,
            "state": "succeeded",
            "attempts": 2,
            "observed_revision": 222,
            "lease_token": None,
        }
        new_process.wait(timeout=_WAIT_TIMEOUT)
        assert new_process.returncode == 0

        connection, queue = _open_queue(
            database,
            library_root,
            now=3.0,
            wallclock=1003.0,
        )
        try:
            final = queue.get(task_id)
        finally:
            connection.close()
        assert final is not None
        assert final.state.value == "succeeded"
        assert final.attempts == 2
        assert final.observed_revision == 222
        assert final.lease_token is None
    finally:
        _stop_process(new_process)
        _stop_process(old_process)





