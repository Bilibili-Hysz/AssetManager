"""Regression tests for the low-severity performance/crash-handler batch.

Covers:
  - Bug 14: measure() must not leak record() telemetry failures
  - Bug 15: recent() with a non-positive limit returns an empty snapshot
  - Bug 16: _redact() masks absolute paths and secret-shaped values
  - Bug 17: threading.excepthook is installed alongside sys.excepthook
  - Bug 18: repeated-crash detection annotates the log
"""
import sys
import threading
import time
from collections import deque
from types import SimpleNamespace

from AssetsManager.core import crash_handler
from AssetsManager.core.crash_handler import _redact
from AssetsManager.core.performance import PerformanceRecorder


# ── Bug 14: measure must not leak record() failures on the success path ─────


def test_measure_swallows_record_value_error_on_success_path(monkeypatch):
    recorder = PerformanceRecorder(enabled=True)

    def boom(*args, **kwargs):
        raise ValueError("telemetry exploded")

    monkeypatch.setattr(recorder, "record", boom)
    with recorder.measure("directory.list"):
        pass  # body succeeds — telemetry failure must not propagate
    assert recorder.recent() == ()


def test_measure_swallows_record_type_error_on_success_path(monkeypatch):
    recorder = PerformanceRecorder(enabled=True)

    def boom(*args, **kwargs):
        raise TypeError("telemetry exploded")

    monkeypatch.setattr(recorder, "record", boom)
    with recorder.measure("directory.list"):
        pass
    assert recorder.recent() == ()


# ── Bug 15: non-positive recent() limit yields nothing ──────────────────────


def test_recent_non_positive_limit_returns_empty_snapshot():
    recorder = PerformanceRecorder(enabled=True)
    recorder.record("a", 1)
    recorder.record("b", 2)

    assert recorder.recent(-1) == ()
    assert recorder.recent(0) == ()
    assert [e.name for e in recorder.recent()] == ["a", "b"]
    assert [e.name for e in recorder.recent(5)] == ["a", "b"]
    assert [e.name for e in recorder.recent(1)] == ["b"]


# ── Bug 16: _redact masks absolute paths and secret-shaped values ───────────


def test_redact_masks_windows_drive_path():
    message = r"Failed to open C:\Users\alice\AppData\Roaming\myapp\token.json"
    redacted = _redact(message)
    assert "C:\\Users" not in redacted
    assert "[path]" in redacted


def test_redact_masks_forward_slash_drive_path():
    redacted = _redact("No such file: 'C:/Users/bob/secret.pem'")
    assert "C:/Users" not in redacted
    assert "[path]" in redacted


def test_redact_masks_unc_path():
    redacted = _redact(r"Denied on \\server\share\config.db")
    assert "\\\\server" not in redacted
    assert "[path]" in redacted


def test_redact_masks_key_value_secrets():
    redacted = _redact("auth failed: token=abc123def456ghi, user=bob")
    assert "abc123def456ghi" not in redacted


def test_redact_masks_bearer_and_password_values():
    redacted = _redact("Bearer eyJhbGciOiJIUzI1NiJ9.payload password: hunter2")
    assert "eyJhbGciOiJIUzI1NiJ9" not in redacted
    assert "hunter2" not in redacted


def test_redact_keeps_plain_message_unchanged():
    message = "Query failed on column 'name'"
    assert _redact(message) == message


# ── Bug 17: threading.excepthook is installed and writes to disk ────────────


def test_install_sets_both_excepthooks():
    original_sys = sys.excepthook
    original_thread = threading.excepthook
    try:
        crash_handler.install()
        assert sys.excepthook is crash_handler._excepthook
        assert threading.excepthook is crash_handler._thread_excepthook
    finally:
        sys.excepthook = original_sys
        threading.excepthook = original_thread
        crash_handler._original_hook = None
        crash_handler._original_thread_hook = None


def test_thread_excepthook_writes_report_to_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(crash_handler, "SHARED_DIR", tmp_path)
    monkeypatch.setattr(crash_handler, "CRASH_LOG", tmp_path / "crash.log")
    monkeypatch.setattr(crash_handler, "_original_thread_hook", None)
    monkeypatch.setattr(crash_handler, "_crash_times", deque())
    monkeypatch.setattr(crash_handler, "_in_hook", False)

    args = SimpleNamespace(
        exc_type=ValueError,
        exc_value=ValueError("worker boom"),
        exc_traceback=None,
        thread=None,
    )
    crash_handler._thread_excepthook(args)

    assert crash_handler._in_hook is False
    content = (tmp_path / "crash.log").read_text(encoding="utf-8")
    assert "worker boom" in content
    assert "ValueError" in content


# ── Bug 18: repeated-crash detection annotates the log ──────────────────────


def test_note_crash_counts_until_threshold(monkeypatch):
    monkeypatch.setattr(crash_handler, "_crash_times", deque())
    results = [
        crash_handler._note_crash() for _ in range(crash_handler._CRASH_THRESHOLD)
    ]
    assert results == [False] * (crash_handler._CRASH_THRESHOLD - 1) + [True]


def test_note_crash_prunes_stale_entries(monkeypatch):
    stale = time.time() - crash_handler._CRASH_WINDOW_SECONDS - 1
    monkeypatch.setattr(crash_handler, "_crash_times", deque([stale] * 4))
    assert crash_handler._note_crash() is False
    assert len(crash_handler._crash_times) == 1


def test_repeated_crashes_annotate_log(tmp_path, monkeypatch):
    monkeypatch.setattr(crash_handler, "SHARED_DIR", tmp_path)
    monkeypatch.setattr(crash_handler, "CRASH_LOG", tmp_path / "crash.log")
    monkeypatch.setattr(crash_handler, "_crash_times", deque())
    monkeypatch.setattr(crash_handler, "_in_hook", False)
    monkeypatch.setattr(crash_handler, "_original_hook", None)

    for _ in range(crash_handler._CRASH_THRESHOLD):
        crash_handler._excepthook(RuntimeError, RuntimeError("boom"), None)

    content = (tmp_path / "crash.log").read_text(encoding="utf-8")
    assert content.count("CRASH:") == crash_handler._CRASH_THRESHOLD
    assert "Repeated crashes" in content
    assert len(crash_handler._crash_times) == crash_handler._CRASH_THRESHOLD


def test_log_without_marker_below_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(crash_handler, "SHARED_DIR", tmp_path)
    monkeypatch.setattr(crash_handler, "CRASH_LOG", tmp_path / "crash.log")
    monkeypatch.setattr(crash_handler, "_crash_times", deque())
    monkeypatch.setattr(crash_handler, "_in_hook", False)
    monkeypatch.setattr(crash_handler, "_original_hook", None)

    crash_handler._excepthook(RuntimeError, RuntimeError("single"), None)

    content = (tmp_path / "crash.log").read_text(encoding="utf-8")
    assert "Repeated crashes" not in content
