"""Background task runner for file-list operations."""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Qt

_log = logging.getLogger(__name__)

# QRunnables run with the pool default ``autoDelete=True``: QThreadPool deletes
# the C++ object as soon as ``run()`` returns, and PySide6 does not keep the
# Python wrapper (nor the closures it captures, e.g. sessions/services) alive.
# The wrapper must therefore be held from Python until the ``done`` signal has
# been delivered on the main thread — otherwise a queued delivery is dropped
# and the task is garbage collected before its completion callback runs.
_orphan_ops: set[QRunnable] = set()


def run_in_background(
    func: Callable,
    *args,
    on_done: Callable[[], None] | None = None,
    background_ops: list[QRunnable] | None = None,
) -> None:
    """Run ``func(*args)`` on a worker thread.

    If *on_done* is provided, it is called on the main thread after
    completion.  If *background_ops* is provided (a list owned by the
    calling panel), the runnable is added to it so the panel can track
    in-flight operations and keep it alive until the done signal fires.
    """
    class _Sig(QObject):
        done = Signal()

    class _Op(QRunnable):
        def __init__(self, fn, fn_args, fn_sig):
            super().__init__()
            self._fn = fn
            self._a = fn_args
            self._sig = fn_sig

        def run(self):
            op_sig = self._sig
            try:
                self._fn(*self._a)
            except Exception:
                _log.exception("Background task failed")
            if op_sig is not None:
                op_sig.done.emit()

    sig = _Sig()
    op = _Op(func, args, sig)
    if on_done is not None:
        sig.done.connect(on_done)
    if background_ops is not None:
        background_ops.append(op)

        def _cleanup():
            background_ops.remove(op)
        sig.done.connect(_cleanup, Qt.ConnectionType.SingleShotConnection)
    else:
        _orphan_ops.add(op)

        def _cleanup():
            _orphan_ops.discard(op)
        sig.done.connect(_cleanup, Qt.ConnectionType.SingleShotConnection)
    QThreadPool.globalInstance().start(op)
