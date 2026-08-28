"""Tests for UndoService."""
import os
from pathlib import Path

import pytest

from AssetsManager.application.file_operation_service import FileOperationService
from AssetsManager.application.undo_service import UndoEntry, UndoService


class _RecordingFileOperations:
    def __init__(self):
        self.calls = []

    def move(self, source, destination, *, library_root):
        self.calls.append(("move", source, destination, library_root))

    def restore_backup(self, backup, destination, *, library_root):
        self.calls.append(("restore_backup", backup, destination, library_root))

    def delete_permanent(self, paths, *, library_root):
        self.calls.append(("delete_permanent", paths, library_root))


class _FailingFileOperations:
    def move(self, source, destination, *, library_root):
        raise OSError("blocked")

    def delete_permanent(self, paths, *, library_root):
        return type("Result", (), {"ok": False})()


class _DegradedRestoreFileOperations:
    """restore_backup reports filesystem success with a degraded projection."""

    def __init__(self):
        self.calls = []

    def move(self, source, destination, *, library_root):
        self.calls.append(("move", source, destination, library_root))

    def restore_backup(self, backup, destination, *, library_root):
        self.calls.append(("restore_backup", backup, destination, library_root))
        from AssetsManager.application.file_operation_service import RestoreResult

        return RestoreResult(path=Path(destination), degraded=True)

    def delete_permanent(self, paths, *, library_root):
        self.calls.append(("delete_permanent", paths, library_root))


def test_failed_perform_undo_keeps_source_stack_and_does_not_advance_redo(tmp_path):
    old = tmp_path / "old.txt"
    new = tmp_path / "new.txt"
    new.write_text("asset", encoding="utf-8")
    svc = UndoService()
    svc.record_rename(str(old), str(new))

    assert not svc.perform_undo(_FailingFileOperations(), str(tmp_path))
    assert svc.peek_undo().new == str(new)
    assert svc.peek_redo() is None
    assert new.exists()
    assert not old.exists()


def test_failed_perform_redo_keeps_source_stack_and_does_not_advance_undo(tmp_path):
    path = tmp_path / "asset.txt"
    path.write_text("asset", encoding="utf-8")
    svc = UndoService()
    svc.record_delete(str(path))
    path.unlink()
    assert svc.perform_undo(FileOperationService(), str(tmp_path))

    assert not svc.perform_redo(_FailingFileOperations(), str(tmp_path))
    assert svc.peek_redo().path == str(path)
    assert svc.peek_undo() is None
    assert path.exists()


def test_perform_undo_and_redo_delegate_to_library_file_operations(tmp_path):
    library_root = str(tmp_path)
    source = str(tmp_path / "old.txt")
    renamed = str(tmp_path / "new.txt")
    deleted = str(tmp_path / "deleted.txt")
    backup = str(tmp_path / "backup.txt")
    (tmp_path / "backup.txt").write_text("backup", encoding="utf-8")
    operations = _RecordingFileOperations()
    svc = UndoService(library_root=library_root)

    svc.record_rename(source, renamed)
    assert svc.perform_undo(operations, library_root)
    assert svc.perform_redo(operations, library_root)

    svc._push_undo(UndoEntry(type="delete", path=deleted, backup=backup))
    assert svc.perform_undo(operations, library_root)
    assert svc.perform_redo(operations, library_root)

    assert operations.calls == [
        ("move", renamed, source, library_root),
        ("move", source, renamed, library_root),
        ("restore_backup", backup, deleted, library_root),
        ("delete_permanent", [deleted], library_root),
    ]


def test_peeked_undo_and_redo_entries_preserve_selection_targets(tmp_path):
    """UI callers can derive a target before moving an entry between stacks."""
    old = str(tmp_path / "old.txt")
    new = str(tmp_path / "new.txt")
    operations = _RecordingFileOperations()
    svc = UndoService(library_root=str(tmp_path))
    svc.record_rename(old, new)

    undo_entry = svc.peek_undo()
    assert undo_entry is not None
    assert undo_entry.type == "rename"
    assert undo_entry.old == old  # Undo restores the original path.
    assert svc.perform_undo(operations, str(tmp_path))

    redo_entry = svc.peek_redo()
    assert redo_entry is not None
    assert redo_entry.type == "rename"
    assert redo_entry.new == new  # Redo restores the renamed path.
    assert svc.perform_redo(operations, str(tmp_path))


