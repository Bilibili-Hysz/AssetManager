from __future__ import annotations

import os
import threading
import time

import pytest

from AssetsManager.lan.zip_cleanup import ZipCleanupService, cleanup_zip_path


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_manual_queue_backoff_cap_dedup_and_privacy() -> None:
    clock = Clock()
    service = ZipCleanupService(base_delay=2, max_delay=5, clock=clock, start_worker=False)
    calls: list[str] = []
    assert service.schedule("one", lambda: calls.append("first") or False)
    assert service.schedule("one", lambda: calls.append("replacement") or True)
    assert service.run_due() == 0
    clock.now = 2
    assert service.run_due() == 1
    assert calls == ["first"]
    assert service.snapshot() == {
        "pending_count": 1,
        "retry_attempts": 1,
        "completed_count": 0,
        "oldest_pending_seconds": 2.0,
        "last_error_type": None,
    }
    clock.now = 6
    service.run_due()
    clock.now = 11
    service.run_due()
    assert calls == ["first", "first", "first"]
    assert service.snapshot()["retry_attempts"] == 3


def test_queue_capacity_exception_and_concurrent_manual_run() -> None:
    clock = Clock()
    service = ZipCleanupService(max_pending=1, base_delay=1, clock=clock, start_worker=False)
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def attempt() -> bool:
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(1)
        raise RuntimeError("private path must not be reported")

    assert service.schedule("one", attempt)
    assert not service.schedule("two", lambda: True)
    clock.now = 1
    worker = threading.Thread(target=service.run_due)
    worker.start()
    assert entered.wait(1)
    assert service.run_due() == 0
    release.set()
    worker.join(1)
    assert calls == 1
    snapshot = service.snapshot()
    assert snapshot["last_error_type"] == "RuntimeError"
    assert "path" not in str(snapshot)
    service.close()


def test_worker_restarts_after_empty_queue() -> None:
    service = ZipCleanupService(base_delay=0.01)
    done = threading.Event()
    assert service.schedule("one", lambda: done.set() or True)
    assert done.wait(1)
    deadline = time.monotonic() + 1
    while service._worker is not None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert service._worker is None
    again = threading.Event()
    assert service.schedule("two", lambda: again.set() or True)
    assert again.wait(1)
    service.close()


def test_failed_worker_start_is_retained_and_duplicate_schedule_recovers(monkeypatch) -> None:
    from AssetsManager.lan import zip_cleanup

    original_start = threading.Thread.start
    starts = 0

    def fail_once(thread: threading.Thread) -> None:
        nonlocal starts
        starts += 1
        if starts == 1:
            raise RuntimeError("thread resources unavailable")
        original_start(thread)

    monkeypatch.setattr(zip_cleanup.threading.Thread, "start", fail_once)
    service = ZipCleanupService(base_delay=0.01)
    completed = threading.Event()
    attempt_calls = 0

    def attempt() -> bool:
        nonlocal attempt_calls
        attempt_calls += 1
        completed.set()
        return True

    assert service.schedule("entry", attempt)
    assert service.snapshot()["pending_count"] == 1
    assert service.snapshot()["last_error_type"] == "RuntimeError"
    assert service.schedule("entry", lambda: False)
    assert completed.wait(1)
    assert attempt_calls == 1
    service.close()


def test_cleanup_path_success_missing_and_distinct_callbacks(tmp_path) -> None:
    path = tmp_path / "archive.zip"
    path.write_bytes(b"content")
    callbacks: list[str] = []
    assert cleanup_zip_path(path, lambda: callbacks.append("deleted"))
    assert not path.exists()
    assert callbacks == ["deleted"]
    assert cleanup_zip_path(path, lambda: callbacks.append("missing"))
    assert callbacks == ["deleted", "missing"]


