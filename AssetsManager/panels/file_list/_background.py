"""Background task runner for file-list operations."""
from __future__ import annotations

import logging
from typing import Any, Callable

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


def run_task(
    func: Callable[[], Any],
    *,
    on_done: Callable[[Any, BaseException | None], None] | None = None,
    background_ops: list[QRunnable] | None = None,
) -> None:
    """Run ``func()`` on a worker thread and deliver its outcome to the GUI thread.

    Unlike :func:`run_in_background` (fire-and-forget with no result), this
    variant captures the callable's return value (or the raised exception)
    and, when *on_done* is provided, invokes ``on_done(result, exc)`` on the
    main thread via a queued signal.  Exactly one of *result*/*exc* is
    ``None``.  *background_ops* has the same ownership semantics as in
    :func:`run_in_background`.
    """

    class _ResultSig(QObject):
        finished = Signal(object, object)

    class _ResultOp(QRunnable):
        def __init__(self, fn, sig):
            super().__init__()
            self._fn = fn
            self._sig = sig

        def run(self):
            result: Any = None
            exc: BaseException | None = None
            try:
                result = self._fn()
            except Exception as error:  # noqa: BLE001 — delivered to the caller
                _log.exception("Background task failed")
                result = None
                exc = error
            sig = self._sig
            sig.finished.emit(result, exc)

    sig = _ResultSig()
    op = _ResultOp(func, sig)
    if on_done is not None:
        sig.finished.connect(on_done)
    if background_ops is not None:
        background_ops.append(op)

        def _cleanup():
            background_ops.remove(op)
        sig.finished.connect(_cleanup, Qt.ConnectionType.SingleShotConnection)
    else:
        _orphan_ops.add(op)

        def _cleanup():
            _orphan_ops.discard(op)
        sig.finished.connect(_cleanup, Qt.ConnectionType.SingleShotConnection)
    QThreadPool.globalInstance().start(op)
