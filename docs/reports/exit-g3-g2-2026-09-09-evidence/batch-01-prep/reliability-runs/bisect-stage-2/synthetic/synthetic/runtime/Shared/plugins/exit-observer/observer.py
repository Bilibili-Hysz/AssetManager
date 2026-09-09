"""G3/G2 观察器 bisect 变体（仅诊断挂死点用，非 O1/O2 正式实现）。

背景：可靠性验证 attempt-4/5/6 中，观察器在 exe 内 register() 后 GUI
事件循环停摆（窗口无响应、LAN 不启动、export-ack 永不出现 → 挂死点在
_ExportWatcher.start() 之前的 register 路径上）。本变体按阶段开启观察
器部件并在状态文件留下 stage 标记，用于定位挂死发生在哪一步。

环境变量：
  AM_G3_BISECT_STAGE   1..5（每级包含更低级的全部部件）
    1 = 仅 _Recorder + recorder_startup emit
    2 = + _Filter (Qt eventFilter)
    3 = + _NativeFilter (native event filter)
    4 = + builtins.__import__ 钩子
    5 = + _ExportWatcher 线程 / atexit
  AM_G3_BISECT_STATUS  状态文件路径（每阶段一条 + 心跳）

除分段外与正式 observer.py 的 register() 逻辑一致；本文件只用于定位，
不用于对照矩阵。
"""
from __future__ import annotations

import builtins
import ctypes
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication

_STAGE = max(1, min(5, int(os.environ.get("AM_G3_BISECT_STAGE", "1"))))
_STATUS = os.environ.get("AM_G3_BISECT_STATUS", "").strip()
_LOG_PATH = os.environ.get("AM_EXIT_DIAGNOSTIC_LOG", "").strip()
_RUN_ID = os.environ.get("AM_G3_RUN_ID", "bisect")
_PHASE = os.environ.get("AM_G3_PHASE", "first-exit")

_EVENTS = {
    QEvent.Type.ShortcutOverride: "ShortcutOverride",
    QEvent.Type.KeyPress: "KeyPress",
    QEvent.Type.KeyRelease: "KeyRelease",
    QEvent.Type.Shortcut: "Shortcut",
    QEvent.Type.WindowActivate: "WindowActivate",
    QEvent.Type.WindowDeactivate: "WindowDeactivate",
    QEvent.Type.WindowStateChange: "WindowStateChange",
    QEvent.Type.FocusIn: "FocusIn",
    QEvent.Type.FocusOut: "FocusOut",
    QEvent.Type.Show: "Show",
    QEvent.Type.Hide: "Hide",
    QEvent.Type.Close: "Close",
    QEvent.Type.Destroy: "Destroy",
    QEvent.Type.HideToParent: "HideToParent",
}
_NATIVE_MESSAGES = {
    0x0001: "WM_CREATE", 0x0002: "WM_DESTROY", 0x0006: "WM_ACTIVATE",
    0x0008: "WM_KILLFOCUS", 0x0016: "WM_ACTIVATEAPP", 0x0018: "WM_SHOWWINDOW",
    0x0010: "WM_CLOSE", 0x0112: "WM_SYSCOMMAND",
    0x0100: "WM_KEYDOWN", 0x0101: "WM_KEYUP",
    0x0104: "WM_SYSKEYDOWN", 0x0105: "WM_SYSKEYUP",
}
_seq = 0
_lock = threading.Lock()
_error_count = 0


