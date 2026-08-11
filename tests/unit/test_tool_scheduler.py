"""Unit tests for the tool scheduler argument handling."""
import pytest

from AssetsManager.core import tool_scheduler


def _run_tool_and_capture(monkeypatch, tool, **kwargs):
    """Run a tool, returning the command list passed to Popen."""
    calls = []

    class _FakePopen:
        def __init__(self, cmd, **kwargs):
            calls.append(cmd)

    monkeypatch.setattr(tool_scheduler.subprocess, "Popen", _FakePopen)
    tool_scheduler.run_tool(tool, **kwargs)
    return calls


def test_run_tool_normalizes_numeric_args(monkeypatch):
    calls = _run_tool_and_capture(
        monkeypatch,
        {"name": "Tool", "cmd": "tool.exe", "args": ["--port", 8080, "--workers", 4.5]})
    assert calls == [["tool.exe", "--port", "8080", "--workers", "4.5"]]


def test_run_tool_substitutes_placeholders_in_normalized_args(monkeypatch):
    calls = _run_tool_and_capture(
        monkeypatch,
        {"name": "Tool", "cmd": "tool.exe", "args": ["{file}", "--count", 2]},
        file_path="C:/tmp/a.txt")
    assert calls == [["tool.exe", "C:/tmp/a.txt", "--count", "2"]]


def test_run_tool_rejects_bool_args():
    with pytest.raises(ValueError, match="Invalid tool args"):
        tool_scheduler.run_tool(
            {"name": "Tool", "cmd": "tool.exe", "args": ["--debug", True]})


def test_run_tool_rejects_non_scalar_args():
    with pytest.raises(ValueError, match="Invalid tool args"):
        tool_scheduler.run_tool(
            {"name": "Tool", "cmd": "tool.exe", "args": [["--port", 8080]]})
