"""Tests for the explicit asset import service (audit task C1)."""
import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.application.import_service import ImportService
from AssetsManager.domain.event_bus import EventBus
from AssetsManager.domain.events import FileSystemChanged


def _bootstrap_and_import(tmp_path, monkeypatch):
    """Build a bootstrap, open a session, and patch the event bus."""
    bus = EventBus()
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    library = tmp_path / "library"
    library.mkdir()
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    scoped = bootstrap.runtime_for(session).services
    file_operations = scoped.file_operation_service
    return bootstrap, session, file_operations, bus


def _make_service(session, file_operations):
    return ImportService(session, file_operations)


def _seed_replay_manifest(service, store, operation_id, source, destination):
    target = destination / source.name
    store.create(
        operation_id=operation_id,
        destination=destination,
        payload={
            "payload_version": 2,
            "destination": str(destination.resolve()),
            "items": [{
                "source": str(source.resolve()),
                "relative": "",
                "target": str(target.resolve()),
                "state": "pending",
                "copy_id": f"{operation_id}:0",
                "source_fingerprint": service._source_fingerprint(source),
            }],
        },
        state="recovery_pending",
    )
    return target


def test_replay_import_adopts_matching_target_without_copy(tmp_path, monkeypatch):
    bootstrap, session, file_operations, _bus = _bootstrap_and_import(
        tmp_path, monkeypatch
    )
    try:
        source = tmp_path / "source.txt"
        source.write_text("source")
        destination = session.root / "dest"
        service = _make_service(session, file_operations)
        store = file_operations._import_manifest_store
        target = _seed_replay_manifest(service, store, "import-deadbeef", source, destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("source")
        monkeypatch.setattr(
            service,
            "_copy_one",
            lambda *_args, **_kwargs: pytest.fail("matching replay must adopt"),
        )
        replay = service.replay_import("import-deadbeef")
        assert replay.copied == 1
        assert replay.failed == []
        assert target.read_text() == "source"
    finally:
        bootstrap.library_service.close()


def test_replay_missing_target_uses_manifest_target(tmp_path, monkeypatch):
    bootstrap, session, file_operations, _bus = _bootstrap_and_import(
        tmp_path, monkeypatch
    )
    try:
        source = tmp_path / "source.txt"
        source.write_text("source")
        destination = session.root / "dest"
        service = _make_service(session, file_operations)
        store = file_operations._import_manifest_store
        target = _seed_replay_manifest(service, store, "import-cafebabe", source, destination)
        replay = service.replay_import("import-cafebabe")
        assert replay.copied == 1
        assert target.read_text() == "source"
    finally:
        bootstrap.library_service.close()


def test_replay_source_change_and_target_conflict_fail_closed(tmp_path, monkeypatch):
    bootstrap, session, file_operations, _bus = _bootstrap_and_import(
        tmp_path, monkeypatch
    )
    try:
        source = tmp_path / "source.txt"
        source.write_text("source")
        destination = session.root / "dest"
        service = _make_service(session, file_operations)
        store = file_operations._import_manifest_store
        target = _seed_replay_manifest(service, store, "import-deadcafe", source, destination)
        source.write_text("changed")
        replay = service.replay_import("import-deadcafe")
        assert replay.copied == 0
        assert any("source_changed" in item for item in replay.failed)
        assert not target.exists()
    finally:
        bootstrap.library_service.close()


def test_replay_target_conflict_is_preserved(tmp_path, monkeypatch):
    bootstrap, session, file_operations, _bus = _bootstrap_and_import(
        tmp_path, monkeypatch
    )
    try:
        source = tmp_path / "source.txt"
        source.write_text("source")
        destination = session.root / "dest"
        service = _make_service(session, file_operations)
        store = file_operations._import_manifest_store
        target = _seed_replay_manifest(
            service, store, "import-f00dbabe", source, destination
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("rival")

        replay = service.replay_import("import-f00dbabe")

        assert replay.copied == 0
        assert replay.degraded is True
        assert any("replay_conflict" in item for item in replay.failed)
        assert target.read_text() == "rival"
    finally:
        bootstrap.library_service.close()


def test_legacy_v1_manifest_is_not_automatically_replayed(tmp_path, monkeypatch):
    bootstrap, session, file_operations, _bus = _bootstrap_and_import(
        tmp_path, monkeypatch
    )
    try:
        source = tmp_path / "source.txt"
        source.write_text("source")
        destination = session.root / "dest"
        target = destination / source.name
        store = file_operations._import_manifest_store
        store.create(
            operation_id="import-legacy1",
            destination=destination,
            payload={
                "payload_version": 1,
                "destination": str(destination.resolve()),
                "items": [{
                    "source": str(source.resolve()),
                    "target": str(target.resolve()),
                    "state": "pending",
                }],
            },
            state="recovery_pending",
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("source")

        replay = _make_service(session, file_operations).replay_import(
            "import-legacy1"
        )

        assert replay.copied == 0
        assert replay.failed == []
        assert target.read_text() == "source"
        assert store.get("import-legacy1")["state"] == "recovery_pending"
    finally:
        bootstrap.library_service.close()


def test_repeated_normal_import_keeps_auto_rename_contract(tmp_path, monkeypatch):
    bootstrap, session, file_operations, _bus = _bootstrap_and_import(
        tmp_path, monkeypatch
    )
    try:
        source = tmp_path / "source.txt"
        source.write_text("source")
        destination = session.root / "dest"
        service = _make_service(session, file_operations)
        first = service.import_sources([source], destination)
        second = service.import_sources([source], destination)
        assert first.copied == second.copied == 1
        assert (destination / "source.txt").exists()
        assert (destination / "source_1.txt").exists()
    finally:
        bootstrap.library_service.close()


def test_cancelled_import_with_broken_queue_stays_recoverable(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    library_root = session.root
    destination = session.root / "dest"
    try:
        src = tmp_path / "tree"
        src.mkdir()
        (src / "a.txt").write_text("a")
        (src / "b.txt").write_text("b")

        def fail_queue(**kwargs):
            raise RuntimeError("queue unavailable")

        monkeypatch.setattr(
            file_operations._reconciliation_queue, "enqueue_or_merge", fail_queue
        )
        calls = []

        def progress(done, total):
            calls.append((done, total))

        def cancel():
            # progress(0,total) fires before the loop; cancel after the first
            # file has been copied so partial compensation is exercised.
            return len(calls) >= 2

        with pytest.raises(Exception) as raised:
            _make_service(session, file_operations).import_sources(
                [src], destination, progress=progress, should_cancel=cancel
            )
        from AssetsManager.application.import_service import ImportCancelled
        assert isinstance(raised.value, ImportCancelled)
        partial = raised.value.partial_result
        assert partial.copied >= 1
        operation_id = partial.operation_id
        record = file_operations._import_manifest_store.get(operation_id)
        # The cancelled intent must stay recoverable: a terminal state without
        # durable index compensation would hide the copied file forever.
        assert record["state"] in {"running", "recovery_pending"}
        assert (destination / "a.txt").read_text() == "a"
    finally:
        bootstrap.library_service.close()

    reopened = ApplicationBootstrap()
    reopened_session = reopened.library_service.open_session(library_root)
    try:
        services = reopened.runtime_for(reopened_session).services
        tasks = services.reconciliation_queue.snapshot()
        matching = [
            task for task in tasks if operation_id in task.operation_ids
        ]
        assert len(matching) == 1
        record = services.file_operation_service._import_manifest_store.get(
            operation_id
        )
        assert record["state"] == "completed"
        names = [entry.name for entry in destination.iterdir()]
        assert names.count("a.txt") == 1
        assert (destination / "a.txt").read_text() == "a"
    finally:
        reopened.library_service.close()


def test_update_failure_with_broken_queue_keeps_recovery_pending(
    tmp_path, monkeypatch
):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    library_root = session.root
    destination = session.root / "dest"
    try:
        source = tmp_path / "source.txt"
        source.write_text("x")
        store = file_operations._import_manifest_store

        def fail_update(*args, **kwargs):
            raise RuntimeError("manifest update unavailable")

        def fail_queue(**kwargs):
            raise RuntimeError("queue unavailable")

        monkeypatch.setattr(store, "update_item", fail_update)
        monkeypatch.setattr(
            file_operations._reconciliation_queue, "enqueue_or_merge", fail_queue
        )
        result = _make_service(session, file_operations).import_sources(
            [source], destination
        )
        assert result.degraded is True
        assert result.failed
        operation_id = result.operation_id
        record = store.get(operation_id)
        assert record["state"] == "recovery_pending"
        # The physical copy still succeeded before the bookkeeping failure.
        assert (destination / "source.txt").read_text() == "x"
    finally:
        bootstrap.library_service.close()

    reopened = ApplicationBootstrap()
    reopened_session = reopened.library_service.open_session(library_root)
    try:
        services = reopened.runtime_for(reopened_session).services
        tasks = services.reconciliation_queue.snapshot()
        assert any(
            operation_id in task.operation_ids
            and task.reason == "import_manifest_recovery"
            for task in tasks
        )
        record = services.file_operation_service._import_manifest_store.get(
            operation_id
        )
        assert record["state"] == "completed"
        names = [entry.name for entry in destination.iterdir()]
        assert names.count("source.txt") == 1
    finally:
        reopened.library_service.close()


def test_clean_import_finish_failure_enqueues_manifest_recovery(
    tmp_path, monkeypatch
):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    library_root = session.root
    destination = session.root / "dest"
    try:
        source = tmp_path / "source.txt"
        source.write_text("hello")
        store = file_operations._import_manifest_store
        queue_calls = []
        original_enqueue = file_operations._reconciliation_queue.enqueue_or_merge

        def capture_enqueue(**kwargs):
            queue_calls.append(kwargs)
            return original_enqueue(**kwargs)

        def fail_finish(*args, **kwargs):
            raise RuntimeError("finish unavailable")

        monkeypatch.setattr(
            file_operations._reconciliation_queue,
            "enqueue_or_merge",
            capture_enqueue,
        )
        monkeypatch.setattr(store, "finish", fail_finish)
        result = _make_service(session, file_operations).import_sources(
            [source], destination
        )
        assert result.copied == 1
        operation_id = result.operation_id
        assert any(
            call["reason"] == "import_manifest_recovery" for call in queue_calls
        )
        record = store.get(operation_id)
        assert record["state"] == "running"
    finally:
        bootstrap.library_service.close()

    reopened = ApplicationBootstrap()
    reopened_session = reopened.library_service.open_session(library_root)
    try:
        services = reopened.runtime_for(reopened_session).services
        record = services.file_operation_service._import_manifest_store.get(
            operation_id
        )
        assert record["state"] == "completed"
    finally:
        reopened.library_service.close()


def test_replay_continues_after_manifest_update_exception(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        source_a = tmp_path / "a.txt"
        source_b = tmp_path / "b.txt"
        source_a.write_text("a")
        source_b.write_text("b")
        destination = session.root / "dest"
        service = _make_service(session, file_operations)
        store = file_operations._import_manifest_store
        target_a = destination / "a.txt"
        target_b = destination / "b.txt"
        store.create(
            operation_id="import-cafe0001",
            destination=destination,
            payload={
                "payload_version": 2,
                "destination": str(destination.resolve()),
                "items": [
                    {
                        "source": str(source_a.resolve()),
                        "relative": "",
                        "target": str(target_a.resolve()),
                        "state": "pending",
                        "copy_id": "import-cafe0001:0",
                        "source_fingerprint": service._source_fingerprint(source_a),
                    },
                    {
                        "source": str(source_b.resolve()),
                        "relative": "",
                        "target": str(target_b.resolve()),
                        "state": "pending",
                        "copy_id": "import-cafe0001:1",
                        "source_fingerprint": service._source_fingerprint(source_b),
                    },
                ],
            },
            state="recovery_pending",
        )
        original_update = store.update_item
        update_calls = 0

        def raise_once(*args, **kwargs):
            nonlocal update_calls
            update_calls += 1
            if update_calls == 1:
                raise RuntimeError("manifest replay update unavailable")
            return original_update(*args, **kwargs)

        monkeypatch.setattr(store, "update_item", raise_once)
        replay = service.replay_import("import-cafe0001")

        assert replay.processed == 2
        assert replay.copied == 2
        assert replay.degraded is True
        assert any("manifest replay update" in item for item in replay.failed)
        assert target_a.read_text() == "a"
        assert target_b.read_text() == "b"
    finally:
        bootstrap.library_service.close()


def test_replay_claim_race_returns_deterministic_failure(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        source = tmp_path / "source.txt"
        source.write_text("source")
        destination = session.root / "dest"
        service = _make_service(session, file_operations)
        store = file_operations._import_manifest_store
        _seed_replay_manifest(service, store, "import-cafe0002", source, destination)

        def lose_claim(_operation_id):
            return None

        monkeypatch.setattr(store, "begin_replay", lose_claim)
        replay = service.replay_import("import-cafe0002")

        assert replay.copied == 0
        assert replay.degraded is True
        assert any("replay claim lost" in item for item in replay.failed)
    finally:
        bootstrap.library_service.close()


def test_replay_finish_failure_enqueues_manifest_recovery(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        source = tmp_path / "source.txt"
        source.write_text("source")
        destination = session.root / "dest"
        service = _make_service(session, file_operations)
        store = file_operations._import_manifest_store
        _seed_replay_manifest(service, store, "import-cafe0003", source, destination)
        queue_calls = []
        original_enqueue = file_operations._reconciliation_queue.enqueue_or_merge

        def capture_enqueue(**kwargs):
            queue_calls.append(kwargs)
            return original_enqueue(**kwargs)

        def fail_finish(*args, **kwargs):
            return False

        monkeypatch.setattr(
            file_operations._reconciliation_queue,
            "enqueue_or_merge",
            capture_enqueue,
        )
        monkeypatch.setattr(store, "finish", fail_finish)
        replay = service.replay_import("import-cafe0003")

        assert any(
            call["reason"] == "import_manifest_recovery" for call in queue_calls
        )
        assert any("finish unavailable" in item for item in replay.failed)
        assert replay.degraded is True
    finally:
        bootstrap.library_service.close()


def test_import_persists_manifest_and_marks_completed(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        source = tmp_path / "source.txt"
        source.write_text("hello")
        destination = session.root / "dest"
        result = _make_service(session, file_operations).import_sources([source], destination)
        assert result.operation_id
        store = file_operations._import_manifest_store
        record = store.get(result.operation_id)
        assert record is not None
        assert record["state"] == "completed"
        assert record["payload"]["items"][0]["state"] == "copied"
        assert record["payload"]["items"][0]["target"] == str(
            (destination / "source.txt").resolve()
        )
    finally:
        bootstrap.library_service.close()


def test_import_queue_failure_leaves_recovery_manifest(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        source = tmp_path / "source.txt"
        source.write_text("hello")
        destination = session.root / "dest"

        def fail_queue(**kwargs):
            raise RuntimeError("queue unavailable")

        monkeypatch.setattr(
            file_operations._reconciliation_queue, "enqueue_or_merge", fail_queue
        )
        import AssetsManager.application.import_service as module
        monkeypatch.setattr(
            module.shutil,
            "copyfileobj",
            lambda *_args: (_ for _ in ()).throw(OSError("copy failed")),
        )
        result = _make_service(session, file_operations).import_sources([source], destination)
        assert result.degraded is True
        record = file_operations._import_manifest_store.get(result.operation_id)
        assert record["state"] == "recovery_pending"
    finally:
        bootstrap.library_service.close()


def test_runtime_recovery_enqueues_unresolved_manifest(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    root = session.root
    destination = root / "dest"
    store = file_operations._import_manifest_store
    store.create(
        operation_id="import-restart",
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
    bootstrap.library_service.close()

    restarted = ApplicationBootstrap()
    try:
        reopened = restarted.library_service.open_session(root)
        services = restarted.runtime_for(reopened).services
        tasks = services.reconciliation_queue.snapshot()
        assert any(
            "import-restart" in task.operation_ids
            and task.reason == "import_manifest_recovery"
            for task in tasks
        )
    finally:
        restarted.library_service.close()


def test_import_single_file(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        source = tmp_path / "source.txt"
        source.write_text("hello")
        dest = session.root / "dest"
        dest.mkdir()

        result = _make_service(session, file_operations).import_sources([source], dest)

        assert result.copied == 1
        assert result.skipped == 0
        assert result.failed == []
        assert (dest / "source.txt").read_text() == "hello"
    finally:
        bootstrap.library_service.close()


def test_import_directory_tree_recursive(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        src = tmp_path / "tree"
        (src / "nested" / "deep").mkdir(parents=True)
        (src / "a.txt").write_text("a")
        (src / "nested" / "b.txt").write_text("b")
        (src / "nested" / "deep" / "c.txt").write_text("c")
        # dot-prefixed entries are skipped
        (src / ".hidden.txt").write_text("hidden")
        (src / ".git").mkdir()
        (src / ".git" / "config").write_text("x")

        dest = session.root / "dest"
        dest.mkdir()

        result = _make_service(session, file_operations).import_sources([src], dest)

        assert result.copied == 3
        assert result.failed == []
        # Directory structure is preserved inside the destination.
        assert (dest / "a.txt").exists()
        assert (dest / "nested" / "b.txt").exists()
        assert (dest / "nested" / "deep" / "c.txt").exists()
        assert not (dest / ".hidden.txt").exists()
        assert not (dest / "config").exists()
    finally:
        bootstrap.library_service.close()


def test_in_library_source_skipped(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        inside = session.root / "already.txt"
        inside.write_text("x")
        dest = session.root / "dest"
        dest.mkdir()

        result = _make_service(session, file_operations).import_sources([inside], dest)

        assert result.copied == 0
        assert result.skipped == 1
        assert not (dest / "already.txt").exists()
    finally:
        bootstrap.library_service.close()


def test_destination_outside_library_raises(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        source = tmp_path / "source.txt"
        source.write_text("x")
        outside = tmp_path / "outside"
        outside.mkdir()

        with pytest.raises(ValueError):
            _make_service(session, file_operations).import_sources([source], outside)
    finally:
        bootstrap.library_service.close()


def test_name_conflict_auto_rename(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        source = tmp_path / "file.txt"
        source.write_text("new")
        dest = session.root / "dest"
        dest.mkdir()
        (dest / "file.txt").write_text("old")

        result = _make_service(session, file_operations).import_sources([source], dest)

        assert result.copied == 1
        assert (dest / "file.txt").read_text() == "old"
        # unique_destination uses "%stem_%n%suffix"
        assert (dest / "file_1.txt").read_text() == "new"
    finally:
        bootstrap.library_service.close()


def test_planned_target_rival_is_not_overwritten_or_cleaned(tmp_path, monkeypatch):
    bootstrap, session, file_operations, _bus = _bootstrap_and_import(
        tmp_path, monkeypatch
    )
    try:
        source = tmp_path / "source.txt"
        source.write_text("source")
        destination = session.root / "dest"
        destination.mkdir()
        service = _make_service(session, file_operations)
        original_copy = service._copy_one
        rival = destination / source.name

        def create_rival(src, rel, destination_dir, target=None, **_kwargs):
            assert target == rival
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x", encoding="utf-8") as handle:
                handle.write("rival")
            return original_copy(src, rel, destination_dir, target)

        monkeypatch.setattr(service, "_copy_one", create_rival)
        result = service.import_sources([source], destination)

        assert result.copied == 0
        assert result.degraded is True
        assert result.failed
        assert rival.read_text() == "rival"
    finally:
        bootstrap.library_service.close()


def test_copy_one_rejects_existing_explicit_target(tmp_path, monkeypatch):
    bootstrap, session, file_operations, _bus = _bootstrap_and_import(
        tmp_path, monkeypatch
    )
    try:
        source = tmp_path / "source.txt"
        source.write_text("source")
        destination = session.root / "dest"
        destination.mkdir()
        service = _make_service(session, file_operations)
        target = destination / "target.txt"

        assert service._copy_one(source, Path(), destination, target) == target
        with pytest.raises(FileExistsError):
            service._copy_one(source, Path(), destination, target)
        assert target.read_text() == "source"
    finally:
        bootstrap.library_service.close()


def test_preexisting_explicit_target_is_preserved(tmp_path, monkeypatch):
    bootstrap, session, file_operations, _bus = _bootstrap_and_import(
        tmp_path, monkeypatch
    )
    try:
        source = tmp_path / "source.txt"
        source.write_text("source")
        destination = session.root / "dest"
        destination.mkdir()
        target = destination / "target.txt"
        target.write_text("keep")
        service = _make_service(session, file_operations)

        with pytest.raises(FileExistsError):
            service._copy_one(source, Path(), destination, target)
        assert os.path.lexists(target)
        assert target.read_text() == "keep"
    finally:
        bootstrap.library_service.close()


def test_partial_exclusive_copy_is_cleaned_up(tmp_path, monkeypatch):
    bootstrap, session, file_operations, _bus = _bootstrap_and_import(
        tmp_path, monkeypatch
    )
    try:
        source = tmp_path / "source.txt"
        source.write_text("source")
        destination = session.root / "dest"
        import AssetsManager.application.import_service as module

        def write_then_fail(_source_handle, target_handle):
            target_handle.write(b"partial")
            raise OSError("stream failed")

        monkeypatch.setattr(module.shutil, "copyfileobj", write_then_fail)
        result = _make_service(session, file_operations).import_sources(
            [source], destination
        )

        target = destination / source.name
        assert result.copied == 0
        assert result.processed == result.total == 1
        assert result.degraded is True
        assert result.failed
        assert not os.path.lexists(target)
    finally:
        bootstrap.library_service.close()


def test_replaced_target_is_not_deleted_during_cleanup(tmp_path, monkeypatch):
    bootstrap, session, file_operations, _bus = _bootstrap_and_import(
        tmp_path, monkeypatch
    )
    try:
        source = tmp_path / "source.txt"
        source.write_text("source")
        destination = session.root / "dest"
        import AssetsManager.application.import_service as module
        target = destination / source.name

        def replace_then_fail(_source_path, _target_path, **_kwargs):
            target.unlink()
            target.write_text("rival")
            raise OSError("stat failed after replacement")

        monkeypatch.setattr(module.shutil, "copystat", replace_then_fail)
        result = _make_service(session, file_operations).import_sources(
            [source], destination
        )

        assert result.copied == 0
        assert result.degraded is True
        assert target.read_text() == "rival"
    finally:
        bootstrap.library_service.close()


def test_existing_nested_symlink_destination_is_rejected_without_external_write(
    tmp_path, monkeypatch
):
    bootstrap, session, file_operations, _bus = _bootstrap_and_import(
        tmp_path, monkeypatch
    )
    try:
        source = tmp_path / "source.txt"
        source.write_text("source")
        destination = session.root / "dest"
        destination.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        nested = destination / "nested"
        try:
            nested.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"symlink unavailable: {exc}")

        with pytest.raises(ValueError, match="escapes the library root"):
            _make_service(session, file_operations).import_sources(
                [source], destination / "nested"
            )

        assert nested.is_symlink()
        assert not (outside / source.name).exists()
    finally:
        bootstrap.library_service.close()


def test_post_plan_nested_parent_revalidation_is_fail_closed(tmp_path, monkeypatch):
    bootstrap, session, file_operations, _bus = _bootstrap_and_import(
        tmp_path, monkeypatch
    )
    try:
        source_tree = tmp_path / "tree"
        (source_tree / "nested").mkdir(parents=True)
        (source_tree / "nested" / "source.txt").write_text("source")
        destination = session.root / "dest"
        import AssetsManager.application.import_service as module
        original_check = module._reject_link_or_reparse_ancestors

        def reject_nested(root, candidate):
            if Path(candidate).name == "nested":
                raise OSError("simulated reparse parent")
            return original_check(root, candidate)

        monkeypatch.setattr(
            module, "_reject_link_or_reparse_ancestors", reject_nested
        )
        result = _make_service(session, file_operations).import_sources(
            [source_tree], destination
        )

        assert result.copied == 0
        assert result.degraded is True
        assert result.failed
        assert not (destination / "nested" / "source.txt").exists()
    finally:
        bootstrap.library_service.close()


def test_ancestor_inspection_failure_is_fail_closed(tmp_path, monkeypatch):
    root = tmp_path / "library"
    root.mkdir()
    candidate = root / "dest" / "nested"
    candidate.parent.mkdir()
    candidate.mkdir()
    import AssetsManager.application.import_service as module
    real_lstat = module.os.lstat

    def fail_nested(path):
        if Path(path).name == "nested":
            raise OSError("inspection failed")
        return real_lstat(path)

    monkeypatch.setattr(module.os, "lstat", fail_nested)
    with pytest.raises(OSError, match="inspection failed"):
        module._reject_link_or_reparse_ancestors(root, candidate)


def test_windows_junction_destination_is_rejected_without_external_write(
    tmp_path, monkeypatch
):
    if os.name != "nt":
        pytest.skip("Windows junction test")
    bootstrap, session, file_operations, _bus = _bootstrap_and_import(
        tmp_path, monkeypatch
    )
    junction = session.root / "dest" / "junction"
    outside = tmp_path / "junction-outside"
    destination = session.root / "dest"
    destination.mkdir()
    outside.mkdir()
    try:
        import subprocess
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            pytest.skip(f"junction unavailable: {result.stdout} {result.stderr}")
        source = tmp_path / "source.txt"
        source.write_text("source")
        with pytest.raises(ValueError, match="escapes the library root"):
            _make_service(session, file_operations).import_sources(
                [source], junction
            )
        assert not (outside / source.name).exists()

    finally:
        bootstrap.library_service.close()
        if junction.exists():
            import shutil
            shutil.rmtree(junction, ignore_errors=True)


def test_copy_one_rejects_source_drift_from_manifest_fingerprint(
    tmp_path, monkeypatch
):
    bootstrap, session, file_operations, _bus = _bootstrap_and_import(
        tmp_path, monkeypatch
    )
    try:
        source = tmp_path / "source.txt"
        source.write_text("original")
        destination = session.root / "dest"
        destination.mkdir()
        service = _make_service(session, file_operations)
        stale = service._source_fingerprint(source)
        source.write_text("mutated")
        target = destination / "target.txt"

        with pytest.raises(OSError, match="changed since manifest fingerprint"):
            service._copy_one(
                source, Path(), destination, target, expected_fingerprint=stale
            )
        assert not os.path.lexists(target)
    finally:
        bootstrap.library_service.close()


def test_copy_one_detects_source_mutation_during_stream(tmp_path, monkeypatch):
    bootstrap, session, file_operations, _bus = _bootstrap_and_import(
        tmp_path, monkeypatch
    )
    try:
        source = tmp_path / "source.txt"
        source.write_text("original")
        destination = session.root / "dest"
        destination.mkdir()
        import AssetsManager.application.import_service as module
        service = _make_service(session, file_operations)
        fingerprint = service._source_fingerprint(source)
        target = destination / "target.txt"
        original_copyfileobj = module.shutil.copyfileobj

        def copy_then_mutate(source_handle, target_handle):
            original_copyfileobj(source_handle, target_handle)
            # Rewrite the underlying file after streaming completes; the
            # same-handle post-check must notice size/mtime divergence.
            with open(source, "r+b") as handle:
                handle.seek(0, os.SEEK_END)
                handle.write(b"tail")

        monkeypatch.setattr(module.shutil, "copyfileobj", copy_then_mutate)

        with pytest.raises(OSError, match="source changed while copying"):
            service._copy_one(
                source,
                Path(),
                destination,
                target,
                expected_fingerprint=fingerprint,
            )
        assert not os.path.lexists(target)
    finally:
        bootstrap.library_service.close()


def test_dangling_symlink_target_is_rejected_without_touching_external_path(
    tmp_path, monkeypatch
):
    bootstrap, session, file_operations, _bus = _bootstrap_and_import(
        tmp_path, monkeypatch
    )
    try:
        source = tmp_path / "source.txt"
        source.write_text("source")
        destination = session.root / "dest"
        destination.mkdir()
        link = destination / source.name
        external = tmp_path / "outside.txt"
        try:
            link.symlink_to(external)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"symlink unavailable: {exc}")

        result = _make_service(session, file_operations).import_sources(
            [source], destination
        )

        assert result.copied == 0
        assert result.degraded is True
        assert os.path.lexists(link)
        assert not external.exists()
    finally:
        bootstrap.library_service.close()


def test_progress_monotonic_and_reaches_total(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        src = tmp_path / "tree"
        src.mkdir()
        for i in range(5):
            (src / f"f{i}.txt").write_text("x")
        dest = session.root / "dest"
        dest.mkdir()

        calls = []

        def progress(done, total):
            calls.append((done, total))

        _make_service(session, file_operations).import_sources(
            [src], dest, progress=progress
        )

        assert calls, "progress must be invoked"
        dones = [d for d, _ in calls]
        totals = [t for _, t in calls]
        assert dones == sorted(dones), "progress must be monotonic non-decreasing"
        assert totals == [totals[0]] * len(totals), "total must be stable"
        assert calls[-1][0] == calls[-1][1] == 5, "final done must equal total"
    finally:
        bootstrap.library_service.close()


def test_single_failure_does_not_abort_and_is_recorded(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        src = tmp_path / "tree"
        src.mkdir()
        (src / "good.txt").write_text("good")
        (src / "broken.txt").write_text("break")
        dest = session.root / "dest"
        dest.mkdir()

        import AssetsManager.application.import_service as mod

        real_read = mod.ImportService._read_source

        def flaky_read(self, src_path):
            if Path(src_path).name == "broken.txt":
                raise OSError("simulated copy failure")
            return real_read(self, src_path)

        monkeypatch.setattr(mod.ImportService, "_read_source", flaky_read)

        result = _make_service(session, file_operations).import_sources([src], dest)

        assert result.copied == 1
        assert result.failed, "the failing file must be recorded as failed"
        assert any("broken.txt" in f for f in result.failed)
        assert (dest / "good.txt").exists()
    finally:
        bootstrap.library_service.close()


def test_exactly_one_import_event_published(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        events = []
        bus.subscribe(FileSystemChanged, events.append)

        src = tmp_path / "tree"
        src.mkdir()
        (src / "a.txt").write_text("a")
        (src / "b.txt").write_text("b")
        dest = session.root / "dest"
        dest.mkdir()

        _make_service(session, file_operations).import_sources([src], dest)

        import_events = [e for e in events if e.kind == "import"]
        assert len(import_events) == 1
        assert import_events[0].library_root == session.root_str
        assert import_events[0].session_token == session.event_token
        assert import_events[0].paths == (str(dest.resolve()),)
    finally:
        bootstrap.library_service.close()


def test_import_cancellation_returns_partial_result_without_event_or_refresh(
    tmp_path, monkeypatch
):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    events = []
    bus.subscribe(FileSystemChanged, events.append)
    try:
        src = tmp_path / "tree"
        src.mkdir()
        for name in ("a.txt", "b.txt", "c.txt"):
            (src / name).write_text(name)
        dest = session.root / "dest"
        calls = []
        refresh_calls = []
        queue_calls = []
        original_enqueue = file_operations._reconciliation_queue.enqueue_or_merge
        monkeypatch.setattr(
            file_operations._reconciliation_queue,
            "enqueue_or_merge",
            lambda **kwargs: (queue_calls.append(kwargs), original_enqueue(**kwargs))[1],
        )
        original_refresh = file_operations._refresh_directory_tree
        monkeypatch.setattr(
            file_operations,
            "_refresh_directory_tree",
            lambda path: refresh_calls.append(path),
        )

        def progress(done, total):
            calls.append((done, total))

        def cancel():
            return len(calls) >= 2

        with pytest.raises(Exception) as raised:
            _make_service(session, file_operations).import_sources(
                [src], dest, progress=progress, should_cancel=cancel
            )
        from AssetsManager.application.import_service import ImportCancelled
        assert isinstance(raised.value, ImportCancelled)
        partial = raised.value.partial_result
        assert partial is not None
        assert partial.cancelled is True
        assert partial.copied >= 1
        assert not refresh_calls
        assert events == []
        assert (dest / "a.txt").exists()
        assert any(call["reason"] == "import_partial" for call in queue_calls)
        assert callable(original_refresh)
    finally:
        bootstrap.library_service.close()


def test_import_late_cancellation_enqueues_rescan_without_refresh_or_event(
    tmp_path, monkeypatch,
):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    events = []
    bus.subscribe(FileSystemChanged, events.append)
    try:
        source = tmp_path / "source.txt"
        source.write_text("source")
        destination = session.root / "dest"
        refresh_calls = []
        queue_calls = []
        monkeypatch.setattr(
            file_operations,
            "_refresh_directory_tree",
            lambda path: refresh_calls.append(path),
        )
        original_enqueue = file_operations._reconciliation_queue.enqueue_or_merge
        monkeypatch.setattr(
            file_operations._reconciliation_queue,
            "enqueue_or_merge",
            lambda **kwargs: (queue_calls.append(kwargs), original_enqueue(**kwargs))[1],
        )
        progress_calls = []

        def progress(done, total):
            progress_calls.append((done, total))

        def cancel():
            return bool(progress_calls and progress_calls[-1] == (1, 1))

        with pytest.raises(Exception) as raised:
            _make_service(session, file_operations).import_sources(
                [source], destination, progress=progress, should_cancel=cancel,
            )
        from AssetsManager.application.import_service import ImportCancelled
        assert isinstance(raised.value, ImportCancelled)
        partial = raised.value.partial_result
        assert partial is not None
        assert partial.copied == 1
        assert (destination / "source.txt").read_text() == "source"
        assert refresh_calls == []
        assert events == []
        assert any(call["reason"] == "import_partial" for call in queue_calls)
    finally:
        bootstrap.library_service.close()


def test_import_manifest_update_failure_continues_copy_and_degrades(
    tmp_path, monkeypatch,
):
    bootstrap, session, file_operations, _bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        source_a = tmp_path / "a.txt"
        source_b = tmp_path / "b.txt"
        source_a.write_text("a")
        source_b.write_text("b")
        destination = session.root / "dest"
        store = file_operations._import_manifest_store
        original_update = store.update_item
        calls = 0

        def fail_once(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("manifest update unavailable")
            return original_update(*args, **kwargs)

        monkeypatch.setattr(store, "update_item", fail_once)
        result = _make_service(session, file_operations).import_sources(
            [source_a, source_b], destination,
        )

        assert result.copied == 2
        assert result.degraded is True
        assert (destination / "a.txt").exists()
        assert (destination / "b.txt").exists()
        assert any("manifest update" in item for item in result.failed)
    finally:
        bootstrap.library_service.close()


def test_import_copy_failure_is_degraded_and_queues_index_rescan(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        source = tmp_path / "source.txt"
        source.write_text("x")
        dest = session.root / "dest"
        import AssetsManager.application.import_service as module
        monkeypatch.setattr(
            module.shutil,
            "copyfileobj",
            lambda *_args: (_ for _ in ()).throw(OSError("copy failed")),
        )
        result = _make_service(session, file_operations).import_sources([source], dest)
        assert result.degraded is True
        assert result.processed == result.total == 1
        assert result.failed
        assert any(task.reason == "import_partial" for task in file_operations._reconciliation_queue.snapshot())
    finally:
        bootstrap.library_service.close()


def test_import_empty_sources_is_noop(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    events = []
    bus.subscribe(FileSystemChanged, events.append)
    try:
        result = _make_service(session, file_operations).import_sources([], session.root / "dest")
        assert result.copied == result.skipped == 0
        assert result.operation_id
        assert not events
    finally:
        bootstrap.library_service.close()


def test_import_holds_session_lease_until_copy_finishes(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    entered = threading.Event()
    release = threading.Event()
    source = tmp_path / "source.txt"
    source.write_text("x")
    destination = session.root / "dest"

    import AssetsManager.application.import_service as module
    original_copyfileobj = module.shutil.copyfileobj

    def blocking_copyfileobj(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original_copyfileobj(*args, **kwargs)

    monkeypatch.setattr(module.shutil, "copyfileobj", blocking_copyfileobj)
    result = []
    worker = threading.Thread(
        target=lambda: result.append(
            _make_service(session, file_operations).import_sources([source], destination)
        )
    )
    worker.start()
    assert entered.wait(5)

    close_done = threading.Event()
    closer = threading.Thread(
        target=lambda: (bootstrap.library_service.close_session(session), close_done.set())
    )
    closer.start()
    try:
        assert not close_done.wait(0.2)
        assert session.is_closed
        with pytest.raises(RuntimeError, match="closed"):
            _make_service(session, file_operations).import_sources([], destination)
    finally:
        release.set()
    worker.join(5)
    closer.join(5)
    assert result and result[0].copied == 1
    assert close_done.is_set()


def test_closed_session_rejected(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    source = tmp_path / "source.txt"
    source.write_text("x")
    dest = session.root / "dest"
    dest.mkdir()
    service = _make_service(session, file_operations)
    session.close()

    with pytest.raises(RuntimeError):
        service.import_sources([source], dest)

    bootstrap.library_service.close()
