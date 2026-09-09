"""G3/G2 联合定位观察器（O1=有界内存缓冲 / O2=同步写盘）。

单一实现派生：O1/O2 共享全部观察点、字段、过滤与导入时机；模式选择只改
记录出口（``AM_G3_OBSERVE_MODE``=buffered|synced）。相对参照 observed-14
``observer.py``（SHA-256 faf0acc9…）的改动见 source-diff.patch。

纪律（方案 §5）：
- 不提前导入 MainWindow；不替换生产方法对象；不改信号连接（观察信号
  aboutToQuit / lastWindowClosed 只是新增连接，不触碰既有连接）。
- sys.monitoring 只启用目标 code 的本地事件（request_exit / closeEvent /
  _shutdown_resources），不启用全局追踪。
- 每条事件含 run_id、相位（first-exit/restart-exit）、PID/TID、窗口标识、
  事件类型、序号、单调时间、丢弃计数。
- O1 缓冲容量上限显式定义（``AM_G3_BUFFER_LIMIT``，默认 20000 条）：溢出
  保最新、弃最旧、精确计数，且每条记录带 dropped_so_far。
- 失败/超时导出不依赖 Qt 主线程：后台守护线程轮询 ``AM_G3_EXPORT_REQUEST``
  请求文件，从内存缓冲导出 JSONL 并以 ``AM_G3_EXPORT_ACK`` 回执；此外
  atexit 后备导出保证"控制器从不发请求、进程正常退出"时事件仍落盘
  （``AM_G3_FINAL_FLUSH``）。正常路径的导出同样优先由守护线程完成；
  atexit 只处理"请求从未出现"的最后保全。
- 状态文件（``AM_G3_STATUS_FILE``）每条事件后小成本更新，控制器可无侵入
  读到序号/丢弃/错误数，用于区分"记录器活着"与"零事件"。
- 记录器自身异常显式记录（recorder_error，partial 标志）+ 状态文件
  error_count，与"零事件"明确区分；无法导出时由控制器标注"日志不完整"。
"""
from __future__ import annotations

import atexit
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

# ── 模式与缓冲参数（显式定义）────────────────────────────────────────
_DEFAULT_BUFFER_LIMIT = 20000          # O1 内存缓冲容量上限（条）
_EXPORT_POLL_INTERVAL_S = 0.20          # 守护线程轮询控制器导出请求的间隔
_MAX_RECORD_BYTES = 16384               # 单条记录序列化上限（防异常巨对象）
_STATE_WRITE_INTERVAL_S = 1.0          # 状态文件最小更新间隔（降 IO 成本）

_PHASE = os.environ.get("AM_G3_PHASE", "first-exit")   # first-exit | restart-exit
_RUN_ID = os.environ.get("AM_G3_RUN_ID", "unknown-run")
_MODE = os.environ.get("AM_G3_OBSERVE_MODE", "buffered")  # buffered | synced
_BUFFER_LIMIT = max(1, int(os.environ.get("AM_G3_BUFFER_LIMIT",
                                          str(_DEFAULT_BUFFER_LIMIT))))
_LOG_PATH = os.environ.get("AM_EXIT_DIAGNOSTIC_LOG", "").strip()
_EXPORT_REQUEST = os.environ.get("AM_G3_EXPORT_REQUEST", "").strip()
_EXPORT_ACK = os.environ.get("AM_G3_EXPORT_ACK", "").strip()
_FINAL_FLUSH = os.environ.get("AM_G3_FINAL_FLUSH", "").strip()
_STATUS_FILE = os.environ.get("AM_G3_STATUS_FILE", "").strip()

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
_SC_MINIMIZE = 0xF020
_SC_RESTORE = 0xF120
_SC_MAXIMIZE = 0xF030

_user32 = None


def _user32_api():
    global _user32
    if _user32 is None:
        _user32 = ctypes.windll.user32
    return _user32


def _tid() -> int:
    return ctypes.windll.kernel32.GetCurrentThreadId()


def _win_state(hwnd: int) -> dict[str, Any]:
    """原生窗口状态采样（IsWindow/IsIconic/IsZoomed/可见性）。"""
    out: dict[str, Any] = {"is_window": None, "visible": None,
                           "minimized": None, "maximized": None}
    try:
        u = _user32_api()
        out.update({
            "is_window": bool(u.IsWindow(hwnd)),
            "visible": bool(u.IsWindowVisible(hwnd)),
            "minimized": bool(u.IsIconic(hwnd)),
            "maximized": bool(u.IsZoomed(hwnd)),
        })
    except Exception as exc:
        out["error"] = repr(exc)
    return out


