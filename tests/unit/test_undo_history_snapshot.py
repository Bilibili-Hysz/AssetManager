"""UndoService.history_snapshot — read-only panel snapshot (H1-b E-C2).

Covers the shape contract of the session undo history view: newest-first
ordering across the undo and redo stacks, batch child counts, the raw target
text, the push timestamp, the backup-retention flag, and the guarantee that
no execution machinery (callbacks, backup paths) leaks into the snapshot.
The LIFO semantics themselves are covered by test_undo_service.py.
"""
from dataclasses import fields
from time import time
from types import SimpleNamespace

from AssetsManager.application.undo_service import UndoHistoryItem, UndoService


def _service():
    return UndoService(library_root="/lib")


def _ok_file_operations():
    """Minimal file_operations double whose every move/restore succeeds."""
    return SimpleNamespace(
        move=lambda source, destination, library_root=None: SimpleNamespace(ok=True),
        restore_backup=lambda backup, destination, library_root=None: SimpleNamespace(ok=True),
        delete_permanent=lambda paths, library_root=None: SimpleNamespace(ok=True),
    )


def test_snapshot_lists_undo_stack_newest_first():
    service = _service()
    try:
        service.record_rename("/lib/a.png", "/lib/b.png")
        service.record_custom("tag_add", lambda is_undo: True, path="hero")

        snapshot = service.history_snapshot()

        assert [item.entry_type for item in snapshot] == ["tag_add", "rename"]
        assert all(item.origin == "undo" for item in snapshot)
        assert snapshot[0].target == "hero"
        assert snapshot[1].target == "/lib/a.png -> /lib/b.png"
        # Push timestamps are stamped and non-decreasing (newest first).
        assert snapshot[0].recorded_at > 0
        assert snapshot[0].recorded_at >= snapshot[1].recorded_at > 0
    finally:
        service.cleanup()


def test_batch_entry_reports_child_count_without_target():
    service = _service()
    try:
        batch = service.record_rename_batch([
            ("/lib/a.png", "/lib/moved/a.png"),
            ("/lib/b.png", "/lib/moved/b.png"),
            ("/lib/c.png", "/lib/moved/c.png"),
        ])
        assert batch is not None

        snapshot = service.history_snapshot()

        assert len(snapshot) == 1
        item = snapshot[0]
        assert item.is_batch is True
        assert item.child_count == 3
        assert item.target == ""  # the panel renders the translated count
        assert item.origin == "undo"
    finally:
        service.cleanup()


def test_undo_moves_entry_to_redo_in_snapshot():
    service = _service()
    try:
        service.record_rename("/lib/a.png", "/lib/b.png")
        assert service.perform_undo(_ok_file_operations(), "/lib") is True

        snapshot = service.history_snapshot()

        assert [item.origin for item in snapshot] == ["redo"]
        assert snapshot[0].entry_type == "rename"

        assert service.perform_redo(_ok_file_operations(), "/lib") is True
        assert [item.origin for item in service.history_snapshot()] == ["undo"]
    finally:
        service.cleanup()


def test_delete_entry_carries_backup_retention_flag(tmp_path):
    service = _service()
    try:
        victim = tmp_path / "victim.txt"
        victim.write_text("data", encoding="utf-8")
        assert service.record_delete(str(victim)) is True

        item = service.history_snapshot()[0]

        assert item.entry_type == "delete"
        assert item.target == str(victim)
        assert item.has_backup is True
    finally:
        service.cleanup()


def test_rename_batch_has_no_backup_retention():
    service = _service()
    try:
        service.record_rename_batch([("/lib/a.png", "/lib/b.png")])

        item = service.history_snapshot()[0]

        assert item.has_backup is False
    finally:
        service.cleanup()


def test_snapshot_exposes_no_execution_machinery(tmp_path):
    service = _service()
    try:
        victim = tmp_path / "victim.txt"
        victim.write_text("data", encoding="utf-8")
        assert service.record_delete(str(victim)) is True

        item = service.history_snapshot()[0]

        item_fields = {field.name for field in fields(UndoHistoryItem)}
        # No callback, no backup location, no raw entry object.
        assert "callback" not in item_fields
        assert "backup" not in item_fields
        assert not hasattr(item, "callback")
        assert item_fields == {
            "entry_type", "target", "recorded_at", "degraded", "failed",
            "is_batch", "child_count", "has_backup", "origin",
        }
    finally:
        service.cleanup()


def test_snapshot_of_empty_stacks_is_empty():
    service = _service()
    try:
        assert service.history_snapshot() == []
    finally:
        service.cleanup()


def test_recorded_at_is_wall_clock():
    service = _service()
    try:
        before = time()
        service.record_rename("/lib/a.png", "/lib/b.png")
        after = time()

        recorded_at = service.history_snapshot()[0].recorded_at

        assert before <= recorded_at <= after
    finally:
        service.cleanup()
