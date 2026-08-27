"""Windows-safe dual-process import manifest recovery claim race."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import textwrap
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_REPO_ROOT = Path(__file__).resolve().parents[2]
# Child processes pay a full interpreter + package import on Windows, and a
# cold start under full-suite memory pressure has been observed beyond 30s;
# keep a generous ceiling so slow starts cannot flake the barrier waits.
_WAIT_TIMEOUT = 90.0
_POLL_INTERVAL = 0.01

_CHILD_SCRIPT = textwrap.dedent(
    r'''
    from __future__ import annotations

    import json
    from pathlib import Path
    import sqlite3
    import sys
    import time

    from AssetsManager.application.import_manifest_store import (
        ImportManifestRecoveryService,
        ImportManifestStore,
    )
    from AssetsManager.application.reconciliation_queue import ReconciliationQueue
    from AssetsManager.application.reconciliation_queue_store import (
        SQLiteReconciliationQueueStore,
    )


    def write_json(path_text, payload):
        path = Path(path_text)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        # The parent polls and reads the final path concurrently; a Windows
        # replace can transiently fail while that handle is open.
        deadline = time.monotonic() + 10.0
        while True:
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)


    def wait_for(path_text):
        deadline = time.monotonic() + 30.0
        path = Path(path_text)
        while time.monotonic() < deadline and not path.exists():
            time.sleep(0.01)
        if not path.exists():
            raise TimeoutError(f"control file was not released: {path}")


    def main():
        database, library_root, status_path, release_path = sys.argv[1:5]
        connection = sqlite3.connect(database, check_same_thread=False, timeout=10.0)
        try:
            store = ImportManifestStore(connection, library_root)
            records = store.list_recovery()
            if len(records) != 1:
                raise AssertionError(f"unexpected recovery records: {records!r}")
            record = records[0]
            write_json(
                status_path,
                {
                    "phase": "listed",
                    "operation_id": record["operation_id"],
                    "generation": record["generation"],
                },
            )
            wait_for(release_path)
            # Return the pre-barrier snapshot so both workers exercise the same
            # generation/state CAS predicate.
            store.list_recovery = lambda: (record,)
            queue_store = SQLiteReconciliationQueueStore(
                connection=connection,
                library_root=library_root,
                allow_unmanaged=True,
            )
            queue = ReconciliationQueue(
                library_root=library_root,
                persistence_store=queue_store,
            )
            recovered = ImportManifestRecoveryService(store, queue).recover()
            write_json(
                status_path,
                {"phase": "done", "recovered": list(recovered)},
            )
        except BaseException as error:
            write_json(
                status_path,
                {"phase": "error", "type": type(error).__name__, "message": str(error)},
            )
            raise
        finally:
            connection.close()


    if __name__ == "__main__":
        main()
    ''',
)


def _start_child(database: Path, root: Path, status: Path, release: Path):
    environment = os.environ.copy()
    pythonpath = str(_REPO_ROOT)
    if environment.get("PYTHONPATH"):
        pythonpath += os.pathsep + environment["PYTHONPATH"]
    environment["PYTHONPATH"] = pythonpath
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            _CHILD_SCRIPT,
            str(database),
            str(root),
            str(status),
            str(release),
        ],
        cwd=str(_REPO_ROOT),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
    )


_CHECKPOINT_CHILD_SCRIPT = textwrap.dedent(
    r'''
    from __future__ import annotations

    import json
    from pathlib import Path
    import sqlite3
    import sys
    import threading
    import time

    from AssetsManager.application.import_manifest_store import (
        ImportManifestRecoveryService,
        ImportManifestStore,
    )
    from AssetsManager.application.reconciliation_queue import ReconciliationQueue
    from AssetsManager.application.reconciliation_queue_store import (
        SQLiteReconciliationQueueStore,
    )


    def write_json(path_text, payload):
        path = Path(path_text)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        # The parent polls and reads the final path concurrently; a Windows
        # replace can transiently fail while that handle is open.
        deadline = time.monotonic() + 10.0
        while True:
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)


    class ShortLeaseStore(ImportManifestStore):
        """Force a short wall-clock lease so takeover polls stay fast."""

        def claim_recovery(self, record, *, now=None, lease_seconds=30.0):
            return super().claim_recovery(
                record, now=now, lease_seconds=float(lease_arg)
            )


    def main():
        global lease_arg
        database, library_root, status_path, mode, lease_arg = sys.argv[1:6]
        connection = sqlite3.connect(database, check_same_thread=False, timeout=10.0)
        try:
            store = ShortLeaseStore(connection, library_root)
            records = store.list_recovery()
            if len(records) != 1:
                raise AssertionError(f"unexpected recovery records: {records!r}")
            record = records[0]
            write_json(
                status_path,
                {
                    "phase": "listed",
                    "operation_id": record["operation_id"],
                    "generation": record["generation"],
                },
            )
            queue_store = SQLiteReconciliationQueueStore(
                connection=connection,
                library_root=library_root,
                allow_unmanaged=True,
            )
            queue = ReconciliationQueue(
                library_root=library_root,
                persistence_store=queue_store,
            )
            blocked = threading.Event()
            if mode == "after_claim":
                real_enqueue = queue.enqueue_or_merge

                def blocked_enqueue(**kwargs):
                    # Claim is already committed here; enqueue has not run.
                    write_json(
                        status_path,
                        {"phase": "checkpoint", "stage": "after_claim"},
                    )
                    blocked.wait()
                    return real_enqueue(**kwargs)

                queue.enqueue_or_merge = blocked_enqueue
            elif mode == "after_enqueue":
                real_finish = store.finish_recovery

                def blocked_finish(record_claimed, **kwargs):
                    # Enqueue is already committed here; finish has not run.
                    write_json(
                        status_path,
                        {"phase": "checkpoint", "stage": "after_enqueue"},
                    )
                    blocked.wait()
                    return real_finish(record_claimed, **kwargs)

                store.finish_recovery = blocked_finish
            else:
                raise AssertionError(f"unknown checkpoint mode: {mode}")
            recovered = ImportManifestRecoveryService(store, queue).recover()
            write_json(
                status_path,
                {"phase": "done", "recovered": list(recovered)},
            )
        except BaseException as error:
            write_json(
                status_path,
                {"phase": "error", "type": type(error).__name__, "message": str(error)},
            )
            raise
        finally:
            connection.close()


    if __name__ == "__main__":
        main()
    ''',
)


def _start_checkpoint_child(
    database: Path,
    root: Path,
    status: Path,
    mode: str,
    lease_seconds: str = "3.0",
):
    environment = os.environ.copy()
    pythonpath = str(_REPO_ROOT)
    if environment.get("PYTHONPATH"):
        pythonpath += os.pathsep + environment["PYTHONPATH"]
    environment["PYTHONPATH"] = pythonpath
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            _CHECKPOINT_CHILD_SCRIPT,
            str(database),
            str(root),
            str(status),
            mode,
            lease_seconds,
        ],
        cwd=str(_REPO_ROOT),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
    )


def _wait_json(path: Path, *, phase: str | None = None):
    deadline = time.monotonic() + _WAIT_TIMEOUT
    last_error = None
    while time.monotonic() < deadline:
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("phase") == "error":
                    raise AssertionError(payload)
                if phase is None or payload.get("phase") == phase:
                    return payload
            except (OSError, json.JSONDecodeError, AssertionError) as error:
                last_error = error
        time.sleep(_POLL_INTERVAL)
    raise AssertionError(f"timed out waiting for {path}; last_error={last_error!r}")


def _stop(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3.0)


def test_dual_process_manifest_recovery_has_one_claim_winner(tmp_path):
    from AssetsManager.application.import_manifest_store import ImportManifestStore
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    root = tmp_path / "library"
    root.mkdir()
    destination = root / "dest"
    database_path = tmp_path / "manifest-claim.sqlite3"
    initializer = sqlite3.connect(str(database_path), check_same_thread=False)
    initializer.executescript(database._SCHEMA)
    initializer.commit()
    migrate(initializer)
    store = ImportManifestStore(initializer, root)
    store.create(
        operation_id="claim-process-race",
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
    initializer.close()

    children = []
    statuses = []
    releases = []
    try:
        for index in range(2):
            status = tmp_path / f"child-{index}.json"
            release = tmp_path / f"release-{index}"
            statuses.append(status)
            releases.append(release)
            children.append(_start_child(database_path, root, status, release))

        listed = [_wait_json(status) for status in statuses]
        assert listed == [
            {
                "phase": "listed",
                "operation_id": "claim-process-race",
                "generation": 0,
            },
            {
                "phase": "listed",
                "operation_id": "claim-process-race",
                "generation": 0,
            },
        ]
        for release in releases:
            release.touch()
        completed = [_wait_json(status, phase="done") for status in statuses]
        for child in children:
            child.wait(timeout=_WAIT_TIMEOUT)
            assert child.returncode == 0, child.stderr.read().decode(errors="replace")
        recovered_count = sum(
            "claim-process-race" in payload.get("recovered", [])
            for payload in completed
        )
        assert recovered_count == 1, completed

        connection = sqlite3.connect(str(database_path), check_same_thread=False)
        try:
            final = ImportManifestStore(connection, root).get("claim-process-race")
            assert final["state"] == "completed"
            assert final["attempts"] == 1
            assert final["generation"] == 2
            assert final["recovery_claim_token"] is None
            queue_rows = connection.execute(
                "SELECT operation_ids FROM reconciliation_tasks"
            ).fetchall()
            assert len(queue_rows) == 1
            assert json.loads(queue_rows[0][0]) == ["claim-process-race"]
        finally:
            connection.close()
    finally:
        for release in releases:
            release.touch()
        for child in children:
            _stop(child)


def _seed_running_manifest(database_path: Path, root: Path, operation_id: str):
    from AssetsManager.application.import_manifest_store import ImportManifestStore
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    destination = root / "dest"
    initializer = sqlite3.connect(str(database_path), check_same_thread=False)
    initializer.executescript(database._SCHEMA)
    initializer.commit()
    migrate(initializer)
    store = ImportManifestStore(initializer, root)
    store.create(
        operation_id=operation_id,
        destination=destination,
        payload={
            "payload_version": 1,
            "destination": str(destination.resolve()),
            "items": [
                {
                    "source": str((database_path.parent / "source.txt").resolve()),
                    "target": str((destination / "source.txt").resolve()),
                    "state": "pending",
                }
            ],
        },
        state="running",
    )
    initializer.close()


def _open_parent_view(database_path: Path, root: Path):
    from AssetsManager.application.import_manifest_store import (
        ImportManifestRecoveryService,
        ImportManifestStore,
    )
    from AssetsManager.application.reconciliation_queue import ReconciliationQueue
    from AssetsManager.application.reconciliation_queue_store import (
        SQLiteReconciliationQueueStore,
    )

    connection = sqlite3.connect(str(database_path), check_same_thread=False, timeout=10.0)
    store = ImportManifestStore(connection, root)
    queue_store = SQLiteReconciliationQueueStore(
        connection=connection,
        library_root=root,
        allow_unmanaged=True,
    )
    queue = ReconciliationQueue(
        library_root=root,
        persistence_store=queue_store,
    )
    service = ImportManifestRecoveryService(store, queue)
    return connection, store, service


def _queue_snapshot(connection):
    rows = connection.execute(
        "SELECT task_id, operation_ids FROM reconciliation_tasks"
    ).fetchall()
    return [
        (task_id, json.loads(operation_ids)) for task_id, operation_ids in rows
    ]


def _wait_for_takeover(service, operation_id, *, deadline_seconds=20.0):
    deadline = time.monotonic() + deadline_seconds
    recovered: tuple[str, ...] = ()
    while time.monotonic() < deadline:
        recovered = service.recover()
        if operation_id in recovered:
            return recovered
        time.sleep(0.25)
    raise AssertionError(
        f"takeover did not converge within {deadline_seconds}s; last={recovered!r}"
    )


def _wait_checkpoint_with_diagnostics(status: Path, child) -> dict:
    """Wait for the checkpoint barrier; surface child state if it times out."""
    try:
        return _wait_json(status, phase="checkpoint")
    except AssertionError:
        alive = child is not None and child.poll() is None
        stderr = (
            child.stderr.read().decode(errors="replace")[-2000:]
            if child is not None and not alive
            else "<child still running>"
        )
        raise AssertionError(
            f"child never reached its checkpoint (alive={alive}); "
            f"stderr tail:\n{stderr}"
        ) from None


def test_kill_after_claim_blocks_takeover_until_lease_expiry(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    database_path = tmp_path / "checkpoint-claim.sqlite3"
    operation_id = "claim-kill-checkpoint"
    _seed_running_manifest(database_path, root, operation_id)

    status = tmp_path / "child.json"
    child = _start_checkpoint_child(database_path, root, status, "after_claim")
    try:
        checkpoint = _wait_checkpoint_with_diagnostics(status, child)
        assert checkpoint["stage"] == "after_claim"
        _stop(child)
        child = None

        connection, store, service = _open_parent_view(database_path, root)
        try:
            # Claim committed by the killed child must be visible and live.
            record = store.get(operation_id)
            assert record["state"] == "running"
            assert record["generation"] == 1
            assert record["recovery_claim_token"] is not None
            assert (
                record["recovery_lease_expires_at"]
                > time.time()
            )
            assert _queue_snapshot(connection) == []
            # A live lease blocks an immediate takeover attempt.
            assert service.recover() == ()
            assert _queue_snapshot(connection) == []

            # After lease expiry the parent takes over and converges.
            _wait_for_takeover(service, operation_id)
            final = store.get(operation_id)
            assert final["state"] == "completed"
            assert final["attempts"] == 1
            assert final["generation"] == 3
            assert final["recovery_claim_token"] is None
            snapshot = _queue_snapshot(connection)
            assert len(snapshot) == 1
            assert snapshot[0][1] == [operation_id]
        finally:
            connection.close()
    finally:
        _stop(child)


def test_kill_after_enqueue_keeps_single_queue_task_across_restart(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    database_path = tmp_path / "checkpoint-enqueue.sqlite3"
    operation_id = "enqueue-kill-checkpoint"
    _seed_running_manifest(database_path, root, operation_id)

    status = tmp_path / "child.json"
    child = _start_checkpoint_child(database_path, root, status, "after_enqueue")
    try:
        checkpoint = _wait_checkpoint_with_diagnostics(status, child)
        assert checkpoint["stage"] == "after_enqueue"

        pre_kill_connection, _pre_store, _pre_service = _open_parent_view(
            database_path, root
        )
        snapshot_before_kill = _queue_snapshot(pre_kill_connection)
        pre_kill_connection.close()
        assert len(snapshot_before_kill) == 1
        stable_task_id = snapshot_before_kill[0][0]
        assert snapshot_before_kill[0][1] == [operation_id]

        _stop(child)
        child = None

        connection, store, service = _open_parent_view(database_path, root)
        try:
            # The enqueue survived the kill; the claim lease is still live.
            record = store.get(operation_id)
            assert record["state"] == "running"
            assert record["generation"] == 1
            assert record["recovery_claim_token"] is not None
            snapshot = _queue_snapshot(connection)
            assert len(snapshot) == 1
            assert snapshot[0][0] == stable_task_id
            # Live lease blocks immediate takeover without duplicating tasks.
            assert service.recover() == ()
            snapshot = _queue_snapshot(connection)
            assert len(snapshot) == 1
            assert snapshot[0][0] == stable_task_id
            assert snapshot[0][1].count(operation_id) == 1

            # Takeover merges into the same task instead of creating a row.
            _wait_for_takeover(service, operation_id)
            final = store.get(operation_id)
            assert final["state"] == "completed"
            assert final["attempts"] == 1
            assert final["generation"] == 3
            assert final["recovery_claim_token"] is None
            snapshot = _queue_snapshot(connection)
            assert len(snapshot) == 1
            assert snapshot[0][0] == stable_task_id
            assert snapshot[0][1].count(operation_id) == 1

            # A further restart-time pass finds nothing left to do.
            assert service.recover() == ()
            assert len(_queue_snapshot(connection)) == 1
        finally:
            connection.close()
    finally:
        _stop(child)
