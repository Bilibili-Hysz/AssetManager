"""Tests for UndoService."""
import os

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
