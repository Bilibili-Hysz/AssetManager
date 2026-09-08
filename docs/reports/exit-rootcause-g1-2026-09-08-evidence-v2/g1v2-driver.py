# G1 EXPERIMENT DRIVER v2 (interface x scancode 2x2) - corrected design per
# docs/reports/exit-rootcause-g1-review-2026-09-09.md R1/R2/R3.
# NOT the official acceptance driver (bd8142 stays untouched).
#
# v2 corrections vs the round-1 2x2 (interface x gap):
#   R1: interface and scancode co-varied in round-1 (A/B called
#       keybd_event(vk, 0, ...) while C/D used SendInput with nonzero scan).
#       v2 splits them cleanly. The keyboard-layout scan query runs in EVERY
#       cell so its timing cost is constant; only its USE differs:
#         E = keybd_event, scan=0    (historical failing form: every archived
#                                     failing-era driver called keybd_event with
#                                     scan 0; observed-08 native-input timing
#                                     0.4-0.9 ms shows back-to-back, no gaps)
#         F = keybd_event, scan!=0   (isolates: does a real scan help keybd?)
#         G = SendInput,   scan=0    (isolates: does SendInput work vk-only?)
#         H = SendInput,   scan!=0   (round-1 D = official bd8142 form)
#       NO inter-event sleeps in any cell: the round-1 "historical 30ms gap"
#       attribution was wrong - the archived failing drivers f989e27 and the
#       observed-08 timing show back-to-back events. The gap factor is
#       explicitly out of scope for v2.
#   R2: the exit-state sampler now also covers the RESTART exit (round-1 wired
#       it to the first exit only).
#   R3: every 200 ms exit sample records the full-system foreground window PID
#       and process NAME (not just a target-yes/no bit), so a foreground steal
#       is attributable instead of merely detected.
#   Per-run evidence embeds the experiment driver hash, argv, mode definition
#   and wall-clock start, so no run can be mis-filed under another condition.
"""W6 functional acceptance chassis reused by the G1 v2 input experiment.

Runs the same hash-bound in-package functional checks as the official W6
driver (info/login/font/thumbnail/notes/live change), then delivers Ctrl+Q
under one of the four E/F/G/H input cells, samples window/foreground state
through BOTH exits (first + restart), and records everything per run.

Every failure prints INVALID and exits non-zero.

Usage:
  python scripts/perf/w6_g1_input_v2.py --exe <AssetManager.exe> \
      --mode onefile --maximized --auto-open --input-mode E --tag E1
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

if os.name == "nt":
    import ctypes as _ctypes
    from ctypes import wintypes as _wintypes

    _ENUM_WINDOWS_PROC = _ctypes.WINFUNCTYPE(
        _ctypes.c_bool, _wintypes.HWND, _wintypes.LPARAM,
    )
else:  # pragma: no cover - the probe itself reports INVALID off Windows
    _ENUM_WINDOWS_PROC = None

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
ROOT = Path(__file__).resolve().parents[2]

PASSWORD = "W6-Functional-Password!"
SHARE_NAME = "W6-Functional"
LIB_FILES = 12
INFO_TIMEOUT_S = 180.0        # includes onefile extraction
CLOSE_TIMEOUT_S = 30.0

INPUT_MODE = "H"  # set by main(); module-level so send() sees it
MODE_DEFINITIONS = {
    "E": {"interface": "keybd_event", "scan": "zero"},
    "F": {"interface": "keybd_event", "scan": "real"},
    "G": {"interface": "SendInput", "scan": "zero"},
    "H": {"interface": "SendInput", "scan": "real"},
}


def _invalid(message: str) -> RuntimeError:
    """Mark an observation gap as an acceptance failure, never as a pass."""
    return RuntimeError(message)


class _InputDeliveryError(RuntimeError):
    """An unsafe Ctrl+Q delivery attempt with JSON-safe observations."""

    def __init__(self, message: str, evidence: dict[str, Any]):
        super().__init__(message)
        self.evidence = evidence


class _InputInjectionError(RuntimeError):
    """A SendInput event was not inserted; receipt remains available for evidence."""

    def __init__(self, message: str, receipt: dict[str, Any]):
        super().__init__(message)
        self.receipt = receipt


def _win32():
    """Return the small, dependency-free Win32 surface used by this probe."""
    if os.name != "nt":
        raise _invalid("W6 functional GUI acceptance requires Windows")
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD), ("th32CntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetCurrentThreadId.argtypes = ()
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    user32 = ctypes.windll.user32
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetWindow.restype = wintypes.HWND
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsWindowEnabled.argtypes = (wintypes.HWND,)
    user32.IsWindowEnabled.restype = wintypes.BOOL
    user32.IsZoomed.argtypes = (wintypes.HWND,)
    user32.IsZoomed.restype = wintypes.BOOL
    user32.IsIconic.argtypes = (wintypes.HWND,)
    user32.IsIconic.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32.PostMessageW.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = (wintypes.HWND,)
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.SetFocus.argtypes = (wintypes.HWND,)
    user32.SetFocus.restype = wintypes.HWND
    user32.GetForegroundWindow.argtypes = ()
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.GetKeyboardLayout.argtypes = (wintypes.DWORD,)
    user32.GetKeyboardLayout.restype = ctypes.c_void_p
    user32.MapVirtualKeyExW.argtypes = (wintypes.UINT, wintypes.UINT, ctypes.c_void_p)
    user32.MapVirtualKeyExW.restype = wintypes.UINT
    user32.keybd_event.argtypes = (ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_size_t)
    user32.keybd_event.restype = None
    if _ENUM_WINDOWS_PROC is None:
        raise _invalid("Win32 EnumWindows callback is unavailable")
    user32.EnumWindows.argtypes = (_ENUM_WINDOWS_PROC, wintypes.LPARAM)
    user32.EnumWindows.restype = wintypes.BOOL

    return ctypes, wintypes, PROCESSENTRY32W


def _descendant_pids(root_pid: int) -> set[int]:
    """Read the current Windows process tree rooted at ``root_pid``."""
    ctypes, wintypes, entry_type = _win32()
    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snapshot == wintypes.HANDLE(-1).value:
        raise _invalid("CreateToolhelp32Snapshot failed")
    try:
        entry = entry_type()
        entry.dwSize = ctypes.sizeof(entry)
        parents: dict[int, list[int]] = {}
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            raise _invalid("Process32FirstW failed")
        while True:
            parents.setdefault(int(entry.th32ParentProcessID), []).append(int(entry.th32ProcessID))
            entry.dwSize = ctypes.sizeof(entry)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
        result = {root_pid}
        pending = [root_pid]
        while pending:
            parent = pending.pop()
            for pid in parents.get(parent, []):
                if pid not in result:
                    result.add(pid)
                    pending.append(pid)
        return result
    finally:
        kernel32.CloseHandle(snapshot)


def _pid_names(pids: set[int]) -> dict[int, str]:
    """Map PIDs to executable names from one snapshot (for attribution)."""
    ctypes, wintypes, entry_type = _win32()
    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        return {}
    try:
        entry = entry_type()
        entry.dwSize = ctypes.sizeof(entry)
        names: dict[int, str] = {}
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return names
        while True:
            pid = int(entry.th32ProcessID)
            if pid in pids and pid not in names:
                names[pid] = str(entry.szExeFile)
            entry.dwSize = ctypes.sizeof(entry)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
        return names
    finally:
        kernel32.CloseHandle(snapshot)


def _list_windows(pids: set[int]) -> list[dict[str, Any]]:
    """Return every titled top-level native window owned by this PID tree."""
    ctypes, wintypes, _entry_type = _win32()
    user32 = ctypes.windll.user32
    found: list[dict[str, Any]] = []
    assert _ENUM_WINDOWS_PROC is not None

    @_ENUM_WINDOWS_PROC
    def collect(hwnd, _lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) not in pids:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, len(title))
        if title.value:
            class_name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_name, len(class_name))
            found.append({
                "hwnd": int(hwnd), "pid": int(pid.value), "title": title.value,
                "class": class_name.value,
                "owner": int(user32.GetWindow(hwnd, 4) or 0),  # GW_OWNER
                "visible": bool(user32.IsWindowVisible(hwnd)),
                "enabled": bool(user32.IsWindowEnabled(hwnd)),
                "maximized": bool(user32.IsZoomed(hwnd)),
                "minimized": bool(user32.IsIconic(hwnd)),
            })
        return True

    if not user32.EnumWindows(collect, 0):
        raise _invalid("EnumWindows failed")
    return found


def _find_window(pids: set[int]) -> dict[str, Any] | None:
    found = _list_windows(pids)
    visible = [item for item in found if item["visible"] and item["owner"] == 0]
    if not visible:
        return None
    if len(visible) != 1:
        raise _invalid(f"ambiguous visible package windows: {visible}")
    return visible[0]


def _wait_for_window(root_pid: int, timeout_s: float) -> dict[str, Any]:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        window = _find_window(_descendant_pids(root_pid))
        if window is not None:
            return window
        time.sleep(0.25)
    raise _invalid(f"no top-level package window found for PID tree {root_pid}")


def _wait_for_main_window(root_pid: int, timeout_s: float) -> dict[str, Any]:
    """Wait for a stable, unique visible top-level window in the launched tree."""
    deadline = time.perf_counter() + timeout_s
    previous: tuple[int, int, str, bool] | None = None
    last_window: dict[str, Any] | None = None
    while time.perf_counter() < deadline:
        window = _find_window(_descendant_pids(root_pid))
        last_window = window
        if window is not None:
            observation = (
                int(window["hwnd"]), int(window["pid"]), str(window["title"]),
                bool(window["maximized"]),
            )
            if observation == previous:
                stable = dict(window)
                stable["ready_predicates"] = {
                    "own_process_tree": True,
                    "sole_visible_unowned_window": True,
                    "stable_hwnd_pid_title_maximized": True,
                    "stable_observations": 2,
                }
                return stable
            previous = observation
        else:
            previous = None
        time.sleep(0.25)
    raise _invalid(
        f"no stable MainWindow in PID tree {root_pid}; last window={last_window!r}")


def _gui_thread_info(hwnd: int) -> dict[str, Any]:
    """Read native GUI-thread state for diagnostics without affecting focus."""
    ctypes, wintypes, _entry_type = _win32()
    user32 = ctypes.windll.user32
    import ctypes as native_ctypes

    class GUITHREADINFO(native_ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("hwndActive", wintypes.HWND),
            ("hwndFocus", wintypes.HWND),
            ("hwndCapture", wintypes.HWND),
            ("hwndMenuOwner", wintypes.HWND),
            ("hwndMoveSize", wintypes.HWND),
            ("hwndCaret", wintypes.HWND),
            ("rcCaret", wintypes.RECT),
        ]

    result: dict[str, Any] = {"query_success": False}
    try:
        target_pid = wintypes.DWORD()
        target_thread = int(user32.GetWindowThreadProcessId(hwnd, ctypes.byref(target_pid)))
        result["target_thread"] = target_thread
        if not target_thread:
            result["error"] = "GetWindowThreadProcessId returned no target thread"
            return result
        info = GUITHREADINFO()
        info.cbSize = native_ctypes.sizeof(GUITHREADINFO)
        user32.GetGUIThreadInfo.argtypes = (wintypes.DWORD, native_ctypes.POINTER(GUITHREADINFO))
        user32.GetGUIThreadInfo.restype = wintypes.BOOL
        if not user32.GetGUIThreadInfo(target_thread, native_ctypes.byref(info)):
            result["error"] = "GetGUIThreadInfo returned false"
            return result
        result.update({
            "query_success": True,
            "cb_size": int(info.cbSize),
            "flags": int(info.flags),
            "active": int(info.hwndActive or 0),
            "focus": int(info.hwndFocus or 0),
            "capture": int(info.hwndCapture or 0),
            "menu_owner": int(info.hwndMenuOwner or 0),
            "move_size": int(info.hwndMoveSize or 0),
            "caret": int(info.hwndCaret or 0),
        })
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _send_input_key(user32: Any, wintypes: Any, target_thread: int, vk: int,
                    *, key_up: bool, scan: int) -> dict[str, Any]:
    """Insert one VK keyboard event; the CALLER's scan value is sent as given.

    The cell's scan policy (zero vs real) is decided by the caller so the
    keyboard-layout scan query runs in EVERY cell at constant cost.
    """
    import ctypes as native_ctypes

    class KEYBDINPUT(native_ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", native_ctypes.c_size_t)]

    class MOUSEINPUT(native_ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", native_ctypes.c_size_t)]

    class HARDWAREINPUT(native_ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                    ("wParamH", wintypes.WORD)]

    class INPUTUNION(native_ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(native_ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", INPUTUNION)]

    expected_size = 40 if native_ctypes.sizeof(native_ctypes.c_void_p) == 8 else 28
    if native_ctypes.sizeof(INPUT) != expected_size:
        raise RuntimeError(f"unexpected INPUT size {native_ctypes.sizeof(INPUT)}, expected {expected_size}")
    receipt = {"vk": vk, "key_up": key_up, "target_thread": target_thread,
               "scan_sent": scan, "input_size": native_ctypes.sizeof(INPUT)}
    event = INPUT()
    event.type = 1  # INPUT_KEYBOARD
    event.u.ki.wVk = vk
    event.u.ki.wScan = scan
    event.u.ki.dwFlags = 2 if key_up else 0  # VK semantics; no SCANCODE flag.
    user32.SendInput.argtypes = (wintypes.UINT, native_ctypes.POINTER(INPUT), native_ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT
    receipt["inserted"] = int(user32.SendInput(1, native_ctypes.byref(event), native_ctypes.sizeof(INPUT)))
    if receipt["inserted"] != 1:
        raise _InputInjectionError("SendInput inserted 0/1 keyboard events", receipt)
    return receipt


def _focus_window(hwnd: int, *, purpose: str, timeout_s: float = 5.0) -> None:
    """Bring one known test window to the foreground, or fail without input."""
    ctypes, wintypes, _entry_type = _win32()
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        if not user32.IsWindowVisible(hwnd):
            raise _invalid(f"{purpose} is hidden; no focus or key was sent")
        if not user32.IsWindowEnabled(hwnd):
            raise _invalid(f"{purpose} is disabled; no focus or key was sent")
        foreground = int(user32.GetForegroundWindow() or 0)
        if foreground == hwnd:
            return
        target_pid = wintypes.DWORD()
        target_thread = int(user32.GetWindowThreadProcessId(hwnd, ctypes.byref(target_pid)))
        if not target_thread:
            raise _invalid(f"could not resolve target thread for {purpose}")
        foreground_pid = wintypes.DWORD()
        foreground_thread = (
            int(user32.GetWindowThreadProcessId(foreground, ctypes.byref(foreground_pid)))
            if foreground else 0
        )
        current_thread = int(kernel32.GetCurrentThreadId())
        attached_target = False
        attached_foreground = False
        try:
            if target_thread != current_thread:
                attached_target = bool(user32.AttachThreadInput(current_thread, target_thread, True))
            if foreground_thread and foreground_thread != current_thread:
                attached_foreground = bool(
                    user32.AttachThreadInput(current_thread, foreground_thread, True))
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetFocus(hwnd)
        finally:
            if attached_foreground:
                user32.AttachThreadInput(current_thread, foreground_thread, False)
            if attached_target:
                user32.AttachThreadInput(current_thread, target_thread, False)
        if int(user32.GetForegroundWindow() or 0) == hwnd:
            return
        time.sleep(0.1)
    raise _invalid(f"could not focus {purpose} within {timeout_s:.1f}s; no key was sent")



def _send_ctrl_q(hwnd: int, *, expected_maximized: bool | None = None) -> dict[str, Any]:
    """Deliver Ctrl+Q under the current E/F/G/H cell. No inter-event sleeps.

    The round-1 gap factor is retired: every archived failing-era driver sent
    back-to-back events (observed-08 native timing 0.4-0.9 ms; archived driver
    f989e27 has no sleeps between keybd_event calls). The keyboard-layout scan
    query runs in every cell; cells differ only in interface and whether the
    queried scan is actually set on the event.
    """
    ctypes, wintypes, _entry_type = _win32()
    user32 = ctypes.windll.user32
    evidence: dict[str, Any] = {
        "entry": "Ctrl+Q", "expected_maximized": expected_maximized,
        "input_mode": INPUT_MODE, "mode_definition": MODE_DEFINITIONS[INPUT_MODE],
        "stages": [], "input_receipts": [],
    }
    stages: list[dict[str, Any]] = evidence["stages"]
    modifier_keys = {"Ctrl": 0x11, "Alt": 0x12, "Shift": 0x10,
                     "Win": (0x5B, 0x5C)}
    ctrl_pressed = False
    q_pressed = False
    target_thread = 0

    def observe(stage: str) -> dict[str, Any]:
        modifiers = {
            name: any(int(user32.GetAsyncKeyState(vk)) & 0x8000 for vk in
                      ((code,) if isinstance(code, int) else code))
            for name, code in modifier_keys.items()
        }
        observation = {
            "stage": stage,
            "monotonic_s": round(time.monotonic(), 6),
            "foreground_is_target": int(user32.GetForegroundWindow() or 0) == hwnd,
            "window_visible": bool(user32.IsWindowVisible(hwnd)),
            "window_enabled": bool(user32.IsWindowEnabled(hwnd)),
            "window_maximized": bool(user32.IsZoomed(hwnd)),
            "window_minimized": bool(user32.IsIconic(hwnd)),
            "modifiers": modifiers,
        }
        stages.append(observation)
        return observation

    def fail(message: str) -> _InputDeliveryError:
        evidence["outcome"] = "invalid_input_delivery"
        return _InputDeliveryError(message, evidence)

    def send(vk: int, *, key_up: bool) -> None:
        nonlocal target_thread
        interface = MODE_DEFINITIONS[INPUT_MODE]["interface"]
        real_scan = int(user32.MapVirtualKeyExW(vk, 0, user32.GetKeyboardLayout(target_thread)))
        scan_sent = 0 if MODE_DEFINITIONS[INPUT_MODE]["scan"] == "zero" else real_scan
        flags = (0x2 if key_up else 0)
        if interface == "keybd_event":
            user32.keybd_event(vk, scan_sent, flags, 0)
            evidence["input_receipts"].append(
                {"interface": "keybd_event", "vk": vk, "key_up": key_up,
                 "scan_sent": scan_sent, "scan_real": real_scan})
            return
        receipt = _send_input_key(user32, wintypes, target_thread, vk,
                                  key_up=key_up, scan=scan_sent)
        receipt["scan_real"] = real_scan
        evidence["input_receipts"].append(receipt)

    last_error = "foreground never settled on the package window"
    try:
        for attempt in (1, 2):
            _focus_window(hwnd, purpose="package window for Ctrl+Q")
            # Foreground activation is asynchronous from the target Qt event
            # loop; do not queue the shortcut in the same scheduling turn.
            time.sleep(0.15)
            if int(user32.GetForegroundWindow() or 0) == hwnd:
                break
            last_error = f"attempt {attempt}: package window lost foreground before Ctrl+Q"
        else:
            observe("focus_not_settled")
            raise fail(f"{last_error}; shortcut was not sent")

        before = observe("before_ctrl_down")
        if expected_maximized is not None and before["window_maximized"] != expected_maximized:
            raise fail("window state changed before Ctrl+Q; shortcut was not sent")
        if not before["window_enabled"]:
            raise fail("package window is disabled before Ctrl+Q; shortcut was not sent")
        q_was_preheld = bool(int(user32.GetAsyncKeyState(ord("Q"))) & 0x8000)
        before["q_was_preheld"] = q_was_preheld
        held = [name for name, pressed in before["modifiers"].items() if pressed]
        if held:
            raise fail(f"refusing Ctrl+Q while user holds modifier(s) {held}; shortcut was not sent")
        if q_was_preheld:
            raise fail("refusing Ctrl+Q while user holds Q; shortcut was not sent")
        if not before["foreground_is_target"]:
            raise fail("package window lost foreground before Ctrl+Q; shortcut was not sent")

        target_pid = wintypes.DWORD()
        target_thread = int(user32.GetWindowThreadProcessId(hwnd, ctypes.byref(target_pid)))
        if not target_thread:
            raise fail("could not resolve target thread before Ctrl+Q; shortcut was not sent")

        ctrl_pressed = True
        send(0x11, key_up=False)
        after_ctrl = observe("after_ctrl_down_before_q")
        if not after_ctrl["foreground_is_target"]:
            raise fail("package window lost foreground after Ctrl down; Q was not sent")

        q_pressed = True
        send(ord("Q"), key_up=False)
        after_q = observe("after_q_down")
        if not after_q["foreground_is_target"]:
            # The application may legitimately process Ctrl+Q and disappear
            # before this observation; preserve the uncertainty, no second Q.
            evidence["outcome"] = "delivery_uncertain"
            evidence["focus_changed_after_q"] = True
        else:
            evidence["outcome"] = "q_sent_with_target_foreground"
    except _InputDeliveryError:
        raise
    except Exception as exc:
        try:
            observe("input_exception")
        except Exception:
            pass
        raise fail(f"Ctrl+Q input exception: {type(exc).__name__}: {exc}") from exc
    finally:
        release_errors: list[str] = []
        if q_pressed:
            try:
                send(ord("Q"), key_up=True)
            except Exception as exc:
                release_errors.append(f"Q up: {type(exc).__name__}: {exc}")
        if ctrl_pressed:
            try:
                send(0x11, key_up=True)
            except Exception as exc:
                release_errors.append(f"Ctrl up: {type(exc).__name__}: {exc}")
        evidence["released_probe_keys"] = {"Ctrl": ctrl_pressed, "Q": q_pressed}
        try:
            observe("after_probe_key_release")
        except Exception as exc:
            release_errors.append(f"post-release observation: {type(exc).__name__}: {exc}")
        if release_errors:
            evidence["release_errors"] = release_errors
            evidence["outcome"] = "invalid_input_delivery"
            if sys.exc_info()[0] is None:
                raise _InputDeliveryError("Ctrl+Q release failed: " + "; ".join(release_errors), evidence)
    return evidence


def _send_enter(hwnd: int) -> None:
    """Activate the single seeded StartupWindow library card once via Enter."""
    ctypes, wintypes, _entry_type = _win32()
    user32 = ctypes.windll.user32
    _focus_window(hwnd, purpose="StartupWindow for Enter")
    target_pid = wintypes.DWORD()
    target_thread = int(user32.GetWindowThreadProcessId(hwnd, ctypes.byref(target_pid)))
    if not target_thread:
        raise _invalid("could not resolve target thread for Enter")
    _send_input_key(user32, wintypes, target_thread, 0x0D, key_up=False, scan=28)
    _send_input_key(user32, wintypes, target_thread, 0x0D, key_up=True, scan=28)


def _wait_for_exit(proc: subprocess.Popen[bytes], timeout_s: float,
                   app_hwnd: int | None = None, samples: list | None = None) -> int:
    """Poll for exit; sample window + full-system foreground every 200ms.

    v2 (R3): every sample records the foreground window PID and process NAME,
    so a foreground steal is attributable instead of merely detected.  Wired
    to BOTH the first exit and the restart exit (R2).
    """
    import ctypes
    user32 = ctypes.windll.user32
    names_cache: dict[int, str] = {}
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        rc = proc.poll()
        if rc is not None:
            return rc
        if app_hwnd is not None and samples is not None:
            fg = int(user32.GetForegroundWindow() or 0)
            fg_pid = 0
            if fg:
                pid_buf = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(fg, ctypes.byref(pid_buf))
                fg_pid = int(pid_buf.value)
            if fg_pid and fg_pid not in names_cache:
                try:
                    names_cache[fg_pid] = _pid_names({fg_pid}).get(fg_pid, "?")
                except Exception:
                    names_cache[fg_pid] = "?"
            samples.append({
                "monotonic_s": round(time.monotonic(), 3),
                "iconic": bool(user32.IsIconic(app_hwnd)),
                "zoomed": bool(user32.IsZoomed(app_hwnd)),
                "visible": bool(user32.IsWindowVisible(app_hwnd)),
                "fg_target": fg == app_hwnd,
                "fg_pid": fg_pid,
                "fg_name": names_cache.get(fg_pid) if fg_pid else None,
            })
        time.sleep(0.2)
    raise _invalid(f"normal Ctrl+Q exit did not complete within {timeout_s:.1f}s")


def _exit_timeout_observation(hwnd: int, base_url: str, proc: subprocess.Popen[bytes]) -> dict[str, Any]:
    """Capture state after a normal-exit timeout without changing the app."""
    ctypes, wintypes, _entry_type = _win32()
    user32 = ctypes.windll.user32
    foreground = int(user32.GetForegroundWindow() or 0)
    foreground_pid = wintypes.DWORD()
    if foreground:
        user32.GetWindowThreadProcessId(foreground, ctypes.byref(foreground_pid))
    fg_name = None
    if int(foreground_pid.value):
        try:
            fg_name = _pid_names({int(foreground_pid.value)}).get(int(foreground_pid.value))
        except Exception:
            fg_name = None
    observation: dict[str, Any] = {
        "process_poll": proc.poll(),
        "focused_native_handle": hwnd,
        "window_visible": bool(user32.IsWindowVisible(hwnd)),
        "window_enabled": bool(user32.IsWindowEnabled(hwnd)),
        "window_maximized": bool(user32.IsZoomed(hwnd)),
        "window_minimized": bool(user32.IsIconic(hwnd)),
        "foreground_is_target": foreground == hwnd,
        "foreground_pid": int(foreground_pid.value),
        "foreground_name": fg_name,
        "gui_thread_info": _gui_thread_info(hwnd),
    }
    try:
        observation["own_process_windows"] = _list_windows(_descendant_pids(proc.pid))
    except Exception as exc:
        observation["own_process_windows_error"] = f"{type(exc).__name__}: {exc}"
    try:
        status, _headers, _body = _http("GET", f"{base_url}/api/info", timeout=5)
        observation["api_info_status"] = status
    except Exception as exc:
        observation["api_info_error"] = f"{type(exc).__name__}: {exc}"
    return observation



def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _build_library(root: Path) -> Path:
    from PIL import Image

    lib = root / "library"
    lib.mkdir(parents=True)
    for i in range(LIB_FILES):
        img = Image.new("RGB", (512, 512), ((i * 23) % 256, (i * 57) % 256, (i * 91) % 256))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        (lib / f"pkg_{i:03d}.png").write_bytes(buf.getvalue())
    return lib


def _seed_runtime(runtime_root: Path, lib: Path, port: int, maximized: bool) -> Path:
    shared = runtime_root / "Shared"
    shared.mkdir(parents=True, exist_ok=True)
    settings = {
        "_cfg_version": 2,
        "_legacy_migrated": True,
        "recent_libraries": [str(lib)],
        "theme": "Navy",
        "window_maximized": bool(maximized),
        "lan_auto_start": True,
        "lan_auth_mode": "password",
        "lan_password": PASSWORD,
        "lan_port": port,
        "lan_bind": "127.0.0.1",
        "lan_share_name": SHARE_NAME,
        "lan_share_safety_ack_version": 1,
        "lan_trusted_network_confirmed": False,
    }
    path = shared / "settings.json"
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def _http(method: str, url: str, *, data: dict | None = None,
          cookie: str | None = None, timeout: float = 20.0):
    request = urllib.request.Request(url, method=method)
    if cookie:
        request.add_header("Cookie", cookie)
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, data=body, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True)
    parser.add_argument("--mode", required=True, choices=("onefile", "onedir"))
    parser.add_argument("--maximized", action="store_true")
    parser.add_argument("--auto-open", action="store_true",
                        help="focus the one seeded StartupWindow card and press Enter once")
    parser.add_argument("--input-mode", default="H", choices=("E", "F", "G", "H"),
                        help="G1 v2 2x2: E=keybd/scan0 F=keybd/scan "
                             "G=SendInput/scan0 H=SendInput/scan")
    parser.add_argument("--tag", default="", help="output JSON tag for this iteration")
    args = parser.parse_args()
    global INPUT_MODE
    INPUT_MODE = args.input_mode

    exe = Path(args.exe).resolve()
    if not exe.is_file():
        print(f"INVALID: exe not found: {exe}")
        return 1

    # Self-identify so every run JSON binds to THIS driver version.
    driver_path = Path(__file__).resolve()
    driver_sha = hashlib.sha256(driver_path.read_bytes()).hexdigest()

    tmp = Path(tempfile.mkdtemp(prefix="w6-g1v2-"))
    runtime_root = tmp / "runtime"
    lib = _build_library(tmp)
    port = _free_port()
    settings_path = _seed_runtime(runtime_root, lib, port, args.maximized)

    print(f"bundle: {args.mode} ({exe})")
    print(f"input cell: {INPUT_MODE} = {MODE_DEFINITIONS[INPUT_MODE]}")
    print(f"runtime: {runtime_root}")
    print(f"lan: http://127.0.0.1:{port} (password auth)")
    print(f"driver sha256: {driver_sha}")

    env = dict(os.environ)
    env["AM_RUNTIME_ROOT"] = str(runtime_root)
    proc = subprocess.Popen([str(exe)], env=env, cwd=str(ROOT))
    print(f"launched pid={proc.pid}")

    failures: list[str] = []
    restarted: subprocess.Popen[bytes] | None = None
    evidence: dict = {
        "mode": args.mode, "exe_sha256": None, "pid": proc.pid,
        "port": port, "maximized": args.maximized, "checks": {},
        "g1v2": {
            "input_mode": INPUT_MODE,
            "mode_definition": MODE_DEFINITIONS[INPUT_MODE],
            "driver_sha256": driver_sha,
            "argv": vars(args),
            "wall_clock_start": datetime.datetime.now().isoformat(timespec="seconds"),
            "design_note": "no inter-event sleeps in any cell; scan query in every cell",
        },
    }

    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    evidence["exe_sha256"] = digest
    print(f"exe sha256: {digest}")

    base = f"http://127.0.0.1:{port}"

    if args.auto_open:
        try:
            _send_enter(_wait_for_window(proc.pid, 15.0)["hwnd"])
        except RuntimeError as exc:
            failures.append(str(exc))

    deadline = time.perf_counter() + INFO_TIMEOUT_S
    info_status = None
    info_body = b""
    while time.perf_counter() < deadline:
        if proc.poll() is not None:
            failures.append(f"process exited early with code {proc.returncode}")
            break
        try:
            info_status, _h, info_body = _http("GET", f"{base}/api/info", timeout=5)
            if info_status == 200:
                break
        except Exception:
            pass
        time.sleep(1.0)
    if info_status != 200:
        failures.append(f"/api/info never returned 200 (last {info_status}) within {INFO_TIMEOUT_S}s")
    else:
        info = json.loads(info_body)
        evidence["checks"]["info"] = {
            "share_name": info.get("share_name"),
            "auth_mode": info.get("auth_mode"),
        }
        if info.get("share_name") != SHARE_NAME:
            failures.append(f"share_name mismatch: {info.get('share_name')!r}")

    if not failures:
        try:
            evidence["window_initial_api_precondition"] = {
                "endpoint": "/api/info", "status": info_status,
            }
            window = _wait_for_main_window(proc.pid, 15.0)
            evidence["window_initial"] = window
            if window["maximized"] != args.maximized:
                failures.append(
                    f"window maximized={window['maximized']}, expected {args.maximized}")
            else:
                print(f"window OK: hwnd={window['hwnd']} maximized={window['maximized']}")
        except RuntimeError as exc:
            failures.append(str(exc))

    cookie = ""
    if not failures:
        status, headers, _body = _http("POST", f"{base}/api/auth/login",
                                       data={"password": PASSWORD})
        set_cookie = headers.get("Set-Cookie", "")
        if status != 200 or "lan_token=" not in set_cookie:
            failures.append(f"login failed: HTTP {status}, set-cookie={set_cookie[:60]!r}")
        else:
            cookie = set_cookie.split(";", 1)[0]
            evidence["checks"]["login"] = "ok"
            print("login OK")

    if not failures:
        # notes + rating write path (metadata end-to-end through the LAN API)
        status, _h, _b = _http("PUT", f"{base}/api/notes/pkg_000.png",
                               cookie=cookie, data={"notes": "G1v2 note"})
        status_r, _h, _b = _http("PUT", f"{base}/api/rating/pkg_000.png",
                                 cookie=cookie, data={"rating": 4})
        status_m, _h, meta_body = _http("GET", f"{base}/api/meta/pkg_000.png", cookie=cookie)
        meta = json.loads(meta_body) if status_m == 200 else {}
        if ((status, status_r, status_m) != (200, 200, 200)
                or meta.get("notes") != "G1v2 note" or meta.get("rating") != 4):
            failures.append(f"notes/rating failed: HTTP {status}/{status_r}/{status_m}, {meta.get('notes')!r}")
        else:
            evidence["checks"]["notes_rating"] = "ok"
            print("notes/rating OK")

    # -- first exit: Ctrl+Q with sampler wired (R2/R3) ------------------
    close_note: dict[str, Any] = {}
    app_hwnd = evidence.get("window_initial", {}).get("hwnd")
    if failures:
        close_note["status"] = "not_attempted_after_prior_failure"
    elif proc.poll() is not None or not isinstance(app_hwnd, int):
        failures.append("process/window unavailable before close acceptance")
        close_note["status"] = "unavailable"
    else:
        try:
            close_note["input_delivery"] = _send_ctrl_q(app_hwnd, expected_maximized=args.maximized)
            close_note["exit_state_samples"] = []
            try:
                code = _wait_for_exit(proc, CLOSE_TIMEOUT_S, app_hwnd,
                                      close_note["exit_state_samples"])
            except RuntimeError:
                close_note["normal_exit_timeout_observation"] = _exit_timeout_observation(
                    app_hwnd, base, proc)
                raise
            close_note["normal_exit"] = {"entry": "Ctrl+Q", "exit_code": code}
            if code != 0:
                raise _invalid(f"normal Ctrl+Q exit returned {code}")
        except RuntimeError as exc:
            if isinstance(exc, _InputDeliveryError):
                close_note["input_delivery"] = exc.evidence
            failures.append(str(exc))
    evidence["close"] = close_note
    print(f"close exit: {close_note.get('normal_exit')}")

    if not failures:
        # Persisted state is an assertion, not informational.
        saved = json.loads(settings_path.read_text(encoding="utf-8"))
        persisted = {
            "window_maximized": saved.get("window_maximized"),
            "has_geometry": isinstance(saved.get("window_geometry"), str)
                            and len(saved.get("window_geometry", "")) > 0,
        }
        evidence["checks"]["geometry_persisted"] = persisted
        if persisted["window_maximized"] != args.maximized or not persisted["has_geometry"]:
            failures.append(f"geometry persistence contract failed: {persisted}")

    if not failures:
        # -- restart exit: sampler wired here too (R2) -------------------
        restarted = subprocess.Popen([str(exe)], env=env, cwd=str(ROOT))
        restart_evidence: dict[str, Any] = {"pid": restarted.pid}
        evidence["restart"] = restart_evidence
        try:
            if args.auto_open:
                _send_enter(_wait_for_window(restarted.pid, 15.0)["hwnd"])
            deadline = time.perf_counter() + INFO_TIMEOUT_S
            status = None
            while time.perf_counter() < deadline:
                if restarted.poll() is not None:
                    break
                try:
                    status, _headers, _body = _http("GET", f"{base}/api/info", timeout=5)
                    if status == 200:
                        break
                except Exception:
                    pass
                time.sleep(1.0)
            if status != 200:
                raise _invalid(f"restarted LAN /api/info never returned 200 (last {status})")
            restart_evidence["window_api_precondition"] = {
                "endpoint": "/api/info", "status": status,
            }
            restart_window = _wait_for_main_window(restarted.pid, 15.0)
            restart_evidence["window"] = restart_window
            if restart_window["maximized"] != args.maximized:
                raise _invalid(
                    f"restarted window maximized={restart_window['maximized']}, expected {args.maximized}")
            status, headers, _body = _http("POST", f"{base}/api/auth/login", data={"password": PASSWORD})
            restart_cookie = headers.get("Set-Cookie", "").split(";", 1)[0]
            if status != 200 or not restart_cookie.startswith("lan_token="):
                raise _invalid(f"restarted login failed: HTTP {status}")
            status, _headers, body = _http("GET", f"{base}/api/meta/pkg_000.png", cookie=restart_cookie)
            restored_meta = json.loads(body) if status == 200 else {}
            restart_evidence["notes_rating"] = restored_meta
            if (status != 200 or restored_meta.get("notes") != "G1v2 note"
                    or restored_meta.get("rating") != 4):
                raise _invalid(f"notes/rating not persisted after restart: HTTP {status}, {restored_meta}")
            restart_evidence["input_delivery"] = _send_ctrl_q(
                restart_window["hwnd"], expected_maximized=args.maximized)
            # v2: sampler + foreground stream NOW wired to the restart exit.
            restart_evidence["exit_state_samples"] = []
            try:
                restart_code = _wait_for_exit(restarted, CLOSE_TIMEOUT_S,
                                              restart_window["hwnd"],
                                              restart_evidence["exit_state_samples"])
            except RuntimeError:
                restart_evidence["normal_exit_timeout_observation"] = _exit_timeout_observation(
                    restart_window["hwnd"], base, restarted)
                raise
            restart_evidence["normal_exit_code"] = restart_code
            if restart_code != 0:
                raise _invalid(f"restarted Ctrl+Q exit returned {restart_code}")
            print("restart exit OK (sampler recorded)")
        except RuntimeError as exc:
            if isinstance(exc, _InputDeliveryError):
                restart_evidence["input_delivery"] = exc.evidence
            failures.append(str(exc))

    # Forced termination is cleanup for an already-invalid isolated run.
    if failures:
        cleanup: list[dict[str, Any]] = []
        for label, candidate in (("initial", proc), ("restart", restarted)):
            if candidate is not None and candidate.poll() is None:
                result = subprocess.run(
                    ["taskkill", "/F", "/PID", str(candidate.pid), "/T"],
                    capture_output=True, text=True,
                )
                cleanup.append({"process": label, "pid": candidate.pid,
                                "returncode": result.returncode})
        evidence["invalid_run_cleanup"] = cleanup

    out = Path("artifacts/g1v2")
    out.mkdir(parents=True, exist_ok=True)
    evidence["valid"] = not failures
    evidence["failures"] = failures
    tag = (f"{args.tag}-{args.mode}{'-max' if args.maximized else ''}"
           if args.tag else f"{args.mode}{'-maximized' if args.maximized else ''}")
    (out / f"{tag}.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=1), encoding="utf-8")

    if failures:
        print(f"INVALID: {'; '.join(failures)}")
        return 1
    print(f"G1V2 ({INPUT_MODE} {args.mode}{' max' if args.maximized else ''}): PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
