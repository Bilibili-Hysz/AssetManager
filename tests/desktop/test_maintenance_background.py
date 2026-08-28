"""Background maintenance tasks: backup/restore runner and thumbnail clear.

Asserts the threading contract instead of (untestable) "UI does not freeze":
- the long work runs on a non-GUI worker thread;
- completion callbacks are marshalled back to the GUI thread;
- a busy runner rejects re-entrant triggers instead of queueing a second task;
- the settings-dialog clear-thumbnails flow disables its buttons and
  reports (removed, failed) counts on completion.
"""
import os
import threading
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from AssetsManager.dialogs._maintenance_tasks import (
    BusyProgressDialog,
    MaintenanceTaskRunner,
)
from AssetsManager.dialogs.settings_dialog import SettingsDialog


def _app():
    return QApplication.instance() or QApplication([])


def _pump(app, predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


class _BlockingWork:
    """Worker body that blocks until the test releases it."""

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.threads = []

    def __call__(self):
        self.threads.append(threading.current_thread())
        self.started.set()
        self.release.wait(5.0)


# ── MaintenanceTaskRunner ───────────────────────────────────────


def test_runner_rejects_reentry_while_busy(monkeypatch):
    app = _app()
    runner = MaintenanceTaskRunner(None)
    work = _BlockingWork()
    prompts = []
    monkeypatch.setattr(
        QMessageBox, "information", staticmethod(lambda *args: prompts.append(args))
    )

    assert runner.run(
        work, title="T", busy_text="B", reentry_text="busy!"
    ) is True
    assert work.started.wait(2.0)
    assert runner.is_busy

    # A second trigger while the task runs is rejected with a prompt.
    assert runner.run(
        work, title="T", busy_text="B", reentry_text="busy!"
    ) is False
    assert prompts == [(None, "T", "busy!")]
    assert len(work.threads) == 1

    work.release.set()
    assert _pump(app, lambda: not runner.is_busy)
    assert not runner.is_busy


def test_runner_work_runs_off_gui_thread_and_success_back_on_gui_thread():
    app = _app()
    gui_thread = threading.current_thread()
    runner = MaintenanceTaskRunner(None)
    results = []

    assert runner.run(
        lambda: "payload",
        title="T",
        busy_text="B",
        reentry_text="r",
        on_success=lambda value: results.append(
            (threading.current_thread(), value)
        ),
    ) is True

    assert _pump(app, lambda: bool(results))
    assert results[0][0] is gui_thread
    assert results[0][1] == "payload"


def test_runner_reenables_disabled_widgets_and_delivers_error():
    app = _app()
    runner = MaintenanceTaskRunner(None)
    button = QPushButton()
    errors = []

    def _boom():
        raise RuntimeError("boom")

    assert runner.run(
        _boom,
        title="T",
        busy_text="B",
        reentry_text="r",
        disable=(button,),
        on_error=lambda exc: errors.append(exc),
    ) is True
    assert button.isEnabled() is False

    assert _pump(app, lambda: bool(errors))
    assert button.isEnabled() is True
    assert errors and isinstance(errors[0], RuntimeError)
    assert str(errors[0]) == "boom"
    assert not runner.is_busy


def test_busy_progress_dialog_ignores_close_and_reject_until_finished():
    _app()
    dialog = BusyProgressDialog(None, "T", "B")
    dialog.show()
    assert dialog.isVisible()

    dialog.close()
    assert dialog.isVisible()  # closeEvent ignored while running
    dialog.reject()
    assert dialog.isVisible()  # Esc ignored while running

    dialog.finish()
    assert not dialog.isVisible()


# ── Settings dialog: clear thumbnails ───────────────────────────


class _FakeLoader:
    def __init__(self, removed=3, failed=0):
        self.removed = removed
        self.failed = failed
        self.worker_thread = None
        self.started = threading.Event()
        self.release = threading.Event()

    def clear_thumb_cache_async(self, on_progress=None, on_complete=None):
        def _run():
            self.worker_thread = threading.current_thread()
            self.started.set()
            self.release.wait(5.0)
            if on_progress:
                on_progress(1, 2)
                on_progress(2, 2)
            if on_complete:
                on_complete(self.removed, self.failed)

        threading.Thread(target=_run, daemon=True).start()
        return True


def _patch_dialog_messages(monkeypatch, question=QMessageBox.StandardButton.Yes):
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: question)
    )
    boxes = {"information": [], "warning": []}
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda *a, **k: boxes["information"].append(a)),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda *a, **k: boxes["warning"].append(a)),
    )
    return boxes


