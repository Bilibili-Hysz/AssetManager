"""Background task runner for file-list operations."""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Qt

_log = logging.getLogger(__name__)


def run_in_background(
    func: Callable,
    *args,
    on_done: Callable[[], None] | None = None,
    background_ops: list[QObject] | None = None,
) -> None:
    """Run ``func(*args)`` on a worker thread.

    If *on_done* is provided, it is called on the main thread after
    completion.  If *background_ops* is provided (a list owned by the
    calling panel), the signal is added to it so the panel can track
    in-flight operations.
    """
    class _Sig(QObject):
        done = Signal()

    class _Op(QRunnable):
        def __init__(s, fn, args, sig):
            super().__init__()
            s.setAutoDelete(False)
            s._fn = fn
            s._a = args
            s._sig = sig

        def run(s):
            try:
                s._fn(*s._a)
            except Exception:
                _log.exception("Background task failed")
            if s._sig is not None:
                s._sig.done.emit()

    sig = _Sig() if on_done is not None else None
    if on_done is not None and background_ops is not None:
        sig.done.connect(on_done)
        background_ops.append(sig)

        def _cleanup():
            background_ops.remove(sig)
        sig.done.connect(_cleanup, Qt.ConnectionType.SingleShotConnection)
    QThreadPool.globalInstance().start(_Op(func, args, sig))
