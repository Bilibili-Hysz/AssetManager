"""Tests for the desktop library backup/restore menu entry points (B1).

The backup/restore work runs on a worker thread behind the shared
maintenance runner; the tests assert both the service contract and the
thread affinity (work off the GUI thread, completion callbacks back on
the GUI thread).
"""
import os
import threading
import time
from types import SimpleNamespace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from AssetsManager.dialogs._maintenance_tasks import MaintenanceTaskRunner
from AssetsManager.window import MainWindow


def _app():
    return QApplication.instance() or QApplication([])


def _pump(app, predicate, timeout=5.0):
    """Run the event loop until *predicate* is true or *timeout* elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


class _FakeExportService:
    def __init__(self, restore_ok=True):
        self._restore_ok = restore_ok
        self.backup_calls = []
        self.restore_calls = []
        self.backup_threads = []
        self.restore_threads = []

    def backup_filename(self, root):
        return "lib_backup_20260814.assetbackup.zip"

    def create_backup(self, root, destination):
        self.backup_threads.append(threading.current_thread())
        self.backup_calls.append((str(root), str(destination)))
        return SimpleNamespace(
            destination=Path(destination),
            file_count=3,
            bytes_written=12345,
        )

    def restore_backup(self, archive, root, *, overwrite_existing):
        self.restore_threads.append(threading.current_thread())
        self.restore_calls.append((str(archive), str(root), overwrite_existing))
        if not self._restore_ok:
            raise RuntimeError("corrupt archive")
        return SimpleNamespace(data_dir=Path("C:/fake/RuntimeData/library-data"))


class _FakeSession:
    root = Path("C:/fake/library")


def _skeleton_window(session=None, export_service=None):
    win = MainWindow.__new__(MainWindow)
    win._library_session = session
    # A bare __new__ window has no C++ object to parent dialogs to; the
    # production code creates the runner with owner=window lazily.
    win._maintenance_runner = MaintenanceTaskRunner(None)
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


def test_backup_writes_archive_and_reports_success_on_gui_thread(
    monkeypatch, tmp_path
):
    app = _app()
    gui_thread = threading.current_thread()
    dest = tmp_path / "lib_backup.assetbackup.zip"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(dest), "filter")),
    )
    reported = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda *args: reported.append((threading.current_thread(), args))),
    )
    service = _FakeExportService()
    win = _skeleton_window(session=_FakeSession(), export_service=service)

    win._backup_library()

    assert win._maintenance_runner.is_busy
    assert _pump(app, lambda: not win._maintenance_runner.is_busy)

    assert service.backup_calls == [(str(_FakeSession.root), str(dest))]
    # The service call ran on a worker thread, the success box on the GUI thread.
    assert service.backup_threads and service.backup_threads[0] is not gui_thread
    assert reported and reported[0][0] is gui_thread
    assert "12345" in reported[0][1][2]


def test_backup_failure_reports_critical_on_gui_thread(monkeypatch, tmp_path):
    app = _app()
    gui_thread = threading.current_thread()
    dest = tmp_path / "lib_backup.assetbackup.zip"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(dest), "filter")),
    )

    class _FailingService(_FakeExportService):
        def create_backup(self, root, destination):
            super().create_backup(root, destination)
            raise RuntimeError("disk full")

    service = _FailingService()
    win = _skeleton_window(session=_FakeSession(), export_service=service)
    critical = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda *args: critical.append((threading.current_thread(), args))),
    )

    win._backup_library()

    assert _pump(app, lambda: not win._maintenance_runner.is_busy)

    assert critical and critical[0][0] is gui_thread
    assert "disk full" in critical[0][1][2]


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


def test_restore_confirms_then_restores_on_worker_thread(monkeypatch, tmp_path):
    app = _app()
    gui_thread = threading.current_thread()
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
    reported = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda *args: reported.append((threading.current_thread(), args))),
    )
    service = _FakeExportService()
    win = _skeleton_window(session=_FakeSession(), export_service=service)

    win._restore_library()

    assert win._maintenance_runner.is_busy
    assert _pump(app, lambda: not win._maintenance_runner.is_busy)

    assert service.restore_calls == [(str(archive), str(_FakeSession.root), True)]
    assert service.restore_threads and service.restore_threads[0] is not gui_thread
    assert reported and reported[0][0] is gui_thread
    assert "library-data" in reported[0][1][2]


def test_restore_surfaces_failure(monkeypatch, tmp_path):
    app = _app()
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

    assert _pump(app, lambda: not win._maintenance_runner.is_busy)

    assert len(recorded) == 1
    assert "corrupt archive" in recorded[0][2]
