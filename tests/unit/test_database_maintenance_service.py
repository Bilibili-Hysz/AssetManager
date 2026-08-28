from __future__ import annotations

import sqlite3
import threading
import time

import pytest

from AssetsManager.application.database_maintenance_service import (
    DatabaseMaintenanceService,
    MaintenanceFailureResult,
    VacuumResult,
)


def _service(session):
    return DatabaseMaintenanceService(
        connection_provider=session.connection_for,
        session=session,
    )


def test_database_size_reports_sqlite_file_size(opened_session):
    bootstrap, session = opened_session
    result = _service(session).database_size()
    assert result.database_path.is_file()
    assert result.size_bytes == result.database_path.stat().st_size
    assert result.size_bytes > 0


def test_closed_session_is_rejected(opened_session):
    bootstrap, session = opened_session
    service = _service(session)
    bootstrap.library_service.close_session(session)
    with pytest.raises(RuntimeError, match="closed LibrarySession"):
        service.database_size()
    with pytest.raises(RuntimeError, match="closed LibrarySession"):
        service.checkpoint()
    with pytest.raises(RuntimeError, match="closed LibrarySession"):
        service.vacuum()


def test_passive_checkpoint_returns_sqlite_result(opened_session):
    bootstrap, session = opened_session
    result = _service(session).checkpoint("PASSIVE")
    assert result.mode == "PASSIVE"
    assert result.success
    assert result.busy == 0
    assert result.log_frames >= 0
    assert result.checkpointed_frames >= 0


def test_checkpoint_failure_is_reported(opened_session):
    bootstrap, session = opened_session
    class FailingConnection:
        def __init__(self):
            self.busy_timeout = 4321

        def execute(self, sql, *args):
            if sql == "PRAGMA busy_timeout":
                return self
            if sql.startswith("PRAGMA busy_timeout="):
                self.busy_timeout = int(sql.split("=", 1)[1])
                return self
            if "wal_checkpoint" in sql:
                raise sqlite3.OperationalError("checkpoint unavailable")
            return self

        def fetchone(self):
            return (self.busy_timeout,)

    connection = FailingConnection()
    result = DatabaseMaintenanceService(
        connection_provider=lambda _root: connection,
        session=session,
    ).checkpoint()
    assert not result.success
    assert result.error == "checkpoint unavailable"
    assert connection.busy_timeout == 4321


def test_checkpoint_busy_result_preserves_connection_timeout(opened_session):
    bootstrap, session = opened_session
    class BusyConnection:
        def __init__(self):
            self.busy_timeout = 4321
            self._fetches = [(4321,), (1, 17, 3)]

        def execute(self, sql, *args):
            if sql == "PRAGMA busy_timeout":
                return self
            if sql.startswith("PRAGMA busy_timeout="):
                self.busy_timeout = int(sql.split("=", 1)[1])
            return self

        def fetchone(self):
            return self._fetches.pop(0)

    connection = BusyConnection()
    service = DatabaseMaintenanceService(
        connection_provider=lambda _root: connection,
        session=session,
    )
    result = service.checkpoint("FULL")

    assert result.busy == 1
    assert result.log_frames == 17
    assert result.checkpointed_frames == 3
    assert not result.success
    assert result.error == "WAL checkpoint is busy"
    assert connection.busy_timeout == 4321


def test_schedule_after_stop_reports_service_closed(opened_session):
    bootstrap, session = opened_session
    service = _service(session)
    service.stop()
    with pytest.raises(RuntimeError, match="Database maintenance service is closed"):
        service.schedule("checkpoint")
    assert service.last_schedule_error == "service_closed"


def test_checkpoint_cancellation_restores_connection_timeout(opened_session):
    bootstrap, session = opened_session
    class CancelConnection:
        def __init__(self):
            self.busy_timeout = 4321
            self.service = None

        def execute(self, sql, *args):
            if sql == "PRAGMA busy_timeout":
                return self
            if sql.startswith("PRAGMA busy_timeout="):
                self.busy_timeout = int(sql.split("=", 1)[1])
                return self
            if "wal_checkpoint" in sql:
                self.service._cancel_event.set()
                raise sqlite3.OperationalError("interrupted")
            return self

        def fetchone(self):
            return (self.busy_timeout,)

    connection = CancelConnection()
    service = DatabaseMaintenanceService(
        connection_provider=lambda _root: connection,
        session=session,
    )
    connection.service = service
    with pytest.raises(RuntimeError, match="Database maintenance cancelled"):
        service.checkpoint()
    assert connection.busy_timeout == 4321


def test_checkpoint_after_stop_is_rejected_as_closed_service(opened_session):
    bootstrap, session = opened_session
    service = _service(session)
    service.stop()
    with pytest.raises(RuntimeError, match="Database maintenance service is closed"):
        service.checkpoint()


def test_schedule_start_failure_retains_feedback_state(opened_session, monkeypatch):
    bootstrap, session = opened_session
    service = _service(session)

    def fail_start(_thread):
        raise RuntimeError("thread start failed")

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    assert not service.schedule("checkpoint")
    assert not service.running
    assert service.last_schedule_error == (
        "worker_start_failed: RuntimeError: thread start failed"
    )
    result = service.last_result
    assert isinstance(result, MaintenanceFailureResult)
    assert result.operation == "checkpoint"
    assert result.error == "RuntimeError: thread start failed"


def test_vacuum_has_explicit_unsupported_boundary(opened_session):
    bootstrap, session = opened_session
    result = _service(session).vacuum()
    assert isinstance(result, VacuumResult)
    assert not result.supported
    assert not result.success
    assert "maintenance coordinator" in result.reason


