"""Shared background runner for long maintenance tasks (backup / restore).

Both the main window menu and the settings dialog trigger the same
GB-scale library backup / restore service calls.  This module gives both
entry points one identical UI contract:

- the service call runs on a worker thread (GUI never blocks);
- a modal busy progress dialog is shown for the duration and cannot be
  dismissed while the task runs (the operations are not cancellable);
- only one backup/restore task runs at a time per owner; a re-entrant
  trigger is rejected with a prompt instead of queueing a second task;
- the completion callbacks are marshalled back to the GUI thread and
  decide the success/failure presentation for their caller.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QProgressDialog

from AssetsManager.panels.file_list._background import run_task

_log = logging.getLogger(__name__)

try:
    from shiboken6 import Shiboken
except ImportError:  # pragma: no cover - PySide6 always ships shiboken6
    Shiboken = None


def _alive(obj) -> bool:
    """True while a C++-backed QObject has not been destroyed."""
    if obj is None:
        return False
    if Shiboken is not None:
        try:
            return Shiboken.isValid(obj)
        except Exception:
            return False
    return True


class BusyProgressDialog(QProgressDialog):
    """Busy progress dialog that cannot be dismissed while a task runs.

    Backup/restore have no cooperative cancellation, so closing the dialog
    would only hide the (still running) task.  The dialog therefore ignores
    close requests until the runner marks it finished.
    """

    def __init__(self, owner, title: str, busy_text: str):
        super().__init__(owner)
        self.setProperty("maintenance_finished", False)
        self.setWindowTitle(title)
        self.setLabelText(busy_text)
        self.setRange(0, 0)  # indeterminate: busy indicator
        self.setCancelButton(None)
        self.setAutoClose(False)
        self.setAutoReset(False)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumDuration(0)

    def closeEvent(self, event):
        if not self.property("maintenance_finished"):
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self):
        # Esc must not dismiss the dialog while the task is running.
        if not self.property("maintenance_finished"):
            return
        super().reject()

    def finish(self):
        self.setProperty("maintenance_finished", True)
        self.reset()
        self.close()


class MaintenanceTaskRunner(QObject):
    """Run one long maintenance task at a time on a worker thread.

    The triggering slot stays on the GUI thread; *work* executes on a
    ``QThreadPool`` worker and the completion callbacks are delivered back
    on the GUI thread via a queued signal (see
    :func:`AssetsManager.panels.file_list._background.run_task`).
    """

    def __init__(self, owner=None):
        super().__init__()
        self._owner = owner
        self._busy = False
        self._generation = 0
        self._dialog: BusyProgressDialog | None = None
        self._disabled: tuple = ()

    @property
    def is_busy(self) -> bool:
        return self._busy

    def run(
        self,
        work: Callable[[], Any],
        *,
        title: str,
        busy_text: str,
        reentry_text: str,
        # Callbacks may return the QMessageBox result; the runner ignores it.
        on_success: Callable[[Any], object] | None = None,
        on_error: Callable[[BaseException], object] | None = None,
        disable: tuple = (),
    ) -> bool:
        """Start *work* in the background; return False when rejected.

        While a task is running this shows the re-entry prompt (instead of
        queueing a second task) and returns False.  The widgets in
        *disable* are disabled until the task completes.
        """
        if self._busy:
            self._reentry_prompt(title, reentry_text)
            return False
        self._busy = True
        self._generation += 1
        generation = self._generation
        self._disabled = tuple(disable)
        for widget in self._disabled:
            if _alive(widget):
                widget.setEnabled(False)
        dialog = BusyProgressDialog(self._owner, title, busy_text)
        self._dialog = dialog

        def _on_done(result, exc):
            self._finish(generation, result, exc, on_success, on_error)

        run_task(work, on_done=_on_done)
        dialog.show()
        return True

    # ── Completion plumbing ────────────────────────────────────

    def _finish(self, generation, result, exc, on_success, on_error):
        if generation != self._generation:
            return
        self._busy = False
        dialog = self._dialog
        self._dialog = None
        if dialog is not None and _alive(dialog):
            dialog.finish()
        for widget in self._disabled:
            if _alive(widget):
                widget.setEnabled(True)
        self._disabled = ()
        if exc is not None:
            if on_error is not None:
                self._dispatch(on_error, exc)
            return
        if on_success is not None:
            self._dispatch(on_success, result)

    def _dispatch(self, callback, value):
        try:
            callback(value)
        except Exception:
            # A destroyed owner must not crash the queued completion.
            _log.exception("Maintenance task completion callback failed")

    def _reentry_prompt(self, title: str, reentry_text: str):
        from PySide6.QtWidgets import QMessageBox

        parent = self._owner if _alive(self._owner) else None
        QMessageBox.information(parent, title, reentry_text)
