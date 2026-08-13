"""Tests for the explicit asset import service (audit task C1)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.application.import_service import ImportService
from AssetsManager.domain.event_bus import EventBus
from AssetsManager.domain.events import FileSystemChanged


def _bootstrap_and_import(tmp_path, monkeypatch):
    """Build a bootstrap, open a session, and patch the event bus."""
    bus = EventBus()
    import AssetsManager.domain.event_bus as eb
    monkeypatch.setattr(eb, "_instance", bus)

    library = tmp_path / "library"
    library.mkdir()
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    scoped = bootstrap.runtime_for(session).services
    file_operations = scoped.file_operation_service
    return bootstrap, session, file_operations, bus


def _make_service(session, file_operations):
    return ImportService(session, file_operations)


def test_import_single_file(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        source = tmp_path / "source.txt"
        source.write_text("hello")
        dest = session.root / "dest"
        dest.mkdir()

        result = _make_service(session, file_operations).import_sources([source], dest)

        assert result.copied == 1
        assert result.skipped == 0
        assert result.failed == []
        assert (dest / "source.txt").read_text() == "hello"
    finally:
        bootstrap.library_service.close()


def test_import_directory_tree_recursive(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        src = tmp_path / "tree"
        (src / "nested" / "deep").mkdir(parents=True)
        (src / "a.txt").write_text("a")
        (src / "nested" / "b.txt").write_text("b")
        (src / "nested" / "deep" / "c.txt").write_text("c")
        # dot-prefixed entries are skipped
        (src / ".hidden.txt").write_text("hidden")
        (src / ".git").mkdir()
        (src / ".git" / "config").write_text("x")

        dest = session.root / "dest"
        dest.mkdir()

        result = _make_service(session, file_operations).import_sources([src], dest)

        assert result.copied == 3
        assert result.failed == []
        # Directory structure is preserved inside the destination.
        assert (dest / "a.txt").exists()
        assert (dest / "nested" / "b.txt").exists()
        assert (dest / "nested" / "deep" / "c.txt").exists()
        assert not (dest / ".hidden.txt").exists()
        assert not (dest / "config").exists()
    finally:
        bootstrap.library_service.close()


def test_in_library_source_skipped(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        inside = session.root / "already.txt"
        inside.write_text("x")
        dest = session.root / "dest"
        dest.mkdir()

        result = _make_service(session, file_operations).import_sources([inside], dest)

        assert result.copied == 0
        assert result.skipped == 1
        assert not (dest / "already.txt").exists()
    finally:
        bootstrap.library_service.close()


def test_destination_outside_library_raises(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        source = tmp_path / "source.txt"
        source.write_text("x")
        outside = tmp_path / "outside"
        outside.mkdir()

        with pytest.raises(ValueError):
            _make_service(session, file_operations).import_sources([source], outside)
    finally:
        bootstrap.library_service.close()


def test_name_conflict_auto_rename(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        source = tmp_path / "file.txt"
        source.write_text("new")
        dest = session.root / "dest"
        dest.mkdir()
        (dest / "file.txt").write_text("old")

        result = _make_service(session, file_operations).import_sources([source], dest)

        assert result.copied == 1
        assert (dest / "file.txt").read_text() == "old"
        # unique_destination uses "%stem_%n%suffix"
        assert (dest / "file_1.txt").read_text() == "new"
    finally:
        bootstrap.library_service.close()


def test_progress_monotonic_and_reaches_total(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        src = tmp_path / "tree"
        src.mkdir()
        for i in range(5):
            (src / f"f{i}.txt").write_text("x")
        dest = session.root / "dest"
        dest.mkdir()

        calls = []

        def progress(done, total):
            calls.append((done, total))

        _make_service(session, file_operations).import_sources(
            [src], dest, progress=progress
        )

        assert calls, "progress must be invoked"
        dones = [d for d, _ in calls]
        totals = [t for _, t in calls]
        assert dones == sorted(dones), "progress must be monotonic non-decreasing"
        assert totals == [totals[0]] * len(totals), "total must be stable"
        assert calls[-1][0] == calls[-1][1] == 5, "final done must equal total"
    finally:
        bootstrap.library_service.close()


def test_single_failure_does_not_abort_and_is_recorded(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        src = tmp_path / "tree"
        src.mkdir()
        (src / "good.txt").write_text("good")
        (src / "broken.txt").write_text("break")
        dest = session.root / "dest"
        dest.mkdir()

        import AssetsManager.application.import_service as mod
        real_copy2 = mod.shutil.copy2

        def flaky_copy2(src_path, dst_path):
            if Path(src_path).name == "broken.txt":
                raise OSError("simulated copy failure")
            return real_copy2(src_path, dst_path)

        monkeypatch.setattr(mod.shutil, "copy2", flaky_copy2)

        result = _make_service(session, file_operations).import_sources([src], dest)

        assert result.copied == 1
        assert result.failed, "the failing file must be recorded as failed"
        assert any("broken.txt" in f for f in result.failed)
        assert (dest / "good.txt").exists()
    finally:
        bootstrap.library_service.close()


def test_exactly_one_import_event_published(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    try:
        events = []
        bus.subscribe(FileSystemChanged, events.append)

        src = tmp_path / "tree"
        src.mkdir()
        (src / "a.txt").write_text("a")
        (src / "b.txt").write_text("b")
        dest = session.root / "dest"
        dest.mkdir()

        _make_service(session, file_operations).import_sources([src], dest)

        import_events = [e for e in events if e.kind == "import"]
        assert len(import_events) == 1
        assert import_events[0].library_root == session.root_str
        assert import_events[0].session_token == session.event_token
        assert import_events[0].paths == (str(dest.resolve()),)
    finally:
        bootstrap.library_service.close()


def test_closed_session_rejected(tmp_path, monkeypatch):
    bootstrap, session, file_operations, bus = _bootstrap_and_import(tmp_path, monkeypatch)
    source = tmp_path / "source.txt"
    source.write_text("x")
    dest = session.root / "dest"
    dest.mkdir()
    service = _make_service(session, file_operations)
    session.close()

    with pytest.raises(RuntimeError):
        service.import_sources([source], dest)

    bootstrap.library_service.close()
