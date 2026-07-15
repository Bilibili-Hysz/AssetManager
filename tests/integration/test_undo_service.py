"""Tests for UndoService."""
import os

from AssetsManager.application.undo_service import UndoService


class _FailingFileOperations:
    def move(self, source, destination, *, library_root):
        raise OSError("filesystem failure")


def test_failed_undo_keeps_entry_on_undo_stack(tmp_path):
    svc = UndoService()
    svc.record_rename("missing-new", "old")

    assert not svc.perform_undo(_FailingFileOperations(), str(tmp_path))
    assert svc.can_undo()
    assert not svc.can_redo()


def test_failed_redo_keeps_entry_on_redo_stack(tmp_path):
    svc = UndoService()
    svc.record_rename("old", "missing-new")
    assert svc.undo() is not None

    assert not svc.perform_redo(_FailingFileOperations(), str(tmp_path))
    assert not svc.can_undo()
    assert svc.can_redo()


def test_record_rename_and_undo(tmp_path):
    src = tmp_path / "old.txt"
    src.write_text("data", encoding="utf-8")

    svc = UndoService()
    svc.record_rename(str(src), str(tmp_path / "new.txt"))
    os.rename(str(src), str(tmp_path / "new.txt"))

    assert svc.can_undo()
    entry = svc.undo()
    assert entry is not None
    assert entry.type == "rename"
    assert svc.execute_undo(entry) is True
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
    entry = svc.undo()
    assert entry is not None
    assert entry.type == "delete"
    assert svc.execute_undo(entry) is True
    assert (tmp_path / "file.txt").exists()
    assert (tmp_path / "file.txt").read_text(encoding="utf-8") == "data"


def test_delete_redo_can_be_undone_again(tmp_path):
    src = tmp_path / "file.txt"
    src.write_text("data", encoding="utf-8")

    svc = UndoService()
    try:
        svc.record_delete(str(src))
        os.remove(str(src))

        entry = svc.undo()
        assert entry is not None
        assert svc.execute_undo(entry) is True
        assert src.exists()

        redo_entry = svc.redo()
        assert redo_entry is not None
        assert svc.execute_redo(redo_entry) is True
        assert not src.exists()

        entry_again = svc.undo()
        assert entry_again is not None
        assert svc.execute_undo(entry_again) is True
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

        assert undo.perform_undo(scoped.file_operation_service, str(library))
        assert source.read_text(encoding="utf-8") == "data"
        assert index.get_entry(conn, source) is not None
        assert created[-1].path == str(source)

        assert undo.perform_redo(scoped.file_operation_service, str(library))
        assert not source.exists()
        assert TagStore(str(library)).get_tags(str(source)) == []
        assert ThumbnailRepository(conn).list_all() == []
        assert not thumbnail_file.exists()
        assert index.get_entry(conn, source) is None
        assert deleted[-1].path == str(source)
    finally:
        undo.cleanup()


def test_rename_undo_and_redo_keep_metadata_and_index_consistent(tmp_path):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.core.tag_store import TagStore

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
    undo = scoped.undo_service

    try:
        undo.record_rename(str(old), str(new))
        scoped.file_operation_service.move(old, new, library_root=library)

        assert undo.perform_undo(scoped.file_operation_service, str(library))
        assert old.exists()
        assert TagStore(str(library)).get_tags(str(old)) == ["hero"]
        assert index.get_entry(conn, old) is not None
        assert index.get_entry(conn, new) is None

        assert undo.perform_redo(scoped.file_operation_service, str(library))
        assert new.exists()
        assert TagStore(str(library)).get_tags(str(new)) == ["hero"]
        assert index.get_entry(conn, new) is not None
        assert index.get_entry(conn, old) is None
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


def test_execute_redo_rename(tmp_path):
    src = tmp_path / "old.txt"
    src.write_text("data", encoding="utf-8")

    svc = UndoService()
    svc.record_rename(str(src), str(tmp_path / "new.txt"))
    os.rename(str(src), str(tmp_path / "new.txt"))

    entry = svc.undo()
    assert entry is not None
    svc.execute_undo(entry)
    assert (tmp_path / "old.txt").exists()

    redo_entry = svc.redo()
    assert redo_entry is not None
    assert svc.execute_redo(redo_entry) is True
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
