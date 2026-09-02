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
                real_bind = store.bind_recovery_task

                def blocked_bind(record_claimed, task_id, **kwargs):
                    # Enqueue is already committed here; manifest ownership
                    # has not yet been bound to the durable queue task.
                    write_json(
                        status_path,
                        {"phase": "checkpoint", "stage": "after_enqueue"},
                    )
                    blocked.wait()
                    return real_bind(record_claimed, task_id, **kwargs)

                store.bind_recovery_task = blocked_bind
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


_OUTBOX_ACK_CHECKPOINT_CHILD_SCRIPT = textwrap.dedent(
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
        deadline = time.monotonic() + 10.0
        while True:
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)


    def main():
        (
            database,
            library_root,
            status_path,
            operation_id,
            mode,
            lease_seconds,
            callback_max_age,
        ) = sys.argv[1:8]
        connection = sqlite3.connect(database, check_same_thread=False, timeout=10.0)
        try:
            manifest_store = ImportManifestStore(connection, library_root)
            queue_store = SQLiteReconciliationQueueStore(
                connection=connection,
                library_root=library_root,
                allow_unmanaged=True,
            )
            queue = ReconciliationQueue(
                library_root=library_root,
                persistence_store=queue_store,
            )
            original_drain = queue.drain_transition_outbox

            def drain_with_short_lease(*args, **kwargs):
                kwargs.setdefault("lease_seconds", float(lease_seconds))
                kwargs.setdefault("callback_max_age", float(callback_max_age))
                return original_drain(*args, **kwargs)

            queue.drain_transition_outbox = drain_with_short_lease
            if mode == "after_manifest_cas_before_outbox_ack":
                original_acknowledge = queue_store.acknowledge_transition_outbox

                def checkpoint_before_ack(event_id, *, delivery_token):
                    row = connection.execute(
                        "SELECT reason FROM reconciliation_transition_outbox "
                        "WHERE id=? AND library_root=?",
                        (event_id, queue_store.library_root),
                    ).fetchone()
                    if row is None or row[0] != "succeeded":
                        return original_acknowledge(
                            event_id,
                            delivery_token=delivery_token,
                        )
                    record = manifest_store.get(operation_id, include_items=False)
                    if record is None or record.get("state") != "completed":
                        raise AssertionError(
                            "succeeded outbox event reached acknowledgement before "
                            "the manifest CAS committed"
                        )
                    write_json(
                        status_path,
                        {
                            "phase": "checkpoint",
                            "stage": "after_manifest_cas_before_outbox_ack",
                            "event_id": event_id,
                            "manifest_generation": record["generation"],
                        },
                    )
                    # The parent terminates this interpreter here.  A normal
                    # return would acknowledge the event and defeat the crash
                    # boundary under test.
                    threading.Event().wait()

                queue_store.acknowledge_transition_outbox = checkpoint_before_ack
            elif mode in {
                "after_first_terminal_manifest_cas",
                "after_first_evicted_manifest_cas",
            }:
                original_transition = manifest_store.record_recovery_task_transition
                expected_state = (
                    "terminal"
                    if mode == "after_first_terminal_manifest_cas"
                    else "evicted"
                )
                expected_phase = (
                    "dead_letter"
                    if expected_state == "terminal"
                    else "pending"
                )
                expected_reason = expected_state

                def checkpoint_after_first_transition(
                    manifest_operation_id,
                    task_id,
                    task_state,
                    **kwargs,
                ):
                    changed = original_transition(
                        manifest_operation_id,
                        task_id,
                        task_state,
                        **kwargs,
                    )
                    if (
                        manifest_operation_id != operation_id
                        or str(task_state).lower() != expected_state
                    ):
                        return changed
                    record = manifest_store.get(operation_id, include_items=False)
                    if (
                        not changed
                        or record is None
                        or record.get("payload", {}).get("recovery_phase")
                        != expected_phase
                    ):
                        raise AssertionError(
                            f"{expected_state} outbox event did not persist the first "
                            "manifest CAS before its checkpoint"
                        )
                    if (
                        expected_state == "evicted"
                        and record.get("payload", {}).get("recovery_task_id")
                        is not None
                    ):
                        raise AssertionError(
                            "evicted outbox event did not clear the first manifest binding"
                        )
                    row = connection.execute(
                        "SELECT id FROM reconciliation_transition_outbox "
                        "WHERE library_root=? AND reason=? "
                        "AND delivered_at IS NULL AND delivery_token IS NOT NULL",
                        (queue_store.library_root, expected_reason),
                    ).fetchone()
                    if row is None:
                        raise AssertionError(
                            f"{expected_state} outbox event lost its delivery lease before "
                            "the first manifest CAS"
                        )
                    write_json(
                        status_path,
                        {
                            "phase": "checkpoint",
                            "stage": f"after_first_{expected_state}_manifest_cas",
                            "event_id": row[0],
                            "manifest_generation": record["generation"],
                        },
                    )
                    threading.Event().wait()
                    return changed

                manifest_store.record_recovery_task_transition = (
                    checkpoint_after_first_transition
                )
            elif mode == "long_callback":
                original_transition = ImportManifestRecoveryService.handle_task_transition

                def blocked_transition(recovery_service, transition):
                    current = getattr(transition, "current", None)
                    state = getattr(current, "state", current)
                    state_value = getattr(state, "value", state)
                    if str(state_value).lower() != "succeeded":
                        return original_transition(recovery_service, transition)
                    row = connection.execute(
                        "SELECT id, delivery_lease_expires_at "
                        "FROM reconciliation_transition_outbox "
                        "WHERE library_root=? AND delivered_at IS NULL "
                        "AND delivery_token IS NOT NULL AND reason='succeeded' "
                        "ORDER BY id ASC LIMIT 1",
                        (queue_store.library_root,),
                    ).fetchone()
                    if row is None:
                        raise AssertionError(
                            "long callback checkpoint did not observe a leased outbox event"
                        )
                    write_json(
                        status_path,
                        {
                            "phase": "checkpoint",
                            "stage": "inside_long_callback",
                            "event_id": row[0],
                            "delivery_lease_expires_at": row[1],
                            "manifest_generation": recovery_service.store.get(
                                operation_id,
                                include_items=False,
                            )["generation"],
                        },
                    )
                    # The parent waits until the bounded callback-age policy
                    # lets this lease expire, then terminates this process.
                    threading.Event().wait()
                    return original_transition(recovery_service, transition)

                ImportManifestRecoveryService.handle_task_transition = blocked_transition
            else:
                raise AssertionError(f"unknown outbox checkpoint mode: {mode}")
            ImportManifestRecoveryService(manifest_store, queue)
            raise AssertionError("outbox acknowledgement checkpoint did not block")
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