def test_cleanup_retry_does_not_delete_replaced_path(monkeypatch, tmp_path) -> None:
    path = tmp_path / "archive.zip"
    path.write_bytes(b"old")
    real_unlink = os.unlink
    callbacks: list[str] = []
    failed = False

    def flaky_unlink(value: str | os.PathLike[str]) -> None:
        nonlocal failed
        if os.path.normcase(os.path.abspath(value)) == os.path.normcase(os.path.abspath(path)) and not failed:
            failed = True
            raise PermissionError("locked")
        real_unlink(value)

    monkeypatch.setattr("AssetsManager.lan.zip_cleanup.os.unlink", flaky_unlink)
    # Test the path attempt through a local manual service to avoid mutating
    # the production singleton's timing state.
    from AssetsManager.lan import zip_cleanup

    normalized = os.path.normcase(os.path.abspath(path))
    attempt = zip_cleanup._PathCleanupAttempt(
        normalized, zip_cleanup._fingerprint(normalized), lambda: callbacks.append("done")
    )
    with pytest.raises(PermissionError):
        attempt()
    real_unlink(path)
    path.write_bytes(b"replacement")
    with pytest.raises(zip_cleanup.IdentityChangedError):
        attempt()
    assert path.read_bytes() == b"replacement"
    assert callbacks == []


def test_cleanup_callback_runs_once_after_retry(monkeypatch, tmp_path) -> None:
    path = tmp_path / "archive.zip"
    path.write_bytes(b"content")
    real_unlink = os.unlink
    failures = 0
    callbacks: list[str] = []

    def flaky_unlink(value: str | os.PathLike[str]) -> None:
        nonlocal failures
        if os.path.normcase(os.path.abspath(value)) == os.path.normcase(os.path.abspath(path)) and failures == 0:
            failures += 1
            raise PermissionError("locked")
        real_unlink(value)

    monkeypatch.setattr("AssetsManager.lan.zip_cleanup.os.unlink", flaky_unlink)
    from AssetsManager.lan import zip_cleanup

    normalized = os.path.normcase(os.path.abspath(path))
    attempt = zip_cleanup._PathCleanupAttempt(
        normalized, zip_cleanup._fingerprint(normalized), lambda: callbacks.append("done")
    )
    with pytest.raises(PermissionError):
        attempt()
    assert attempt()
    assert attempt()
    assert callbacks == ["done"]


def test_cleanup_zip_path_records_permission_error_without_releasing_callback(monkeypatch, tmp_path) -> None:
    from AssetsManager.lan import zip_cleanup

    path = tmp_path / "archive.zip"
    path.write_bytes(b"content")
    clock = Clock()
    service = ZipCleanupService(base_delay=1, clock=clock, start_worker=False)
    monkeypatch.setattr(zip_cleanup, "_PROCESS_ZIP_CLEANUP", service)
    monkeypatch.setattr(
        zip_cleanup.os,
        "unlink",
        lambda _value: (_ for _ in ()).throw(PermissionError("locked")),
    )
    callbacks: list[str] = []

    assert not cleanup_zip_path(path, lambda: callbacks.append("released"))
    assert service.snapshot()["pending_count"] == 1
    assert callbacks == []
    clock.now = 1
    assert service.run_due() == 1
    assert service.snapshot()["last_error_type"] == "PermissionError"
    assert callbacks == []


def test_full_cleanup_queue_keeps_existing_intent_and_does_not_release_rejected_callback(
    monkeypatch, tmp_path
) -> None:
    from AssetsManager.lan import zip_cleanup

    path = tmp_path / "archive.zip"
    path.write_bytes(b"content")
    service = ZipCleanupService(max_pending=1, start_worker=False)
    monkeypatch.setattr(zip_cleanup, "_PROCESS_ZIP_CLEANUP", service)
    monkeypatch.setattr(
        zip_cleanup.os,
        "unlink",
        lambda _value: (_ for _ in ()).throw(PermissionError("locked")),
    )
    retained: list[str] = []
    rejected: list[str] = []

    assert service.schedule("retained", lambda: retained.append("ran") or False)
    assert not cleanup_zip_path(path, lambda: rejected.append("released"))
    assert service.snapshot()["pending_count"] == 1
    assert retained == []
    assert rejected == []