def test_peeked_delete_entry_distinguishes_undo_restore_from_redo_removal(tmp_path):
    path = tmp_path / "deleted.txt"
    backup = tmp_path / "backup.txt"
    backup.write_text("backup", encoding="utf-8")
    operations = _RecordingFileOperations()
    svc = UndoService(library_root=str(tmp_path))
    svc._push_undo(UndoEntry(type="delete", path=str(path), backup=str(backup)))

    undo_entry = svc.peek_undo()
    assert undo_entry is not None
    assert undo_entry.path == str(path)  # Undo has a concrete restored target.
    assert svc.perform_undo(operations, str(tmp_path))

    redo_entry = svc.peek_redo()
    assert redo_entry is not None
    assert redo_entry.path == str(path)  # Redo removes this path; it has no selection target.


def test_operation_succeeded_treats_degraded_restore_as_success():
    """A degraded restore is not a failure: the file is back, so undo/redo
    stack movement proceeds — the degraded signal is handled separately."""
    from AssetsManager.application.file_operation_service import RestoreResult

    assert UndoService._operation_succeeded(
        RestoreResult(path=Path("restored.txt"), degraded=True)
    ) is True
    assert UndoService._operation_succeeded(type("R", (), {"ok": False})()) is False


def test_degraded_restore_annotates_entry_instead_of_poisoning_stack(tmp_path):
    """A degraded projection restore must not be recorded as a fully clean
    success: the entry moves to the redo stack annotated ``degraded`` (it
    must not stay on the undo stack as a poisoned/failed entry)."""
    path = tmp_path / "asset.txt"
    backup = tmp_path / "backup.txt"
    backup.write_text("backup", encoding="utf-8")
    operations = _DegradedRestoreFileOperations()
    svc = UndoService(library_root=str(tmp_path))
    try:
        svc._push_undo(UndoEntry(type="delete", path=str(path), backup=str(backup)))

        assert svc.perform_undo(operations, str(tmp_path))
        assert svc.peek_undo() is None
        redo_entry = svc.peek_redo()
        assert redo_entry is not None
        assert redo_entry.degraded is True

        # Redo re-executes the delete itself; the stale degraded annotation
        # from the previous restore is cleared.
        assert svc.perform_redo(operations, str(tmp_path))
        undone_entry = svc.peek_undo()
        assert undone_entry is not None
        assert undone_entry.degraded is False
    finally:
        svc.cleanup()


def test_undo_records_session_scoped_execution_outcomes(tmp_path):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.core.performance import PerformanceRecorder

    library = tmp_path / "library"
    library.mkdir()
    old = library / "old.txt"
    new = library / "new.txt"
    old.write_text("data", encoding="utf-8")
    recorder = PerformanceRecorder(enabled=True)
    bootstrap = ApplicationBootstrap(performance_recorder=recorder)
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
    undo = scoped.undo_service
    undo.record_rename(str(old), str(new))
    assert scoped.file_operation_service.move(old, new) == new
    recorder.clear()

    assert undo.perform_undo(scoped.file_operation_service)
    assert undo.perform_redo(scoped.file_operation_service)

    events = [event for event in recorder.recent() if event.name == "file.undo"]
    assert [(event.attributes["command"], event.attributes["outcome"]) for event in events] == [
        ("undo", "success"), ("redo", "success")
    ]
    assert all(event.session_token == scoped.session.event_token for event in events)
    assert [event.attributes["phase"] for event in events] == ["events_published", "events_published"]
    assert [event for event in recorder.recent() if event.name == "file.command"] == []


def test_record_rename_and_undo(tmp_path):
    src = tmp_path / "old.txt"
    src.write_text("data", encoding="utf-8")

    svc = UndoService()
    svc.record_rename(str(src), str(tmp_path / "new.txt"))
    os.rename(str(src), str(tmp_path / "new.txt"))

    assert svc.can_undo()
    assert svc.perform_undo(FileOperationService(), str(tmp_path))
    assert (tmp_path / "old.txt").exists()
    assert not (tmp_path / "new.txt").exists()


