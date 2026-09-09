"""Passive Qt exit diagnostic using code-local ``sys.monitoring`` callbacks."""
from __future__ import annotations

import builtins, ctypes, json, os, sys, threading, time
from pathlib import Path
from typing import Any, Callable
from PySide6.QtCore import QAbstractNativeEventFilter, QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication

_EVENTS = {QEvent.Type.ShortcutOverride: "ShortcutOverride", QEvent.Type.KeyPress: "KeyPress", QEvent.Type.KeyRelease: "KeyRelease", QEvent.Type.Shortcut: "Shortcut", QEvent.Type.WindowActivate: "WindowActivate", QEvent.Type.WindowDeactivate: "WindowDeactivate", QEvent.Type.WindowStateChange: "WindowStateChange", QEvent.Type.FocusIn: "FocusIn", QEvent.Type.FocusOut: "FocusOut"}

class _Log:
    def __init__(self, path: str) -> None: self.path, self.lock = Path(path), threading.Lock()
    def emit(self, kind: str, **fields: Any) -> None:
        try:
            with self.lock, self.path.open("a", encoding="utf-8") as file:
                file.write(json.dumps({"pid": os.getpid(), "time": time.time(), "record_type": kind, **fields}, ensure_ascii=False, default=str) + "\n")
        except Exception: pass

def _summary(obj: object | None) -> dict[str, Any] | None:
    if obj is None: return None
    result: dict[str, Any] = {"class": type(obj).__name__}
    for name in ("windowTitle", "isVisible", "isActiveWindow", "isMaximized", "isMinimized"):
        value = getattr(obj, name, None)
        if callable(value):
            try: result["title" if name == "windowTitle" else name] = str(value()) if name == "windowTitle" else bool(value())
            except Exception: pass
    if type(obj).__name__ == "MainWindow":
        try: result["force_quit"] = bool(getattr(obj, "_force_quit"))
        except Exception: pass
    return result

def _enum(value: Any) -> int: return int(getattr(value, "value", value))

class _Filter(QObject):
    def __init__(self, app: QApplication, log: _Log) -> None: super().__init__(app); self.app, self.log = app, log
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        try:
            event_type, label = event.type(), _EVENTS.get(event.type())
            if label is None: return False
            if event_type in (QEvent.Type.WindowActivate, QEvent.Type.WindowDeactivate, QEvent.Type.WindowStateChange, QEvent.Type.FocusIn, QEvent.Type.FocusOut) and type(watched).__name__ not in ("MainWindow", "QWindow"): return False
            fields: dict[str, Any] = {"event": label, "target": _summary(watched), "app_focus_widget": _summary(self.app.focusWidget()), "app_focus_window": _summary(self.app.focusWindow()), "app_active_window": _summary(self.app.activeWindow())}
            if event_type in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                key, modifiers = _enum(event.key()), _enum(event.modifiers())  # type: ignore[attr-defined]
                native_virtual_key = int(event.nativeVirtualKey())  # type: ignore[attr-defined]
                native_scan_code = int(event.nativeScanCode())  # type: ignore[attr-defined]
                is_native_q_or_ctrl = native_virtual_key in (0x51, 0x11, 0xA2, 0xA3)
                if key != _enum(Qt.Key.Key_Q) and key != _enum(Qt.Key.Key_Control) and not (modifiers & _enum(Qt.KeyboardModifier.ControlModifier)) and not is_native_q_or_ctrl: return False
                fields.update(key=key, modifiers=modifiers, native_virtual_key=native_virtual_key, native_scan_code=native_scan_code)
            elif event_type == QEvent.Type.Shortcut: fields.update(key=str(event.key().toString()), is_ambiguous=bool(event.isAmbiguous()))  # type: ignore[attr-defined]
            if event_type == QEvent.Type.WindowStateChange:
                old_state = getattr(event, "oldState", None)
                current_state = getattr(watched, "windowState", None)
                fields.update(old_window_state=_enum(old_state()) if callable(old_state) else None, new_window_state=_enum(current_state()) if callable(current_state) else None, minimized=bool(watched.isMinimized()) if hasattr(watched, "isMinimized") else None, visible=bool(watched.isVisible()) if hasattr(watched, "isVisible") else None)
            self.log.emit("event", **fields)
        except Exception as exc: self.log.emit("observer_error", phase="filter", error=repr(exc))
        return False

_filter: _Filter | None = None
_native_filter: QAbstractNativeEventFilter | None = None
_original_import: Callable[..., Any] | None = None
_log: _Log | None = None
_tool: int | None = None
_codes: dict[object, str] = {}

_WM_KEYDOWN, _WM_KEYUP, _WM_SYSKEYDOWN, _WM_SYSKEYUP = 0x0100, 0x0101, 0x0104, 0x0105
_NATIVE_KEY_MESSAGES = {_WM_KEYDOWN: "WM_KEYDOWN", _WM_KEYUP: "WM_KEYUP", _WM_SYSKEYDOWN: "WM_SYSKEYDOWN", _WM_SYSKEYUP: "WM_SYSKEYUP"}

class _MSG(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint), ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t), ("time", ctypes.c_uint), ("pt_x", ctypes.c_long), ("pt_y", ctypes.c_long), ("lPrivate", ctypes.c_uint)]

