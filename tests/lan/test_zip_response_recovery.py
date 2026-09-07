"""Retry ownership contracts for temporary ZIP HTTP responses."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from AssetsManager.lan import temporary_file_response, zip_cleanup
from AssetsManager.lan.temporary_file_response import (
    TemporaryFileResponse,
    _TemporaryFileOwner,
)


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _retry_service(monkeypatch: pytest.MonkeyPatch, clock: _Clock) -> zip_cleanup.ZipCleanupService:
    service = zip_cleanup.ZipCleanupService(clock=clock, start_worker=False)
    monkeypatch.setattr(zip_cleanup, "get_process_zip_cleanup", lambda: service)
    return service


def test_failed_close_retries_then_releases_archive_callback(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "close-retry.zip"
    archive.write_bytes(b"archive")
    clock = _Clock()
    service = _retry_service(monkeypatch, clock)
    callback_calls: list[str] = []

    class FlakyFile:
        def __init__(self) -> None:
            self.fail = True
            self.closed = False

        def close(self) -> None:
            if self.fail:
                raise OSError("still busy")
            self.closed = True

    opened = FlakyFile()
    owner = _TemporaryFileOwner(str(archive), lambda: callback_calls.append("released"))
    owner.begin_open()
    owner.cleanup()

    assert owner.finish_open(opened) is False
    assert archive.exists()
    assert callback_calls == []
    assert service.snapshot()["pending_count"] == 1

    clock.advance(1)
    assert service.run_due() == 1
    assert archive.exists()
    assert callback_calls == []
    assert service.snapshot()["last_error_type"] == "OSError"

    opened.fail = False
    clock.advance(2)
    assert service.run_due() == 1
    assert opened.closed
    assert not archive.exists()
    assert callback_calls == ["released"]
    assert service.snapshot()["pending_count"] == 0

    assert owner.cleanup() is True
    assert callback_calls == ["released"]


def test_retry_reports_custom_close_error_then_releases_once(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "custom-close-retry.zip"
    archive.write_bytes(b"archive")
    clock = _Clock()
    service = _retry_service(monkeypatch, clock)
    callback_calls: list[str] = []

    class CloseDenied(Exception):
        def __init__(self, error_code: int) -> None:
            self.error_code = error_code
            super().__init__(error_code)

    class FlakyFile:
        def __init__(self) -> None:
            self.fail = True

        def close(self) -> None:
            if self.fail:
                raise CloseDenied(32)

    opened = FlakyFile()
    owner = _TemporaryFileOwner(str(archive), lambda: callback_calls.append("released"))
    owner.begin_open()
    owner.cleanup()
    assert owner.finish_open(opened) is False

    clock.advance(1)
    assert service.run_due() == 1
    assert service.snapshot()["last_error_type"] == "CloseDenied"
    assert callback_calls == []

    opened.fail = False
    clock.advance(2)
    assert service.run_due() == 1
    assert callback_calls == ["released"]
    assert owner.cleanup() is True
    assert callback_calls == ["released"]


def test_permanent_unlink_failure_keeps_owner_and_callback(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "unlink-retry.zip"
    archive.write_bytes(b"archive")
    clock = _Clock()
    service = _retry_service(monkeypatch, clock)
    callback_calls: list[str] = []

    monkeypatch.setattr(
        temporary_file_response.os,
        "unlink",
        lambda _path: (_ for _ in ()).throw(OSError("still busy")),
    )
    owner = _TemporaryFileOwner(str(archive), lambda: callback_calls.append("released"))

    assert owner.cleanup() is False
    assert archive.exists()
    assert callback_calls == []
    assert service.snapshot()["pending_count"] == 1

    clock.advance(1)
    assert service.run_due() == 1
    assert archive.exists()
    assert callback_calls == []
    assert service.snapshot()["pending_count"] == 1

    assert service.snapshot()["last_error_type"] == "OSError"
    assert service.snapshot()["retry_attempts"] == 1


def test_retry_does_not_delete_replacement_at_failed_path(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "replaced.zip"
    archive.write_bytes(b"original")
    clock = _Clock()
    service = _retry_service(monkeypatch, clock)
    callback_calls: list[str] = []
    real_unlink = temporary_file_response.os.unlink
    attempts = 0

    def fail_once(path: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("busy")
        real_unlink(path)

    monkeypatch.setattr(temporary_file_response.os, "unlink", fail_once)
    owner = _TemporaryFileOwner(str(archive), lambda: callback_calls.append("released"))

    assert owner.cleanup() is False
    archive.write_bytes(b"replacement archive")
    clock.advance(1)
    assert service.run_due() == 1

    assert archive.read_bytes() == b"replacement archive"
    assert callback_calls == []
    assert service.snapshot()["pending_count"] == 1


def test_retry_releases_callback_when_original_was_removed_elsewhere(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "removed-elsewhere.zip"
    archive.write_bytes(b"original")
    clock = _Clock()
    service = _retry_service(monkeypatch, clock)
    callback_calls: list[str] = []
    real_unlink = temporary_file_response.os.unlink

    monkeypatch.setattr(
        temporary_file_response.os,
        "unlink",
        lambda _path: (_ for _ in ()).throw(OSError("busy")),
    )
    owner = _TemporaryFileOwner(str(archive), lambda: callback_calls.append("released"))
    assert owner.cleanup() is False

    real_unlink(archive)
    clock.advance(1)
    assert service.run_due() == 1
    assert callback_calls == ["released"]
    assert service.snapshot()["pending_count"] == 0


def test_lstat_failure_keeps_owner_without_unlinking(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "cannot-stat.zip"
    archive.write_bytes(b"archive")
    clock = _Clock()
    service = _retry_service(monkeypatch, clock)
    callback_calls: list[str] = []
    unlink_calls: list[str] = []

    monkeypatch.setattr(
        temporary_file_response.os,
        "lstat",
        lambda _path: (_ for _ in ()).throw(PermissionError("denied")),
    )
    monkeypatch.setattr(
        temporary_file_response.os,
        "unlink",
        lambda path: unlink_calls.append(str(path)),
    )
    owner = _TemporaryFileOwner(str(archive), lambda: callback_calls.append("released"))

    assert owner.cleanup() is False
    assert archive.exists()
    assert unlink_calls == []
    assert callback_calls == []
    assert service.snapshot()["pending_count"] == 1

    clock.advance(1)
    assert service.run_due() == 1
    assert service.snapshot()["last_error_type"] == "PermissionError"


def test_cleanup_during_open_waits_for_owner_before_unlink(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "opening.zip"
    archive.write_bytes(b"archive")
    unlinked: list[str] = []
    real_unlink = temporary_file_response.os.unlink

    def observe_unlink(path: str) -> None:
        unlinked.append(path)
        real_unlink(path)

    monkeypatch.setattr(temporary_file_response.os, "unlink", observe_unlink)
    owner = _TemporaryFileOwner(str(archive))
    owner.begin_open()

    assert owner.cleanup() is False
    assert archive.exists()
    assert unlinked == []

    opened = archive.open("rb")
    assert owner.finish_open(opened) is False
    assert opened.closed
    assert not archive.exists()
    assert unlinked == [str(archive)]


@pytest.mark.anyio
async def test_executor_rejection_queues_response_owner(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "executor-rejected.zip"
    archive.write_bytes(b"archive")
    clock = _Clock()
    service = _retry_service(monkeypatch, clock)
    loop = asyncio.get_running_loop()
    response = TemporaryFileResponse(None, str(archive), headers={})

    monkeypatch.setattr(
        loop,
        "run_in_executor",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("executor shut down")),
    )
    response._schedule_cleanup()

    assert archive.exists()
    assert service.snapshot()["pending_count"] == 1
    clock.advance(1)
    assert service.run_due() == 1
    assert not archive.exists()
