import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest

import AssetsManager.application.import_manifest_store as manifest_store_module
from AssetsManager.application.import_manifest_store import (
    ImportManifestRecoveryService,
    ImportManifestStore,
)
from AssetsManager.application.reconciliation_queue import (
    ReconciliationTransitionDisposition,
)
from AssetsManager.core.db_migrations import migrate


def _store(tmp_path):
    from AssetsManager.core import database

    root = tmp_path / "library"
    root.mkdir()
    conn = sqlite3.connect(":memory:")
    conn.executescript(database._SCHEMA)
    conn.commit()
    migrate(conn)
    return root, conn, ImportManifestStore(conn, root)


def _payload(root, destination, *, state="pending"):
    target = destination / "file.txt"
    return {
        "payload_version": 1,
        "destination": str(destination.resolve()),
        "items": [
            {
                "source": str((root.parent / "source.txt").resolve()),
                "target": str(target.resolve()),
                "state": state,
            }
        ],
    }


def test_manifest_round_trip_and_item_cas(tmp_path):
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    store.create(
        operation_id="import-test",
        destination=destination,
        payload=_payload(root, destination),
    )
    record = store.get("import-test")
    assert record is not None
    assert record["state"] == "prepared"
    assert store.update_item("import-test", item_index=0, state="copied")
    updated = store.get("import-test")
    assert updated["payload"]["items"][0]["state"] == "copied"
    assert store.finish("import-test", state="completed")
    assert store.get("import-test")["state"] == "completed"
    conn.close()


def test_manifest_rejects_escape_and_oversized_items(tmp_path):
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    payload = _payload(root, destination)
    payload["items"][0]["target"] = str((tmp_path / "outside.txt").resolve())
    with pytest.raises(ValueError, match="escapes"):
        store.create(operation_id="escape", destination=destination, payload=payload)
    payload = _payload(root, destination)
    payload["items"] = [dict(payload["items"][0]) for _ in range(10_001)]
    with pytest.raises(ValueError, match="items"):
        store.create(operation_id="too-many", destination=destination, payload=payload)
    conn.close()


def test_terminal_manifest_cannot_be_reactivated(tmp_path):
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    store.create(
        operation_id="terminal",
        destination=destination,
        payload=_payload(root, destination),
        state="running",
    )
    assert store.finish("terminal", state="completed")
    assert not store.update_item("terminal", item_index=0, state="copied")
    assert not store.finish("terminal", state="recovery_pending")
    assert store.get("terminal")["state"] == "completed"
    conn.close()


def test_recovery_enqueues_once_and_does_not_publish_import_event(tmp_path):
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    store.create(
        operation_id="recover-me",
        destination=destination,
        payload=_payload(root, destination),
        state="running",
    )

    class Queue:
        def __init__(self):
            self.calls = []

        def enqueue_or_merge(self, **kwargs):
            self.calls.append(kwargs)

    queue = Queue()
    recovery = ImportManifestRecoveryService(store, queue)
    assert recovery.recover() == ("recover-me",)
    assert queue.calls[0]["reason"] == "import_manifest_recovery"
    assert queue.calls[0]["operation_id"] == "recover-me"
    assert store.get("recover-me")["state"] == "completed"
    assert recovery.recover() == ()
    assert len(queue.calls) == 1
    conn.close()


def test_recovery_stays_pending_until_matching_queue_ack(tmp_path):
    """Queue acceptance is not a manifest completion proof."""
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    store.create(
        operation_id="ack-gated",
        destination=destination,
        payload=_payload(root, destination),
        state="running",
    )

    class Queue:
        def __init__(self):
            self.tasks = []

        def enqueue_or_merge(self, **kwargs):
            task = SimpleNamespace(
                task_id="recon-ack-gated",
                state="pending",
                operation_ids=(kwargs["operation_id"],),
            )
            self.tasks.append(task)
            return task

        def snapshot(self):
            return tuple(self.tasks)

    queue = Queue()
    recovery = ImportManifestRecoveryService(store, queue)
    assert recovery.recover() == ("ack-gated",)
    pending = store.get("ack-gated")
    assert pending["state"] == "recovery_pending"
    assert pending["payload"]["recovery_phase"] == "enqueued"
    assert pending["payload"]["recovery_task_id"] == "recon-ack-gated"
    assert not recovery.acknowledge_task(
        SimpleNamespace(
            task_id="wrong-task", state="succeeded", operation_ids=("ack-gated",)
        )
    )
    assert store.get("ack-gated")["state"] == "recovery_pending"

    queue.tasks[0].state = "succeeded"
    assert recovery.acknowledge_task(queue.tasks[0]) == ("ack-gated",)
    completed = store.get("ack-gated")
    assert completed["state"] == "completed"
    assert completed["payload"]["recovery_phase"] == "reconciled"
    assert recovery.acknowledge_task(queue.tasks[0]) == ("ack-gated",)
    conn.close()