def test_clear_thumbnails_runs_on_worker_and_reports_counts(monkeypatch):
    app = _app()
    dialog = SettingsDialog()
    try:
        loader = _FakeLoader(removed=3, failed=0)
        host = SimpleNamespace(file_list=SimpleNamespace(_loader=loader))
        monkeypatch.setattr(SettingsDialog, "parent", lambda self: host)
        boxes = _patch_dialog_messages(monkeypatch)

        dialog._clear_thumbnails()

        assert loader.started.wait(2.0)
        # Buttons disabled and progress shown while the worker runs.
        assert dialog._clear_btn.isEnabled() is False
        assert dialog._regen_btn.isEnabled() is False
        assert not dialog._progress.isHidden()

        loader.release.set()
        assert _pump(app, lambda: bool(boxes["information"]))

        assert loader.worker_thread is not threading.current_thread()
        assert dialog._clear_btn.isEnabled() is True
        assert dialog._regen_btn.isEnabled() is True
        assert dialog._progress.isHidden()
        assert boxes["information"] and "3" in boxes["information"][0][2]

        dialog.close()
        app.processEvents()
    finally:
        dialog.deleteLater()
        app.processEvents()


def test_clear_thumbnails_reports_failed_file_count(monkeypatch):
    app = _app()
    dialog = SettingsDialog()
    try:
        loader = _FakeLoader(removed=2, failed=1)
        host = SimpleNamespace(file_list=SimpleNamespace(_loader=loader))
        monkeypatch.setattr(SettingsDialog, "parent", lambda self: host)
        boxes = _patch_dialog_messages(monkeypatch)

        dialog._clear_thumbnails()
        loader.release.set()
        assert _pump(app, lambda: bool(boxes["information"]))

        message = boxes["information"][0][2]
        assert "2" in message and "1" in message

        dialog.close()
        app.processEvents()
    finally:
        dialog.deleteLater()
        app.processEvents()


def test_clear_thumbnails_without_library_warns(monkeypatch):
    app = _app()
    dialog = SettingsDialog()
    try:
        boxes = _patch_dialog_messages(monkeypatch, question=QMessageBox.StandardButton.Yes)
        monkeypatch.setattr(SettingsDialog, "parent", lambda self: None)

        dialog._clear_thumbnails()

        assert boxes["warning"] and boxes["information"] == []
        dialog.close()
        app.processEvents()
    finally:
        dialog.deleteLater()
        app.processEvents()


# ── Settings dialog: backup tab busy guard ──────────────────────


def test_refresh_backup_status_keeps_buttons_disabled_while_task_busy(monkeypatch):
    _app()
    dialog = SettingsDialog()
    try:
        dialog._library_settings_adapter = SimpleNamespace(
            library_root=None,
            view_model=lambda: SimpleNamespace(restore_allowed=True),
            list_restore_quarantine=lambda: (),
            session_token="token",
        )
        busy_runner = SimpleNamespace(is_busy=True)
        dialog._maintenance_runner = busy_runner
        for button in (dialog._export_btn, dialog._backup_btn, dialog._restore_btn):
            button.setEnabled(False)

        dialog._refresh_backup_status()

        # The busy guard must not re-enable buttons the runner disabled.
        assert dialog._export_btn.isEnabled() is False
        assert dialog._backup_btn.isEnabled() is False
        assert dialog._restore_btn.isEnabled() is False
        dialog.close()
        app = _app()
        app.processEvents()
    finally:
        dialog.deleteLater()
        app.processEvents()
