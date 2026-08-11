"""Integration evidence for library-owner stop-the-world handoff.

These tests intentionally stay at the observable ownership boundary.  They do
not invent lifecycle events: the log is populated only by wrappers around the
existing Runtime, reconciliation worker, database, and lock APIs.
"""

from __future__ import annotations

import pytest

from AssetsManager.application import ApplicationBootstrap, ReconciliationWorkerStopTimeout


def _close_bootstrap(bootstrap: ApplicationBootstrap) -> None:
    """Best-effort bounded cleanup for a bootstrap used by an evidence test."""
    try:
        bootstrap.library_service.close()
    except BaseException:
        # The assertions in the test should report the lifecycle failure.  Do
        # not hide it behind fixture cleanup, but make a second close attempt
        # for retryable teardown states.
        try:
            bootstrap.library_service.close()
        except BaseException:
            pass


def test_library_owner_handoff_observes_stop_the_world_order(tmp_path, monkeypatch):
    """A new bootstrap acquires the root only after old runtime teardown commits."""
    library = tmp_path / "library"
    library.mkdir()
    events: list[str] = []

    old_bootstrap = ApplicationBootstrap()
    new_bootstrap = ApplicationBootstrap()
    old_session = old_bootstrap.library_service.open_session(library)
    old_runtime = old_bootstrap.runtime_for(old_session)
    old_reconciliation = old_runtime.services.reconciliation_service
    assert old_reconciliation is not None
    assert old_reconciliation.is_running

    original_mark_closing = old_runtime.mark_closing
    original_worker_stop = old_reconciliation.stop
    original_runtime_close = old_runtime.close
    # Capture the concrete DatabaseManager instance without introducing a new
    # production seam; ApplicationBootstrap already exposes its container.
    from AssetsManager.core.database import DatabaseManager

    database = old_bootstrap.resolve(DatabaseManager)
    original_db_close = database.close_library
    original_lock_release = old_bootstrap.library_service._release_library_lock

    def mark_closing():
        events.append("old_runtime_close_started")
        return original_mark_closing()

    def worker_stop(*args, **kwargs):
        events.append("old_worker_stop")
        return original_worker_stop(*args, **kwargs)

    def runtime_close():
        events.append("old_runtime_cleanup")
        return original_runtime_close()

    def db_close(root):
        events.append("old_db_release")
        return original_db_close(root)

    def lock_release(key):
        events.append("old_lock_release")
        return original_lock_release(key)

    monkeypatch.setattr(old_runtime, "mark_closing", mark_closing)
    monkeypatch.setattr(old_reconciliation, "stop", worker_stop)
    monkeypatch.setattr(old_runtime, "close", runtime_close)
    monkeypatch.setattr(database, "close_library", db_close)
    monkeypatch.setattr(old_bootstrap.library_service, "_release_library_lock", lock_release)

    try:
        events.append("old_owner_close_requested")
        old_bootstrap.library_service.close_session(old_session)

        assert old_session.is_closed
        assert not old_reconciliation.is_running
        assert old_runtime._state == "closed"

        events.append("new_owner_open_requested")
        new_session = new_bootstrap.library_service.open_session(library)
        events.append("new_owner_opened")
        new_runtime = new_bootstrap.runtime_for(new_session)
        events.append("new_runtime_started")
        new_reconciliation = new_runtime.services.reconciliation_service

        assert new_reconciliation is not None
        assert new_reconciliation.is_running
        assert new_session.root == old_session.root
        assert events.index("old_runtime_close_started") < events.index("old_worker_stop")
        assert events.index("old_worker_stop") < events.index("old_runtime_cleanup")
        assert events.index("old_runtime_cleanup") < events.index("old_db_release")
        assert events.index("old_db_release") < events.index("old_lock_release")
        assert events.index("old_lock_release") < events.index("new_owner_opened")
        assert events.index("new_owner_opened") < events.index("new_runtime_started")
    finally:
        _close_bootstrap(new_bootstrap)
        _close_bootstrap(old_bootstrap)


def test_library_owner_handoff_is_blocked_until_stop_timeout_is_retried(
    tmp_path, monkeypatch
):
    """A failed old-owner stop keeps the canonical root unavailable to a contender."""
    library = tmp_path / "library"
    library.mkdir()

    old_bootstrap = ApplicationBootstrap()
    new_bootstrap = ApplicationBootstrap()
    old_session = old_bootstrap.library_service.open_session(library)
    old_runtime = old_bootstrap.runtime_for(old_session)
    old_reconciliation = old_runtime.services.reconciliation_service
    assert old_reconciliation is not None
    assert old_reconciliation.is_running

    original_stop = old_reconciliation.stop
    calls = 0

    def stop_once_then_delegate(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ReconciliationWorkerStopTimeout("controlled owner stop timeout")
        return original_stop(*args, **kwargs)

    monkeypatch.setattr(old_reconciliation, "stop", stop_once_then_delegate)

    try:
        with pytest.raises(ReconciliationWorkerStopTimeout, match="controlled owner stop timeout"):
            old_bootstrap.library_service.close_session(old_session)

        assert old_session.is_closed
        assert old_reconciliation.is_running
        assert old_runtime._state == "failed"

        with pytest.raises(RuntimeError, match="teardown|owned by another LibraryService"):
            new_bootstrap.library_service.open_session(library)

        # The failed owner must explicitly retry and commit teardown before a
        # second bootstrap can acquire the same canonical root.
        old_bootstrap.library_service.close_session(old_session)
        assert calls == 2
        assert not old_reconciliation.is_running
        assert old_runtime._state == "closed"

        new_session = new_bootstrap.library_service.open_session(library)
        new_runtime = new_bootstrap.runtime_for(new_session)
        new_reconciliation = new_runtime.services.reconciliation_service
        assert new_reconciliation is not None
        assert new_reconciliation.is_running
    finally:
        _close_bootstrap(new_bootstrap)
        _close_bootstrap(old_bootstrap)

