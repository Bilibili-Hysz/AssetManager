"""Crash handler — global exception hook for packaged builds.

Installs sys.excepthook override that writes crash dumps to
RuntimeData/Shared/crash.log. Essential for console=False PyInstaller
builds where stderr is invisible.

Usage (in app.py, before QApplication.exec):
    from AssetsManager.core.crash_handler import install
    install()
"""
import re
import sys
import traceback
from datetime import datetime

from AssetsManager.core.database import SHARED_DIR

CRASH_LOG = SHARED_DIR / "crash.log"
MAX_SIZE = 512 * 1024  # 512 KB

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


def _redact(text: str) -> str:
    """Mask common secret shapes in exception text while keeping it readable."""
    if not text:
        return text
    redacted = _SENSITIVE_BEARER.sub(r"\1***", text)
    redacted = _SENSITIVE_BASIC.sub(r"\1***", redacted)
    redacted = _SENSITIVE_KEY_VALUE.sub(r"\1***", redacted)
    redacted = _SENSITIVE_VALUE.sub("***", redacted)
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
            _rotate_log()
            SHARED_DIR.mkdir(parents=True, exist_ok=True)
            lines = [
                f"{'=' * 60}",
                f"CRASH: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"Type: {exc_type.__name__ if exc_type else 'Unknown'}",
                f"Message: {_redact(str(exc_value))}",
            ]
            if exc_tb:
                lines.append("Traceback:")
                lines.extend(_redact(line) for line in traceback.format_tb(exc_tb))
            lines.append(f"{'=' * 60}\n")
            with open(CRASH_LOG, "a", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception:
            # Hook-internal failures must never propagate: an exception here
            # re-enters sys.excepthook (this function) and would recurse.
            pass
        # Call original excepthook if available
        if _original_hook:
            _original_hook(exc_type, exc_value, exc_tb)
    finally:
        _in_hook = False


_in_hook = False
_original_hook = None


def install() -> None:
    """Install the crash handler. Safe to call multiple times."""
    global _original_hook
    if _original_hook is None:
        _original_hook = sys.excepthook
    sys.excepthook = _excepthook