def test_recovery_success_transition_is_idempotent_after_ack(tmp_path):
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    store.create(
        operation_id="transition-success",
        destination=destination,
        payload=_payload(root, destination),
        state="running",
    )
    record = store.get("transition-success", include_items=False)
    assert record is not None
    assert store.bind_recovery_task(record, "recon-transition-success")
    assert store.record_recovery_task_transition(
        "transition-success",
        "recon-transition-success",
        "succeeded",
        task_attempts=1,
    )
    # A queue listener and the startup compensator may both observe the same
    # durable success.  The second event must remain an idempotent success.
    assert store.record_recovery_task_transition(
        "transition-success",
        "recon-transition-success",
        "succeeded",
        task_attempts=1,
    )
    completed = store.get("transition-success")
    assert completed["state"] == "completed"
    assert completed["payload"]["recovery_task_id"] == "recon-transition-success"
    conn.close()


def test_transition_returns_retry_when_manifest_write_cannot_commit(tmp_path, monkeypatch):
    """A durable consumer must not convert a DB error into an outbox ACK."""
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    operation_id = "transition-write-retry"
    task_id = "recon-transition-write-retry"
    store.create(
        operation_id=operation_id,
        destination=destination,
        payload=_payload(root, destination),
        state="running",
    )
    record = store.get(operation_id, include_items=False)
    assert record is not None
    assert store.bind_recovery_task(record, task_id)

    class Queue:
        pass

    recovery = ImportManifestRecoveryService(store, Queue())
    task = SimpleNamespace(
        task_id=task_id,
        library_root=str(root),
        path=str(root),
        kind=SimpleNamespace(value="asset_index_root_rescan"),
        state="succeeded",
        operation_ids=(operation_id,),
        attempts=1,
        last_error_type=None,
        last_error=None,
    )
    transition = SimpleNamespace(
        previous=None,
        current=task,
        operation_ids=(operation_id,),
    )

    def unavailable(*_args, **_kwargs):
        raise sqlite3.OperationalError("manifest database unavailable")

    monkeypatch.setattr(store, "record_recovery_task_transition", unavailable)
    assert (
        recovery.handle_task_transition(transition)
        is ReconciliationTransitionDisposition.RETRY
    )
    assert store.get(operation_id)["state"] == "recovery_pending"
    conn.close()


def test_transition_envelope_cannot_expand_task_operation_scope(tmp_path):
    """Only ids present on the task snapshots may be acknowledged."""
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    for operation_id in ("scope-op-1", "scope-op-2", "scope-op-3"):
        store.create(
            operation_id=operation_id,
            destination=destination,
            payload=_payload(root, destination),
            state="running",
        )
        record = store.get(operation_id, include_items=False)
        assert record is not None
        assert store.bind_recovery_task(record, "recon-scope")

    class Queue:
        pass

    recovery = ImportManifestRecoveryService(store, Queue())
    task = SimpleNamespace(
        task_id="recon-scope",
        library_root=str(root),
        path=str(root),
        kind=SimpleNamespace(value="asset_index_root_rescan"),
        state="succeeded",
        operation_ids=("scope-op-1", "scope-op-2"),
        attempts=1,
        last_error_type=None,
        last_error=None,
    )
    transition = SimpleNamespace(
        previous=None,
        current=task,
        # This id is deliberately not present on the durable task snapshot.
        operation_ids=("scope-op-1", "scope-op-2", "scope-op-3"),
    )

    assert (
        recovery.handle_task_transition(transition)
        is ReconciliationTransitionDisposition.APPLIED
    )
    assert store.get("scope-op-1")["state"] == "completed"
    assert store.get("scope-op-2")["state"] == "completed"
    # Binding is itself a visible recovery transition; the forged id must not
    # advance this unrelated manifest beyond its pending state.
    assert store.get("scope-op-3")["state"] == "recovery_pending"
    conn.close()


def test_stale_transition_attempt_is_ignored(tmp_path):
    """A delayed lower-attempt event cannot regress a newer phase."""
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    store.create(
        operation_id="stale-attempt",
        destination=destination,
        payload=_payload(root, destination),
        state="running",
    )
    record = store.get("stale-attempt", include_items=False)
    assert record is not None
    assert store.bind_recovery_task(record, "recon-stale")
    assert store.record_recovery_task_transition(
        "stale-attempt", "recon-stale", "running", task_attempts=2
    )
    assert store.record_recovery_task_transition(
        "stale-attempt", "recon-stale", "retryable", task_attempts=1
    )
    current = store.get("stale-attempt")
    assert current["payload"]["recovery_phase"] == "running"
    assert current["payload"]["recovery_task_attempts"] == 2
    conn.close()


