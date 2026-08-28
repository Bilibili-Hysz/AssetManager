import sqlite3
from uuid import uuid4

import pytest

import AssetsManager.application.import_manifest_store as manifest_store_module
from AssetsManager.application.import_manifest_store import (
    ImportManifestRecoveryService,
    ImportManifestStore,
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
