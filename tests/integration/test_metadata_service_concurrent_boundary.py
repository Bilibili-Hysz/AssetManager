"""Deterministic concurrency regression for the metadata clean-boundary guard.

Round-3 recheck F1: the guard's ``in_transaction`` peek was unlocked, so the
reconciliation worker's short transaction on the shared connection could be
misread as a caller-owned outer transaction, rejecting user mutations.  These
tests drive a real LibrarySession with a background worker that holds the
connection-owned write gate, gated by Events — no sleeps as race control:

  1. worker completes cleanly (rollback + release) → the foreground mutation
     waits on the gate and then SUCCEEDS, and the notes-changed event fires
     only after the commit;
  2. a caller opens an outer transaction after the service guard but before
     the repository write → the mutation fails closed without an event.
"""
import sqlite3
import threading
from contextlib import contextmanager

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
    yield bootstrap, session, service, conn, library, asset
    bootstrap.library_service.close()


def _hold_worker(conn, ready: threading.Event, release: threading.Event, errors: list):
    """Hold the connection write gate with an open transaction until release."""

    def run() -> None:
        try:
            from AssetsManager.core.database import db_write_lock
            with db_write_lock(conn):
                conn.execute("BEGIN")
                ready.set()
                if not release.wait(timeout=5):
                    raise TimeoutError("foreground did not release the holder")
                conn.rollback()
        except BaseException as exc:
            errors.append(exc)
            ready.set()

    thread = threading.Thread(target=run, name="metadata-boundary-holder", daemon=True)
    thread.start()
    return thread


def test_set_notes_waits_out_worker_and_succeeds(runtime, monkeypatch):
    _bootstrap, session, service, conn, library, asset = runtime
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import AssetNotesChanged
    import AssetsManager.domain.event_bus as eb

    bus = EventBus()
    publications: list[tuple[bool, str | None]] = []

    def observe(event) -> None:
        assert event.file_path == str(asset)
        with sqlite3.connect(session.data_dir / "assetmanager.db") as reader:
            row = reader.execute(
                "SELECT notes FROM file_meta WHERE file_path=?", (str(asset),)
            ).fetchone()
        publications.append((conn.in_transaction, row[0] if row else None))

    bus.subscribe(AssetNotesChanged, observe)
    monkeypatch.setattr(eb, "_instance", bus)

    ready, release, errors = threading.Event(), threading.Event(), []
    holder = _hold_worker(conn, ready, release, errors)
    try:
        assert ready.wait(timeout=5), "holder never opened its transaction"

        outcome: dict = {}
        entered, completed = threading.Event(), threading.Event()
        from AssetsManager.core import database

        original_write_lock = database.db_write_lock
        foreground_thread: list[threading.Thread | None] = [None]

        @contextmanager
        def observe_foreground_lock(connection):
            if threading.current_thread() is foreground_thread[0]:
                entered.set()
            with original_write_lock(connection):
                yield

        monkeypatch.setattr(database, "db_write_lock", observe_foreground_lock)

        def foreground():
            try:
                service.set_notes(library, asset, "waited-out")
                outcome["ok"] = True
            except Exception as exc:  # pragma: no cover - failure path
                outcome["error"] = repr(exc)
            finally:
                completed.set()

        worker = threading.Thread(target=foreground, daemon=True)
        foreground_thread[0] = worker
        worker.start()
        assert entered.wait(timeout=5), "foreground did not attempt the write lock"
        release.set()
        assert completed.wait(timeout=5), "foreground did not finish after release"
        worker.join(timeout=5)
        assert outcome.get("ok"), f"set_notes must succeed after the worker commits: {outcome}"
        assert not worker.is_alive()
        # The event fires after commit: no open transaction remains and an
        # independent SQLite connection can already observe the new notes.
        assert service.get_notes(library, asset) == "waited-out"
        assert publications == [(False, "waited-out")]
    finally:
        release.set()
        holder.join(timeout=10)
        assert not errors, f"holder failed: {errors}"


def test_set_notes_fails_closed_when_transaction_starts_after_service_guard(
    runtime, monkeypatch
):
    _bootstrap, session, service, conn, library, asset = runtime
    from AssetsManager.application.metadata_service import MetadataService
    from AssetsManager.core.database import db_write_lock
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import AssetNotesChanged
    import AssetsManager.domain.event_bus as eb

    bus = EventBus()
    events: list = []
    bus.subscribe(AssetNotesChanged, events.append)
    monkeypatch.setattr(eb, "_instance", bus)

    guard_passed, allow_write, completed = (
        threading.Event(), threading.Event(), threading.Event()
    )
    original_guard = MetadataService._require_event_safe_transaction

    def pause_after_guard(self, repo):
        original_guard(self, repo)
        guard_passed.set()
        assert allow_write.wait(timeout=5), "test never released guarded mutation"

    monkeypatch.setattr(
        MetadataService, "_require_event_safe_transaction", pause_after_guard
    )
    outcome: dict = {}

    def foreground() -> None:
        try:
            service.set_notes(library, asset, "must-not-write")
            outcome["ok"] = True
        except Exception as exc:
            outcome["error"] = exc
        finally:
            completed.set()

    worker = threading.Thread(target=foreground, daemon=True)
    worker.start()
    try:
        assert guard_passed.wait(timeout=5), "service guard did not pass"
        # Deliberately violate the normal caller invariant: retain an outer
        # transaction after releasing its connection gate. The repository must
        # recheck under that gate before writing, closing the guard/write gap.
        with session.operation(), db_write_lock(conn):
            conn.execute("BEGIN")
        allow_write.set()
        assert completed.wait(timeout=5), "mutation did not finish"
        worker.join(timeout=5)
        assert isinstance(outcome.get("error"), RuntimeError)
        assert "clean transaction boundary" in str(outcome["error"])
        assert events == []
        assert conn.in_transaction
        assert service.get_notes(library, asset) == ""
    finally:
        allow_write.set()
        if conn.in_transaction:
            conn.rollback()