def test_terminal_transition_dead_letters_without_restart_reenqueue(tmp_path):
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    store.create(
        operation_id="transition-terminal",
        destination=destination,
        payload=_payload(root, destination),
        state="running",
    )
    record = store.get("transition-terminal", include_items=False)
    assert record is not None
    task_id = "recon-transition-terminal"
    assert store.bind_recovery_task(record, task_id)

    class Queue:
        def __init__(self):
            self.tasks = [
                SimpleNamespace(
                    task_id=task_id,
                    library_root=str(root),
                    path=str(root),
                    kind=SimpleNamespace(value="asset_index_root_rescan"),
                    state="terminal",
                    operation_ids=("transition-terminal",),
                    attempts=5,
                    last_error_type="PermanentError",
                    last_error="cannot repair",
                )
            ]
            self.enqueue_calls = 0

        def refresh(self):
            return True

        def snapshot(self):
            return tuple(self.tasks)

        def enqueue_or_merge(self, **kwargs):
            self.enqueue_calls += 1
            pytest.fail("dead-lettered recovery must wait for explicit retry")

    queue = Queue()
    recovery = ImportManifestRecoveryService(store, queue)
    transition = SimpleNamespace(
        previous=None,
        current=queue.tasks[0],
        operation_ids=("transition-terminal",),
    )
    assert (
        recovery.handle_task_transition(transition)
        is ReconciliationTransitionDisposition.APPLIED
    )
    dead = store.get("transition-terminal")
    assert dead["state"] == "recovery_pending"
    assert dead["payload"]["recovery_phase"] == "dead_letter"
    assert recovery.recover() == ()
    assert queue.enqueue_calls == 0
    conn.close()


@pytest.mark.parametrize(
    ("terminal_state", "expected_phase"),
    (("terminal", "dead_letter"), ("cancelled", "cancelled")),
)
def test_explicit_recovery_retry_supersedes_terminal_task_and_ignores_old_events(
    tmp_path, terminal_state, expected_phase
):
    """A manual retry gives the manifest a new task ownership generation."""
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    operation_id = f"retry-{terminal_state}"
    old_task_id = f"recon-old-{terminal_state}"
    new_task_id = f"recon-new-{terminal_state}"
    store.create(
        operation_id=operation_id,
        destination=destination,
        payload=_payload(root, destination),
        state="running",
    )
    record = store.get(operation_id, include_items=False)
    assert record is not None
    assert store.bind_recovery_task(record, old_task_id)
    assert store.record_recovery_task_transition(
        operation_id,
        old_task_id,
        terminal_state,
        task_attempts=3,
        error_type="PermanentError",
        error="repair rejected",
    )
    dead = store.get(operation_id)
    assert dead is not None
    assert dead["payload"]["recovery_phase"] == expected_phase

    def task(task_id, state, attempts):
        return SimpleNamespace(
            task_id=task_id,
            library_root=str(root),
            path=str(root),
            kind=SimpleNamespace(value="asset_index_root_rescan"),
            state=state,
            operation_ids=(operation_id,),
            attempts=attempts,
            last_error_type="PermanentError" if state != "succeeded" else None,
            last_error="repair rejected" if state != "succeeded" else None,
        )

    class Queue:
        def __init__(self):
            self.tasks = [task(old_task_id, terminal_state, 3)]
            self.enqueue_calls = 0

        def refresh(self):
            return True

        def snapshot(self):
            return tuple(self.tasks)

        def enqueue_or_merge(self, **kwargs):
            self.enqueue_calls += 1
            assert kwargs["operation_id"] == operation_id
            replacement = task(new_task_id, "pending", 0)
            self.tasks.append(replacement)
            return replacement

    queue = Queue()
    recovery = ImportManifestRecoveryService(store, queue)
    assert recovery.retry_dead_letter(operation_id)
    assert not recovery.retry_dead_letter(operation_id)
    assert queue.enqueue_calls == 1
    pending = store.get(operation_id)
    assert pending is not None
    assert pending["state"] == "recovery_pending"
    assert pending["payload"]["recovery_phase"] == "enqueued"
    assert pending["payload"]["recovery_task_id"] == new_task_id
    assert pending["payload"]["recovery_retry_count"] == 1
    assert pending["payload"]["recovery_retry_superseded_task_id"] == old_task_id
    assert old_task_id in pending["payload"]["recovery_retired_task_ids"]

    # A listener retry can observe the old terminal event after the replacement
    # has been bound.  It is an accepted no-op, never a second dead letter.
    old_transition = SimpleNamespace(
        previous=None,
        current=queue.tasks[0],
        operation_ids=(operation_id,),
    )
    assert (
        recovery.handle_task_transition(old_transition)
        is ReconciliationTransitionDisposition.STALE
    )
    after_old_event = store.get(operation_id)
    assert after_old_event is not None
    assert after_old_event["payload"]["recovery_task_id"] == new_task_id
    assert after_old_event["payload"]["recovery_phase"] == "enqueued"

    queue.tasks[1] = task(new_task_id, "succeeded", 1)
    new_transition = SimpleNamespace(
        previous=None,
        current=queue.tasks[1],
        operation_ids=(operation_id,),
    )
    assert (
        recovery.handle_task_transition(new_transition)
        is ReconciliationTransitionDisposition.APPLIED
    )
    assert store.get(operation_id)["state"] == "completed"
    # The delayed old event is still an idempotent no-op after the new ACK.
    assert (
        recovery.handle_task_transition(old_transition)
        is ReconciliationTransitionDisposition.STALE
    )
    assert store.get(operation_id)["state"] == "completed"
    conn.close()


