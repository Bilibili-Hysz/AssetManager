"""Deterministically observe the MetadataService guard/write TOCTOU window.

This is an isolated-review probe.  It does not modify production sources.
It deliberately models a caller-owned transaction which begins while holding
the connection gate, then releases that gate while retaining the transaction.
That is required to enter the window; ordinary reconciliation work which
commits/rolls back before releasing the gate cannot trigger it.
"""
from __future__ import annotations

import threading
from pathlib import Path


def main() -> None:
    import tempfile

    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.application.metadata_service import MetadataService
    from AssetsManager.core.database import db_write_lock
    from AssetsManager.domain.event_bus import EventBus
    from AssetsManager.domain.events import AssetNotesChanged
    import AssetsManager.domain.event_bus as event_bus_module

    with tempfile.TemporaryDirectory(prefix="metadata-guard-toctou-") as raw:
        base = Path(raw)
        library = base / "library"
        library.mkdir()
        asset = library / "asset.txt"
        asset.write_text("asset", encoding="utf-8")

        bootstrap = ApplicationBootstrap()
        session = bootstrap.library_service.open_session(library)
        service = bootstrap.runtime_for(session).services.metadata_service
        conn = session.connection_for(session.root)

        bus = EventBus()
        events: list[AssetNotesChanged] = []
        bus.subscribe(AssetNotesChanged, events.append)
        event_bus_module._instance = bus

        guard_passed = threading.Event()
        permit_write = threading.Event()
        original_guard = MetadataService._require_event_safe_transaction

        def paused_guard(self, repo):
            original_guard(self, repo)
            guard_passed.set()
            if not permit_write.wait(timeout=5):
                raise TimeoutError("probe never permitted the metadata write")

        MetadataService._require_event_safe_transaction = paused_guard
        outcome: dict[str, object] = {}

        def mutate() -> None:
            try:
                service.set_notes(library, asset, "ephemeral")
                outcome["ok"] = True
            except BaseException as exc:
                outcome["error"] = repr(exc)

        worker = threading.Thread(target=mutate, name="metadata-mutation")
        worker.start()
        assert guard_passed.wait(timeout=5), "clean-boundary guard did not pass"

        # This begins a legitimate caller-owned outer transaction under the
        # connection lock, but intentionally leaves its eventual commit/rollback
        # to the caller after this scope.  It is not a normal reconciliation
        # short transaction.
        with session.operation(), db_write_lock(conn):
            assert not conn.in_transaction
            conn.execute("BEGIN")
            assert conn.in_transaction

        permit_write.set()
        worker.join(timeout=5)
        assert outcome == {"ok": True}, outcome
        assert conn.in_transaction, "write unexpectedly committed caller transaction"
        assert len(events) == 1, events
        assert service.get_notes(library, asset) == "ephemeral"

        with session.operation(), db_write_lock(conn):
            conn.rollback()
        assert service.get_notes(library, asset) == ""

        print("guard_passed_before_outer_transaction=True")
        print("mutation_completed=True")
        print(f"events_published={len(events)}")
        print("notes_before_rollback=ephemeral")
        print("notes_after_rollback=<empty>")
        bootstrap.library_service.close()


if __name__ == "__main__":
    main()
