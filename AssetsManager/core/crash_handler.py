"""Crash handler — global exception hooks for packaged builds.

Installs sys.excepthook and threading.excepthook overrides that write crash
dumps to RuntimeData/Shared/crash.log. Essential for console=False PyInstaller
builds where stderr is invisible.

Usage (in app.py, before QApplication.exec):
    from AssetsManager.core.crash_handler import install
    install()
"""
import re
import sys
import threading
import traceback
from collections import deque
from datetime import datetime
from time import time

from AssetsManager.core.path_resolver import SHARED_DIR

CRASH_LOG = SHARED_DIR / "crash.log"
MAX_SIZE = 512 * 1024  # 512 KB

# Repeated-crash guard: once more than _CRASH_THRESHOLD crashes land within a
# _CRASH_WINDOW_SECONDS window, reports are annotated so crash loops stand out.
# Diagnostic only — application behavior is unchanged.
_CRASH_WINDOW_SECONDS = 600  # 10 minutes
_CRASH_THRESHOLD = 5

_SENSITIVE_KEY_VALUE = re.compile(
    r"(\b(?:tokens?|secrets?|password|passwd|pwd|passphrase|"
    r"api[_-]?key|apikey|authorization|auth[_-]?header|credentials?|"
    r"access[_-]?key|private[_-]?key|client[_-]?secret|refresh[_-]?token|bearer|"
    r"access[_-]?token|id[_-]?token|session[_-]?token|client[_-]?token)\b"
    r"[^\s=:,]*\s*(?:=|:)\s*[\"']?)([^\"'\s,;)}\]]+(?:\s+[^\"'\s,;)}\]]+)?)",
    re.IGNORECASE,
)
_SENSITIVE_BEARER = re.compile(
    r"(\bBearer\s+)[A-Za-z0-9._\-+/=]{8,}",
    re.IGNORECASE,
)
_SENSITIVE_BASIC = re.compile(
    r"(\bBasic\s+)[A-Za-z0-9+/=]{8,}",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"\b(?:sk|pk|rk|ghp|gho|github_pat|AKIA|ya29|eyJ)[A-Za-z0-9._\-+/=]{12,}\b"
)
# Absolute paths (drive letter or UNC share) — e.g. "C:\Users\alice\...".
# The trailing-punctuation lookbehind keeps "(C:\data)" readable as "([path])".
_SENSITIVE_PATH = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\)"
    r"[A-Za-z0-9 _.\-\\/()\[\]{}]+(?<![\)\]])"
)


def _redact(text: str) -> str:
    """Mask common secret shapes and absolute paths in exception text."""
    if not text:
        return text
    redacted = _SENSITIVE_BEARER.sub(r"\1***", text)
    redacted = _SENSITIVE_BASIC.sub(r"\1***", redacted)
    redacted = _SENSITIVE_KEY_VALUE.sub(r"\1***", redacted)
    redacted = _SENSITIVE_VALUE.sub("***", redacted)
    redacted = _SENSITIVE_PATH.sub("[path]", redacted)
    return redacted


def _rotate_log() -> None:
    if CRASH_LOG.exists() and CRASH_LOG.stat().st_size > MAX_SIZE:
        old = CRASH_LOG.with_suffix(".log.old")
        try:
            if old.exists():
                old.unlink()
            CRASH_LOG.rename(old)
        except OSError:
            pass


def _note_crash() -> bool:
    """Record one crash timestamp; True when crashes are repeating."""
    now = time()
    while _crash_times and now - _crash_times[0] > _CRASH_WINDOW_SECONDS:
        _crash_times.popleft()
    _crash_times.append(now)
    return len(_crash_times) >= _CRASH_THRESHOLD


def _write_report(exc_type, exc_value, exc_tb) -> None:
    """Serialize one crash report to disk (may raise; callers guard)."""
    _rotate_log()
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{'=' * 60}",
        # Local time: this line is read by whoever is sitting at the machine
        # that crashed, alongside the OS's own local-time logs.
        f"CRASH: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",  # noqa: DTZ005
        f"Type: {exc_type.__name__ if exc_type else 'Unknown'}",
        f"Message: {_redact(str(exc_value))}",
    ]
    if exc_tb:
        lines.append("Traceback:")
        # Stack frames stay verbatim: secrets only appear in the message line,
        # and redacting frames would distort the diagnostics.
        lines.extend(traceback.format_tb(exc_tb))
    if _note_crash():
        lines.append(
            f"Repeated crashes: {len(_crash_times)} crashes "
            f"within {_CRASH_WINDOW_SECONDS // 60} minutes"
        )
    lines.append(f"{'=' * 60}\n")
    with open(CRASH_LOG, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _excepthook(exc_type, exc_value, exc_tb) -> None:
    """Write crash report to disk, then call original handler if any."""
    global _in_hook
    # Re-entrancy guard: an exception raised while formatting/writing the
    # report would re-enter sys.excepthook and recurse forever. Once we are
    # inside the hook, further invocations give up immediately.
    if _in_hook:
        return
    _in_hook = True
    try:
        try:
            _write_report(exc_type, exc_value, exc_tb)
        except Exception:
            # Hook-internal failures must never propagate: an exception here
            # re-enters sys.excepthook (this function) and would recurse.
            pass
        # Call original excepthook if available
        if _original_hook:
            _original_hook(exc_type, exc_value, exc_tb)
    finally:
        _in_hook = False


def _thread_excepthook(args) -> None:
    """Write worker-thread crash report to disk, then original hook."""
    global _in_hook
    # Same re-entrancy guard as _excepthook (both hooks share the flag).
    if _in_hook:
        return
    _in_hook = True
    try:
        try:
            _write_report(args.exc_type, args.exc_value, args.exc_traceback)
        except Exception:
            # Thread-hook failures must never propagate or recurse.
            pass
        if _original_thread_hook:
            _original_thread_hook(args)
    finally:
        _in_hook = False


_in_hook = False
_original_hook = None
_original_thread_hook = None
_crash_times: deque[float] = deque()


def install() -> None:
    """Install crash handlers for main and worker threads. Safe to call
    multiple times."""
    global _original_hook, _original_thread_hook
    if _original_hook is None:
        _original_hook = sys.excepthook
    sys.excepthook = _excepthook
    if _original_thread_hook is None:
        _original_thread_hook = threading.excepthook
    threading.excepthook = _thread_excepthook