def test_explicit_recovery_retry_keeps_pending_intent_when_enqueue_fails(tmp_path):
    """Scheduling failure is diagnosable and does not revoke the retry CAS."""
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    store.create(
        operation_id="retry-enqueue-failure",
        destination=destination,
        payload=_payload(root, destination),
        state="running",
    )
    record = store.get("retry-enqueue-failure", include_items=False)
    assert record is not None
    assert store.bind_recovery_task(record, "recon-old-failure")
    assert store.record_recovery_task_transition(
        "retry-enqueue-failure", "recon-old-failure", "terminal"
    )

    class Queue:
        def refresh(self):
            return True

        def snapshot(self):
            return ()

        def enqueue_or_merge(self, **kwargs):
            raise RuntimeError("queue unavailable")

    recovery = ImportManifestRecoveryService(store, Queue())
    assert recovery.retry_dead_letter("retry-enqueue-failure")
    pending = store.get("retry-enqueue-failure")
    assert pending is not None
    assert pending["state"] == "recovery_pending"
    assert pending["payload"]["recovery_phase"] == "pending"
    assert pending["payload"].get("recovery_task_id") is None
    assert pending["payload"]["recovery_retry_count"] == 1
    assert pending["last_error_type"] == "RuntimeError"
    assert pending["last_error"] == "queue unavailable"
    conn.close()


def test_explicit_recovery_retry_reconciles_lost_terminal_callback(tmp_path):
    """The operator need not wait for a listener/restart to expose a retry."""
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    operation_id = "retry-lost-callback"
    old_task_id = "recon-lost-callback"
    store.create(
        operation_id=operation_id,
        destination=destination,
        payload=_payload(root, destination),
        state="running",
    )
    record = store.get(operation_id, include_items=False)
    assert record is not None
    assert store.bind_recovery_task(record, old_task_id)

    def task(task_id, state):
        return SimpleNamespace(
            task_id=task_id,
            library_root=str(root),
            path=str(root),
            kind=SimpleNamespace(value="asset_index_root_rescan"),
            state=state,
            operation_ids=(operation_id,),
            attempts=2,
            last_error_type="PermanentError" if state == "terminal" else None,
            last_error="lost listener" if state == "terminal" else None,
        )

    class Queue:
        def __init__(self):
            self.tasks = [task(old_task_id, "terminal")]
            self.enqueue_calls = 0

        def refresh(self):
            return True

        def snapshot(self):
            return tuple(self.tasks)

        def enqueue_or_merge(self, **kwargs):
            self.enqueue_calls += 1
            replacement = task("recon-after-lost-callback", "pending")
            self.tasks.append(replacement)
            return replacement

    queue = Queue()
    recovery = ImportManifestRecoveryService(store, queue)
    assert recovery.retry_dead_letter(operation_id)
    assert queue.enqueue_calls == 1
    pending = store.get(operation_id)
    assert pending is not None
    assert pending["payload"]["recovery_phase"] == "enqueued"
    assert pending["payload"]["recovery_task_id"] == "recon-after-lost-callback"
    assert old_task_id in pending["payload"]["recovery_retired_task_ids"]
    conn.close()


def test_explicit_recovery_retry_cas_accepts_only_one_concurrent_request(tmp_path):
    """Two operators/processes cannot schedule two replacement tasks."""
    from AssetsManager.core import database

    root = tmp_path / "library"
    root.mkdir()
    destination = root / "dest"
    db_path = tmp_path / "retry-race.sqlite3"
    initializer = sqlite3.connect(str(db_path), check_same_thread=False)
    initializer.executescript(database._SCHEMA)
    initializer.commit()
    migrate(initializer)
    initializer.close()
    first_connection = sqlite3.connect(str(db_path), check_same_thread=False, timeout=5.0)
    second_connection = sqlite3.connect(str(db_path), check_same_thread=False, timeout=5.0)
    try:
        first_store = ImportManifestStore(first_connection, root)
        second_store = ImportManifestStore(second_connection, root)
        first_store.create(
            operation_id="retry-race",
            destination=destination,
            payload=_payload(root, destination),
            state="running",
        )
        record = first_store.get("retry-race", include_items=False)
        assert record is not None
        assert first_store.bind_recovery_task(record, "recon-race-old")
        assert first_store.record_recovery_task_transition(
            "retry-race", "recon-race-old", "terminal"
        )

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(
                executor.map(
                    lambda store: store.request_recovery_retry("retry-race"),
                    (first_store, second_store),
                )
            )
        assert outcomes.count(True) == 1
        assert outcomes.count(False) == 1
        current = first_store.get("retry-race")
        assert current is not None
        assert current["payload"]["recovery_phase"] == "pending"
        assert current["payload"]["recovery_retry_count"] == 1
        assert current["payload"]["recovery_retired_task_ids"] == ["recon-race-old"]
    finally:
        first_connection.close()
        second_connection.close()


