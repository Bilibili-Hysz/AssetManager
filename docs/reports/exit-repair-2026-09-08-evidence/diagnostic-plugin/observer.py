"""Temporary, passive Qt observer used only by the exit-repair harness.

The module is deliberately self-contained so copying this directory below a
synthetic runtime's ``Shared/plugins`` directory cannot change product code.
It only appends JSON lines to the explicitly supplied diagnostic path.
"""

from __future__ import annotations

import functools
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication


_EVENT_NAMES = {
    QEvent.Type.ShortcutOverride: "ShortcutOverride",
    QEvent.Type.KeyPress: "KeyPress",
    QEvent.Type.KeyRelease: "KeyRelease",
    QEvent.Type.Shortcut: "Shortcut",
    QEvent.Type.WindowActivate: "WindowActivate",
    QEvent.Type.WindowDeactivate: "WindowDeactivate",
    QEvent.Type.WindowStateChange: "WindowStateChange",
    QEvent.Type.FocusIn: "FocusIn",
    QEvent.Type.FocusOut: "FocusOut",
}


class _JsonlLog:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def emit(self, record_type: str, **fields: Any) -> None:
        record = {
            "pid": os.getpid(),
            "time": time.time(),
            "record_type": record_type,
            **fields,
        }
        try:
            payload = json.dumps(record, ensure_ascii=False, default=str)
            with self._lock, self._path.open("a", encoding="utf-8") as stream:
                stream.write(payload + "\n")
        except Exception:
            # Instrumentation must never alter application control flow.
            pass


def _object_summary(obj: object | None) -> dict[str, Any] | None:
    if obj is None:
        return None
    summary: dict[str, Any] = {"class": type(obj).__name__}
    title = getattr(obj, "windowTitle", None)
    if callable(title):
        try:
            summary["title"] = str(title())
        except Exception:
            pass
    for name in ("isVisible", "isActiveWindow", "isMaximized"):
        predicate = getattr(obj, name, None)
        if callable(predicate):
            try:
                summary[name] = bool(predicate())
            except Exception:
                pass
    return summary


def _enum_value(value: Any) -> int:
    """Read PySide enum/flag values without relying on ``int(Flag)`` support."""
    raw_value = getattr(value, "value", value)
    return int(raw_value)


class _ApplicationObserver(QObject):
    def __init__(self, app: QApplication, log: _JsonlLog) -> None:
        super().__init__(app)
        self._app = app
        self._log = log

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        try:
            event_type = event.type()
            event_name = _EVENT_NAMES.get(event_type)
            if event_name is None:
                return False
            if event_type in (
                QEvent.Type.WindowActivate,
                QEvent.Type.WindowDeactivate,
                QEvent.Type.WindowStateChange,
                QEvent.Type.FocusIn,
                QEvent.Type.FocusOut,
            ) and type(watched).__name__ not in ("MainWindow", "QWindow"):
                return False
            fields: dict[str, Any] = {
                "event": event_name,
                "target": _object_summary(watched),
            }
            if event_type in (
                QEvent.Type.ShortcutOverride,
                QEvent.Type.KeyPress,
                QEvent.Type.KeyRelease,
            ):
                key = _enum_value(event.key())  # type: ignore[attr-defined]
                modifiers = _enum_value(event.modifiers())  # type: ignore[attr-defined]
                if (
                    key != _enum_value(Qt.Key.Key_Q)
                    and key != _enum_value(Qt.Key.Key_Control)
                    and not (modifiers & _enum_value(Qt.KeyboardModifier.ControlModifier))
                ):
                    return False
                fields.update(key=key, modifiers=modifiers)
            elif event_type == QEvent.Type.Shortcut:
                key_sequence = event.key()  # type: ignore[attr-defined]
                fields.update(
                    key=str(key_sequence.toString()),
                    modifiers=None,
                    is_ambiguous=bool(event.isAmbiguous()),  # type: ignore[attr-defined]
                )
            self._log.emit("event", **fields)
        except Exception as exc:
            self._log.emit("observer_error", phase="event_filter", error=repr(exc))
        return False

def _wrap_method(log: _JsonlLog, cls: type, method_name: str) -> None:
    original = getattr(cls, method_name)
    if getattr(original, "_exit_diagnostic_wrapped", False):
        return

    @functools.wraps(original)
    def observed(self: object, *args: Any, **kwargs: Any) -> Any:
        target = _object_summary(self)
        log.emit("call", phase="enter", method=f"{cls.__name__}.{method_name}", target=target)
        try:
            result = original(self, *args, **kwargs)
        except BaseException as exc:
            log.emit(
                "call",
                phase="error",
                method=f"{cls.__name__}.{method_name}",
                target=target,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise
        log.emit("call", phase="return", method=f"{cls.__name__}.{method_name}", target=target)
        return result

    setattr(observed, "_exit_diagnostic_wrapped", True)
    setattr(cls, method_name, observed)


_observer: _ApplicationObserver | None = None


def register(_host: object) -> None:
    """Install process-local observation before the first MainWindow is made."""
    global _observer
    log_path = os.environ.get("AM_EXIT_DIAGNOSTIC_LOG", "").strip()
    if not log_path or _observer is not None:
        return

    app = QApplication.instance()
    if app is None:
        return
    log = _JsonlLog(log_path)
    from AssetsManager.window import MainWindow
    from AssetsManager.window_lifecycle_coordinator import WindowLifecycleCoordinator

    _wrap_method(log, MainWindow, "request_exit")
    _wrap_method(log, MainWindow, "closeEvent")
    _wrap_method(log, MainWindow, "_shutdown_resources")
    _wrap_method(log, WindowLifecycleCoordinator, "shutdown_resources")

    _observer = _ApplicationObserver(app, log)
    app.installEventFilter(_observer)
    app.aboutToQuit.connect(lambda: log.emit("application", signal="aboutToQuit"))
    app.lastWindowClosed.connect(lambda: log.emit("application", signal="lastWindowClosed"))
    log.emit("plugin", phase="registered", application=_object_summary(app))


def unregister(_host: object) -> None:
    """Remove only the passive event filter."""
    global _observer
    if _observer is None:
        return
    _observer._app.removeEventFilter(_observer)
    _observer = None
