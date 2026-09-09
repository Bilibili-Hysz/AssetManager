"""Static contracts for the W6 package acceptance probe's window readiness."""
from __future__ import annotations

import ctypes
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from ctypes import wintypes

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "perf" / "w6_package_functional.py"
SPEC = importlib.util.spec_from_file_location("w6_package_functional", SCRIPT)
assert SPEC and SPEC.loader
w6 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(w6)


class _FakeUser32:
    def __init__(self, hwnd: int = 100, *, held: set[int] | None = None,
                 enabled: bool = True, on_event=None, raise_on_event=None):
        self.hwnd = hwnd
        self.foreground = hwnd
        self.held = set(held or ())
        self.enabled = enabled
        self.events: list[tuple[int, int]] = []
        self.on_event = on_event
        self.raise_on_event = raise_on_event
        self.SendInput = _FakeSendInput(self)

    def GetForegroundWindow(self):
        return self.foreground

    def IsWindowVisible(self, _hwnd):
        return True

    def IsZoomed(self, _hwnd):
        return True

    def IsIconic(self, _hwnd):
        return False

    def IsWindowEnabled(self, _hwnd):
        return self.enabled

    def GetAsyncKeyState(self, key):
        return 0x8000 if key in self.held else 0

    def keybd_event(self, vk, _scan, flags, _extra):
        self.events.append((vk, flags))
        if flags == 0:
            self.held.add(vk)
        elif flags == 2:
            self.held.discard(vk)
        if self.on_event is not None:
            self.on_event(self, vk, flags)
        if self.raise_on_event is not None and self.raise_on_event(vk, flags):
            raise OSError("fake key delivery failure")

    def GetWindowThreadProcessId(self, _hwnd, pid_ptr):
        pid_ptr._obj.value = 123
        return 456

    def GetKeyboardLayout(self, _thread_id):
        return 1

    def MapVirtualKeyExW(self, _vk, _kind, _layout):
        return 42


class _FakeSendInput:
    def __init__(self, owner: _FakeUser32):
        self.owner = owner
        self.argtypes = None
        self.restype = None
        self.result = 1

    def __call__(self, _count, event_ptr, _size):
        event = event_ptr._obj.u.ki
        self.owner.keybd_event(int(event.wVk), 0, int(event.dwFlags), 0)
        return self.result