class _NativeFilter(QAbstractNativeEventFilter):
    def __init__(self, log: _Log) -> None: super().__init__(); self.log = log
    def nativeEventFilter(self, event_type: bytes, message: object) -> tuple[bool, int]:  # noqa: N802
        try:
            pointer = int(message)
            native = ctypes.cast(pointer, ctypes.POINTER(_MSG)).contents
            label = _NATIVE_KEY_MESSAGES.get(native.message)
            if label and int(native.wParam) in (0x51, 0x11, 0xA2, 0xA3):
                self.log.emit("native_event", event_type=bytes(event_type).decode("ascii", "replace"), event=label, hwnd=int(native.hwnd or 0), virtual_key=int(native.wParam), lparam=int(native.lParam))
        except Exception as exc:
            self.log.emit("observer_error", phase="native_filter", error=repr(exc))
        return False, 0

def _emit_call(phase: str, code: object) -> None:
    if _log is None: return
    try:
        # The monitoring callback calls this helper, so the instrumented method
        # is two frames above this helper on CPython 3.14.
        frame = sys._getframe(2); method = _codes.get(code, getattr(code, "co_qualname", "unknown")); target = _summary(frame.f_locals.get("self"))
        event = frame.f_locals.get("event"); accepted = getattr(event, "isAccepted", None)
        _log.emit("call", phase=phase, method=method, target=target, event_accepted=bool(accepted()) if str(method).endswith(".closeEvent") and callable(accepted) else None)
    except Exception as exc: _log.emit("observer_error", phase="monitor", error=repr(exc))
def _start(code: object, _offset: int) -> None: _emit_call("enter", code)
def _return(code: object, _offset: int, _value: object) -> None: _emit_call("return", code)
def _unwind(code: object, _offset: int, _exception: object) -> None: _emit_call("unwind", code)

def _install_monitor(window_module: object) -> None:
    global _tool, _codes
    if _tool is not None or _log is None: return
    cls = getattr(window_module, "MainWindow")
    originals = {name: getattr(cls, name) for name in ("request_exit", "closeEvent", "_shutdown_resources")}
    mon = sys.monitoring; tool = next((i for i in range(3, 6) if mon.get_tool(i) is None), None)
    if tool is None: raise RuntimeError("no free sys.monitoring tool id")
    mon.use_tool_id(tool, "exit-diagnostic-observer")
    events = mon.events.PY_START | mon.events.PY_RETURN
    try:
        mon.register_callback(tool, mon.events.PY_START, _start); mon.register_callback(tool, mon.events.PY_RETURN, _return)
        unwind_enabled = False
        try: mon.register_callback(tool, mon.events.PY_UNWIND, _unwind); unwind_enabled = True
        except Exception: pass
        _codes = {method.__code__: f"MainWindow.{name}" for name, method in originals.items()}
        for code in _codes: mon.set_local_events(tool, code, events)
        if unwind_enabled:
            try:
                for code in _codes: mon.set_local_events(tool, code, events | mon.events.PY_UNWIND)
                events |= mon.events.PY_UNWIND
            except Exception:
                for code in _codes: mon.set_local_events(tool, code, events)
        if any(getattr(cls, name) is not method for name, method in originals.items()): raise RuntimeError("method identity changed")
    except Exception:
        for code in _codes: mon.set_local_events(tool, code, 0)
        for event in (mon.events.PY_START, mon.events.PY_RETURN, mon.events.PY_UNWIND): mon.register_callback(tool, event, None)
        mon.free_tool_id(tool); _codes = {}; raise
    _tool = tool; _log.emit("plugin", phase="lazy_monitoring_installed", tool_id=tool, global_events=mon.get_events(tool))

def _import(name: str, globals: dict[str, Any] | None = None, locals: dict[str, Any] | None = None, fromlist: object = (), level: int = 0) -> Any:
    original = _original_import
    if original is None: return builtins.__import__(name, globals, locals, fromlist, level)
    result = original(name, globals, locals, fromlist, level)
    if name == "AssetsManager.window" and "MainWindow" in (fromlist or ()):
        try: _install_monitor(result)
        except Exception as exc:
            if _log is not None: _log.emit("observer_error", phase="lazy_monitor_install", error=repr(exc))
        finally:
            if builtins.__import__ is _import: builtins.__import__ = original
    return result

def register(_host: object) -> None:
    global _filter, _native_filter, _original_import, _log
    path = os.environ.get("AM_EXIT_DIAGNOSTIC_LOG", "").strip()
    if not path or _filter is not None: return
    app = QApplication.instance()
    if app is None: return
    _log = _Log(path); _filter = _Filter(app, _log); _native_filter = _NativeFilter(_log)
    app.installEventFilter(_filter); app.installNativeEventFilter(_native_filter)
    app.aboutToQuit.connect(lambda: _log.emit("application", signal="aboutToQuit")); app.lastWindowClosed.connect(lambda: _log.emit("application", signal="lastWindowClosed"))
    _original_import = builtins.__import__; builtins.__import__ = _import; _log.emit("plugin", phase="registered")

def unregister(_host: object) -> None:
    global _filter, _native_filter, _original_import, _log, _tool, _codes
    if _original_import is not None and builtins.__import__ is _import: builtins.__import__ = _original_import
    if _tool is not None:
        mon = sys.monitoring
        for code in _codes: mon.set_local_events(_tool, code, 0)
        for event in (mon.events.PY_START, mon.events.PY_RETURN, mon.events.PY_UNWIND): mon.register_callback(_tool, event, None)
        mon.free_tool_id(_tool)
    if _filter is not None: _filter.app.removeEventFilter(_filter)
    if _native_filter is not None: QApplication.instance().removeNativeEventFilter(_native_filter)
    _filter, _native_filter, _original_import, _log, _tool, _codes = None, None, None, None, None, {}