def test_recovery_refreshes_queue_before_reusing_bound_task(tmp_path):
    """A stale queue instance must see a durable task before enqueueing."""
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    payload = _payload(root, destination)
    payload["recovery_task_id"] = "recon-refresh-me"
    payload["recovery_phase"] = "enqueued"
    store.create(
        operation_id="refresh-me",
        destination=destination,
        payload=payload,
        state="recovery_pending",
    )

    class Queue:
        def __init__(self):
            self.tasks = []
            self.refresh_calls = 0

        def refresh(self):
            self.refresh_calls += 1
            if not self.tasks:
                self.tasks.append(
                    SimpleNamespace(
                        task_id="recon-refresh-me",
                        state="pending",
                        operation_ids=("refresh-me",),
                    )
                )
            return True

        def snapshot(self):
            return tuple(self.tasks)

        def enqueue_or_merge(self, **kwargs):
            pytest.fail("an active task found after refresh must be reused")

    queue = Queue()
    recovery = ImportManifestRecoveryService(store, queue)
    assert recovery.recover() == ()
    assert queue.refresh_calls >= 1
    assert store.get("refresh-me")["state"] == "recovery_pending"
    conn.close()


def test_recovery_refresh_finds_succeeded_task_and_acks_without_reenqueue(tmp_path):
    """A durable success seen after refresh completes the original binding."""
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    payload = _payload(root, destination)
    payload["recovery_task_id"] = "recon-refresh-success"
    payload["recovery_phase"] = "enqueued"
    store.create(
        operation_id="refresh-success",
        destination=destination,
        payload=payload,
        state="recovery_pending",
    )

    class Queue:
        def __init__(self):
            self.tasks = []
            self.refresh_calls = 0
            self.enqueue_calls = 0

        def refresh(self):
            self.refresh_calls += 1
            if not self.tasks:
                self.tasks.append(
                    SimpleNamespace(
                        task_id="recon-refresh-success",
                        state="succeeded",
                        operation_ids=("refresh-success",),
                    )
                )
            return True

        def snapshot(self):
            return tuple(self.tasks)

        def enqueue_or_merge(self, **kwargs):
            self.enqueue_calls += 1
            pytest.fail("a durable succeeded task must be ACKed, not replaced")

    queue = Queue()
    recovery = ImportManifestRecoveryService(store, queue)
    assert recovery.recover() == ()
    assert queue.refresh_calls >= 1
    assert queue.enqueue_calls == 0
    completed = store.get("refresh-success")
    assert completed["state"] == "completed"
    assert completed["payload"]["recovery_task_id"] == "recon-refresh-success"
    assert completed["payload"]["recovery_phase"] == "reconciled"
    conn.close()


def test_recovery_refresh_failure_does_not_rebind_stale_task(tmp_path):
    """A bound manifest stays pending when the queue snapshot is unavailable."""
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    payload = _payload(root, destination)
    payload["recovery_task_id"] = "recon-stale-bound"
    payload["recovery_phase"] = "enqueued"
    store.create(
        operation_id="stale-bound",
        destination=destination,
        payload=payload,
        state="recovery_pending",
    )

    class Queue:
        def refresh(self):
            raise RuntimeError("durable queue unavailable")

        def snapshot(self):
            pytest.fail("stale snapshot must not be consulted after refresh failure")

        def enqueue_or_merge(self, **kwargs):
            pytest.fail("bound task must not be replaced after refresh failure")

    recovery = ImportManifestRecoveryService(store, Queue())
    assert recovery.recover() == ()
    pending = store.get("stale-bound")
    assert pending["state"] == "recovery_pending"
    assert pending["payload"]["recovery_task_id"] == "recon-stale-bound"
    conn.close()


def test_item_terminal_state_cannot_be_rewritten(tmp_path):
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    store.create(
        operation_id="item-guard",
        destination=destination,
        payload=_payload(root, destination),
        state="running",
    )
    assert store.update_item("item-guard", item_index=0, state="copied")
    assert not store.update_item("item-guard", item_index=0, state="failed")
    assert store.get("item-guard")["payload"]["items"][0]["state"] == "copied"
    conn.close()


def test_malformed_recovery_row_isolated_from_valid_row(tmp_path):
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    now = 1.0
    conn.execute(
        "INSERT INTO import_manifests (operation_id, library_root, destination, state, payload, "
        "generation, attempts, last_error_type, last_error, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 0, 0, NULL, NULL, ?, ?)",
        ("bad-payload", str(root), str(destination), "running", "not-json", now, now),
    )
    store.create(
        operation_id="good-payload",
        destination=destination,
        payload=_payload(root, destination),
        state="running",
    )

    class Queue:
        def __init__(self):
            self.calls = []

        def enqueue_or_merge(self, **kwargs):
            self.calls.append(kwargs)

    queue = Queue()
    recovered = ImportManifestRecoveryService(store, queue).recover()
    assert recovered == ("good-payload",)
    assert [call["operation_id"] for call in queue.calls] == ["good-payload"]
    malformed = store.get("bad-payload")
    assert malformed["malformed"] is True
    assert malformed["state"] == "recovery_pending"
    assert malformed["attempts"] == 1
    assert malformed["last_error_type"] == "JSONDecodeError"
    conn.close()


