"""Deterministically reproduce MetadataService's unlocked transaction check.

This is an evidence probe, not a product test.  It creates a real isolated
LibrarySession, then has a background worker hold the connection-owned write
lock and an open SQLite transaction.  The foreground metadata mutation should
not treat that worker transaction as its own outer transaction, but the
current unlocked check does and rejects it before attempting its repository
write.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
# Invoking a file under scripts/perf makes that directory Python's import root.
# Restore the project root explicitly so the probe is runnable as documented.
sys.path.insert(0, str(ROOT))


def main() -> int:
    # Database runtime paths are read while importing the application modules,
    # so establish this process-only root before those imports.
    with tempfile.TemporaryDirectory(
        prefix="metadata-race-runtime-", dir=ARTIFACTS
    ) as isolated_root:
        runtime_root = Path(isolated_root)
        os.environ["AM_RUNTIME_ROOT"] = str(runtime_root)

        from AssetsManager.application.bootstrap import ApplicationBootstrap
        from AssetsManager.application.metadata_service import MetadataService
        from AssetsManager.core.database import db_write_lock

        library = runtime_root / "synthetic-library"
        library.mkdir()
        asset = library / "asset.txt"
        asset.write_text("asset", encoding="utf-8")

        bootstrap = ApplicationBootstrap()
        session = bootstrap.library_service.open_session(library)
        service = MetadataService.for_session(session)
        conn = session.connection_for(session.root)
        holder_ready = threading.Event()
        release_holder = threading.Event()
        holder_errors: list[BaseException] = []

        def hold_worker_transaction() -> None:
            try:
                with db_write_lock(conn):
                    conn.execute("BEGIN")
                    holder_ready.set()
                    if not release_holder.wait(timeout=10):
                        raise TimeoutError("foreground did not release transaction holder")
                    conn.rollback()
            except BaseException as exc:  # surfaced by the foreground assertion
                holder_errors.append(exc)
                holder_ready.set()

        holder = threading.Thread(
            target=hold_worker_transaction, name="metadata-race-holder", daemon=True
        )
        holder.start()
        try:
            if not holder_ready.wait(timeout=5):
                raise TimeoutError("background transaction holder did not become ready")
            if holder_errors:
                raise AssertionError("holder failed before probe") from holder_errors[0]
            if not conn.in_transaction:
                raise AssertionError("holder did not leave a transaction open")

            try:
                service.set_notes(library, asset, "must-not-write")
            except RuntimeError as exc:
                expected = "MetadataService metadata mutations require a clean transaction boundary"
                if str(exc) != expected:
                    raise AssertionError(f"unexpected RuntimeError: {exc!r}") from exc
                print("REPRODUCED: foreground set_notes rejected worker-owned transaction")
                print(f"exception={type(exc).__name__}: {exc}")
            else:
                raise AssertionError("set_notes unexpectedly succeeded while worker transaction was open")
        finally:
            release_holder.set()
            holder.join(timeout=5)
            if holder.is_alive():
                raise RuntimeError("background transaction holder did not stop")
            if holder_errors:
                raise AssertionError("holder failed during cleanup") from holder_errors[0]
            bootstrap.library_service.close()

        print("CLEANUP: worker rolled back and isolated runtime was closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