@pytest.mark.parametrize(
    ("max_pending", "base_delay", "max_delay"),
    [
        (True, 1, 60),
        (0, 1, 60),
        (1, 0, 60),
        (1, float("nan"), 60),
        (1, float("inf"), 60),
        (1, 2, 1),
        (1, 1, float("nan")),
        (1, 1, float("inf")),
    ],
)
def test_cleanup_service_rejects_invalid_bounds(max_pending, base_delay, max_delay) -> None:
    with pytest.raises(ValueError):
        ZipCleanupService(max_pending=max_pending, base_delay=base_delay, max_delay=max_delay)


def test_permanent_failure_backoff_caps_without_integer_overflow() -> None:
    clock = Clock()
    service = ZipCleanupService(base_delay=1, max_delay=60, clock=clock, start_worker=False)
    assert service.schedule("forever", lambda: False)
    for _ in range(1_101):
        clock.now += 60
        assert service.run_due() == 1
    snapshot = service.snapshot()
    assert snapshot["pending_count"] == 1
    assert snapshot["retry_attempts"] == 1_101
    assert service._pending["forever"].retry_delay == 60


def test_worker_waits_while_manual_runner_owns_the_only_entry(monkeypatch) -> None:
    from AssetsManager.lan import zip_cleanup

    clock = Clock()
    service = ZipCleanupService(base_delay=1, clock=clock, start_worker=False)
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    all_running_wait = threading.Event()

    def attempt() -> bool:
        entered.set()
        release.wait(1)
        completed.set()
        return True

    original_wait = threading.Condition.wait

    def observed_wait(condition: threading.Condition, timeout: float | None = None) -> bool:
        if condition is service._condition and timeout is None:
            all_running_wait.set()
        return original_wait(condition, timeout)

    monkeypatch.setattr(zip_cleanup.threading.Condition, "wait", observed_wait)
    assert service.schedule("entry", attempt)
    clock.now = 1
    manual = threading.Thread(target=service.run_due)
    manual.start()
    assert entered.wait(1)
    # Start the daemon only after the manual runner has claimed the entry.
    # Duplicate scheduling wakes it and must take its all-running wait branch.
    service._start_worker = True
    assert service.schedule("entry", lambda: False)
    assert all_running_wait.wait(1)
    release.set()
    manual.join(1)
    assert completed.is_set()
    deadline = time.monotonic() + 1
    while service._worker is not None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert service._worker is None
    service.close()


def test_cleanup_path_stat_failure_and_initial_identity_race_are_queued(monkeypatch, tmp_path) -> None:
    from AssetsManager.lan import zip_cleanup

    path = tmp_path / "archive.zip"
    path.write_bytes(b"content")
    service = ZipCleanupService(start_worker=False)
    monkeypatch.setattr(zip_cleanup, "_PROCESS_ZIP_CLEANUP", service)
    callbacks: list[str] = []
    real_lstat = os.lstat

    monkeypatch.setattr(
        zip_cleanup.os,
        "lstat",
        lambda _value: (_ for _ in ()).throw(PermissionError("blocked")),
    )
    assert not cleanup_zip_path(path, lambda: callbacks.append("stat"))
    assert callbacks == []

    lstat_calls = 0

    def changed_on_second_stat(value: str | os.PathLike[str]):
        nonlocal lstat_calls
        lstat_calls += 1
        result = real_lstat(value)
        if lstat_calls == 2:
            fields = list(result)
            fields[1] += 1
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(zip_cleanup.os, "lstat", changed_on_second_stat)
    assert not cleanup_zip_path(path, lambda: callbacks.append("changed"))
    assert callbacks == []
    assert service.snapshot()["pending_count"] == 2
