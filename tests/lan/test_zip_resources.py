"""Concurrency and ownership contracts for process-wide ZIP resources."""
from __future__ import annotations

import concurrent.futures
import threading
from pathlib import Path

import pytest

from AssetsManager.lan import temporary_file_response
from AssetsManager.lan.temporary_file_response import _TemporaryFileOwner
from AssetsManager.lan.zip_resources import (
    MAX_ZIP_OUTPUT_BYTES,
    ZIP_BUDGET_APP_KEY,
    ZipResourceBudget,
    get_process_zip_budget,
)


def test_budget_defaults_and_app_key_contract() -> None:
    budget = ZipResourceBudget()

    assert MAX_ZIP_OUTPUT_BYTES == 512 * 1024 * 1024
    assert budget.max_jobs == 4
    assert budget.max_reserved_bytes == 2 * 1024 * 1024 * 1024
    assert ZIP_BUDGET_APP_KEY is not None
    assert get_process_zip_budget() is get_process_zip_budget()


def test_exact_job_and_byte_boundaries_are_admitted() -> None:
    budget = ZipResourceBudget(max_jobs=2, max_reserved_bytes=10)
    first = budget.try_acquire(6)
    second = budget.try_acquire(4)

    assert first is not None
    assert second is not None
    assert budget.snapshot() == {"active_jobs": 2, "reserved_bytes": 10}
    assert budget.try_acquire(0) is None

    first.release()
    assert budget.snapshot() == {"active_jobs": 1, "reserved_bytes": 4}
    assert budget.try_acquire(7) is None
    second.release()
    assert budget.snapshot() == {"active_jobs": 0, "reserved_bytes": 0}

    exact = budget.try_acquire(10)
    assert exact is not None
    assert budget.snapshot() == {"active_jobs": 1, "reserved_bytes": 10}
    exact.release()


def test_retain_handles_share_one_count_and_release_is_idempotent() -> None:
    budget = ZipResourceBudget(max_jobs=1, max_reserved_bytes=100)
    owner = budget.try_acquire(25)
    assert owner is not None
    child = owner.retain()
    grandchild = child.retain()

    owner.release()
    owner.release()
    assert budget.snapshot() == {"active_jobs": 1, "reserved_bytes": 25}
    child.release()
    child.release()
    assert budget.snapshot() == {"active_jobs": 1, "reserved_bytes": 25}
    grandchild.release()
    grandchild.release()
    assert budget.snapshot() == {"active_jobs": 0, "reserved_bytes": 0}
    with pytest.raises(RuntimeError):
        owner.retain()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_jobs", True),
        ("max_jobs", 1.0),
        ("max_jobs", -1),
        ("max_reserved_bytes", False),
        ("max_reserved_bytes", "10"),
        ("max_reserved_bytes", -1),
    ],
)
def test_constructor_rejects_invalid_resource_limits(field: str, value: object) -> None:
    kwargs = {field: value}
    with pytest.raises(ValueError):
        ZipResourceBudget(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [True, False, 1.5, "10", -1])
def test_invalid_acquire_input_does_not_change_counters(value: object) -> None:
    budget = ZipResourceBudget(max_jobs=2, max_reserved_bytes=10)
    before = budget.snapshot()

    with pytest.raises(ValueError):
        budget.try_acquire(value)  # type: ignore[arg-type]

    assert budget.snapshot() == before


def test_competing_threads_cannot_exceed_either_limit() -> None:
    budget = ZipResourceBudget(max_jobs=4, max_reserved_bytes=20)
    barrier = threading.Barrier(32)
    acquired = []

    def attempt() -> None:
        reservation = budget.try_acquire(5)
        if reservation is not None:
            acquired.append(reservation)
        barrier.wait(timeout=10)
        if reservation is not None:
            reservation.release()

    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
        futures = [pool.submit(attempt) for _ in range(32)]
        for future in futures:
            future.result(timeout=15)

    assert len(acquired) == 4
    assert budget.snapshot() == {"active_jobs": 0, "reserved_bytes": 0}


def test_late_open_deletes_file_then_calls_callback_once(tmp_path: Path) -> None:
    archive = tmp_path / "late.zip"
    archive.write_bytes(b"archive")
    callback_calls = []
    owner: _TemporaryFileOwner

    def callback() -> None:
        callback_calls.append("called")
        # Re-entry must not deadlock: cleanup runs after the owner lock is
        # released and sees the completed state.
        owner.cleanup()

    owner = _TemporaryFileOwner(str(archive), callback)
    owner.begin_open()
    owner.cleanup()
    assert callback_calls == []

    opened = archive.open("rb")
    assert owner.finish_open(opened) is False
    assert opened.closed
    assert not archive.exists()
    assert callback_calls == ["called"]
    owner.cleanup()
    assert callback_calls == ["called"]


def test_same_handle_can_be_released_concurrently_without_underflow() -> None:
    budget = ZipResourceBudget(max_jobs=1, max_reserved_bytes=10)
    reservation = budget.try_acquire(10)
    assert reservation is not None
    barrier = threading.Barrier(8)

    def release() -> None:
        barrier.wait(timeout=10)
        reservation.release()

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(release) for _ in range(8)]
        for future in futures:
            future.result(timeout=15)
    assert budget.snapshot() == {"active_jobs": 0, "reserved_bytes": 0}


def test_delete_failure_does_not_release_callback_until_retry(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "delete-failure.zip"
    archive.write_bytes(b"archive")
    callback_calls = []
    owner = _TemporaryFileOwner(str(archive), lambda: callback_calls.append("called"))
    owner.begin_open()
    owner.cleanup()
    opened = archive.open("rb")

    real_unlink = temporary_file_response.os.unlink
    monkeypatch.setattr(
        temporary_file_response.os,
        "unlink",
        lambda _path: (_ for _ in ()).throw(OSError("busy")),
    )
    assert owner.finish_open(opened) is False
    assert opened.closed
    assert callback_calls == []
    assert archive.exists()

    monkeypatch.setattr(temporary_file_response.os, "unlink", real_unlink)
    owner.cleanup()
    assert callback_calls == ["called"]
    assert not archive.exists()


def test_close_failure_does_not_release_callback_until_close_succeeds(tmp_path: Path) -> None:
    archive = tmp_path / "close-failure.zip"
    archive.write_bytes(b"archive")
    callback_calls = []

    class FlakyFile:
        def __init__(self) -> None:
            self.fail = True
            self.closed = False

        def close(self) -> None:
            if self.fail:
                raise OSError("busy")
            self.closed = True

    opened = FlakyFile()
    owner = _TemporaryFileOwner(str(archive), lambda: callback_calls.append("called"))
    owner.begin_open()
    owner.cleanup()
    assert owner.finish_open(opened) is False
    assert callback_calls == []
    assert archive.exists()

    opened.fail = False
    owner.cleanup()
    assert opened.closed
    assert callback_calls == ["called"]
    assert not archive.exists()
