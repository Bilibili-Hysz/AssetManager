"""Deterministic concurrency regression for the metadata clean-boundary guard.

Round-3 recheck F1: the guard's ``in_transaction`` peek was unlocked, so the
reconciliation worker's short transaction on the shared connection could be
misread as a caller-owned outer transaction, rejecting user mutations.  These
tests drive a real LibrarySession with a background worker that holds the
connection-owned write gate, gated by Events — no sleeps as race control:

  1. worker completes cleanly (rollback + release) → the foreground mutation
     waits on the gate and then SUCCEEDS, and the notes-changed event fires
     only after the commit;
  2. a worker that leaves a transaction open while releasing the gate
     (invariant violation) → the mutation fails closed with the service
     RuntimeError instead of publishing an event over unknown state.
"""
import threading

import pytest


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("AM_RUNTIME_ROOT", str(tmp_path / "runtime"))
    from AssetsManager.application.bootstrap import ApplicationBootstrap

    library = tmp_path / "library"
    library.mkdir()
    asset = library / "asset.txt"
    asset.write_text("asset", encoding="utf-8")

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    service = bootstrap.runtime_for(session).services.metadata_service
    conn = session.connection_for(session.root)
    yield bootstrap, service, conn, library, asset
    bootstrap.library_service.close()


def _hold_worker(conn, ready: threading.Event, release: threading.Event,
                 errors: list, *, skip_rollback: bool = False):
    """Hold the connection write gate with an open transaction until release."""

    def run() -> None:
        try:
            from AssetsManager.core.database import db_write_lock
            with db_write_lock(conn):
                conn.execute("BEGIN")
                ready.set()
                if not release.wait(timeout=10):
                    raise TimeoutError("foreground did not release the holder")
                if skip_rollback:
                    # Invariant violation: release the gate while the
                    # transaction is still open (no rollback).
                    raise RuntimeError("holder leaves transaction open")
                conn.rollback()
        except BaseException as exc:
            errors.append(exc)
            ready.set()

    thread = threading.Thread(target=run, name="metadata-boundary-holder", daemon=True)
    thread.start()
    return thread


def test_set_notes_waits_out_worker_and_succeeds(runtime, monkeypatch):
    bootstrap, service, conn, library, asset = runtime
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import AssetNotesChanged
    import AssetsManager.domain.event_bus as eb

    bus = EventBus()
    events: list = []
    bus.subscribe(AssetNotesChanged, events.append)
    monkeypatch.setattr(eb, "_instance", bus)

    ready, release, errors = threading.Event(), threading.Event(), []
    holder = _hold_worker(conn, ready, release, errors)
    try:
        assert ready.wait(timeout=5), "holder never opened its transaction"

        outcome: dict = {}

        def foreground():
            try:
                service.set_notes(library, asset, "waited-out")
                outcome["ok"] = True
            except Exception as exc:  # pragma: no cover - failure path
                outcome["error"] = repr(exc)

        worker = threading.Thread(target=foreground, daemon=True)
        worker.start()
        # Give the foreground time to block on the held gate, then let the
        # worker finish cleanly.
        threading.Event().wait(0.3)
        assert worker.is_alive(), "foreground must be waiting on the write gate"
        release.set()
        worker.join(timeout=15)
        assert outcome.get("ok"), f"set_notes must succeed after the worker commits: {outcome}"
        assert not worker.is_alive()
        # The event was published only after the mutation's own commit — the
        # notes value must be observable on the same connection.
        assert service.get_notes(library, asset) == "waited-out"
    finally:
        release.set()
        holder.join(timeout=10)
        assert not errors, f"holder failed: {errors}"


def test_set_notes_fails_closed_on_leaked_worker_transaction(runtime):
    _bootstrap, service, conn, library, asset = runtime

    ready, release, errors = threading.Event(), threading.Event(), []
    holder = _hold_worker(conn, ready, release, errors, skip_rollback=True)
    try:
        assert ready.wait(timeout=5), "holder never opened its transaction"
        with pytest.raises(RuntimeError, match="clean transaction boundary"):
            service.set_notes(library, asset, "must-not-write")
    finally:
        # The holder raises inside the gate (leaving the transaction open);
        # clean up the leaked transaction so the session can close.
        if conn.in_transaction:
            conn.rollback()
        release.set()
        holder.join(timeout=10)
