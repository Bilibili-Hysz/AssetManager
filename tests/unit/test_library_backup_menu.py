"""Tests for the desktop library backup/restore menu entry points (B1)."""
import os
from types import SimpleNamespace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from AssetsManager.window import MainWindow


def _app():
    return QApplication.instance() or QApplication([])


class _FakeExportService:
    def __init__(self, restore_ok=True):
        self._restore_ok = restore_ok
        self.backup_calls = []
        self.restore_calls = []

    def backup_filename(self, root):
        return "lib_backup_20260814.assetbackup.zip"

    def create_backup(self, root, destination):
        self.backup_calls.append((str(root), str(destination)))
        return SimpleNamespace(
            destination=Path(destination),
            file_count=3,
            bytes_written=12345,
        )

    def restore_backup(self, archive, root, *, overwrite_existing):
        self.restore_calls.append((str(archive), str(root), overwrite_existing))
        if not self._restore_ok:
            raise RuntimeError("corrupt archive")
        return SimpleNamespace(data_dir=Path("C:/fake/RuntimeData/library-data"))


class _FakeSession:
    root = Path("C:/fake/library")


def _skeleton_window(session=None, export_service=None):
    win = MainWindow.__new__(MainWindow)
    win._library_session = session
    if export_service is not None:
        win._scoped_services_for_session = (
            lambda s: SimpleNamespace(export_service=export_service)
        )
    return win


def test_backup_requires_open_library(monkeypatch):
    _app()
    recorded = []
    monkeypatch.setattr(
        QMessageBox, "information", staticmethod(lambda *args: recorded.append(args))
    )
    win = _skeleton_window(session=None)

    win._backup_library()

    assert len(recorded) == 1


def test_backup_writes_archive_and_reports_success(monkeypatch, tmp_path):
    _app()
    dest = tmp_path / "lib_backup.assetbackup.zip"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(dest), "filter")),
    )
    recorded = []
    monkeypatch.setattr(
        QMessageBox, "information", staticmethod(lambda *args: recorded.append(args))
    )
    service = _FakeExportService()
    win = _skeleton_window(session=_FakeSession(), export_service=service)

    win._backup_library()

    assert service.backup_calls == [(str(_FakeSession.root), str(dest))]
    assert len(recorded) == 1
    assert "12345" in recorded[0][2]


def test_restore_cancels_when_file_dialog_returns_empty(monkeypatch):
    _app()
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *a, **k: ("", "filter")),
    )
    recorded = []
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *args: recorded.append(args))
    )
    win = _skeleton_window(session=_FakeSession())

    win._restore_library()

    assert recorded == []


def test_restore_confirms_then_restores(monkeypatch, tmp_path):
    _app()
    archive = tmp_path / "lib_backup.assetbackup.zip"
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *a, **k: (str(archive), "filter")),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    recorded = []
    monkeypatch.setattr(
        QMessageBox, "information", staticmethod(lambda *args: recorded.append(args))
    )
    service = _FakeExportService()
    win = _skeleton_window(session=_FakeSession(), export_service=service)

    win._restore_library()

    assert service.restore_calls == [(str(archive), str(_FakeSession.root), True)]
    assert len(recorded) == 1


def test_restore_surfaces_failure(monkeypatch, tmp_path):
    _app()
    archive = tmp_path / "lib_backup.assetbackup.zip"
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *a, **k: (str(archive), "filter")),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    recorded = []
    monkeypatch.setattr(
        QMessageBox, "critical", staticmethod(lambda *args: recorded.append(args))
    )
    service = _FakeExportService(restore_ok=False)
    win = _skeleton_window(session=_FakeSession(), export_service=service)

    win._restore_library()

    assert len(recorded) == 1
    assert "corrupt archive" in recorded[0][2]