def test_recovery_finish_failure_is_retryable_and_not_reported_success(tmp_path, monkeypatch):
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    store.create(
        operation_id="finish-retry",
        destination=destination,
        payload=_payload(root, destination),
        state="running",
    )

    class Queue:
        def __init__(self):
            self.calls = []

        def enqueue_or_merge(self, **kwargs):
            self.calls.append(kwargs)

    queue = Queue()
    original_finish = store.finish_recovery
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return False
        return original_finish(*args, **kwargs)

    monkeypatch.setattr(store, "finish_recovery", fail_once)
    recovery = ImportManifestRecoveryService(store, queue)
    assert recovery.recover() == ()
    assert store.get("finish-retry")["state"] == "recovery_pending"
    assert recovery.recover() == ("finish-retry",)
    assert store.get("finish-retry")["state"] == "completed"
    assert len(queue.calls) == 2
    conn.close()


def test_recovery_finish_exception_is_recorded_and_retryable(tmp_path, monkeypatch):
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    store.create(
        operation_id="finish-exception",
        destination=destination,
        payload=_payload(root, destination),
        state="running",
    )

    class Queue:
        def __init__(self):
            self.calls = []

        def enqueue_or_merge(self, **kwargs):
            self.calls.append(kwargs)

    queue = Queue()
    original_finish = store.finish_recovery

    def fail_finish(*args, **kwargs):
        raise sqlite3.OperationalError("manifest database unavailable")

    monkeypatch.setattr(store, "finish_recovery", fail_finish)
    recovery = ImportManifestRecoveryService(store, queue)
    assert recovery.recover() == ()
    pending = store.get("finish-exception")
    assert pending["state"] == "recovery_pending"
    assert pending["attempts"] == 1
    assert pending["last_error_type"] == "OperationalError"
    monkeypatch.setattr(store, "finish_recovery", original_finish)
    assert recovery.recover() == ("finish-exception",)
    assert store.get("finish-exception")["state"] == "completed"
    assert len(queue.calls) == 2
    conn.close()


def test_recovery_claim_has_single_winner_and_clears_on_finish(tmp_path):
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    store.create(
        operation_id="claim-once",
        destination=destination,
        payload=_payload(root, destination),
        state="running",
    )
    record = store.get("claim-once")
    claimed = store.claim_recovery(record, now=100.0, lease_seconds=10.0)
    assert claimed is not None
    assert claimed["recovery_claim_token"]
    assert claimed["generation"] == 1
    assert store.claim_recovery(record, now=100.0, lease_seconds=10.0) is None
    assert store.finish_recovery(claimed, now=101.0)
    final = store.get("claim-once")
    assert final["state"] == "completed"
    assert final["recovery_claim_token"] is None
    assert final["recovery_lease_expires_at"] is None
    conn.close()


def test_expired_recovery_claim_can_be_taken_over_old_token_rejected(tmp_path):
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    store.create(
        operation_id="claim-expiry",
        destination=destination,
        payload=_payload(root, destination),
        state="running",
    )
    first = store.claim_recovery(store.get("claim-expiry"), now=100.0, lease_seconds=1.0)
    assert first is not None
    second = store.claim_recovery(store.get("claim-expiry"), now=102.0, lease_seconds=10.0)
    assert second is not None
    assert second["recovery_claim_token"] != first["recovery_claim_token"]
    assert second["generation"] == first["generation"] + 1
    assert not store.finish_recovery(first, now=102.5)
    assert store.finish_recovery(second, now=103.0)
    assert store.get("claim-expiry")["state"] == "completed"
    conn.close()


def test_manifest_finish_fails_closed_under_external_write_lock(tmp_path):
    from AssetsManager.core import database

    root = tmp_path / "library"
    root.mkdir()
    db_path = tmp_path / "manifest-lock.sqlite3"
    initializer = sqlite3.connect(str(db_path), check_same_thread=False)
    initializer.executescript(database._SCHEMA)
    initializer.commit()
    from AssetsManager.core.db_migrations import migrate
    migrate(initializer)
    initializer.close()
    manifest_connection = sqlite3.connect(
        str(db_path), check_same_thread=False, timeout=0.0,
    )
    lock_connection = sqlite3.connect(
        str(db_path), check_same_thread=False, timeout=0.0,
    )
    try:
        store = ImportManifestStore(manifest_connection, root)
        destination = root / "dest"
        store.create(
            operation_id="locked-finish",
            destination=destination,
            payload=_payload(root, destination),
            state="running",
        )
        lock_connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError):
            store.finish("locked-finish", state="completed")
        lock_connection.rollback()
        assert store.finish("locked-finish", state="completed")
    finally:
        lock_connection.close()
        manifest_connection.close()


