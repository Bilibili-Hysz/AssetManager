"""Temporary, passive Qt observer used only by the exit-repair harness.

Full-history copy retained as the baseline before sparse event observation.
"""

from __future__ import annotations

import functools
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
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
        record = {"pid": os.getpid(), "time": time.time(), "record_type": record_type, **fields}
        try:
            with self._lock, self._path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:
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
    window_handle = getattr(obj, "windowHandle", None)
    if callable(window_handle):
        try:
            handle = window_handle()
            if handle is not None:
                summary["hwnd"] = int(handle.winId())
        except Exception:
            pass
    return summary


def _enum_value(value: Any) -> int:
    return int(getattr(value, "value", value))


class _ApplicationObserver(QObject):
    def __init__(self, app: QApplication, log: _JsonlLog) -> None:
        super().__init__(app)
        self._app, self._log, self._ticks = app, log, 0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._heartbeat)
        self._timer.start()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        try:
            event_type = event.type()
            event_name = _EVENT_NAMES.get(event_type)
            if event_name is None:
                return False
            fields: dict[str, Any] = {"event": event_name, "target": _object_summary(watched)}
            if event_type in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                key, modifiers = _enum_value(event.key()), _enum_value(event.modifiers())  # type: ignore[attr-defined]
                if key != _enum_value(Qt.Key.Key_Q) and key != _enum_value(Qt.Key.Key_Control) and not (modifiers & _enum_value(Qt.KeyboardModifier.ControlModifier)):
                    return False
                fields.update(key=key, modifiers=modifiers)
            elif event_type == QEvent.Type.Shortcut:
                fields.update(key=str(event.key().toString()), modifiers=None, is_ambiguous=bool(event.isAmbiguous()))  # type: ignore[attr-defined]
            self._log.emit("event", **fields)
        except Exception as exc:
            self._log.emit("observer_error", phase="event_filter", error=repr(exc))
        return False

    def _heartbeat(self) -> None:
        self._ticks += 1
        try:
            top_levels = list(self._app.topLevelWidgets())
            self._log.emit("heartbeat", tick=self._ticks, active_window=_object_summary(self._app.activeWindow()), focus_widget=_object_summary(self._app.focusWidget()), top_level_count=len(top_levels), top_levels=[_object_summary(widget) for widget in top_levels[:16]])
        except Exception as exc:
            self._log.emit("observer_error", phase="heartbeat", error=repr(exc))
        if self._ticks >= 120:
            self._timer.stop()


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
            log.emit("call", phase="error", method=f"{cls.__name__}.{method_name}", target=target, error_type=type(exc).__name__, error=str(exc))
            raise
        log.emit("call", phase="return", method=f"{cls.__name__}.{method_name}", target=target)
        return result
    setattr(observed, "_exit_diagnostic_wrapped", True)
    setattr(cls, method_name, observed)


_observer: _ApplicationObserver | None = None


def register(_host: object) -> None:
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
    global _observer
    if _observer is None:
        return
    _observer._timer.stop()
    _observer._app.removeEventFilter(_observer)
    _observer = None
