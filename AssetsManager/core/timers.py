"""Cancellable one-shot timer handles for desktop UI scheduling.

D3: instead of anonymous ``QTimer.singleShot`` callbacks that can fire after
their owner is gone, owners hold :class:`TimerHandle` instances parented to a
QObject.  ``cancel()`` is idempotent and each owner can cancel every pending
handle in one pass before shutdown / library switch.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QTimer


class TimerHandle:
    """Owned one-shot timer wrapping QTimer.

    The callback is cleared after firing so a fired handle never keeps a
    bound owner alive; ``cancel`` prevents a queued timeout from delivering.
    """

    def __init__(self, parent: QObject | None, interval_ms: int, callback: Callable[[], None]):
        self._timer = QTimer(parent)
        self._timer.setSingleShot(True)
        self._timer.setInterval(max(0, int(interval_ms)))
        self._callback = callback
        self._fired = False
        self._timer.timeout.connect(self._on_timeout)

    @classmethod
    def schedule(
        cls, parent: QObject | None, interval_ms: int, callback: Callable[[], None]
    ) -> "TimerHandle":
        handle = cls(parent, interval_ms, callback)
        handle._timer.start()
        return handle

    def _on_timeout(self) -> None:
        self._fired = True
        callback, self._callback = self._callback, None
        if callback is not None:
            callback()

    def cancel(self) -> None:
        self._callback = None
        if self._timer.isActive():
            self._timer.stop()

    def is_active(self) -> bool:
        return self._timer.isActive()

    @property
    def fired(self) -> bool:
        return self._fired