def test_file_backed_stale_manifest_cas_cannot_overwrite_newer_connection(tmp_path):
    from AssetsManager.core import database

    root = tmp_path / "library"
    root.mkdir()
    db_path = tmp_path / "manifest.sqlite3"
    initializer = sqlite3.connect(str(db_path), check_same_thread=False)
    initializer.executescript(database._SCHEMA)
    initializer.commit()
    from AssetsManager.core.db_migrations import migrate
    migrate(initializer)
    initializer.close()
    first = sqlite3.connect(str(db_path), check_same_thread=False, timeout=5.0)
    second = sqlite3.connect(str(db_path), check_same_thread=False, timeout=5.0)
    try:
        first_store = ImportManifestStore(first, root)
        second_store = ImportManifestStore(second, root)
        destination = root / "dest"
        payload = _payload(root, destination)
        first_store.create(
            operation_id="stale-cas",
            destination=destination,
            payload=payload,
            state="running",
        )
        stale = first_store.get("stale-cas")
        assert second_store.update_item("stale-cas", item_index=0, state="copied")
        stale_payload = dict(stale["payload"])
        assert not first_store._cas_update(
            "stale-cas",
            expected_generation=stale["generation"],
            expected_state="running",
            state="running",
            payload=__import__("json").dumps(stale_payload),
        )
        current = second_store.get("stale-cas")
        assert current["generation"] == 1
        assert current["payload"]["items"][0]["state"] == "copied"
    finally:
        first.close()
        second.close()


def _v2_payload(root, destination, *, item_count: int) -> dict[str, object]:
    items = []
    for index in range(item_count):
        items.append(
            {
                "source": str((root.parent / f"source-{index:04d}.txt").resolve()),
                "target": str((destination / f"file-{index:04d}.txt").resolve()),
                "state": "pending",
                "copy_id": f"import-{uuid4().hex}:{index}",
                "source_fingerprint": {
                    "size": index,
                    "mtime_ns": index,
                    "sha256": "ab" * 32,
                },
            }
        )
    return {
        "payload_version": 2,
        "destination": str(destination.resolve()),
        "items": items,
    }


def test_update_item_on_large_manifest_validates_only_modified_item(
    tmp_path, monkeypatch
):
    """Importing n files calls update_item n times; each call must not
    re-validate every stored item (the O(n^2) import hot path)."""
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    store.create(
        operation_id="bulk-update",
        destination=destination,
        payload=_v2_payload(root, destination, item_count=500),
        state="running",
    )

    full_validations: list[int] = []
    item_validations: list[int] = []
    original_validate_payload = manifest_store_module._validate_payload
    original_validate_item = manifest_store_module._validate_item

    def counting_validate_payload(*args, **kwargs):
        full_validations.append(1)
        return original_validate_payload(*args, **kwargs)

    def counting_validate_item(*args, **kwargs):
        item_validations.append(1)
        return original_validate_item(*args, **kwargs)

    monkeypatch.setattr(
        manifest_store_module, "_validate_payload", counting_validate_payload
    )
    monkeypatch.setattr(manifest_store_module, "_validate_item", counting_validate_item)

    for index in range(25):
        assert store.update_item("bulk-update", item_index=index, state="copied")
    assert store.update_item(
        "bulk-update", item_index=25, state="failed", error="boom"
    )
    assert full_validations == []
    assert len(item_validations) == 26

    monkeypatch.undo()
    record = store.get("bulk-update")
    assert record is not None
    assert not record.get("malformed")
    states = [item["state"] for item in record["payload"]["items"]]
    assert states[:25] == ["copied"] * 25
    assert states[25] == "failed"
    assert record["payload"]["items"][25]["error"] == "boom"
    assert states[26] == "pending"
    assert record["generation"] == 26
    conn.close()


def test_update_item_still_enforces_payload_size_ceiling(tmp_path):
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    store.create(
        operation_id="oversize",
        destination=destination,
        payload=_payload(root, destination),
        state="running",
    )
    with pytest.raises(ValueError, match="too large"):
        store.update_item(
            "oversize", item_index=0, state="failed", error="x" * (512 * 1024)
        )
    record = store.get("oversize")
    assert record["payload"]["items"][0]["state"] == "pending"
    assert record["payload"]["items"][0].get("error") is None
    conn.close()


def _stream_items(root, destination, operation_id, count):
    for index in range(count):
        yield {
            "source": str((root.parent / f"source-{index}.txt").resolve()),
            "relative": "",
            "target": str((destination / f"file-{index}.txt").resolve()),
            "state": "pending",
            "copy_id": f"{operation_id}:{index}",
            "source_fingerprint": {
                "size": index,
                "mtime_ns": index,
                "sha256": "ab" * 32,
            },
        }


