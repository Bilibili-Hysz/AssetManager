"""Focused tests for the low-priority integrity-service bug fixes.

Covers:
- Bug 9/13: busy/locked quick_check is retried with backoff and classified as
  a retryable warning instead of marking the library unhealthy.
- Bug 11: run() refuses to start a pass once the service is closed.
- Bug 12: a completed scheduled run clears any stale schedule error.
- Bug 14: prune revalidation (filesystem stats) runs before the connection
  write lock is taken; the lock only guards batched pure-SQL deletes.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading
import time

import pytest

from AssetsManager.application import ApplicationBootstrap, DatabaseIntegrityService
from AssetsManager.application import database_integrity_service as integrity_module
from AssetsManager.application.database_integrity_service import _QuickCheckBusy


def _open_session(tmp_path: Path):
    bootstrap = ApplicationBootstrap()
    library = tmp_path / "library"
    library.mkdir()
    session = bootstrap.library_service.open_session(library)
    return bootstrap, session


def _make_service(session) -> DatabaseIntegrityService:
    return DatabaseIntegrityService(
        connection_provider=session.connection_for,
        session=session,
    )


class _FlakyConnection:
    """Wrap a real connection; raise busy for the first N quick_check calls."""

    def __init__(self, real_conn, *, fail_times: int) -> None:
        self._real_conn = real_conn
        self._fail_times = fail_times
        self.quick_check_calls = 0
        self.busy_raised = 0

    def execute(self, sql, *parameters):
        if sql.strip().upper().startswith("PRAGMA QUICK_CHECK"):
            self.quick_check_calls += 1
            if self.quick_check_calls <= self._fail_times:
                self.busy_raised += 1
                raise sqlite3.OperationalError("database is locked")
        return self._real_conn.execute(sql, *parameters)

    def close(self):
        self._real_conn.close()


@pytest.fixture()
def busy_db(tmp_path, monkeypatch):
    """Open a session and force _quick_check's connections through a wrapper.

    Yields (bootstrap, session, factory) where factory(fail_times) installs a
    FlakyConnection for the given number of initial busy failures and returns
    it so the test can inspect attempt counts.
    """
    bootstrap, session = _open_session(tmp_path)
    database_file = session.data_dir / "assetmanager.db"
    real_conn = sqlite3.connect(str(database_file), check_same_thread=False)
    created = {}

    def connect(*_args, **_kwargs):
        flaky = _FlakyConnection(real_conn, fail_times=created["fail_times"])
        created["flaky"] = flaky
        return flaky

    monkeypatch.setattr(
        integrity_module.sqlite3, "connect", connect
    )

    def factory(fail_times):
        created["fail_times"] = fail_times
        created["flaky"] = None
        return created

    created["fail_times"] = 0
    try:
        yield bootstrap, session, factory
    finally:
        bootstrap.library_service.close()


def test_quick_check_retries_busy_then_succeeds(busy_db):
    bootstrap, session, factory = busy_db
    service = _make_service(session)
    created = factory(fail_times=1)
    assert service._quick_check() == "ok"
    flaky = created["flaky"]
    assert flaky.quick_check_calls == 2
    assert flaky.busy_raised == 1


def test_quick_check_busy_exhaustion_raises_retryable_with_backoff(
    busy_db, monkeypatch
):
    bootstrap, session, factory = busy_db
    service = _make_service(session)
    created = factory(fail_times=integrity_module._BUSY_MAX_ATTEMPTS)
    sleeps = []
    real_sleep = time.sleep

    def record_sleep(seconds):
        sleeps.append(seconds)
        real_sleep(0)

    monkeypatch.setattr(integrity_module.time, "sleep", record_sleep)
    with pytest.raises(_QuickCheckBusy):
        service._quick_check()
    flaky = created["flaky"]
    assert flaky.quick_check_calls == integrity_module._BUSY_MAX_ATTEMPTS == 3
    assert sleeps == [
        integrity_module._BUSY_RETRY_BASE_DELAY,
        integrity_module._BUSY_RETRY_BASE_DELAY * 2,
    ]


def test_quick_check_busy_report_is_retryable_warning_not_unhealthy(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = _make_service(session)
        monkeypatch.setattr(
            service,
            "_quick_check",
            lambda: (_ for _ in ()).throw(_QuickCheckBusy("database is locked")),
        )
        report = service.run()
        assert report.healthy
        assert report.quick_check == "ok"
        assert report.issues == ()
        assert any("busy" in warning and "retry" in warning for warning in report.warnings)
    finally:
        bootstrap.library_service.close()


def test_run_after_stop_returns_without_running_pass(tmp_path, monkeypatch):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = _make_service(session)
        monkeypatch.setattr(
            service,
            "_run_pass",
            lambda: pytest.fail("run() must not start a pass after stop"),
        )
        service.stop()
        report = service.run()
        assert not report.healthy
        assert report.quick_check == "error"
        assert report.issues == ("service_closed",)
        assert service.last_schedule_error == "service_closed"
    finally:
        bootstrap.library_service.close()


def test_scheduled_completion_clears_stale_schedule_error(tmp_path, monkeypatch):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = _make_service(session)
        started = threading.Event()
        release = threading.Event()
        original_run = service.run

        def blocked_run():
            started.set()
            release.wait(timeout=5)
            return original_run()

        monkeypatch.setattr(service, "run", blocked_run)
        assert service.schedule()
        assert started.wait(timeout=5)
        # A concurrent schedule attempt records a stale error while the
        # worker is busy; completion must clear it.
        assert not service.schedule()
        assert service.last_schedule_error == "already_running"
        release.set()
        deadline = time.monotonic() + 10
        while service.running and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not service.running
        assert service.last_schedule_error is None
    finally:
        bootstrap.library_service.close()


def test_prune_revalidates_outside_write_lock_and_deletes_in_batch(tmp_path, monkeypatch):
    bootstrap, session = _open_session(tmp_path)
    try:
        existing = session.root / "existing.txt"
        existing.write_text("present", encoding="utf-8")
        missing = session.root / "missing.txt"
        orphan_source = session.root / "missing.png"
        conn = session.connection_for()
        conn.executemany(
            "INSERT INTO file_meta (file_path, notes) VALUES (?, ?)",
            ((str(existing), "keep"), (str(missing), "remove")),
        )
        conn.executemany(
            "INSERT INTO thumbnail_cache (cache_key, source_path, source_mtime) "
            "VALUES (?, ?, ?)",
            (("deadbeef", str(orphan_source), 1.0),),
        )
        conn.commit()

        service = _make_service(session)
        state = {"in_lock": False, "stats_while_locked": 0}
        original_lock = integrity_module.db_write_lock

        @contextmanager
        def tracked_write_lock(conn=None):
            state["in_lock"] = True
            try:
                with original_lock(conn):
                    yield
            finally:
                state["in_lock"] = False

        monkeypatch.setattr(integrity_module, "db_write_lock", tracked_write_lock)
        original_exists = service._exists

        def tracked_exists(path):
            if state["in_lock"]:
                state["stats_while_locked"] += 1
            return original_exists(path)

        monkeypatch.setattr(service, "_exists", tracked_exists)
        report = service.run()
        assert report.healthy
        assert report.metadata_removed == 1
        assert report.thumbnail_metadata_removed == 1
        assert state["stats_while_locked"] == 0
        assert conn.execute(
            "SELECT notes FROM file_meta WHERE file_path=?", (str(existing),)
        ).fetchone() == ("keep",)
    finally:
        bootstrap.library_service.close()


def test_prune_metadata_batches_delete_over_batch_size(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    try:
        conn = session.connection_for()
        total = integrity_module._DELETE_BATCH_SIZE * 2 + 5
        paths = [
            str(session.root / f"missing-{index:04d}.txt") for index in range(total)
        ]
        conn.executemany(
            "INSERT INTO file_meta (file_path, notes) VALUES (?, ?)",
            ((path, "remove") for path in paths),
        )
        conn.commit()
        service = _make_service(session)
        report = service.run()
        assert report.healthy
        assert report.metadata_removed == total
        assert conn.execute("SELECT COUNT(*) FROM file_meta").fetchone() == (0,)
    finally:
        bootstrap.library_service.close()
