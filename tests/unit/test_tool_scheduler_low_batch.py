"""Low-priority batch: tool_scheduler and session_contract defect regressions.

Covers:
  - Bug 22: list_tools() read-only (no write side effect when tools.json
    is missing); set_tools() creates the file on first save
  - Bug 21: run_tool() timeout support — hung tools are terminated
    (kill as a fallback) while the default stays fire-and-forget
  - Bug 24: session_contract raises a neutral error message
"""
import json
import subprocess
import sys
import time

import pytest

from AssetsManager.core import session_contract
from AssetsManager.core import tool_scheduler


# ── Bug 22: list_tools() must not write tools.json ──────────────


def test_list_tools_missing_file_does_not_create_it(tmp_path, monkeypatch):
    tools_path = tmp_path / "tools.json"
    monkeypatch.setattr(tool_scheduler, "TOOLS_PATH", tools_path)

    tools = tool_scheduler.list_tools()

    assert tools == tool_scheduler.DEFAULT_TOOLS
    assert not tools_path.exists(), "read-only query must not touch the disk"


def test_set_tools_creates_file_on_first_save(tmp_path, monkeypatch):
    tools_path = tmp_path / "tools.json"
    monkeypatch.setattr(tool_scheduler, "TOOLS_PATH", tools_path)

    definition = [{"name": "App", "cmd": "app.exe", "args": ["{file}"]}]
    tool_scheduler.set_tools(definition)

    assert tools_path.exists()
    assert json.loads(tools_path.read_text(encoding="utf-8")) == definition
    # the write path is visible to the read path
    assert tool_scheduler.list_tools() == definition


def test_set_tools_rejects_non_list(tmp_path, monkeypatch):
    monkeypatch.setattr(tool_scheduler, "TOOLS_PATH", tmp_path / "tools.json")
    with pytest.raises(ValueError, match="tools must be a list"):
        tool_scheduler.set_tools({"name": "not-a-list"})


# ── Bug 21: run_tool timeout + termination ──────────────────────


def _record_popen(monkeypatch):
    """Patch Popen to record real instances while still spawning them."""
    real_popen = subprocess.Popen
    created = []

    def _recording_popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        created.append(proc)
        return proc

    monkeypatch.setattr(tool_scheduler.subprocess, "Popen", _recording_popen)
    return created


def test_run_tool_terminates_hung_process_on_timeout(monkeypatch):
    created = _record_popen(monkeypatch)
    tool = {"name": "hung", "cmd": sys.executable,
            "args": ["-c", "import time; time.sleep(30)"]}

    started = time.monotonic()
    result = tool_scheduler.run_tool(tool, timeout=0.5)
    elapsed = time.monotonic() - started

    assert result is None  # return contract unchanged
    assert created, "Popen must have been called"
    assert elapsed >= 0.4, "must actually wait before terminating"
    assert created[0].poll() is not None, "hung process must be terminated"


def test_run_tool_kill_fallback_after_terminate(monkeypatch):
    """Popen double that never exits: terminate() then kill() must both run."""
    instances = []

    class _HungPopen:
        def __init__(self, cmd, **kwargs):
            self.cmd = cmd
            self.pid = 4242
            self.terminate_calls = 0
            self.kill_calls = 0
            instances.append(self)

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(self.cmd, timeout)

        def terminate(self):
            self.terminate_calls += 1

        def kill(self):
            self.kill_calls += 1

    monkeypatch.setattr(tool_scheduler.subprocess, "Popen", _HungPopen)
    tool_scheduler.run_tool({"name": "hung", "cmd": "tool.exe", "args": []},
                            timeout=0.5)

    assert instances
    assert instances[0].terminate_calls == 1
    assert instances[0].kill_calls == 1


def test_run_tool_quick_command_completes_within_timeout(monkeypatch):
    created = _record_popen(monkeypatch)

    result = tool_scheduler.run_tool(
        {"name": "quick", "cmd": sys.executable, "args": ["-c", "pass"]},
        timeout=5.0)

    assert result is None
    assert created and created[0].returncode == 0


def test_run_tool_default_launch_does_not_wait(monkeypatch):
    """Default (no timeout) stays fire-and-forget: no wait/terminate calls."""

    class _NoWaitPopen:
        def __init__(self, cmd, **kwargs):
            self.pid = 1234

    calls = []

    def _fake_popen(cmd, **kwargs):
        calls.append(cmd)
        return _NoWaitPopen(cmd, **kwargs)

    monkeypatch.setattr(tool_scheduler.subprocess, "Popen", _fake_popen)

    tool_scheduler.run_tool(
        {"name": "app", "cmd": "app.exe", "args": ["{file}"]},
        file_path="C:/tmp/a.txt")

    assert calls == [["app.exe", "C:/tmp/a.txt"]]
    # The fake has no wait/terminate: if run_tool blocked on it, this test
    # would fail with AttributeError.


# ── Bug 24: session_contract neutral error message ──────────────


def test_require_library_session_neutral_error_message():
    with pytest.raises(TypeError) as excinfo:
        session_contract.require_library_session(object())
    assert "registered LibrarySession" in str(excinfo.value)
    assert "MetadataRepository" not in str(excinfo.value)


def test_require_library_session_accepts_registered_session():
    class _Session:
        pass

    session = _Session()
    session_contract.register_library_session(session)
    assert session_contract.require_library_session(session) is session