def _start_outbox_ack_checkpoint_child(
    database: Path,
    root: Path,
    status: Path,
    operation_id: str,
    mode: str = "after_manifest_cas_before_outbox_ack",
    lease_seconds: str = "3.0",
    callback_max_age: str = "300.0",
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
            _OUTBOX_ACK_CHECKPOINT_CHILD_SCRIPT,
            str(database),
            str(root),
            str(status),
            operation_id,
            mode,
            lease_seconds,
            callback_max_age,
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
            # Queue acceptance only binds recovery ownership. A worker must
            # later complete the task and its durable transition is what ACKs
            # the manifest to completed.
            assert final["state"] == "recovery_pending"
            assert final["payload"]["recovery_phase"] == "enqueued"
            assert final["attempts"] == 0
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


def _seed_succeeded_manifest_outbox(
    database_path: Path,
    root: Path,
    operation_id: str,
) -> str:
    """Create a bound recovery intent plus an undelivered succeeded event."""
    from AssetsManager.application.import_manifest_store import ImportManifestStore
    from AssetsManager.application.reconciliation_queue import ReconciliationQueue
    from AssetsManager.application.reconciliation_queue_store import (
        SQLiteReconciliationQueueStore,
    )
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    destination = root / "dest"
    initializer = sqlite3.connect(str(database_path), check_same_thread=False)
    initializer.executescript(database._SCHEMA)
    initializer.commit()
    migrate(initializer)
    manifest_store = ImportManifestStore(initializer, root)
    queue_store = SQLiteReconciliationQueueStore(
        connection=initializer,
        library_root=root,
        allow_unmanaged=True,
    )
    queue = ReconciliationQueue(
        library_root=root,
        persistence_store=queue_store,
    )
    manifest_store.create(
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
    task = queue.enqueue_or_merge(
        path=root,
        reason="test succeeded recovery outbox",
        operation_id=operation_id,
    )
    record = manifest_store.get(operation_id, include_items=False)
    assert record is not None
    assert manifest_store.bind_recovery_task(record, task.task_id)
    claimed = queue.claim_next(lease_seconds=30.0)
    assert claimed is not None
    assert claimed.task_id == task.task_id
    assert claimed.lease_token is not None
    completed = queue.mark_succeeded(
        claimed.task_id,
        expected_attempts=claimed.attempts,
        lease_token=claimed.lease_token,
    )
    assert completed.state.value == "succeeded"
    initializer.close()
    return task.task_id


def _seed_terminal_merged_manifest_outbox(
    database_path: Path,
    root: Path,
    operation_ids: tuple[str, str],
) -> str:
    """Create one terminal task whose durable transition covers two manifests."""
    from AssetsManager.application.import_manifest_store import ImportManifestStore
    from AssetsManager.application.reconciliation_queue import ReconciliationQueue
    from AssetsManager.application.reconciliation_queue_store import (
        SQLiteReconciliationQueueStore,
    )
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    destination = root / "dest"
    initializer = sqlite3.connect(str(database_path), check_same_thread=False)
    initializer.executescript(database._SCHEMA)
    initializer.commit()
    migrate(initializer)
    manifest_store = ImportManifestStore(initializer, root)
    queue_store = SQLiteReconciliationQueueStore(
        connection=initializer,
        library_root=root,
        allow_unmanaged=True,
    )
    queue = ReconciliationQueue(
        library_root=root,
        persistence_store=queue_store,
    )
    for operation_id in operation_ids:
        manifest_store.create(
            operation_id=operation_id,
            destination=destination,
            payload={
                "payload_version": 1,
                "destination": str(destination.resolve()),
                "items": [
                    {
                        "source": str(
                            (database_path.parent / f"{operation_id}.txt").resolve()
                        ),
                        "target": str((destination / f"{operation_id}.txt").resolve()),
                        "state": "pending",
                    }
                ],
            },
            state="running",
        )
    task = queue.enqueue_or_merge(
        path=root,
        reason="test terminal merged recovery outbox",
        operation_id=operation_ids[0],
    )
    first_record = manifest_store.get(operation_ids[0], include_items=False)
    assert first_record is not None
    assert manifest_store.bind_recovery_task(first_record, task.task_id)
    merged = queue.enqueue_or_merge(
        path=root,
        reason="test terminal merged recovery outbox",
        operation_id=operation_ids[1],
    )
    assert merged.task_id == task.task_id
    second_record = manifest_store.get(operation_ids[1], include_items=False)
    assert second_record is not None
    assert manifest_store.bind_recovery_task(second_record, task.task_id)
    claimed = queue.claim_next(lease_seconds=30.0)
    assert claimed is not None
    assert claimed.task_id == task.task_id
    assert claimed.lease_token is not None
    terminal = queue.mark_terminal(
        claimed.task_id,
        error_type="TestTerminal",
        error="test terminal merged recovery outbox",
        expected_attempts=claimed.attempts,
        lease_token=claimed.lease_token,
    )
    assert terminal.state.value == "terminal"
    assert terminal.operation_ids == operation_ids
    initializer.close()
    return task.task_id


def _seed_evicted_merged_manifest_outbox(
    database_path: Path,
    root: Path,
    operation_ids: tuple[str, str],
) -> str:
    """Create a finished merged task and evict it through the durable queue."""
    from AssetsManager.application.import_manifest_store import ImportManifestStore
    from AssetsManager.application.reconciliation_queue import ReconciliationQueue
    from AssetsManager.application.reconciliation_queue_store import (
        SQLiteReconciliationQueueStore,
    )
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    destination = root / "dest"
    initializer = sqlite3.connect(str(database_path), check_same_thread=False)
    initializer.executescript(database._SCHEMA)
    initializer.commit()
    migrate(initializer)
    manifest_store = ImportManifestStore(initializer, root)
    queue_store = SQLiteReconciliationQueueStore(
        connection=initializer,
        library_root=root,
        allow_unmanaged=True,
    )
    queue = ReconciliationQueue(
        library_root=root,
        max_tasks=1,
        persistence_store=queue_store,
    )
    for operation_id in operation_ids:
        manifest_store.create(
            operation_id=operation_id,
            destination=destination,
            payload={
                "payload_version": 1,
                "destination": str(destination.resolve()),
                "items": [
                    {
                        "source": str(
                            (database_path.parent / f"{operation_id}.txt").resolve()
                        ),
                        "target": str((destination / f"{operation_id}.txt").resolve()),
                        "state": "pending",
                    }
                ],
            },
            state="running",
        )
    task = queue.enqueue_or_merge(
        path=root,
        reason="test evicted merged recovery outbox",
        operation_id=operation_ids[0],
    )
    first_record = manifest_store.get(operation_ids[0], include_items=False)
    assert first_record is not None
    assert manifest_store.bind_recovery_task(first_record, task.task_id)
    merged = queue.enqueue_or_merge(
        path=root,
        reason="test evicted merged recovery outbox",
        operation_id=operation_ids[1],
    )
    assert merged.task_id == task.task_id
    second_record = manifest_store.get(operation_ids[1], include_items=False)
    assert second_record is not None
    assert manifest_store.bind_recovery_task(second_record, task.task_id)
    claimed = queue.claim_next(lease_seconds=30.0)
    assert claimed is not None
    assert claimed.task_id == task.task_id
    assert claimed.lease_token is not None
    terminal = queue.mark_terminal(
        claimed.task_id,
        error_type="TestTerminal",
        error="test evicted merged recovery outbox",
        expected_attempts=claimed.attempts,
        lease_token=claimed.lease_token,
    )
    assert terminal.state.value == "terminal"
    replacement = queue.enqueue_or_merge(
        path=root / "replacement",
        reason="test capacity eviction",
    )
    assert replacement.task_id != task.task_id
    assert queue.get(task.task_id) is None
    initializer.close()
    return task.task_id


def _open_parent_view(database_path: Path, root: Path):
    from AssetsManager.application.import_manifest_store import (
        ImportManifestRecoveryService,
        ImportManifestStore,
    )
    from AssetsManager.application.reconciliation_queue import ReconciliationQueue
    from AssetsManager.application.reconciliation_queue_store import (
        SQLiteReconciliationQueueStore,
    )

    connection = sqlite3.connect(
        str(database_path), check_same_thread=False, timeout=10.0
    )
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


def _wait_outbox_lease_expiry(
    database_path: Path,
    event_id: int,
    *,
    timeout_seconds: float = 10.0,
) -> float:
    """Wait until a leased outbox row is expired while its owner is alive."""
    connection = sqlite3.connect(
        str(database_path), check_same_thread=False, timeout=10.0
    )
    try:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            row = connection.execute(
                "SELECT delivery_attempts, delivery_lease_expires_at "
                "FROM reconciliation_transition_outbox WHERE id=?",
                (event_id,),
            ).fetchone()
            if row is None:
                raise AssertionError(f"outbox event disappeared while waiting: {event_id}")
            if row[0] == 1 and row[1] is not None:
                expires_at = float(row[1])
                if expires_at <= time.time():
                    return expires_at
            time.sleep(0.03)
    finally:
        connection.close()
    raise AssertionError(f"outbox event lease did not expire: {event_id}")


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
            assert final["state"] == "recovery_pending"
            assert final["payload"]["recovery_phase"] == "enqueued"
            assert final["attempts"] == 0
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
            assert final["state"] == "recovery_pending"
            assert final["payload"]["recovery_phase"] == "enqueued"
            assert final["attempts"] == 0
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


def test_crash_after_manifest_cas_replays_succeeded_outbox_without_regression(tmp_path):
    """A crashed pre-ACK delivery must replay as stale without re-CASing state."""
    root = tmp_path / "library"
    root.mkdir()
    database_path = tmp_path / "checkpoint-outbox-ack.sqlite3"
    operation_id = "outbox-ack-kill-checkpoint"
    task_id = _seed_succeeded_manifest_outbox(database_path, root, operation_id)

    status = tmp_path / "child.json"
    child = _start_outbox_ack_checkpoint_child(
        database_path,
        root,
        status,
        operation_id,
    )
    try:
        checkpoint = _wait_checkpoint_with_diagnostics(status, child)
        assert checkpoint["stage"] == "after_manifest_cas_before_outbox_ack"
        assert isinstance(checkpoint["event_id"], int)
        assert checkpoint["manifest_generation"] > 0

        _stop(child)
        child = None

        connection, store, service = _open_parent_view(database_path, root)
        try:
            before_replay = store.get(operation_id, include_items=False)
            assert before_replay is not None
            assert before_replay["state"] == "completed"
            assert before_replay["generation"] == checkpoint["manifest_generation"]
            assert before_replay["payload"]["recovery_task_id"] == task_id
            assert before_replay["payload"]["recovery_phase"] == "reconciled"

            event_id = checkpoint["event_id"]
            leased = connection.execute(
                "SELECT delivery_attempts, delivered_at, delivery_token "
                "FROM reconciliation_transition_outbox WHERE id=?",
                (event_id,),
            ).fetchone()
            assert leased is not None
            assert leased[0] == 1
            assert leased[1] is None
            assert leased[2] is not None

            deadline = time.monotonic() + 20.0
            delivered = 0
            while time.monotonic() < deadline:
                delivered += service.reconciliation_queue.drain_transition_outbox(
                    lease_seconds=1.0
                )
                replayed = connection.execute(
                    "SELECT delivery_attempts, delivered_at, delivery_token "
                    "FROM reconciliation_transition_outbox WHERE id=?",
                    (event_id,),
                ).fetchone()
                if replayed is not None and replayed[1] is not None:
                    break
                time.sleep(0.05)
            else:
                raise AssertionError("succeeded outbox event did not replay after lease expiry")

            assert delivered == 1
            assert replayed[0] == 2
            assert replayed[2] is None
            after_replay = store.get(operation_id, include_items=False)
            assert after_replay is not None
            assert after_replay["state"] == "completed"
            assert after_replay["generation"] == checkpoint["manifest_generation"]
            assert after_replay["attempts"] == before_replay["attempts"]
        finally:
            connection.close()
    finally:
        _stop(child)


def test_long_callback_age_allows_cross_process_outbox_takeover(tmp_path):
    """A stuck callback stops renewing, then another process can complete it."""
    root = tmp_path / "library"
    root.mkdir()
    database_path = tmp_path / "checkpoint-long-callback.sqlite3"
    operation_id = "outbox-long-callback"
    task_id = _seed_succeeded_manifest_outbox(database_path, root, operation_id)

    status = tmp_path / "child.json"
    child = _start_outbox_ack_checkpoint_child(
        database_path,
        root,
        status,
        operation_id,
        mode="long_callback",
        lease_seconds="0.2",
        callback_max_age="0.5",
    )
    try:
        checkpoint = _wait_checkpoint_with_diagnostics(status, child)
        assert checkpoint["stage"] == "inside_long_callback"
        event_id = checkpoint["event_id"]
        assert isinstance(event_id, int)
        assert float(checkpoint["delivery_lease_expires_at"]) > time.time()
        assert isinstance(checkpoint["manifest_generation"], int)

        # The child remains alive and blocked in its callback while heartbeat
        # reaches the 0.5s age budget and stops renewing the 0.2s lease.
        expired_at = _wait_outbox_lease_expiry(database_path, event_id)
        assert expired_at <= time.time()
        _stop(child)
        child = None

        connection, store, service = _open_parent_view(database_path, root)
        try:
            deadline = time.monotonic() + 20.0
            while time.monotonic() < deadline:
                row = connection.execute(
                    "SELECT delivery_attempts, delivered_at, delivery_token "
                    "FROM reconciliation_transition_outbox WHERE id=?",
                    (event_id,),
                ).fetchone()
                if row is not None and row[1] is not None:
                    break
                service.reconciliation_queue.drain_transition_outbox(limit=1)
                time.sleep(0.05)
            else:
                raise AssertionError(
                    "long callback outbox event did not complete after takeover"
                )

            assert row is not None
            assert row[0] == 2
            assert row[2] is None
            completed = store.get(operation_id, include_items=False)
            assert completed is not None
            assert completed["state"] == "completed"
            assert completed["payload"]["recovery_task_id"] == task_id
            assert completed["payload"]["recovery_phase"] == "reconciled"
            assert completed["generation"] == checkpoint["manifest_generation"] + 1
            assert completed["attempts"] == 1
        finally:
            connection.close()
    finally:
        _stop(child)


def test_crash_after_first_terminal_manifest_cas_replays_merged_task(tmp_path):
    """Replay must finish a merged terminal event without regressing its first CAS."""
    root = tmp_path / "library"
    root.mkdir()
    database_path = tmp_path / "checkpoint-terminal-merged.sqlite3"
    operation_ids = ("terminal-merged-first", "terminal-merged-second")
    task_id = _seed_terminal_merged_manifest_outbox(
        database_path,
        root,
        operation_ids,
    )

    status = tmp_path / "child.json"
    child = _start_outbox_ack_checkpoint_child(
        database_path,
        root,
        status,
        operation_ids[0],
        mode="after_first_terminal_manifest_cas",
    )
    try:
        checkpoint = _wait_checkpoint_with_diagnostics(status, child)
        assert checkpoint["stage"] == "after_first_terminal_manifest_cas"
        assert isinstance(checkpoint["event_id"], int)

        _stop(child)
        child = None

        connection, store, service = _open_parent_view(database_path, root)
        try:
            first_before_replay = store.get(operation_ids[0], include_items=False)
            second_before_replay = store.get(operation_ids[1], include_items=False)
            assert first_before_replay is not None
            assert second_before_replay is not None
            assert first_before_replay["state"] == "recovery_pending"
            assert first_before_replay["payload"]["recovery_task_id"] == task_id
            assert first_before_replay["payload"]["recovery_phase"] == "dead_letter"
            assert first_before_replay["generation"] == checkpoint["manifest_generation"]
            assert second_before_replay["state"] == "recovery_pending"
            assert second_before_replay["payload"]["recovery_task_id"] == task_id
            assert second_before_replay["payload"]["recovery_phase"] == "running"

            event_id = checkpoint["event_id"]
            leased = connection.execute(
                "SELECT delivery_attempts, delivered_at, delivery_token "
                "FROM reconciliation_transition_outbox WHERE id=?",
                (event_id,),
            ).fetchone()
            assert leased is not None
            assert leased[0] == 1
            assert leased[1] is None
            assert leased[2] is not None

            deadline = time.monotonic() + 20.0
            delivered = 0
            while time.monotonic() < deadline:
                delivered += service.reconciliation_queue.drain_transition_outbox(
                    lease_seconds=1.0
                )
                replayed = connection.execute(
                    "SELECT delivery_attempts, delivered_at, delivery_token "
                    "FROM reconciliation_transition_outbox WHERE id=?",
                    (event_id,),
                ).fetchone()
                if replayed is not None and replayed[1] is not None:
                    break
                time.sleep(0.05)
            else:
                raise AssertionError("terminal outbox event did not replay after lease expiry")

            assert delivered == 1
            assert replayed[0] == 2
            assert replayed[2] is None
            first_after_replay = store.get(operation_ids[0], include_items=False)
            second_after_replay = store.get(operation_ids[1], include_items=False)
            assert first_after_replay is not None
            assert second_after_replay is not None
            assert first_after_replay["payload"]["recovery_phase"] == "dead_letter"
            assert (
                first_after_replay["generation"]
                == first_before_replay["generation"]
            )
            assert first_after_replay["attempts"] == first_before_replay["attempts"]
            assert second_after_replay["payload"]["recovery_phase"] == "dead_letter"
            assert (
                second_after_replay["generation"]
                == second_before_replay["generation"] + 1
            )
            assert second_after_replay["attempts"] == second_before_replay["attempts"] + 1
        finally:
            connection.close()
    finally:
        _stop(child)


def test_crash_after_first_evicted_manifest_cas_replays_merged_task(tmp_path):
    """Replay must finish a merged eviction without restoring stale bindings."""
    root = tmp_path / "library"
    root.mkdir()
    database_path = tmp_path / "checkpoint-evicted-merged.sqlite3"
    operation_ids = ("evicted-merged-first", "evicted-merged-second")
    task_id = _seed_evicted_merged_manifest_outbox(
        database_path,
        root,
        operation_ids,
    )

    status = tmp_path / "child.json"
    child = _start_outbox_ack_checkpoint_child(
        database_path,
        root,
        status,
        operation_ids[0],
        mode="after_first_evicted_manifest_cas",
    )
    try:
        checkpoint = _wait_checkpoint_with_diagnostics(status, child)
        assert checkpoint["stage"] == "after_first_evicted_manifest_cas"
        assert isinstance(checkpoint["event_id"], int)

        _stop(child)
        child = None

        connection, store, service = _open_parent_view(database_path, root)
        try:
            first_before_replay = store.get(operation_ids[0], include_items=False)
            second_before_replay = store.get(operation_ids[1], include_items=False)
            assert first_before_replay is not None
            assert second_before_replay is not None
            assert first_before_replay["state"] == "recovery_pending"
            assert first_before_replay["payload"].get("recovery_task_id") is None
            assert first_before_replay["payload"]["recovery_phase"] == "pending"
            assert first_before_replay["payload"]["recovery_evicted_task_id"] == task_id
            assert first_before_replay["generation"] == checkpoint["manifest_generation"]
            assert second_before_replay["state"] == "recovery_pending"
            assert second_before_replay["payload"]["recovery_task_id"] == task_id
            assert second_before_replay["payload"]["recovery_phase"] == "dead_letter"

            event_id = checkpoint["event_id"]
            leased = connection.execute(
                "SELECT delivery_attempts, delivered_at, delivery_token "
                "FROM reconciliation_transition_outbox WHERE id=?",
                (event_id,),
            ).fetchone()
            assert leased is not None
            assert leased[0] == 1
            assert leased[1] is None
            assert leased[2] is not None

            deadline = time.monotonic() + 20.0
            delivered = 0
            while time.monotonic() < deadline:
                delivered += service.reconciliation_queue.drain_transition_outbox(
                    limit=1,
                    lease_seconds=1.0,
                )
                replayed = connection.execute(
                    "SELECT delivery_attempts, delivered_at, delivery_token "
                    "FROM reconciliation_transition_outbox WHERE id=?",
                    (event_id,),
                ).fetchone()
                if replayed is not None and replayed[1] is not None:
                    break
                time.sleep(0.05)
            else:
                raise AssertionError("evicted outbox event did not replay after lease expiry")

            assert delivered == 1
            assert replayed[0] == 2
            assert replayed[2] is None
            first_after_replay = store.get(operation_ids[0], include_items=False)
            second_after_replay = store.get(operation_ids[1], include_items=False)
            assert first_after_replay is not None
            assert second_after_replay is not None
            assert first_after_replay["payload"].get("recovery_task_id") is None
            assert first_after_replay["payload"]["recovery_phase"] == "pending"
            assert (
                first_after_replay["generation"]
                == first_before_replay["generation"]
            )
            assert first_after_replay["attempts"] == first_before_replay["attempts"]
            assert second_after_replay["payload"].get("recovery_task_id") is None
            assert second_after_replay["payload"]["recovery_phase"] == "pending"
            assert second_after_replay["payload"]["recovery_evicted_task_id"] == task_id
            assert (
                second_after_replay["generation"]
                == second_before_replay["generation"] + 1
            )
            assert second_after_replay["attempts"] == second_before_replay["attempts"] + 1
        finally:
            connection.close()
    finally:
        _stop(child)
