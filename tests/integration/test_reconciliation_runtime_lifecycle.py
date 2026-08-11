"""Integration tests for reconciliation runtime lifecycle."""

import pytest

from AssetsManager.application import (
    ApplicationBootstrap,
    ReconciliationWorkerStopTimeout,
)


def test_bootstrap_starts_and_stops_reconciliation_worker(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    try:
        runtime = bootstrap.runtime_for(session)
        service = runtime.services.reconciliation_service

        assert service is not None
        assert service.is_running
    finally:
        bootstrap.library_service.close()


def test_close_session_retries_after_reconciliation_stop_timeout(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    runtime = bootstrap.runtime_for(session)
    service = runtime.services.reconciliation_service
    assert service is not None
    original_stop = service.stop
    calls = 0

    def stop_once_then_delegate(*, timeout=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ReconciliationWorkerStopTimeout("controlled stop timeout")
        return original_stop(timeout=timeout)

    monkeypatch.setattr(service, "stop", stop_once_then_delegate)
    try:
        with pytest.raises(ReconciliationWorkerStopTimeout, match="controlled stop timeout"):
            bootstrap.library_service.close_session(session)

        assert session.is_closed
        assert runtime._state == "failed"
        assert runtime._cleanup_in_progress is False
        assert runtime._adapter_cleanup_in_progress is False
        assert service.is_running

        bootstrap.library_service.close_session(session)
        assert session.is_closed
        assert not service.is_running
        assert calls == 2
    finally:
        if not session.is_closed or service.is_running:
            try:
                bootstrap.library_service.close_session(session)
            except BaseException:
                pass
