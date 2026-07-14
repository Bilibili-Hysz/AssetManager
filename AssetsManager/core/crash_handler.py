"""Crash handler — global exception hook for packaged builds.

Installs sys.excepthook override that writes crash dumps to
RuntimeData/Shared/crash.log. Essential for console=False PyInstaller
builds where stderr is invisible.

Usage (in app.py, before QApplication.exec):
    from AssetsManager.core.crash_handler import install
    install()
"""
import sys
import traceback
from datetime import datetime

from AssetsManager.core.database import SHARED_DIR

CRASH_LOG = SHARED_DIR / "crash.log"
MAX_SIZE = 512 * 1024  # 512 KB


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
    try:
        _rotate_log()
        SHARED_DIR.mkdir(parents=True, exist_ok=True)
        lines = [
            f"{'=' * 60}",
            f"CRASH: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Type: {exc_type.__name__ if exc_type else 'Unknown'}",
            f"Message: {exc_value}",
        ]
        if exc_tb:
            lines.append("Traceback:")
            lines.extend(traceback.format_tb(exc_tb))
        lines.append(f"{'=' * 60}\n")
        with open(CRASH_LOG, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except OSError:
        pass
    # Call original excepthook if available
    if _original_hook:
        _original_hook(exc_type, exc_value, exc_tb)


_original_hook = None


def install() -> None:
    """Install the crash handler. Safe to call multiple times."""
    global _original_hook
    if _original_hook is None:
        _original_hook = sys.excepthook
    sys.excepthook = _excepthook