def test_vacuum_never_acquires_connection_and_remains_unsupported(opened_session):
    bootstrap, session = opened_session
    calls = []
    def provider(_root):
        calls.append(True)
        raise AssertionError("VACUUM must not acquire a connection")

    service = DatabaseMaintenanceService(
        connection_provider=provider,
        session=session,
    )
    result = service.vacuum()
    assert isinstance(result, VacuumResult)
    assert not result.supported
    assert calls == []

    # schedule() refuses VACUUM at the boundary: no worker, no result.
    assert service.schedule("vacuum") is False
    assert service.last_schedule_error == "vacuum_not_supported"
    assert not service.running
    assert service.last_result is None
    assert calls == []


def test_checkpoint_can_run_in_background_and_stop(opened_session, monkeypatch):
    bootstrap, session = opened_session
    release = threading.Event()
    try:
        service = _service(session)
        started = threading.Event()

        def blocked_checkpoint(mode="PASSIVE"):
            started.set()
            release.wait(timeout=2)
            return service.checkpoint(mode)

        monkeypatch.setattr(service, "checkpoint", blocked_checkpoint)
        assert service.schedule("checkpoint")
        assert started.wait(timeout=2)
        service.stop()
        release.set()
        service.stop()
        deadline = time.monotonic() + 2
        while service.running and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not service.running
    finally:
        release.set()




def test_schedule_rejects_invalid_checkpoint_mode_before_starting_worker(opened_session):
    bootstrap, session = opened_session
    service = _service(session)
    with pytest.raises(ValueError, match="Unsupported WAL checkpoint mode"):
        service.schedule("checkpoint", mode="not-a-mode")
    assert not service.running
    assert service.last_result is None


def test_background_failure_is_retained_for_product_feedback(opened_session, monkeypatch):
    bootstrap, session = opened_session
    service = _service(session)

    def fail_checkpoint(mode="PASSIVE"):
        raise RuntimeError("checkpoint exploded")

    monkeypatch.setattr(service, "checkpoint", fail_checkpoint)
    assert service.schedule("checkpoint")
    deadline = time.monotonic() + 2
    while service.running and time.monotonic() < deadline:
        time.sleep(0.01)

    result = service.last_result
    assert isinstance(result, MaintenanceFailureResult)
    assert result.operation == "checkpoint"
    assert result.error == "checkpoint exploded"
    assert not result.success


def test_background_schedule_is_single_flight(opened_session, monkeypatch):
    bootstrap, session = opened_session
    release = threading.Event()
    started = threading.Event()
    try:
        service = _service(session)

        def blocked_checkpoint(mode="PASSIVE"):
            started.set()
            release.wait(timeout=2)
            return service.checkpoint(mode)

        monkeypatch.setattr(service, "checkpoint", blocked_checkpoint)
        assert service.schedule("checkpoint")
        assert started.wait(timeout=2)
        assert service.schedule("checkpoint") is False
        assert service.last_schedule_error == "already_running"
    finally:
        release.set()
        service.stop()

def test_checkpoint_rejects_managed_foreign_root_provider(opened_session, tmp_path):
    from AssetsManager.core.database import DatabaseManager

    bootstrap, session = opened_session
    foreign_root = tmp_path / "foreign-library"
    foreign_root.mkdir()
    manager = DatabaseManager()
    try:
        foreign_connection = manager.connection_for(foreign_root)
        service = DatabaseMaintenanceService(
            connection_provider=lambda _root: foreign_connection,
            session=session,
        )

        with pytest.raises(ValueError, match="different library root"):
            service.checkpoint()
    finally:
        manager.close()


def test_schedule_after_session_close_records_session_closed(opened_session):
    bootstrap, session = opened_session
    service = _service(session)
    bootstrap.library_service.close_session(session)
    with pytest.raises(RuntimeError, match="closed LibrarySession"):
        service.schedule("checkpoint")
    assert service.last_schedule_error == "session_closed"


def test_schedule_vacuum_rejected_without_starting_worker(opened_session):
    bootstrap, session = opened_session
    service = _service(session)
    assert service.schedule("vacuum") is False
    assert service.last_schedule_error == "vacuum_not_supported"
    assert not service.running
    assert service.last_result is None


def test_completed_event_published_after_successful_background_run(opened_session):
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import MaintenanceChanged

    bootstrap, session = opened_session
    observed = []
    subscription = get_event_bus().subscribe(MaintenanceChanged, observed.append)
    try:
        service = _service(session)
        assert service.schedule("checkpoint")
        deadline = time.monotonic() + 2
        while service.running and time.monotonic() < deadline:
            time.sleep(0.01)

        assert not service.running
        assert [event.session_token for event in observed] == [session.event_token]
        assert observed[0].library_root == session.root_str
        assert observed[0].kind == "maintenance"
    finally:
        subscription.close()


def test_completed_event_published_after_failed_background_run(opened_session, monkeypatch):
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import MaintenanceChanged

    bootstrap, session = opened_session
    observed = []
    subscription = get_event_bus().subscribe(MaintenanceChanged, observed.append)
    try:
        service = _service(session)

        def fail_checkpoint(mode="PASSIVE"):
            raise RuntimeError("checkpoint exploded")

        monkeypatch.setattr(service, "checkpoint", fail_checkpoint)
        assert service.schedule("checkpoint")
        deadline = time.monotonic() + 2
        while service.running and time.monotonic() < deadline:
            time.sleep(0.01)

        assert not service.running
        assert isinstance(service.last_result, MaintenanceFailureResult)
        assert len(observed) == 1
        assert observed[0].session_token == session.event_token
        assert observed[0].kind == "maintenance"
    finally:
        subscription.close()