def _note(kind: str, **fields: Any) -> None:
    global _seq, _error_count
    try:
        with _lock:
            _seq += 1
            record = {"seq": _seq, "time": time.time(), "kind": kind,
                      "run_id": _RUN_ID, "phase": _PHASE, **fields}
            line = json.dumps(record, ensure_ascii=False, default=str)
            if _LOG_PATH:
                with open(_LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            if _STATUS:
                Path(_STATUS).write_text(
                    json.dumps({"stage": _STAGE, "kind": kind,
                                "seq": _seq, "time": record["time"],
                                "error_count": _error_count},
                               ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        _error_count += 1
        try:
            Path(_STATUS).write_text(
                json.dumps({"stage": _STAGE, "note_error": repr(exc)[:200],
                            "seq": _seq, "time": time.time()}),
                encoding="utf-8")
        except Exception:
            pass


class _Filter(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self.app = app

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        try:
            label = _EVENTS.get(event.type())
            if label is None:
                return False
            if event.type() in (QEvent.Type.Show, QEvent.Type.Hide,
                                QEvent.Type.Close, QEvent.Type.Destroy,
                                QEvent.Type.HideToParent,
                                QEvent.Type.WindowActivate,
                                QEvent.Type.WindowDeactivate,
                                QEvent.Type.WindowStateChange,
                                QEvent.Type.FocusIn, QEvent.Type.FocusOut) \
                    and type(watched).__name__ not in (
                        "MainWindow", "QWindow", "StartupWindow"):
                return False
            _note("event", event=label, target=type(watched).__name__)
        except Exception as exc:
            _note("observer_error", phase="filter", error=repr(exc))
        return False


class _MSG(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                ("time", ctypes.c_uint), ("pt_x", ctypes.c_long),
                ("pt_y", ctypes.c_long), ("lPrivate", ctypes.c_uint)]


class _NativeFilter(QAbstractNativeEventFilter):
    def __init__(self) -> None:
        super().__init__()

    def nativeEventFilter(self, event_type: bytes, message: object) -> tuple[bool, int]:  # noqa: N802
        try:
            pointer = int(message)
            native = ctypes.cast(pointer, ctypes.POINTER(_MSG)).contents
            label = _NATIVE_MESSAGES.get(int(native.message))
            if label is None:
                return False, 0
            if label.startswith("WM_KEY") and int(native.wParam) not in (
                    0x51, 0x11, 0xA2, 0xA3):
                return False, 0
            _note("native_event", event=label, hwnd=int(native.hwnd or 0))
        except Exception as exc:
            _note("observer_error", phase="native", error=repr(exc))
        return False, 0


_filter: _Filter | None = None
_native_filter: QAbstractNativeEventFilter | None = None
_original_import: Callable[..., Any] | None = None
_tool: int | None = None
_codes: dict[object, str] = {}
_watch_stop = threading.Event()


def _heartbeat_thread() -> None:
    while not _watch_stop.wait(2.0):
        _note("heartbeat", stage=_STAGE)


def _import(name: str, globals: dict[str, Any] | None = None,
            locals: dict[str, Any] | None = None, fromlist: object = (),
            level: int = 0) -> Any:
    original = _original_import
    result = original(name, globals, locals, fromlist, level)
    if name == "AssetsManager.window" and "MainWindow" in (fromlist or ()):
        try:
            from AssetsManager.window import MainWindow as _cls
            originals = {n: getattr(_cls, n) for n in
                         ("request_exit", "closeEvent", "_shutdown_resources")}
            mon = sys.monitoring
            tool = next((i for i in range(3, 6) if mon.get_tool(i) is None), None)
            if tool is not None:
                mon.use_tool_id(tool, "g3-bisect")
                events = mon.events.PY_START | mon.events.PY_RETURN
                mon.register_callback(tool, mon.events.PY_START,
                                      lambda code, offset: _note(
                                          "monitor_start",
                                          method=_codes.get(code, "?")))
                mon.register_callback(tool, mon.events.PY_RETURN,
                                      lambda code, offset, value: _note(
                                          "monitor_return",
                                          method=_codes.get(code, "?")))
                _codes = {m.__code__: f"MainWindow.{n}"
                          for n, m in originals.items()}
                for code in _codes:
                    mon.set_local_events(tool, code, events)
                _tool = tool
        except Exception as exc:
            _note("observer_error", phase="install_monitor", error=repr(exc))
        finally:
            if builtins.__import__ is _import:
                builtins.__import__ = original
    return result


def register(_host: object) -> None:
    global _filter, _native_filter, _original_import
    if not _LOG_PATH and not _STATUS:
        return
    if QApplication.instance() is None:
        return
    app = QApplication.instance()
    _note("bisect_register_enter", stage=_STAGE)

    # stage 1: recorder only（emit startup 头）
    _note("recorder_startup", stage=_STAGE, log=_LOG_PATH or None)

    # stage 2: Qt event filter
    if _STAGE >= 2:
        _filter = _Filter(app)
        app.installEventFilter(_filter)
        _note("stage2_qt_filter_installed", stage=_STAGE)

    # stage 3: native event filter
    if _STAGE >= 3:
        _native_filter = _NativeFilter()
        app.installNativeEventFilter(_native_filter)
        _note("stage3_native_filter_installed", stage=_STAGE)

    # stage 4: import 钩子（延迟 sys.monitoring）
    if _STAGE >= 4:
        _original_import = builtins.__import__
        builtins.__import__ = _import
        _note("stage4_import_hook_installed", stage=_STAGE)

    # stage 5: watcher 线程
    if _STAGE >= 5:
        threading.Thread(target=_heartbeat_thread, daemon=True).start()
        _note("stage5_watcher_started", stage=_STAGE)

    _note("bisect_register_done", stage=_STAGE)


def unregister(_host: object) -> None:
    global _filter, _native_filter, _original_import, _tool, _codes
    _watch_stop.set()
    if _original_import is not None and builtins.__import__ is _import:
        builtins.__import__ = _original_import
    if _tool is not None:
        mon = sys.monitoring
        for code in _codes:
            mon.set_local_events(_tool, code, 0)
        for event in (mon.events.PY_START, mon.events.PY_RETURN,
                      mon.events.PY_UNWIND):
            mon.register_callback(_tool, event, None)
        mon.free_tool_id(_tool)
    if _filter is not None:
        _filter.app.removeEventFilter(_filter)
    if _native_filter is not None:
        instance = QApplication.instance()
        if instance is not None:
            instance.removeNativeEventFilter(_native_filter)
    _note("bisect_unregister_done", stage=_STAGE)
    _filter, _native_filter, _original_import, _tool, _codes = \
        None, None, None, None, {}