def test_batch_move_partial_success_undo_restores_only_moved_files(tmp_path):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()
    good = src_dir / "good.txt"
    good.write_text("data", encoding="utf-8")
    missing = src_dir / "missing.txt"  # does not exist

    # Batch move with one failing source: only the successful pair is
    # reported, mirroring the FileOperationResult.moved_pairs contract
    # that _actions.py consumes to record undo entries per moved pair.
    result = FileOperationService().move_to_directory([good, missing], dst_dir)
    assert not result.ok
    assert len(result.moved_pairs) == 1

    svc = UndoService()
    for source, destination in result.moved_pairs:
        svc.record_rename(str(source), str(destination))

    assert svc.can_undo()
    assert svc.perform_undo(FileOperationService(), str(tmp_path))
    # The moved file is restored; the failed source never moved anywhere.
    assert good.exists()
    assert not (dst_dir / "good.txt").exists()
    assert not missing.exists()
    assert not (dst_dir / "missing.txt").exists()


def test_undo_pushes_to_redo(tmp_path):
    src = tmp_path / "old.txt"
    src.write_text("data", encoding="utf-8")

    svc = UndoService()
    svc.record_rename(str(src), str(tmp_path / "new.txt"))

    entry = svc.undo()
    assert entry is not None
    assert svc.can_redo()
    redo_entry = svc.redo()
    assert redo_entry is not None
    assert redo_entry.type == "rename"


def test_record_delete_and_undo(tmp_path):
    src = tmp_path / "file.txt"
    src.write_text("data", encoding="utf-8")

    svc = UndoService()
    svc.record_delete(str(src))
    os.remove(str(src))

    assert svc.can_undo()
    assert svc.perform_undo(FileOperationService(), str(tmp_path))
    assert (tmp_path / "file.txt").exists()
    assert (tmp_path / "file.txt").read_text(encoding="utf-8") == "data"


def test_discard_prepared_delete_cleans_backup_without_recording_history(tmp_path):
    source = tmp_path / "file.txt"
    source.write_text("data", encoding="utf-8")
    svc = UndoService()
    try:
        entry = svc.prepare_delete(str(source))

        assert entry is not None
        assert os.path.exists(entry.backup)
        assert not svc.can_undo()

        svc.discard_delete(entry)

        assert not os.path.exists(entry.backup)
        assert not svc.can_undo()
    finally:
        svc.cleanup()


def test_delete_redo_can_be_undone_again(tmp_path):
    src = tmp_path / "file.txt"
    src.write_text("data", encoding="utf-8")

    svc = UndoService()
    try:
        svc.record_delete(str(src))
        os.remove(str(src))

        operations = FileOperationService()
        assert svc.perform_undo(operations, str(tmp_path))
        assert src.exists()

        assert svc.perform_redo(operations, str(tmp_path))
        assert not src.exists()

        assert svc.perform_undo(operations, str(tmp_path))
        assert src.read_text(encoding="utf-8") == "data"
    finally:
        svc.cleanup()


