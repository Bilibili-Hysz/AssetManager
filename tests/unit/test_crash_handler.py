"""Tests for core/crash_handler.py — global exception hook."""
import sys


class TestCrashHandler:

    def test_install_sets_excepthook(self):
        from AssetsManager.core.crash_handler import install, _excepthook
        original = sys.excepthook
        try:
            install()
            assert sys.excepthook is _excepthook
        finally:
            sys.excepthook = original

    def test_install_preserves_original(self):
        from AssetsManager.core.crash_handler import install
        original = sys.excepthook
        try:
            install()
            # After install, _original_hook should be set
            from AssetsManager.core import crash_handler
            assert crash_handler._original_hook is not None
        finally:
            sys.excepthook = original

    def test_install_idempotent(self):
        from AssetsManager.core.crash_handler import install, _excepthook
        original = sys.excepthook
        try:
            install()
            install()  # Should not raise
            assert sys.excepthook is _excepthook
        finally:
            sys.excepthook = original

    def test_crash_log_path(self):
        from AssetsManager.core.crash_handler import CRASH_LOG
        assert "crash.log" in str(CRASH_LOG)

    def test_max_size_constant(self):
        from AssetsManager.core.crash_handler import MAX_SIZE
        assert MAX_SIZE == 512 * 1024
