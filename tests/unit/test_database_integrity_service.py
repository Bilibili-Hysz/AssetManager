from __future__ import annotations

from pathlib import Path

import pytest
import threading
import time

from AssetsManager.application import ApplicationBootstrap, DatabaseIntegrityService
from AssetsManager.application.database_integrity_service import PathExistence


def _open_session(tmp_path: Path):
    bootstrap = ApplicationBootstrap()
    library = tmp_path / "library"
    library.mkdir()
    session = bootstrap.library_service.open_session(library)
    return bootstrap, session


def test_integrity_check_runs_quick_check_and_prunes_orphans(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    try:
        existing = session.root / "existing.txt"
        existing.write_text("present", encoding="utf-8")
        missing = session.root / "missing.txt"
        orphan_source = session.root / "missing.png"
        live_source = session.root / "live.png"
        live_source.write_bytes(b"image")

        conn = session.connection_for()
        conn.executemany(
            "INSERT INTO file_meta (file_path, notes) VALUES (?, ?)",
            ((str(existing), "keep"), (str(missing), "remove")),
        )
        conn.executemany(
            "INSERT INTO thumbnail_cache "
            "(cache_key, source_path, source_mtime) VALUES (?, ?, ?)",
            (
                ("deadbeef", str(orphan_source), 1.0),
                ("livebeef", str(live_source), 1.0),
            ),
        )
        conn.commit()

        orphan_baked = Path(session.thumb_dir_str) / "deadbeef.webp"
        orphan_baked.write_bytes(b"thumbnail")

        service = DatabaseIntegrityService(
            connection_provider=session.connection_for,
            session=session,
        )
        report = service.run()

        assert report.healthy
        assert report.quick_check == "ok"
        assert report.metadata_removed == 1
        assert report.thumbnail_metadata_removed == 1
        assert report.thumbnail_files_removed == 1
        assert not orphan_baked.exists()
        assert conn.execute(
            "SELECT notes FROM file_meta WHERE file_path=?", (str(existing),)
        ).fetchone() == ("keep",)
        assert conn.execute(
            "SELECT 1 FROM file_meta WHERE file_path=?", (str(missing),)
        ).fetchone() is None
        assert conn.execute(
            "SELECT cache_key FROM thumbnail_cache ORDER BY cache_key"
        ).fetchall() == [("livebeef",)]
        assert service.last_report == report
    finally:
        bootstrap.library_service.close()


def test_integrity_schedule_is_single_flight(tmp_path, monkeypatch):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = DatabaseIntegrityService(
            connection_provider=session.connection_for,
            session=session,
        )
        started = threading.Event()
        release = threading.Event()

        def fake_run():
            started.set()
            release.wait(timeout=2)

        monkeypatch.setattr(service, "run", fake_run)
        assert service.schedule()
        assert started.wait(timeout=2)
        assert not service.schedule()
        assert service.last_schedule_error == "already_running"
        release.set()
        deadline = time.monotonic() + 2
        while service.running and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not service.running
    finally:
        bootstrap.library_service.close()


def test_integrity_check_reports_quick_check_failure_without_cleanup(tmp_path, monkeypatch):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = DatabaseIntegrityService(
            connection_provider=session.connection_for,
            session=session,
        )
        monkeypatch.setattr(
            service,
            "_quick_check",
            lambda: "database disk image is malformed",
        )
        report = service.run()

        assert not report.healthy
        assert report.quick_check == "database disk image is malformed"
        assert report.metadata_removed == 0
        assert report.thumbnail_metadata_removed == 0
        assert report.issues == (
            "SQLite quick_check returned: database disk image is malformed",
        )
    finally:
        bootstrap.library_service.close()


def test_integrity_check_after_session_close_is_reported_as_issue(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    service = DatabaseIntegrityService(
        connection_provider=session.connection_for,
        session=session,
    )
    session.close()
    try:
        report = service.run()
        assert not report.healthy
        assert report.quick_check == "error"
        assert report.issues
    finally:
        bootstrap.library_service.close()



def test_integrity_schedule_start_failure_rolls_back_running(tmp_path, monkeypatch):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = DatabaseIntegrityService(
            connection_provider=session.connection_for,
            session=session,
        )

        def fail_start(_thread):
            raise RuntimeError("thread start failed")

        monkeypatch.setattr(threading.Thread, "start", fail_start)
        assert not service.schedule()
        assert not service.running
        assert service.last_schedule_error == "worker_start_failed: RuntimeError: thread start failed"
        assert service.last_report is not None
        assert not service.last_report.healthy
        assert service.last_report.issues == ("RuntimeError: thread start failed",)
    finally:
        bootstrap.library_service.close()


def test_schedule_after_stop_reports_service_closed(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = DatabaseIntegrityService(
            connection_provider=session.connection_for,
            session=session,
        )
        service.stop()
        assert not service.schedule()
        assert service.last_schedule_error == "service_closed"
    finally:
        bootstrap.library_service.close()


def test_runtime_integrity_shutdown_does_not_commit_with_slow_check(tmp_path, monkeypatch):
    bootstrap, session = _open_session(tmp_path)
    runtime = bootstrap.runtime_for(session)
    service = runtime.services.integrity_service
    started = threading.Event()
    release = threading.Event()
    try:
        def blocked_quick_check():
            started.set()
            release.wait(timeout=2)
            return "ok"

        monkeypatch.setattr(service, "_quick_check", blocked_quick_check)
        assert service.schedule()
        assert started.wait(timeout=2)
        started_at = time.perf_counter()
        bootstrap.library_service.close_session(session)
        elapsed = time.perf_counter() - started_at
        assert elapsed < 5.0
        assert not service.running

        release.set()
        deadline = time.monotonic() + 2
        while service.running and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not service.running
        bootstrap.library_service.close_session(session)
        assert session.is_closed
    finally:
        release.set()
        bootstrap.library_service.close()


def test_integrity_revalidates_metadata_before_delete(tmp_path, monkeypatch):
    bootstrap, session = _open_session(tmp_path)
    try:
        missing = session.root / "restored.txt"
        conn = session.connection_for()
        conn.execute(
            "INSERT INTO file_meta (file_path, notes) VALUES (?, ?)",
            (str(missing), "stale"),
        )
        conn.commit()
        service = DatabaseIntegrityService(
            connection_provider=session.connection_for,
            session=session,
        )
        calls = 0

        def exists_with_restore(path):
            nonlocal calls
            if str(path) == str(missing):
                calls += 1
                if calls == 1:
                    missing.write_text("restored", encoding="utf-8")
                    conn.execute(
                        "UPDATE file_meta SET notes=? WHERE file_path=?",
                        ("fresh", str(missing)),
                    )
                    conn.commit()
                    return False
            return Path(str(path)).is_file() or Path(str(path)).is_dir()

        monkeypatch.setattr(service, "_exists", exists_with_restore)
        report = service.run()
        assert report.metadata_removed == 0
        assert conn.execute(
            "SELECT notes FROM file_meta WHERE file_path=?", (str(missing),)
        ).fetchone() == ("fresh",)
    finally:
        bootstrap.library_service.close()


def test_integrity_revalidates_thumbnail_row_before_delete(tmp_path, monkeypatch):
    bootstrap, session = _open_session(tmp_path)
    try:
        missing = session.root / "missing-source.png"
        replacement = session.root / "replacement-source.png"
        replacement.write_bytes(b"image")
        conn = session.connection_for()
        conn.execute(
            "INSERT INTO thumbnail_cache (cache_key, source_path, source_mtime) VALUES (?, ?, ?)",
            ("stable-key", str(missing), 1.0),
        )
        conn.commit()
        baked = Path(session.thumb_dir_str) / "stable-key.webp"
        baked.write_bytes(b"thumbnail")
        service = DatabaseIntegrityService(
            connection_provider=session.connection_for,
            session=session,
        )
        calls = 0

        def exists_with_replaced_row(path):
            nonlocal calls
            if str(path) == str(missing):
                calls += 1
                if calls == 1:
                    conn.execute(
                        "UPDATE thumbnail_cache SET source_path=? WHERE cache_key=?",
                        (str(replacement), "stable-key"),
                    )
                    conn.commit()
                    return False
            return Path(str(path)).is_file() or Path(str(path)).is_dir()

        monkeypatch.setattr(service, "_exists", exists_with_replaced_row)
        report = service.run()
        assert report.thumbnail_metadata_removed == 0
        assert baked.exists()
        assert conn.execute(
            "SELECT source_path FROM thumbnail_cache WHERE cache_key=?",
            ("stable-key",),
        ).fetchone() == (str(replacement),)
    finally:
        bootstrap.library_service.close()


def test_integrity_skips_adversarial_thumbnail_keys_without_touching_victim(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    try:
        victim = session.root / "victim.webp"
        victim.write_bytes(b"keep")
        conn = session.connection_for()
        keys = ("../victim", "..\\victim", str(victim.with_suffix("")), "\x00malformed")
        conn.executemany(
            "INSERT INTO thumbnail_cache (cache_key, source_path, source_mtime) VALUES (?, ?, ?)",
            ((key, str(session.root / f"missing-{index}.png"), 1.0) for index, key in enumerate(keys)),
        )
        conn.commit()
        service = DatabaseIntegrityService(
            connection_provider=session.connection_for,
            session=session,
        )
        report = service.run()
        assert report.thumbnail_metadata_removed == len(keys)
        assert victim.read_bytes() == b"keep"
    finally:
        bootstrap.library_service.close()


def test_integrity_stop_waits_for_reserved_scheduled_run_with_direct_run(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = DatabaseIntegrityService(
            connection_provider=session.connection_for,
            session=session,
        )
        start_entered = threading.Event()
        release_start = threading.Barrier(2)

        monkeypatch.setattr(service, "_run_pass", lambda: None)
        original_start = threading.Thread.start

        def blocked_start(thread):
            if thread.name == "AssetsManager-IntegrityCheck":
                start_entered.set()
                release_start.wait(timeout=2)
            original_start(thread)

        monkeypatch.setattr(threading.Thread, "start", blocked_start)
        schedule_thread = threading.Thread(target=service.schedule)
        schedule_thread.start()
        assert start_entered.wait(timeout=2)

        service.run()
        assert schedule_thread.is_alive()

        release_start.wait(timeout=2)
        schedule_thread.join(timeout=2)
        assert not schedule_thread.is_alive()
        assert not service.running
        service.stop()
    finally:
        bootstrap.library_service.close()


def test_integrity_cancel_before_prune_commit_rolls_back_delete(tmp_path, monkeypatch):
    bootstrap, session = _open_session(tmp_path)
    try:
        missing = session.root / "cancelled.txt"
        conn = session.connection_for()
        conn.execute(
            "INSERT INTO file_meta (file_path, notes) VALUES (?, ?)",
            (str(missing), "keep-on-cancel"),
        )
        conn.commit()
        service = DatabaseIntegrityService(
            connection_provider=session.connection_for,
            session=session,
        )
        revalidation_entered = threading.Event()
        release_revalidation = threading.Event()
        calls = 0

        def blocked_exists(path):
            nonlocal calls
            if str(path) == str(missing):
                calls += 1
                if calls == 2:
                    revalidation_entered.set()
                    assert release_revalidation.wait(timeout=2)
            return False

        monkeypatch.setattr(service, "_exists", blocked_exists)
        run_thread = threading.Thread(target=service.run)
        run_thread.start()
        assert revalidation_entered.wait(timeout=2)

        stop_started = threading.Event()
        stop_errors = []

        def stop_service():
            stop_started.set()
            try:
                service.stop()
            except Exception as exc:  # pragma: no cover - assertion below reports it
                stop_errors.append(exc)

        stop_thread = threading.Thread(target=stop_service)
        stop_thread.start()
        assert stop_started.wait(timeout=2)
        release_revalidation.set()
        run_thread.join(timeout=2)
        stop_thread.join(timeout=2)

        assert not run_thread.is_alive()
        assert not stop_thread.is_alive()
        assert not stop_errors
        assert conn.execute(
            "SELECT notes FROM file_meta WHERE file_path=?",
            (str(missing),),
        ).fetchone() == ("keep-on-cancel",)
    finally:
        bootstrap.library_service.close()


def test_integrity_session_close_wins_commit_gate_and_rolls_back(tmp_path, monkeypatch):
    bootstrap, session = _open_session(tmp_path)
    try:
        missing = session.root / "close-gated.txt"
        conn = session.connection_for()
        conn.execute(
            "INSERT INTO file_meta (file_path, notes) VALUES (?, ?)",
            (str(missing), "keep-on-close"),
        )
        conn.commit()
        service = DatabaseIntegrityService(
            connection_provider=session.connection_for,
            session=session,
        )
        monkeypatch.setattr(service, "_quick_check", lambda: "ok")
        monkeypatch.setattr(service, "_exists", lambda _path: False)

        gate_entered = threading.Event()
        release_gate = threading.Event()
        original_commit_gate = service._commit_while_live

        def blocked_commit_gate(_service, conn):
            gate_entered.set()
            assert release_gate.wait(timeout=2)
            return original_commit_gate(conn)

        monkeypatch.setattr(
            DatabaseIntegrityService, "_commit_while_live", blocked_commit_gate
        )
        run_thread = threading.Thread(target=service.run)
        run_thread.start()
        assert gate_entered.wait(timeout=2)

        close_done = threading.Event()

        def begin_close():
            session._begin_close()
            close_done.set()

        close_thread = threading.Thread(target=begin_close)
        close_thread.start()
        assert close_done.wait(timeout=2)
        release_gate.set()
        run_thread.join(timeout=2)
        close_thread.join(timeout=2)

        assert not run_thread.is_alive()
        assert not close_thread.is_alive()
        assert conn.execute(
            "SELECT notes FROM file_meta WHERE file_path=?",
            (str(missing),),
        ).fetchone() == ("keep-on-close",)
        session._finish_close()
    finally:
        bootstrap.library_service.close()


def test_integrity_thumbnail_close_gate_keeps_baked_file_on_rollback(
    tmp_path, monkeypatch
):
    bootstrap, session = _open_session(tmp_path)
    try:
        source = session.root / "close-gated-source.png"
        cache_key = "close-gated-thumbnail"
        conn = session.connection_for()
        conn.execute(
            "INSERT INTO thumbnail_cache (cache_key, source_path, source_mtime) "
            "VALUES (?, ?, ?)",
            (cache_key, str(source), 1.0),
        )
        conn.commit()
        baked = Path(session.thumb_dir_str) / f"{cache_key}.webp"
        baked.write_bytes(b"keep-on-close")

        service = DatabaseIntegrityService(
            connection_provider=session.connection_for,
            session=session,
        )
        monkeypatch.setattr(service, "_quick_check", lambda: "ok")
        monkeypatch.setattr(service, "_exists", lambda _path: False)

        gate_entered = threading.Event()
        release_gate = threading.Event()
        original_commit_gate = service._commit_while_live

        def blocked_commit_gate(_service, conn):
            gate_entered.set()
            assert release_gate.wait(timeout=2)
            return original_commit_gate(conn)

        monkeypatch.setattr(
            DatabaseIntegrityService, "_commit_while_live", blocked_commit_gate
        )
        run_thread = threading.Thread(target=service.run)
        run_thread.start()
        assert gate_entered.wait(timeout=2)

        session._begin_close()
        release_gate.set()
        run_thread.join(timeout=2)
        assert not run_thread.is_alive()
        assert conn.execute(
            "SELECT cache_key FROM thumbnail_cache WHERE cache_key=?",
            (cache_key,),
        ).fetchone() == (cache_key,)
        assert baked.exists()
        session._finish_close()
    finally:
        bootstrap.library_service.close()

def test_integrity_check_rejects_managed_foreign_root_provider(tmp_path):
    from AssetsManager.core.database import DatabaseManager

    bootstrap, session = _open_session(tmp_path)
    foreign_root = tmp_path / "foreign-library"
    foreign_root.mkdir()
    manager = DatabaseManager()
    try:
        conn = session.connection_for()
        missing = session.root / "missing.txt"
        conn.execute(
            "INSERT INTO file_meta (file_path, notes) VALUES (?, ?)",
            (str(missing), "must remain"),
        )
        conn.commit()
        foreign_connection = manager.connection_for(foreign_root)
        service = DatabaseIntegrityService(
            connection_provider=lambda _root: foreign_connection,
            session=session,
        )

        report = service.run()

        assert not report.healthy
        assert report.quick_check == "ok"
        assert any("different library root" in issue for issue in report.issues)
        assert conn.execute(
            "SELECT notes FROM file_meta WHERE file_path=?", (str(missing),)
        ).fetchone() == ("must remain",)
    finally:
        manager.close()
        bootstrap.library_service.close()

@pytest.mark.parametrize("failure", [OSError("closed resource"), ValueError("bad path"), TypeError("bad type")])
def test_integrity_path_check_failures_are_unknown_and_never_delete(
    tmp_path, monkeypatch, failure
):
    bootstrap, session = _open_session(tmp_path)
    try:
        candidate = session.root / "unreadable.txt"
        conn = session.connection_for()
        conn.execute(
            "INSERT INTO file_meta (file_path, notes) VALUES (?, ?)",
            (str(candidate), "must remain"),
        )
        conn.commit()
        service = DatabaseIntegrityService(
            connection_provider=session.connection_for,
            session=session,
        )
        monkeypatch.setattr(service, "_exists", lambda _path: (_ for _ in ()).throw(failure))
        report = service.run()

        assert not report.healthy
        assert report.metadata_removed == 0
        assert conn.execute(
            "SELECT notes FROM file_meta WHERE file_path=?", (str(candidate),)
        ).fetchone() == ("must remain",)
        assert any("state is unknown" in issue for issue in report.issues)
    finally:
        bootstrap.library_service.close()


def test_integrity_foreign_root_is_unknown_and_not_an_orphan(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    try:
        foreign = tmp_path / "foreign" / "asset.png"
        foreign.parent.mkdir()
        foreign.write_bytes(b"outside")
        conn = session.connection_for()
        conn.execute(
            "INSERT INTO file_meta (file_path, notes) VALUES (?, ?)",
            (str(foreign), "foreign must remain"),
        )
        conn.commit()
        service = DatabaseIntegrityService(
            connection_provider=session.connection_for,
            session=session,
        )
        report = service.run()

        assert not report.healthy
        assert report.metadata_removed == 0
        assert conn.execute(
            "SELECT notes FROM file_meta WHERE file_path=?", (str(foreign),)
        ).fetchone() == ("foreign must remain",)
        assert any("state is unknown" in issue for issue in report.issues)
    finally:
        bootstrap.library_service.close()


def test_integrity_exists_contract_distinguishes_missing_from_unknown(tmp_path):
    bootstrap, session = _open_session(tmp_path)
    try:
        service = DatabaseIntegrityService(
            connection_provider=session.connection_for,
            session=session,
        )
        existing = session.root / "present.txt"
        existing.write_text("present", encoding="utf-8")
        missing = session.root / "absent.txt"
        foreign = tmp_path / "outside.txt"
        assert service._exists(existing) is PathExistence.EXISTS
        assert service._exists(missing) is PathExistence.MISSING
        assert service._exists(foreign) is PathExistence.UNKNOWN
    finally:
        bootstrap.library_service.close()

