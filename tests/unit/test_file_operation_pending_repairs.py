"""Unit tests for the durable pending-projection-repair fallback.

When a reconciliation enqueue fails (e.g. disk full), the enqueue request is
persisted as ``pending_projection_repairs/<timestamp>-<uuid>.json`` and
re-enqueued by ``drain_pending_projection_repairs`` (wired into bootstrap
startup).  A marker whose re-enqueue fails again is kept for the next
attempt; drain failures never raise.
"""
import json
from pathlib import Path
from types import SimpleNamespace

from AssetsManager.application.file_operation_service import FileOperationService
from AssetsManager.application.reconciliation_queue import ReconciliationKind
from AssetsManager.core.performance import PerformanceRecorder


def _repair_payload(scope: Path, target: Path) -> dict:
    return {
        "payload_version": 1,
        "operation_kind": "delete",
        "operation_id": "file-op-test",
        "projection_set": [
            "asset_index", "tags", "metadata", "favorites",
            "thumbnail_rows", "thumbnail_bytes",
        ],
        "scope_path": str(scope),
        "target_path": str(target),
        "delete_mode": "permanent",
        "expected_state": {"target_absent": True},
    }


class _FailingQueue:
    """Queue whose enqueues fail a configurable number of times."""

    def __init__(self, failures: int = 10**9):
        self.calls = []
        self.failures = failures

    def enqueue_or_merge(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) <= self.failures:
            raise RuntimeError("reconciliation queue unavailable")


class _WorkingQueue:
    def __init__(self):
        self.enqueued = []

    def enqueue_or_merge(self, **kwargs):
        self.enqueued.append(kwargs)


def _service(tmp_path: Path, queue) -> FileOperationService:
    return FileOperationService(
        session=SimpleNamespace(event_token=None),
        reconciliation_queue=queue,
        pending_projection_repairs_dir=tmp_path / "pending_projection_repairs",
    )


def _record_issue(service: FileOperationService, payload: dict | None) -> None:
    target = Path("C:/lib/asset.txt").resolve()
    service._record_index_refresh_issue(
        "projection_cleanup",
        target,
        status="failed",
        failure=RuntimeError("injected"),
        reconciliation_path=target.parent,
        repair_payload=payload,
    )


def test_enqueue_failure_persists_marker_and_drain_reenqueues(tmp_path):
    failing = _service(tmp_path, _FailingQueue())
    payload = _repair_payload(Path("C:/lib").resolve(), Path("C:/lib/asset.txt").resolve())

    _record_issue(failing, payload)

    directory = tmp_path / "pending_projection_repairs"
    markers = list(directory.glob("*.json"))
    # Both lost requests are persisted: the projection repair and the
    # generic rescan that follows it.
    assert len(markers) == 2
    requests = [
        json.loads(marker.read_text(encoding="utf-8"))["request"]
        for marker in markers
    ]
    by_kind = {request["kind"]: request for request in requests}
    assert set(by_kind) == {
        "filesystem_projection_repair",
        "asset_index_root_rescan",
    }
    assert by_kind["filesystem_projection_repair"]["payload"] == payload
    assert by_kind["filesystem_projection_repair"]["path"] == str(Path("C:/lib").resolve())

    working = _WorkingQueue()
    drained_service = FileOperationService(
        session=SimpleNamespace(event_token=None),
        reconciliation_queue=working,
        pending_projection_repairs_dir=directory,
    )
    assert drained_service.drain_pending_projection_repairs() == 2
    assert list(directory.glob("*.json")) == []
    kinds = {call["kind"] for call in working.enqueued}
    assert kinds == {
        ReconciliationKind.FILESYSTEM_PROJECTION_REPAIR,
        ReconciliationKind.ASSET_INDEX_ROOT_RESCAN,
    }
    repair_call = next(
        call for call in working.enqueued
        if call["kind"] is ReconciliationKind.FILESYSTEM_PROJECTION_REPAIR
    )
    assert repair_call["payload"] == payload
    assert repair_call["path"] == str(Path("C:/lib").resolve())


def test_generic_enqueue_failure_persists_rescan_marker(tmp_path):
    service = _service(tmp_path, _FailingQueue())

    _record_issue(service, None)

    directory = tmp_path / "pending_projection_repairs"
    markers = list(directory.glob("*.json"))
    assert len(markers) == 1
    document = json.loads(markers[0].read_text(encoding="utf-8"))
    assert document["request"]["kind"] == "asset_index_root_rescan"
    assert document["request"]["payload"] is None


def test_drain_keeps_marker_when_reenqueue_fails_again(tmp_path):
    queue = _FailingQueue()
    service = _service(tmp_path, queue)

    _record_issue(service, None)

    directory = tmp_path / "pending_projection_repairs"
    assert len(list(directory.glob("*.json"))) == 1
    assert service.drain_pending_projection_repairs() == 0
    assert len(list(directory.glob("*.json"))) == 1


def test_drain_keeps_unreadable_marker_and_never_raises(tmp_path):
    directory = tmp_path / "pending_projection_repairs"
    directory.mkdir()
    (directory / "1700000000-corrupt.json").write_text("{not json", encoding="utf-8")
    service = _service(tmp_path, _WorkingQueue())

    assert service.drain_pending_projection_repairs() == 0
    assert (directory / "1700000000-corrupt.json").exists()


def test_projection_enqueue_failure_is_not_masked_by_generic_queued(tmp_path):
    # First enqueue (projection repair) fails, second (generic rescan)
    # succeeds: the recorded state must stay distinguishable from a plain
    # "queued" so the lost projection repair stays visible in telemetry.
    recorder = PerformanceRecorder(enabled=True)
    service = FileOperationService(
        session=SimpleNamespace(event_token=None),
        performance_recorder=recorder,
        reconciliation_queue=_FailingQueue(failures=1),
        pending_projection_repairs_dir=tmp_path / "pending_projection_repairs",
    )
    payload = _repair_payload(Path("C:/lib").resolve(), Path("C:/lib/asset.txt").resolve())

    _record_issue(service, payload)

    events = [event for event in recorder.recent() if event.name == "file.index_refresh"]
    assert len(events) == 1
    assert events[0].attributes["reconciliation_state"] == "generic_queued_projection_failed"
    assert events[0].attributes["reconciliation_error_type"] == "RuntimeError"
    # The projection repair request is durably persisted for the next drain.
    directory = tmp_path / "pending_projection_repairs"
    markers = list(directory.glob("*.json"))
    assert len(markers) == 1
    document = json.loads(markers[0].read_text(encoding="utf-8"))
    assert document["request"]["kind"] == "filesystem_projection_repair"