def test_delete_undo_and_redo_reconcile_file_projections(tmp_path):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.core.tag_store import TagStore
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.domain.events import FileSystemChanged
    from AssetsManager.repositories.thumbnail_repository import ThumbnailRepository

    library = tmp_path / "library"
    library.mkdir()
    source = library / "asset.txt"
    source.write_text("data", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
    conn = scoped.session.connection_for(library)
    index = scoped.asset_index_service
    index.index_directory(conn, library, library)
    TagStore(str(library), db_conn=conn).add_tag(str(source), "hero")
    ThumbnailRepository(conn).upsert_entry("thumb", str(source.resolve()), 1.0, 1, 1, 1)
    thumbnail_file = scoped.session.thumb_dir / "thumb.webp"
    thumbnail_file.write_bytes(b"thumb")
    created = []
    deleted = []
    get_event_bus().subscribe(
        FileSystemChanged,
        lambda event: created.append(event) if event.kind == "restored" else None,
    )
    get_event_bus().subscribe(
        FileSystemChanged,
        lambda event: deleted.append(event) if event.kind == "deleted" else None,
    )
    undo = scoped.undo_service

    try:
        undo.record_delete(str(source))
        assert scoped.file_operation_service.delete_to_trash([source]).ok

        assert undo.perform_undo(scoped.file_operation_service)
        assert source.read_text(encoding="utf-8") == "data"
        assert index.get_entry(conn, source) is not None
        assert created[-1].paths == (str(source),)

        assert undo.perform_redo(scoped.file_operation_service)
        assert not source.exists()
        assert TagStore(str(library), db_conn=conn).get_tags(str(source)) == []
        assert ThumbnailRepository(conn).list_all() == []
        assert not thumbnail_file.exists()
        assert index.get_entry(conn, source) is None
        assert deleted[-1].paths == (str(source),)
    finally:
        undo.cleanup()


def test_snapshot_projection_failure_leaves_marker_for_restore(tmp_path, monkeypatch):
    """A failed projection snapshot must not be silent: a durable
    ``.projection.failed`` marker is written next to the backup so the
    restore path can tell the failure apart from a legacy backup without
    snapshot support."""
    from pathlib import Path

    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.core import path_resolver

    library = tmp_path / "library"
    library.mkdir()
    source = library / "asset.txt"
    source.write_text("data", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    undo = None
    try:
        scoped = bootstrap.runtime_for(session).services
        undo = scoped.undo_service

        def broken_pattern(*_args, **_kwargs):
            raise RuntimeError("injected snapshot query failure")

        monkeypatch.setattr(
            path_resolver, "sql_like_descendant_pattern", broken_pattern
        )

        entry = undo.prepare_delete(str(source))

        # The file backup itself succeeded, so the entry exists, but the
        # failed snapshot left its marker next to the backup.
        assert entry is not None
        assert Path(f"{entry.backup}.projection.failed").is_file()
        assert not Path(f"{entry.backup}.projection.json").exists()

        # Discarding the delete also cleans up the failure marker.
        undo.discard_delete(entry)
        assert not Path(f"{entry.backup}.projection.failed").exists()
    finally:
        if undo is not None:
            undo.cleanup()
        bootstrap.library_service.close()


def test_rename_undo_and_redo_reconcile_metadata_thumbnails_and_index(tmp_path):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.core.tag_store import TagStore
    from AssetsManager.repositories.thumbnail_repository import ThumbnailRepository

    library = tmp_path / "library"
    library.mkdir()
    old = library / "old.txt"
    new = library / "new.txt"
    old.write_text("data", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
    conn = scoped.session.connection_for(library)
    index = scoped.asset_index_service
    index.index_directory(conn, library, library)
    TagStore(str(library), db_conn=conn).add_tag(str(old), "hero")
    ThumbnailRepository(conn).upsert_entry("thumb", str(old.resolve()), 1.0, 1, 1, 1)
    old_thumbnail = scoped.session.thumb_dir / "thumb.webp"
    old_thumbnail.write_bytes(b"thumb")
    undo = scoped.undo_service

    try:
        undo.record_rename(str(old), str(new))
        assert scoped.file_operation_service.move(old, new) == new

        assert undo.perform_undo(scoped.file_operation_service)
        assert old.exists()
        assert TagStore(str(library), db_conn=conn).get_tags(str(old)) == ["hero"]
        assert index.get_entry(conn, old) is not None
        assert index.get_entry(conn, new) is None
        assert ThumbnailRepository(conn).list_all()[0][1] == str(old.resolve())

        assert undo.perform_redo(scoped.file_operation_service)
        assert new.exists()
        assert TagStore(str(library), db_conn=conn).get_tags(str(new)) == ["hero"]
        assert index.get_entry(conn, old) is None
        assert index.get_entry(conn, new) is not None
        assert ThumbnailRepository(conn).list_all()[0][1] == str(new.resolve())
    finally:
        undo.cleanup()


def test_undo_service_uses_unique_backup_dir():
    first = UndoService()
    second = UndoService()
    try:
        assert first._undo_dir != second._undo_dir
        assert os.path.basename(first._undo_dir).startswith("AssetsManager_undo_")
    finally:
        first.cleanup()
        second.cleanup()


def test_startup_cleanup_removes_only_old_undo_dirs(tmp_path):
    old_dir = tmp_path / "AssetsManager_undo_old"
    old_dir.mkdir()
    (old_dir / "backup").write_text("stale", encoding="utf-8")
    recent_dir = tmp_path / "AssetsManager_undo_recent"
    recent_dir.mkdir()
    unrelated = tmp_path / "other_temp_dir"
    unrelated.mkdir()
    os.utime(old_dir, (0, 0))
    os.utime(recent_dir, (95, 95))

    removed = UndoService.cleanup_stale_undo_dirs(
        tmp_path, max_age_seconds=10, now=100
    )

    assert removed == 1
    assert not old_dir.exists()
    assert recent_dir.exists()
    assert unrelated.exists()


def test_startup_cleanup_does_not_remove_directory_owned_by_live_process(tmp_path):
    active_dir = tmp_path / "AssetsManager_undo_active"
    active_dir.mkdir()
    (tmp_path / f"{active_dir.name}{UndoService._OWNER_MARKER}").write_text(
        "999999999", encoding="ascii"
    )
    (active_dir / UndoService._OWNER_MARKER).write_text(
        str(os.getpid()), encoding="ascii"
    )
    os.utime(active_dir, (0, 0))

    removed = UndoService.cleanup_stale_undo_dirs(
        tmp_path, max_age_seconds=10, now=100
    )

    assert removed == 0
    assert active_dir.exists()


def test_startup_cleanup_removes_at_most_256_undo_dirs(tmp_path):
    stale_dirs = []
    for index in range(UndoService._MAX_STARTUP_CLEANUP + 1):
        stale_dir = tmp_path / f"AssetsManager_undo_stale_{index}"
        stale_dir.mkdir()
        os.utime(stale_dir, (0, 0))
        stale_dirs.append(stale_dir)

    removed = UndoService.cleanup_stale_undo_dirs(
        tmp_path, max_age_seconds=10, now=100
    )

    assert removed == UndoService._MAX_STARTUP_CLEANUP
    assert sum(stale_dir.exists() for stale_dir in stale_dirs) == 1


def test_startup_cleanup_removes_sidecar_with_stale_undo_dir(tmp_path):
    stale_dir = tmp_path / "AssetsManager_undo_sidecar"
    stale_dir.mkdir()
    sidecar = tmp_path / f"{stale_dir.name}{UndoService._OWNER_MARKER}"
    sidecar.write_text("999999999", encoding="ascii")
    os.utime(stale_dir, (0, 0))

    removed = UndoService.cleanup_stale_undo_dirs(
        tmp_path, max_age_seconds=10, now=100
    )

    assert removed == 1
    assert not stale_dir.exists()
    assert not sidecar.exists()


def test_startup_cleanup_accepts_legacy_in_directory_owner_marker(tmp_path):
    stale_dir = tmp_path / "AssetsManager_undo_legacy"
    stale_dir.mkdir()
    (stale_dir / UndoService._OWNER_MARKER).write_text(
        "999999999", encoding="ascii"
    )
    os.utime(stale_dir, (0, 0))

    removed = UndoService.cleanup_stale_undo_dirs(
        tmp_path, max_age_seconds=10, now=100
    )

    assert removed == 1
    assert not stale_dir.exists()


def test_startup_cleanup_retains_windows_process_when_query_is_denied(
    tmp_path, monkeypatch
):
    import ctypes
    from types import SimpleNamespace

    class _Kernel32:      # noqa: D101 - test double
        def OpenProcess(self, access, inherit_handle, pid):
            return 0

        def GetLastError(self):
            return UndoService._ERROR_ACCESS_DENIED

    active_dir = tmp_path / "AssetsManager_undo_access_denied"
    active_dir.mkdir()
    (tmp_path / f"{active_dir.name}{UndoService._OWNER_MARKER}").write_text(
        "12345", encoding="ascii"
    )
    os.utime(active_dir, (0, 0))
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(
        ctypes, "windll", SimpleNamespace(kernel32=_Kernel32()), raising=False
    )

    assert UndoService.cleanup_stale_undo_dirs(
        tmp_path, max_age_seconds=10, now=100
    ) == 0
    assert active_dir.exists()


@pytest.mark.skipif(
    os.name != "nt",
    reason=(
        "Windows-only cleanup semantics: the test patches os.name to drive "
        "the ctypes.windll/OpenProcess branch, but on POSIX with Python "
        "3.12+ that makes pathlib instantiate WindowsPath, which raises "
        "UnsupportedOperation inside the scan and retains the directory."
    ),
)
def test_startup_cleanup_removes_windows_directory_for_missing_process(
    tmp_path, monkeypatch
):
    import ctypes
    from types import SimpleNamespace

    class _Kernel32:      # noqa: D101 - test double
        def OpenProcess(self, access, inherit_handle, pid):
            return 0

        def GetLastError(self):
            return UndoService._ERROR_INVALID_PARAMETER

    stale_dir = tmp_path / "AssetsManager_undo_missing_process"
    stale_dir.mkdir()
    (tmp_path / f"{stale_dir.name}{UndoService._OWNER_MARKER}").write_text(
        "12345", encoding="ascii"
    )
    os.utime(stale_dir, (0, 0))
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(
        ctypes, "windll", SimpleNamespace(kernel32=_Kernel32()), raising=False
    )

    assert UndoService.cleanup_stale_undo_dirs(
        tmp_path, max_age_seconds=10, now=100
    ) == 1
    assert not stale_dir.exists()


def test_startup_cleanup_does_not_remove_directory_registered_in_process(tmp_path):
    active_dir = tmp_path / "AssetsManager_undo_registered"
    active_dir.mkdir()
    os.utime(active_dir, (0, 0))
    resolved = str(active_dir.resolve())
    with UndoService._active_dirs_lock:
        UndoService._active_undo_dirs.add(resolved)
    try:
        assert UndoService.cleanup_stale_undo_dirs(
            tmp_path, max_age_seconds=0, now=100
        ) == 0
        assert active_dir.exists()
    finally:
        with UndoService._active_dirs_lock:
            UndoService._active_undo_dirs.discard(resolved)


def test_max_depth_evicts_old_entries(tmp_path):
    svc = UndoService(max_depth=2)
    for i in range(5):
        svc.record_rename(f"/tmp/old_{i}.txt", f"/tmp/new_{i}.txt")

    assert len(svc._undo_stack) == 2
    assert svc._undo_stack[0].old == "/tmp/old_3.txt"


def test_new_operation_clears_redo(tmp_path):
    svc = UndoService()
    svc.record_rename("/tmp/a", "/tmp/b")
    svc.undo()
    assert svc.can_redo()

    svc.record_rename("/tmp/c", "/tmp/d")
    assert not svc.can_redo()


def test_can_undo_redo_empty():
    svc = UndoService()
    assert not svc.can_undo()
    assert not svc.can_redo()
    assert svc.undo() is None
    assert svc.redo() is None


def test_redo_rename_through_file_operations(tmp_path):
    src = tmp_path / "old.txt"
    src.write_text("data", encoding="utf-8")

    svc = UndoService()
    svc.record_rename(str(src), str(tmp_path / "new.txt"))
    os.rename(str(src), str(tmp_path / "new.txt"))

    operations = FileOperationService()
    assert svc.perform_undo(operations, str(tmp_path))
    assert (tmp_path / "old.txt").exists()

    assert svc.perform_redo(operations, str(tmp_path))
    assert (tmp_path / "new.txt").exists()
    assert not (tmp_path / "old.txt").exists()


def test_cleanup_removes_undo_dir_and_sidecar(tmp_path):
    svc = UndoService()
    sidecar = f"{svc._undo_dir}{UndoService._OWNER_MARKER}"
    assert os.path.isdir(svc._undo_dir)
    assert os.path.isfile(sidecar)
    svc.cleanup()
    assert not os.path.isdir(svc._undo_dir)
    assert not os.path.exists(sidecar)


def test_clear_removes_all_entries(tmp_path):
    src = tmp_path / "file.txt"
    src.write_text("data", encoding="utf-8")

    svc = UndoService()
    try:
        svc.record_rename(str(src), str(tmp_path / "new.txt"))
        svc.record_delete(str(src))
        assert svc.can_undo()

        svc.clear()

        assert not svc.can_undo()
        assert not svc.can_redo()
        assert svc.undo() is None
        assert svc.redo() is None
    finally:
        svc.cleanup()


def test_clear_cleans_backups(tmp_path):
    src = tmp_path / "file.txt"
    src.write_text("data", encoding="utf-8")

    svc = UndoService()
    try:
        svc.record_delete(str(src))
        backup = svc.peek_undo().backup
        assert os.path.exists(backup)

        svc.clear()

        assert not os.path.exists(backup)
    finally:
        svc.cleanup()


# ── Phase 2.3: Per-library undo isolation ────────────────────────

def test_undo_stacks_isolated_by_library_root(tmp_path):
    """Switching libraries must not carry undo history across libraries."""
    lib_a = tmp_path / "lib_a"
    lib_b = tmp_path / "lib_b"
    lib_a.mkdir()
    lib_b.mkdir()

    src_a = lib_a / "a.txt"
    src_b = lib_b / "b.txt"
    src_a.write_text("data a", encoding="utf-8")
    src_b.write_text("data b", encoding="utf-8")

    svc_a = UndoService(library_root=str(lib_a))
    svc_b = UndoService(library_root=str(lib_b))

    svc_a.record_rename(str(src_a), str(lib_a / "a_new.txt"))
    svc_b.record_delete(str(src_b))

    assert svc_a.can_undo()  # lib A has undo
    assert svc_b.can_undo()  # lib B has undo
    assert svc_a.peek_undo().type == "rename"  # lib A: rename
    assert svc_b.peek_undo().type == "delete"  # lib B: delete

    # Clearing lib B should not affect lib A
    svc_b.clear()
    assert svc_a.can_undo()
    assert not svc_b.can_undo()

    svc_a.cleanup()
    svc_b.cleanup()


def test_two_library_undo_redo_uses_each_session_file_operations(tmp_path):
    from AssetsManager.application import ApplicationBootstrap

    lib_a = tmp_path / "lib_a"
    lib_b = tmp_path / "lib_b"
    lib_a.mkdir()
    lib_b.mkdir()
    old_a, new_a = lib_a / "old_a.txt", lib_a / "new_a.txt"
    old_b, new_b = lib_b / "old_b.txt", lib_b / "new_b.txt"
    old_a.write_text("a", encoding="utf-8")
    old_b.write_text("b", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped_a = bootstrap.runtime_for(bootstrap.library_service.open_session(lib_a)).services
    scoped_b = bootstrap.runtime_for(bootstrap.library_service.open_session(lib_b)).services

    scoped_a.undo_service.record_rename(str(old_a), str(new_a))
    scoped_b.undo_service.record_rename(str(old_b), str(new_b))
    scoped_a.file_operation_service.move(old_a, new_a)
    scoped_b.file_operation_service.move(old_b, new_b)

    assert scoped_a.undo_service.perform_undo(scoped_a.file_operation_service)
    assert old_a.exists() and new_b.exists()
    assert scoped_b.undo_service.can_undo()
    assert scoped_b.undo_service.perform_undo(scoped_b.file_operation_service)
    assert old_b.exists()
    assert scoped_a.undo_service.perform_redo(scoped_a.file_operation_service)
    assert new_a.exists() and old_b.exists()


def test_close_one_library_rejects_its_undo_but_other_library_remains_functional(tmp_path):
    from AssetsManager.application import ApplicationBootstrap

    lib_a = tmp_path / "lib_a"
    lib_b = tmp_path / "lib_b"
    lib_a.mkdir()
    lib_b.mkdir()
    old_b, new_b = lib_b / "old.txt", lib_b / "new.txt"
    old_b.write_text("b", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    session_a = bootstrap.library_service.open_session(lib_a)
    scoped_a = bootstrap.runtime_for(session_a).services
    scoped_b = bootstrap.runtime_for(bootstrap.library_service.open_session(lib_b)).services
    scoped_a.undo_service.record_rename(str(lib_a / "old"), str(lib_a / "new"))
    scoped_b.undo_service.record_rename(str(old_b), str(new_b))
    scoped_b.file_operation_service.move(old_b, new_b)

    session_a.close()

    with pytest.raises(RuntimeError, match="closed"):
        scoped_a.undo_service.perform_undo(scoped_a.file_operation_service)
    assert scoped_b.undo_service.perform_undo(scoped_b.file_operation_service)
    assert old_b.exists()