class _Recorder:
    """有界内存缓冲 / 同步写盘 双出口记录器（模式只在此分流）。"""

    def __init__(self, path: str, mode: str) -> None:
        self.path = Path(path)
        self.mode = mode
        self.lock = threading.Lock()
        self.seq = 0
        self.dropped = 0            # 缓冲溢出丢弃数
        self.error_count = 0        # 记录器自身异常数
        self.buffer: list[dict[str, Any]] = []
        self.started_monotonic = time.monotonic()
        self._file = None            # synced 模式的追加句柄
        self._sync_failed = False
        self._status_written = 0.0
        self._closed = False
        self._exported = False       # 守护线程/atexit 是否已导出
        # 启动状态头（每流第一条；写到 fallback 出口即视为"日志不完整"起点）
        self._startup_emitted = False

    # ── 公共入口 ──────────────────────────────────────────────────
    def emit(self, record_type: str, **fields: Any) -> None:
        try:
            with self.lock:
                self.seq += 1
                record = {
                    "run_id": _RUN_ID,
                    "phase": _PHASE,
                    "pid": os.getpid(),
                    "tid": _tid(),
                    "seq": self.seq,
                    "monotonic_ms": round(time.monotonic() * 1000.0, 3),
                    "dropped_so_far": self.dropped,
                    "record_type": record_type,
                }
                record.update(fields)
                line = self._serialize(record)
                if line is not None:
                    if self.mode == "synced":
                        self._sync_write(line)
                    else:
                        self.buffer.append(record)
                        if len(self.buffer) > _BUFFER_LIMIT:
                            # 容量上限触发：保最新、弃最旧、精确计数。
                            self.buffer.pop(0)
                            self.dropped += 1
                self._maybe_status()
        except Exception as exc:
            self.error_count += 1
            self._fallback_line("recorder_error", repr(exc))

    def export(self, target: Path) -> dict[str, Any]:
        """把当前缓冲导出为 JSONL（O1 失败保全 / 正常收尾均走此路径）。"""
        with self.lock:
            snapshot = list(self.buffer)
            meta = {
                "ack": "ok", "mode": self.mode, "run_id": _RUN_ID,
                "phase": _PHASE, "exported_seq": self.seq,
                "exported_count": len(snapshot), "dropped": self.dropped,
                "error_count": self.error_count,
            }
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("w", encoding="utf-8") as stream:
                    for item in snapshot:
                        stream.write(json.dumps(item, ensure_ascii=False,
                                                default=str) + "\n")
                self._exported = True
            except Exception as exc:
                meta.update({"ack": "failed", "error": repr(exc)[:512],
                             "log_incomplete": True})
                self.error_count += 1
        return meta

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "run_id": _RUN_ID, "phase": _PHASE, "pid": os.getpid(),
                "mode": self.mode, "seq": self.seq,
                "buffered_count": len(self.buffer), "dropped": self.dropped,
                "error_count": self.error_count, "alive": True,
                "monotonic_ms": round(time.monotonic() * 1000.0, 3),
            }

    def final_flush(self) -> None:
        """atexit 后备：请求从未出现时的最后保全（含结束状态头）。"""
        try:
            if self._closed:
                return
            if self.mode == "buffered" and _FINAL_FLUSH and not self._exported:
                meta = self.export(Path(_FINAL_FLUSH))
                if meta.get("ack") != "ok":
                    self._fallback_line("recorder_error",
                                        "final flush export failed")
            if self.mode == "buffered" and not _FINAL_FLUSH:
                # 无后备路径可用时显式留下"日志不完整"标记
                self._fallback_line("recorder_error",
                                    "no final flush path configured; "
                                    "buffered events may be lost")
            self._closed = True
            if self._file is not None:
                try:
                    self._file.flush()
                    self._file.close()
                except Exception:
                    pass
                self._file = None
        except Exception as exc:
            self._fallback_line("recorder_error", f"final_flush: {exc!r}")

    # ── 内部 ──────────────────────────────────────────────────────
    def _serialize(self, record: dict[str, Any]) -> str | None:
        try:
            line = json.dumps(record, ensure_ascii=False, default=str)
            if len(line) > _MAX_RECORD_BYTES:
                record["payload_truncated"] = True
                line = json.dumps(record, ensure_ascii=False, default=str)
            return line
        except Exception as exc:
            self.error_count += 1
            self._fallback_line("recorder_error", repr(exc))
            return None

    def _sync_write(self, line: str) -> None:
        if self._sync_failed:
            return
        try:
            if self._file is None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._file = self.path.open("a", encoding="utf-8")
            self._file.write(line + "\n")
            self._file.flush()
        except Exception:
            self._sync_failed = True
            self.error_count += 1
            self._fallback_line("recorder_error", "sync write failed")

    def _maybe_status(self) -> None:
        if not _STATUS_FILE:
            return
        now = time.monotonic()
        if now - self._status_written < _STATE_WRITE_INTERVAL_S:
            return
        self._status_written = now
        try:
            Path(_STATUS_FILE).write_text(
                json.dumps(self.status(), ensure_ascii=False),
                encoding="utf-8")
        except Exception:
            # 状态文件失败不影响记录主路径
            pass

    def _fallback_line(self, record_type: str, error: str) -> None:
        """记录器自身异常的最小可靠出口（与正常流同文件，partial 标记）。"""
        try:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({
                    "run_id": _RUN_ID, "phase": _PHASE, "pid": os.getpid(),
                    "seq": -1, "record_type": record_type,
                    "error": error[:512],
                    "monotonic_ms": round(time.monotonic() * 1000.0, 3),
                    "partial": True, "log_incomplete": True,
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass


def _summary(obj: object | None) -> dict[str, Any] | None:
    if obj is None:
        return None
    result: dict[str, Any] = {"class": type(obj).__name__}
    for name in ("windowTitle", "isVisible", "isActiveWindow", "isMaximized",
                 "isMinimized"):
        value = getattr(obj, name, None)
        if callable(value):
            try:
                result["title" if name == "windowTitle" else name] = (
                    str(value()) if name == "windowTitle" else bool(value()))
            except Exception:
                pass
    if type(obj).__name__ == "MainWindow":
        try:
            result["force_quit"] = bool(getattr(obj, "_force_quit"))
        except Exception:
            pass
    return result


def _enum(value: Any) -> int:
    return int(getattr(value, "value", value))


def _win_id(obj: object) -> Any:
    """观察对象的窗口标识（原生 HWND；不可用时 None）。

    仅在 Qt 已经创建原生窗口的对象上调用 winId（不强制创建）。典型
    QWidget 会在首次显示后持有 HWND，此查询不会改变窗口状态。
    """
    try:
        wid = obj.winId()
    except Exception:
        return None
    try:
        return int(wid) if wid else None
    except Exception:
        return None


class _Filter(QObject):
    """Qt 事件观察点：输入/焦点/窗口状态/关闭/销毁。"""

    _WINDOWISH = (QEvent.Type.WindowActivate, QEvent.Type.WindowDeactivate,
                  QEvent.Type.WindowStateChange, QEvent.Type.FocusIn,
                  QEvent.Type.FocusOut, QEvent.Type.Show, QEvent.Type.Hide,
                  QEvent.Type.Close, QEvent.Type.Destroy,
                  QEvent.Type.HideToParent)

    def __init__(self, app: QApplication, log: _Recorder) -> None:
        super().__init__(app)
        self.app, self.log = app, log

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        try:
            event_type = event.type()
            label = _EVENTS.get(event_type)
            if label is None:
                return False
            if event_type in self._WINDOWISH and type(watched).__name__ not in (
                    "MainWindow", "QWindow", "StartupWindow"):
                return False
            fields: dict[str, Any] = {
                "event": label, "target": _summary(watched),
                "target_win_id": _win_id(watched),
                "app_focus_widget": _summary(self.app.focusWidget()),
                "app_focus_window": _summary(self.app.focusWindow()),
                "app_active_window": _summary(self.app.activeWindow()),
            }
            if event_type in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress,
                              QEvent.Type.KeyRelease):
                key = _enum(event.key())
                modifiers = _enum(event.modifiers())
                native_virtual_key = int(event.nativeVirtualKey())
                native_scan_code = int(event.nativeScanCode())
                is_native_q_or_ctrl = native_virtual_key in (0x51, 0x11, 0xA2, 0xA3)
                if key != _enum(Qt.Key.Key_Q) and key != _enum(Qt.Key.Key_Control) \
                        and not (modifiers & _enum(Qt.KeyboardModifier.ControlModifier)) \
                        and not is_native_q_or_ctrl:
                    return False
                fields.update(key=key, modifiers=modifiers,
                              native_virtual_key=native_virtual_key,
                              native_scan_code=native_scan_code)
            elif event_type == QEvent.Type.Shortcut:
                fields.update(key=str(event.key().toString()),
                              is_ambiguous=bool(event.isAmbiguous()))
            elif event_type == QEvent.Type.WindowStateChange:
                old_state = getattr(event, "oldState", None)
                current_state = getattr(watched, "windowState", None)
                fields.update(
                    old_window_state=_enum(old_state()) if callable(old_state) else None,
                    new_window_state=_enum(current_state()) if callable(current_state) else None,
                    minimized=bool(watched.isMinimized()) if hasattr(watched, "isMinimized") else None,
                    visible=bool(watched.isVisible()) if hasattr(watched, "isVisible") else None,
                )
            win = fields.get("target_win_id")
            if win:
                fields["native_window_state"] = _win_state(int(win))
            self.log.emit("event", **fields)
        except Exception as exc:
            self.log.emit("observer_error", phase="filter", error=repr(exc))
        return False


class _MSG(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                ("time", ctypes.c_uint), ("pt_x", ctypes.c_long),
                ("pt_y", ctypes.c_long), ("lPrivate", ctypes.c_uint)]


class _NativeFilter(QAbstractNativeEventFilter):
    """原生窗口消息观察点：Ctrl/Q 键消息 + 激活/最小化/关闭/销毁。"""

    _KEEP = ("WM_ACTIVATE", "WM_ACTIVATEAPP", "WM_KILLFOCUS",
             "WM_SHOWWINDOW", "WM_CLOSE", "WM_CREATE", "WM_DESTROY")

    def __init__(self, log: _Recorder) -> None:
        super().__init__()
        self.log = log

    def nativeEventFilter(self, event_type: bytes, message: object) -> tuple[bool, int]:  # noqa: N802
        try:
            pointer = int(message)
            native = ctypes.cast(pointer, ctypes.POINTER(_MSG)).contents
            msg = int(native.message)
            label = _NATIVE_MESSAGES.get(msg)
            if label is None:
                return False, 0
            hwnd = int(native.hwnd or 0)
            wparam = int(native.wParam)
            keep = False
            if label.startswith("WM_KEY") and wparam in (0x51, 0x11, 0xA2, 0xA3):
                keep = True  # Ctrl/Q 的键消息
            elif label in self._KEEP:
                keep = True
            elif label == "WM_SYSCOMMAND" and wparam & 0xFFF0 in (
                    _SC_MINIMIZE, _SC_RESTORE, _SC_MAXIMIZE):
                keep = True  # 最小化/还原/最大化系统命令
            if not keep:
                return False, 0
            self.log.emit(
                "native_event",
                event_type=bytes(event_type).decode("ascii", "replace"),
                event=label, hwnd=hwnd, virtual_key=wparam,
                lparam=int(native.lParam), native_window_state=_win_state(hwnd))
        except Exception as exc:
            self.log.emit("observer_error", phase="native_filter", error=repr(exc))
        return False, 0


# ── sys.monitoring 退出调用观察点（仅目标 code 本地事件）──────────────
def _emit_call(phase: str, code: object) -> None:
    if _recorder is None:
        return
    try:
        frame = sys._getframe(2)
        method = _codes.get(code, getattr(code, "co_qualname", "unknown"))
        target = _summary(frame.f_locals.get("self"))
        event = frame.f_locals.get("event")
        accepted = getattr(event, "isAccepted", None)
        fields: dict[str, Any] = {
            "phase": phase, "method": method, "target": target,
            "target_win_id": _win_id(frame.f_locals.get("self"))
            if frame.f_locals.get("self") is not None else None,
        }
        if str(method).endswith(".closeEvent") and callable(accepted):
            fields["event_accepted"] = bool(accepted())
        if str(method).endswith(".request_exit") and phase == "enter":
            fields["force_quit_before"] = bool(
                getattr(frame.f_locals.get("self"), "_force_quit", None))
        _recorder.emit("call", **fields)
    except Exception as exc:
        _recorder.emit("observer_error", phase="monitor", error=repr(exc))


def _start(code: object, _offset: int) -> None:
    _emit_call("enter", code)


def _return(code: object, _offset: int, _value: object) -> None:
    _emit_call("return", code)


def _unwind(code: object, _offset: int, _exception: object) -> None:
    _emit_call("unwind", code)


def _install_monitor(window_module: object) -> None:
    global _tool, _codes
    if _tool is not None or _recorder is None:
        return
    cls = getattr(window_module, "MainWindow")
    originals = {name: getattr(cls, name)
                 for name in ("request_exit", "closeEvent", "_shutdown_resources")}
    mon = sys.monitoring
    tool = next((i for i in range(3, 6) if mon.get_tool(i) is None), None)
    if tool is None:
        raise RuntimeError("no free sys.monitoring tool id")
    mon.use_tool_id(tool, "exit-diagnostic-observer")
    events = mon.events.PY_START | mon.events.PY_RETURN
    try:
        mon.register_callback(tool, mon.events.PY_START, _start)
        mon.register_callback(tool, mon.events.PY_RETURN, _return)
        unwind_enabled = False
        try:
            mon.register_callback(tool, mon.events.PY_UNWIND, _unwind)
            unwind_enabled = True
        except Exception:
            pass
        _codes = {method.__code__: f"MainWindow.{name}"
                  for name, method in originals.items()}
        for code in _codes:
            mon.set_local_events(tool, code, events)
        if unwind_enabled:
            try:
                for code in _codes:
                    mon.set_local_events(tool, code, events | mon.events.PY_UNWIND)
                events |= mon.events.PY_UNWIND
            except Exception:
                for code in _codes:
                    mon.set_local_events(tool, code, events)
        if any(getattr(cls, name) is not method
               for name, method in originals.items()):
            raise RuntimeError("method identity changed")
    except Exception:
        for code in _codes:
            mon.set_local_events(tool, code, 0)
        for event in (mon.events.PY_START, mon.events.PY_RETURN,
                      mon.events.PY_UNWIND):
            mon.register_callback(tool, event, None)
        mon.free_tool_id(tool)
        _codes = {}
        raise
    _tool = tool
    _recorder.emit("plugin", phase="lazy_monitoring_installed", tool_id=tool,
                   global_events=mon.get_events(tool))


def _import(name: str, globals: dict[str, Any] | None = None,
            locals: dict[str, Any] | None = None, fromlist: object = (),
            level: int = 0) -> Any:
    original = _original_import
    if original is None:
        return builtins.__import__(name, globals, locals, fromlist, level)
    result = original(name, globals, locals, fromlist, level)
    if name == "AssetsManager.window" and "MainWindow" in (fromlist or ()):
        try:
            _install_monitor(result)
        except Exception as exc:
            if _recorder is not None:
                _recorder.emit("observer_error", phase="lazy_monitor_install",
                               error=repr(exc))
        finally:
            if builtins.__import__ is _import:
                builtins.__import__ = original
    return result


class _ExportWatcher(threading.Thread):
    """后台守护线程：轮询控制器的导出请求文件并从内存缓冲导出。

    导出不经过 Qt 主线程：即使主线程卡死，控制器仍可通过请求文件拿到
    已缓冲事件。O2（synced）模式下事件本就已逐条落盘，导出仅回执确认。
    """

    def __init__(self, recorder: _Recorder) -> None:
        super().__init__(daemon=True, name="g3-export-watcher")
        self.recorder = recorder
        self._stop = threading.Event()

    def run(self) -> None:
        request = Path(_EXPORT_REQUEST) if _EXPORT_REQUEST else None
        ack = Path(_EXPORT_ACK) if _EXPORT_ACK else None
        if request is None or ack is None:
            return
        while not self._stop.is_set():
            try:
                if request.exists():
                    content = request.read_text(encoding="utf-8").strip()
                    if content:
                        target = Path(content)
                        if self.recorder.mode == "buffered":
                            ack_payload = self.recorder.export(target)
                        else:
                            ack_payload = {
                                "ack": "ok", "mode": self.recorder.mode,
                                "note": "synced: events already on disk at log path",
                                "dropped": self.recorder.dropped,
                                "error_count": self.recorder.error_count,
                                "exported_seq": self.recorder.seq,
                                "log_path": str(self.recorder.path),
                            }
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_text(
                                json.dumps(ack_payload, ensure_ascii=False,
                                           indent=1), encoding="utf-8")
                        ack_payload["ack_monotonic_ms"] = round(
                            time.monotonic() * 1000.0, 3)
                        ack.write_text(
                            json.dumps(ack_payload, ensure_ascii=False),
                            encoding="utf-8")
                        try:
                            request.unlink()
                        except FileNotFoundError:
                            pass
            except Exception as exc:
                try:
                    Path(_EXPORT_ACK).write_text(
                        json.dumps({"ack": "failed",
                                    "error": repr(exc)[:512],
                                    "log_incomplete": True},
                                   ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass
            self._stop.wait(_EXPORT_POLL_INTERVAL_S)

    def stop(self) -> None:
        self._stop.set()


# ── 装载状态 ─────────────────────────────────────────────────────
_filter: _Filter | None = None
_native_filter: QAbstractNativeEventFilter | None = None
_original_import: Callable[..., Any] | None = None
_recorder: _Recorder | None = None
_exporter: _ExportWatcher | None = None
_tool: int | None = None
_codes: dict[object, str] = {}


def register(_host: object) -> None:
    global _filter, _native_filter, _original_import, _recorder, _exporter
    if not _LOG_PATH or _filter is not None:
        return
    app = QApplication.instance()
    if app is None:
        return

    def _step(label: str) -> None:
        """register() 内部逐步标记（诊断挂死点用；独立小文件）。"""
        marker = os.environ.get("AM_G3_REGISTER_TRACE", "").strip()
        if not marker:
            return
        try:
            with open(marker, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"step": label,
                                     "monotonic_ms": round(
                                         time.monotonic() * 1000.0, 3)})
                        + "\n")
        except Exception:
            pass

    _step("enter")
    try:
        _recorder = _Recorder(_LOG_PATH, _MODE)
        _step("recorder_built")
        # 启动/安装状态头（含模式与容量上限；O2 会立即落盘）
        _recorder.emit("recorder_startup", mode=_MODE,
                       buffer_limit=_BUFFER_LIMIT,
                       observer_version="g3-batch01-0.2")
        _step("startup_emitted")
    except Exception:
        _recorder = None
        return
    _filter = _Filter(app, _recorder)
    _step("qt_filter_built")
    app.installEventFilter(_filter)
    _step("qt_filter_installed")
    _native_filter = _NativeFilter(_recorder)
    _step("native_filter_built")
    app.installNativeEventFilter(_native_filter)
    _step("native_filter_installed")
    # 只新增观察信号连接（aboutToQuit / lastWindowClosed），不改既有连接。
    app.aboutToQuit.connect(
        lambda: _recorder.emit("application", signal="aboutToQuit"))
    app.lastWindowClosed.connect(
        lambda: _recorder.emit("application", signal="lastWindowClosed"))
    _step("signals_connected")
    _original_import = builtins.__import__
    builtins.__import__ = _import
    _step("import_hook_installed")
    if _MODE == "buffered":
        _exporter = _ExportWatcher(_recorder)
        _exporter.start()
        # atexit 后备：正常退出且控制器从未发请求时仍保全事件
        atexit.register(_recorder.final_flush)
        _step("watcher_started_atexit_registered")
    _recorder.emit("plugin", phase="registered", mode=_MODE,
                   buffer_limit=_BUFFER_LIMIT,
                   export_request=_EXPORT_REQUEST or None,
                   final_flush=_FINAL_FLUSH or None)
    _step("registered_emitted")


def unregister(_host: object) -> None:
    global _filter, _native_filter, _original_import, _recorder, _exporter, _tool, _codes
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
    if _exporter is not None:
        _exporter.stop()
    if _filter is not None:
        _filter.app.removeEventFilter(_filter)
    if _native_filter is not None:
        instance = QApplication.instance()
        if instance is not None:
            instance.removeNativeEventFilter(_native_filter)
    if _recorder is not None:
        # 结束状态头：丢弃数/错误数/总序号（判读"流是否完整"的合同字段）
        _recorder.emit("recorder_shutdown", dropped=_recorder.dropped,
                       error_count=_recorder.error_count,
                       total_seq=_recorder.seq,
                       recorder_uptime_s=round(
                           time.monotonic() - _recorder.started_monotonic, 3))
        _recorder.final_flush()
    _filter, _native_filter, _original_import, _recorder, _exporter, _tool, _codes = \
        None, None, None, None, None, None, {}