def _install_fake_input(monkeypatch, user32: _FakeUser32):
    fake_ctypes = SimpleNamespace(byref=ctypes.byref, windll=SimpleNamespace(user32=user32))
    monkeypatch.setattr(w6, "_win32", lambda: (fake_ctypes, wintypes, None))
    monkeypatch.setattr(w6, "_focus_window", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(w6.time, "sleep", lambda _seconds: None)


class _FakeFocusUser32:
    def __init__(self, *, visible: bool, foreground: int, enabled: bool = True,
                 target: int = 100):
        self.visible = visible
        self.foreground = foreground
        self.enabled = enabled
        self.target = target
        self.calls: list[str] = []

    def IsWindowVisible(self, _hwnd):
        self.calls.append("IsWindowVisible")
        return self.visible

    def GetForegroundWindow(self):
        self.calls.append("GetForegroundWindow")
        return self.foreground

    def IsWindowEnabled(self, _hwnd):
        self.calls.append("IsWindowEnabled")
        return self.enabled

    def GetWindowThreadProcessId(self, _hwnd, pid_ptr):
        self.calls.append("GetWindowThreadProcessId")
        pid_ptr._obj.value = 123
        return 456

    def AttachThreadInput(self, *_args):
        self.calls.append("AttachThreadInput")
        return True

    def BringWindowToTop(self, _hwnd):
        self.calls.append("BringWindowToTop")
        return True

    def SetForegroundWindow(self, hwnd):
        self.calls.append("SetForegroundWindow")
        self.foreground = hwnd
        return True

    def SetFocus(self, _hwnd):
        self.calls.append("SetFocus")
        return 1


def _install_fake_focus(monkeypatch, user32: _FakeFocusUser32):
    fake_ctypes = SimpleNamespace(
        byref=ctypes.byref,
        windll=SimpleNamespace(user32=user32, kernel32=SimpleNamespace(GetCurrentThreadId=lambda: 789)),
    )
    monkeypatch.setattr(w6, "_win32", lambda: (fake_ctypes, wintypes, None))
    monkeypatch.setattr(w6.time, "sleep", lambda _seconds: None)


class _FakeGetGUIThreadInfo:
    def __init__(self, *, succeeds: bool):
        self.succeeds = succeeds
        self.argtypes = None
        self.restype = None

    def __call__(self, thread_id, info_ptr):
        assert thread_id == 456
        info = info_ptr._obj
        assert info.cbSize in {48, 72}
        if not self.succeeds:
            return False
        info.flags = 0x14
        info.hwndActive = 100
        info.hwndFocus = 101
        info.hwndCapture = 102
        info.hwndMenuOwner = 103
        info.hwndMoveSize = 104
        info.hwndCaret = 105
        return True


class _FakeGuiInfoUser32:
    def __init__(self, *, succeeds: bool):
        self.GetGUIThreadInfo = _FakeGetGUIThreadInfo(succeeds=succeeds)

    def GetWindowThreadProcessId(self, _hwnd, pid_ptr):
        pid_ptr._obj.value = 321
        return 456


def _install_fake_gui_thread_info(monkeypatch, user32: _FakeGuiInfoUser32):
    fake_ctypes = SimpleNamespace(
        Structure=ctypes.Structure,
        POINTER=ctypes.POINTER,
        byref=ctypes.byref,
        sizeof=ctypes.sizeof,
        windll=SimpleNamespace(user32=user32),
    )
    monkeypatch.setattr(w6, "_win32", lambda: (fake_ctypes, wintypes, None))


def test_main_window_wait_requires_two_stable_generic_window_observations(monkeypatch):
    observed = iter([
        None,
        {"hwnd": 10, "pid": 11, "title": "AssetManager", "maximized": True},
        {"hwnd": 20, "pid": 11, "title": "AssetManager", "maximized": True},
        {"hwnd": 20, "pid": 11, "title": "AssetManager", "maximized": True},
    ])
    calls: list[set[int]] = []
    monkeypatch.setattr(w6, "_descendant_pids", lambda pid: {pid})
    monkeypatch.setattr(w6, "_find_window", lambda pids: calls.append(pids) or next(observed))
    monkeypatch.setattr(w6.time, "sleep", lambda _seconds: None)

    window = w6._wait_for_main_window(11, timeout_s=1.0)

    assert len(calls) == 4
    assert window["hwnd"] == 20
    assert window["ready_predicates"] == {
        "own_process_tree": True,
        "sole_visible_unowned_window": True,
        "stable_hwnd_pid_title_maximized": True,
        "stable_observations": 2,
    }


def test_gui_thread_info_records_native_handles_and_flags(monkeypatch):
    _install_fake_gui_thread_info(monkeypatch, _FakeGuiInfoUser32(succeeds=True))

    result = w6._gui_thread_info(100)

    assert result["query_success"] is True
    assert result["target_thread"] == 456
    assert result["cb_size"] in {48, 72}
    assert result["flags"] == 0x14
    assert result["active"] == 100
    assert result["focus"] == 101
    assert result["capture"] == 102
    assert result["menu_owner"] == 103
    assert result["move_size"] == 104
    assert result["caret"] == 105


def test_gui_thread_info_records_query_failure_without_raising(monkeypatch):
    _install_fake_gui_thread_info(monkeypatch, _FakeGuiInfoUser32(succeeds=False))

    result = w6._gui_thread_info(100)

    assert result == {
        "query_success": False,
        "target_thread": 456,
        "error": "GetGUIThreadInfo returned false",
    }


def test_send_input_key_records_native_size_and_scan(monkeypatch):
    user32 = _FakeUser32()
    _install_fake_input(monkeypatch, user32)

    receipt = w6._send_input_key(user32, wintypes, 456, ord("Q"), key_up=False)

    assert receipt["inserted"] == 1
    assert receipt["scan"] == 42
    assert receipt["input_size"] in {28, 40}


def test_send_input_key_rejects_zero_insertion_and_missing_scan(monkeypatch):
    user32 = _FakeUser32()
    _install_fake_input(monkeypatch, user32)
    user32.SendInput.result = 0
    with pytest.raises(w6._InputInjectionError, match="0/1") as zero:
        w6._send_input_key(user32, wintypes, 456, ord("Q"), key_up=True)
    assert zero.value.receipt["key_up"] is True
    assert zero.value.receipt["inserted"] == 0

    user32.SendInput.result = 1
    monkeypatch.setattr(user32, "MapVirtualKeyExW", lambda *_args: 0)
    with pytest.raises(w6._InputInjectionError, match="no scan") as scan:
        w6._send_input_key(user32, wintypes, 456, ord("Q"), key_up=False)
    assert scan.value.receipt["scan"] == 0


def test_focus_already_visible_foreground_does_not_mutate_window(monkeypatch):
    user32 = _FakeFocusUser32(visible=True, foreground=100)
    _install_fake_focus(monkeypatch, user32)

    w6._focus_window(100, purpose="test")

    assert user32.calls == ["IsWindowVisible", "IsWindowEnabled", "GetForegroundWindow"]
    assert "ShowWindow" not in user32.calls
    assert "SetFocus" not in user32.calls


def test_focus_hidden_window_fails_without_showing_or_focusing(monkeypatch):
    user32 = _FakeFocusUser32(visible=False, foreground=999)
    _install_fake_focus(monkeypatch, user32)

    with pytest.raises(RuntimeError, match="hidden"):
        w6._focus_window(100, purpose="test")

    assert user32.calls == ["IsWindowVisible"]
    assert "ShowWindow" not in user32.calls
    assert "SetFocus" not in user32.calls


def test_focus_disabled_window_fails_without_focusing(monkeypatch):
    user32 = _FakeFocusUser32(visible=True, foreground=999, enabled=False)
    _install_fake_focus(monkeypatch, user32)

    with pytest.raises(RuntimeError, match="disabled"):
        w6._focus_window(100, purpose="test")

    assert user32.calls == ["IsWindowVisible", "IsWindowEnabled"]
    assert "SetForegroundWindow" not in user32.calls
    assert "SetFocus" not in user32.calls


def test_focus_nonforeground_visible_window_uses_focus_calls_but_never_showwindow(monkeypatch):
    user32 = _FakeFocusUser32(visible=True, foreground=999)
    _install_fake_focus(monkeypatch, user32)

    w6._focus_window(100, purpose="test")

    assert "BringWindowToTop" in user32.calls
    assert "SetForegroundWindow" in user32.calls
    assert "SetFocus" in user32.calls
    assert "ShowWindow" not in user32.calls


def test_ctrl_q_rejects_changed_window_state_before_sending(monkeypatch):
    user32 = _FakeUser32()
    _install_fake_input(monkeypatch, user32)
    monkeypatch.setattr(user32, "IsZoomed", lambda _hwnd: False)

    with pytest.raises(w6._InputDeliveryError, match="window state changed") as caught:
        w6._send_ctrl_q(100, expected_maximized=True)

    assert user32.events == []
    assert caught.value.evidence["expected_maximized"] is True
    assert caught.value.evidence["stages"][0]["window_maximized"] is False


def test_ctrl_q_refuses_preheld_modifier_without_sending(monkeypatch):
    user32 = _FakeUser32(held={0x10})  # Shift was already down before the probe.
    _install_fake_input(monkeypatch, user32)

    with pytest.raises(w6._InputDeliveryError) as caught:
        w6._send_ctrl_q(user32.hwnd)

    assert user32.events == []
    assert caught.value.evidence["stages"][0]["modifiers"]["Shift"] is True
    assert caught.value.evidence["released_probe_keys"] == {"Ctrl": False, "Q": False}


def test_ctrl_q_refuses_disabled_window_without_sending(monkeypatch):
    user32 = _FakeUser32(enabled=False)
    _install_fake_input(monkeypatch, user32)

    with pytest.raises(w6._InputDeliveryError) as caught:
        w6._send_ctrl_q(user32.hwnd)

    assert user32.events == []
    assert caught.value.evidence["stages"][0]["window_enabled"] is False


def test_ctrl_q_refuses_preheld_q_without_releasing_user_key(monkeypatch):
    user32 = _FakeUser32(held={ord("Q")})
    _install_fake_input(monkeypatch, user32)

    with pytest.raises(w6._InputDeliveryError) as caught:
        w6._send_ctrl_q(user32.hwnd)

    assert user32.events == []
    assert caught.value.evidence["stages"][0]["q_was_preheld"] is True
    assert caught.value.evidence["released_probe_keys"] == {"Ctrl": False, "Q": False}


def test_ctrl_q_lost_focus_after_ctrl_never_sends_q_and_releases_ctrl(monkeypatch):
    def lose_focus(user32, vk, flags):
        if (vk, flags) == (0x11, 0):
            user32.foreground = 999

    user32 = _FakeUser32(on_event=lose_focus)
    _install_fake_input(monkeypatch, user32)

    with pytest.raises(w6._InputDeliveryError) as caught:
        w6._send_ctrl_q(user32.hwnd)

    assert user32.events == [(0x11, 0), (0x11, 2)]
    assert caught.value.evidence["stages"][1]["foreground_is_target"] is False
    assert caught.value.evidence["released_probe_keys"] == {"Ctrl": True, "Q": False}


def test_ctrl_q_success_returns_json_safe_delivery_evidence(monkeypatch):
    user32 = _FakeUser32()
    _install_fake_input(monkeypatch, user32)

    evidence = w6._send_ctrl_q(user32.hwnd)

    assert evidence["outcome"] == "q_sent_with_target_foreground"
    assert [stage["stage"] for stage in evidence["stages"]] == [
        "before_ctrl_down", "after_ctrl_down_before_q", "after_q_down",
        "after_probe_key_release",
    ]
    assert all(set(stage["modifiers"]) == {"Ctrl", "Alt", "Shift", "Win"}
               for stage in evidence["stages"])
    assert user32.events == [(0x11, 0), (ord("Q"), 0), (ord("Q"), 2), (0x11, 2)]


def test_ctrl_q_key_exception_releases_probe_keys_and_preserves_evidence(monkeypatch):
    user32 = _FakeUser32(raise_on_event=lambda vk, flags: (vk, flags) == (ord("Q"), 0))
    _install_fake_input(monkeypatch, user32)

    with pytest.raises(w6._InputDeliveryError) as caught:
        w6._send_ctrl_q(user32.hwnd)

    assert user32.events == [(0x11, 0), (ord("Q"), 0), (ord("Q"), 2), (0x11, 2)]
    assert caught.value.evidence["released_probe_keys"] == {"Ctrl": True, "Q": True}
    assert caught.value.evidence["outcome"] == "invalid_input_delivery"


def test_ctrl_q_focus_change_after_q_is_recorded_but_not_immediately_rejected(monkeypatch):
    def lose_focus_after_q(user32, vk, flags):
        if (vk, flags) == (ord("Q"), 0):
            user32.foreground = 999

    user32 = _FakeUser32(on_event=lose_focus_after_q)
    _install_fake_input(monkeypatch, user32)

    evidence = w6._send_ctrl_q(user32.hwnd)

    assert evidence["outcome"] == "delivery_uncertain"
    assert evidence["focus_changed_after_q"] is True
    assert evidence["stages"][2]["foreground_is_target"] is False
    assert user32.events == [(0x11, 0), (ord("Q"), 0), (ord("Q"), 2), (0x11, 2)]
