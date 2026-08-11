"""Low-batch UndoService tests: backup failure reporting and disk-space guards.

Bug 16: a failed ``_make_backup`` returned None silently, so deletes were
recorded without undo history and the user was never told.  These tests
pin the new contract: ``record_delete`` returns a bool, failure reasons
surface through ``last_backup_error``, and backups are rejected before
they are attempted when the temp volume lacks free space.
"""
import shutil

from AssetsManager.application.undo_service import UndoService


def _usage(free: int):
    """Minimal stand-in for the namedtuple returned by shutil.disk_usage."""
    return type("Usage", (), {"free": free})()


def test_record_delete_reports_backup_copy_failure(tmp_path, monkeypatch):
    source = tmp_path / "asset.txt"
    source.write_text("data", encoding="utf-8")

    def failing_copy2(src, dst, *args, **kwargs):
        raise OSError("simulated copy failure")

    monkeypatch.setattr(shutil, "copy2", failing_copy2)
    svc = UndoService()
    try:
        assert svc.record_delete(str(source)) is False
        assert not svc.can_undo()
        assert svc.last_backup_error is not None
        assert "simulated copy failure" in svc.last_backup_error
        assert "asset.txt" in svc.last_backup_error
    finally:
        svc.cleanup()


def test_prepare_delete_reports_backup_copy_failure(tmp_path, monkeypatch):
    """The _actions.py caller path keeps its UndoEntry | None contract."""
    source = tmp_path / "asset.txt"
    source.write_text("data", encoding="utf-8")

    def failing_copy2(src, dst, *args, **kwargs):
        raise OSError("simulated copy failure")

    monkeypatch.setattr(shutil, "copy2", failing_copy2)
    svc = UndoService()
    try:
        assert svc.prepare_delete(str(source)) is None
        assert not svc.can_undo()
        assert svc.last_backup_error is not None
        assert "simulated copy failure" in svc.last_backup_error
    finally:
        svc.cleanup()


def test_record_delete_rejects_backup_when_disk_is_full(tmp_path, monkeypatch):
    source = tmp_path / "asset.txt"
    source.write_text("x" * 2048, encoding="utf-8")
    monkeypatch.setattr(shutil, "disk_usage", lambda path: _usage(free=1024))
    svc = UndoService()
    try:
        assert svc.record_delete(str(source)) is False
        assert not svc.can_undo()
        assert svc.last_backup_error is not None
        assert "disk space" in svc.last_backup_error
    finally:
        svc.cleanup()


def test_record_delete_rejects_directory_backup_when_disk_is_full(tmp_path, monkeypatch):
    folder = tmp_path / "assets"
    folder.mkdir()
    (folder / "a.bin").write_bytes(b"a" * 4096)
    (folder / "b.bin").write_bytes(b"b" * 4096)
    monkeypatch.setattr(shutil, "disk_usage", lambda path: _usage(free=4096))
    svc = UndoService()
    try:
        assert svc.prepare_delete(str(folder)) is None
        assert svc.last_backup_error is not None
        assert "disk space" in svc.last_backup_error
    finally:
        svc.cleanup()


def test_record_delete_still_backs_up_normally(tmp_path):
    source = tmp_path / "asset.txt"
    source.write_text("data", encoding="utf-8")
    svc = UndoService()
    try:
        assert svc.record_delete(str(source)) is True
        assert svc.last_backup_error is None
        assert svc.can_undo()
        backup = svc.peek_undo().backup
        assert backup
        assert svc.peek_undo().type == "delete"
    finally:
        svc.cleanup()


def test_successful_backup_clears_previous_error(tmp_path, monkeypatch):
    source = tmp_path / "asset.txt"
    source.write_text("data", encoding="utf-8")
    svc = UndoService()
    try:

        def failing_copy2(src, dst, *args, **kwargs):
            raise OSError("simulated copy failure")

        monkeypatch.setattr(shutil, "copy2", failing_copy2)
        assert svc.record_delete(str(source)) is False
        assert svc.last_backup_error is not None

        monkeypatch.undo()
        assert svc.record_delete(str(source)) is True
        assert svc.last_backup_error is None
    finally:
        svc.cleanup()
