"""Tests for UndoService."""
import os

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
    from AssetsManager.domain.events import FileCreated, FileDeleted
    from AssetsManager.repositories.thumbnail_repository import ThumbnailRepository

    library = tmp_path / "library"
    library.mkdir()
    source = library / "asset.txt"
    source.write_text("data", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))
    conn = scoped.session.db_conn
    index = scoped.asset_index_service
    index.index_directory(conn, library, library)
    TagStore(str(library)).add_tag(str(source), "hero")
    ThumbnailRepository(conn).upsert_entry("thumb", str(source.resolve()), 1.0, 1, 1, 1)
    thumbnail_file = scoped.session.thumb_dir / "thumb.webp"
    thumbnail_file.write_bytes(b"thumb")
    created = []
    deleted = []
    get_event_bus().subscribe(FileCreated, created.append)
    get_event_bus().subscribe(FileDeleted, deleted.append)
    undo = scoped.undo_service

    try:
        undo.record_delete(str(source))
        assert scoped.file_operation_service.delete_to_trash([source]).ok

        assert undo.perform_undo(scoped.file_operation_service)
        assert source.read_text(encoding="utf-8") == "data"
        assert index.get_entry(conn, source) is not None
        assert created[-1].path == str(source)

        assert undo.perform_redo(scoped.file_operation_service)
        assert not source.exists()
        assert TagStore(str(library)).get_tags(str(source)) == []
        assert ThumbnailRepository(conn).list_all() == []
        assert not thumbnail_file.exists()
        assert index.get_entry(conn, source) is None
        assert deleted[-1].path == str(source)
    finally:
        undo.cleanup()


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
    scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))
    conn = scoped.session.db_conn
    index = scoped.asset_index_service
    index.index_directory(conn, library, library)
    TagStore(str(library)).add_tag(str(old), "hero")
    ThumbnailRepository(conn).upsert_entry("thumb", str(old.resolve()), 1.0, 1, 1, 1)
    old_thumbnail = scoped.session.thumb_dir / "thumb.webp"
    old_thumbnail.write_bytes(b"thumb")
    undo = scoped.undo_service

    try:
        undo.record_rename(str(old), str(new))
        assert scoped.file_operation_service.move(old, new) == new

        assert undo.perform_undo(scoped.file_operation_service)
        assert old.exists()
        assert TagStore(str(library)).get_tags(str(old)) == ["hero"]
        assert index.get_entry(conn, old) is not None
        assert index.get_entry(conn, new) is None
        assert ThumbnailRepository(conn).list_all()[0][1] == str(old.resolve())

        assert undo.perform_redo(scoped.file_operation_service)
        assert new.exists()
        assert TagStore(str(library)).get_tags(str(new)) == ["hero"]
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


def test_cleanup_removes_undo_dir(tmp_path):
    svc = UndoService()
    assert os.path.isdir(svc._undo_dir)
    svc.cleanup()
    assert not os.path.isdir(svc._undo_dir)


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
    scoped_a = bootstrap.for_library(bootstrap.library_service.open_session(lib_a))
    scoped_b = bootstrap.for_library(bootstrap.library_service.open_session(lib_b))

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
    scoped_a = bootstrap.for_library(session_a)
    scoped_b = bootstrap.for_library(bootstrap.library_service.open_session(lib_b))
    scoped_a.undo_service.record_rename(str(lib_a / "old"), str(lib_a / "new"))
    scoped_b.undo_service.record_rename(str(old_b), str(new_b))
    scoped_b.file_operation_service.move(old_b, new_b)

    session_a.close()

    with pytest.raises(RuntimeError, match="closed"):
        scoped_a.undo_service.perform_undo(scoped_a.file_operation_service)
    assert scoped_b.undo_service.perform_undo(scoped_b.file_operation_service)
    assert old_b.exists()