def test_stream_manifest_round_trip_and_o1_item_update(tmp_path):
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    operation_id = "import-abcdef"
    # The integration test forces the legacy threshold below this count to
    # cover automatic selection; keeping this unit case small makes its
    # transactional/O(1) assertions fast on Windows CI.
    count = 33
    store.create_stream(
        operation_id=operation_id,
        destination=destination,
        items=_stream_items(root, destination, operation_id, count),
        item_count=count,
        state="running",
    )
    header = store.get(operation_id, include_items=False)
    assert header is not None
    assert header["payload"]["payload_version"] == 3
    assert "items" not in header["payload"]
    assert conn.execute(
        "SELECT COUNT(*) FROM import_manifest_items WHERE operation_id=?",
        (operation_id,),
    ).fetchone()[0] == count
    assert store.has_pending_items(operation_id)
    assert store.update_item(operation_id, item_index=count - 1, state="copied")
    copied = list(store.iter_items(operation_id, states={"copied"}))
    assert copied == [
        (
            count - 1,
            {
                "source": str((root.parent / f"source-{count - 1}.txt").resolve()),
                "relative": "",
                "target": str((destination / f"file-{count - 1}.txt").resolve()),
                "state": "copied",
                "copy_id": f"{operation_id}:{count - 1}",
                "source_fingerprint": {
                    "size": count - 1,
                    "mtime_ns": count - 1,
                    "sha256": "ab" * 32,
                },
            },
        )
    ]
    full = store.get(operation_id)
    assert full is not None
    assert len(full["payload"]["items"]) == count
    assert full["payload"]["items"][-1]["state"] == "copied"
    assert full["generation"] == 1
    conn.close()


def test_stream_manifest_create_is_atomic_on_invalid_item(tmp_path):
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    operation_id = "import-fedcba"

    def items():
        yield from _stream_items(root, destination, operation_id, 1)
        yield {
            "source": str((root.parent / "bad.txt").resolve()),
            "relative": "",
            "target": str((destination / "bad.txt").resolve()),
            "state": "pending",
            "copy_id": "not-a-valid-copy-id",
        }

    with pytest.raises(ValueError, match="copy_id"):
        store.create_stream(
            operation_id=operation_id,
            destination=destination,
            items=items(),
            item_count=2,
            state="running",
        )
    assert conn.execute(
        "SELECT COUNT(*) FROM import_manifests WHERE operation_id=?",
        (operation_id,),
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM import_manifest_items WHERE operation_id=?",
        (operation_id,),
    ).fetchone()[0] == 0
    conn.close()


def test_stream_manifest_corruption_is_reported_as_malformed(tmp_path):
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    operation_id = "import-123abc"
    store.create_stream(
        operation_id=operation_id,
        destination=destination,
        items=_stream_items(root, destination, operation_id, 2),
        item_count=2,
        state="running",
    )
    conn.execute(
        "DELETE FROM import_manifest_items WHERE operation_id=? AND item_index=1",
        (operation_id,),
    )
    conn.commit()
    malformed = store.get(operation_id)
    assert malformed is not None
    assert malformed["malformed"] is True
    assert "incomplete" in str(malformed["last_error"])
    conn.close()


def test_stream_manifest_corruption_cannot_be_acknowledged_terminal(tmp_path):
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    operation_id = "import-abc123"
    items = list(_stream_items(root, destination, operation_id, 1))
    store.create_stream(
        operation_id=operation_id,
        destination=destination,
        items=items,
        item_count=1,
        state="recovery_pending",
    )
    conn.execute(
        "DELETE FROM import_manifest_items WHERE operation_id=?",
        (operation_id,),
    )
    conn.commit()
    assert not store.acknowledge_recovery(operation_id, "recon-corrupt")
    # The parent remains recoverable rather than being terminalized based on
    # a queue success whose corresponding v3 item data is incomplete.
    header = store.get(operation_id, include_items=False)
    assert header is not None
    assert header["state"] == "recovery_pending"
    conn.close()


def test_recovery_rejects_unbound_or_wrong_scope_task(tmp_path):
    root, conn, store = _store(tmp_path)
    destination = root / "dest"
    operation_id = "import-aabbcc"
    store.create(
        operation_id=operation_id,
        destination=destination,
        payload=_payload(root, destination),
        state="recovery_pending",
    )
    assert not store.mark_recovery_running(operation_id, "recon-unbound")
    assert not store.acknowledge_recovery(operation_id, "recon-unbound")

    class Queue:
        def __init__(self):
            self.tasks = []

        def enqueue_or_merge(self, **kwargs):
            task = SimpleNamespace(
                task_id="recon-wrong-scope",
                state="pending",
                operation_ids=(operation_id,),
                library_root=str(root.parent / "other-library"),
                path=str(root.parent / "other-library"),
                kind="asset_index_root_rescan",
            )
            self.tasks.append(task)
            return task

        def snapshot(self):
            return tuple(self.tasks)

    # The service must not ACK a task whose explicit scope differs from the
    # manifest's library, even though the operation id is present.
    queue = Queue()
    recovery = ImportManifestRecoveryService(store, queue)
    assert recovery.recover() == (operation_id,)
    assert recovery.acknowledge_task(queue.tasks[0]) == ()
    assert store.get(operation_id, include_items=False)["state"] == "recovery_pending"
    conn.close()
