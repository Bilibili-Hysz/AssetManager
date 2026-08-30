"""Tests for core/crash_handler.py — global exception hook."""
import sys
from urllib.parse import parse_qs, urlsplit

from AssetsManager.core import crash_handler
from AssetsManager.core.constants import APP_VERSION


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


class TestGithubIssueUrl:
    """Opt-in report channel: URL construction from sanitized crash data."""

    def _build(self, traceback_text="ValueError: boom", **overrides):
        kwargs = dict(
            exc_type="ValueError",
            exc_message="boom with password: hunter2",
            traceback_text=traceback_text,
            app_version=APP_VERSION,
            platform_text="Windows-11-test",
            note="generated note",
        )
        kwargs.update(overrides)
        return crash_handler.build_github_issue_url(**kwargs)

    def test_url_shape_and_base(self):
        url = self._build()
        assert url.startswith(
            "https://github.com/Bilibili-Hysz/AssetManager/issues/new?")

    def test_query_roundtrip_contains_versions_and_os(self):
        url = self._build()
        query = parse_qs(urlsplit(url).query)
        body = query["body"][0]
        title = query["title"][0]
        assert APP_VERSION in body
        assert "Windows-11-test" in body
        assert APP_VERSION in title
        assert "ValueError" in title
        # Note is the last line of the body (auto-generation disclosure).
        assert body.rstrip().endswith("generated note")

    def test_secrets_and_paths_redacted_into_body(self):
        url = self._build(
            traceback_text="File opened from C:\\Users\\alice\\secret.txt")
        query = parse_qs(urlsplit(url).query)
        body = query["body"][0]
        assert "hunter2" not in body
        assert "C:\\Users\\alice" not in body
        assert "[path]" in body

    def test_encoding_roundtrip_preserves_text(self):
        message = "crash near sector & status=ok? yes <tag>"
        url = self._build(exc_message=message)
        query = parse_qs(urlsplit(url).query)
        assert f"Message: {message}" in query["body"][0]

    def test_huge_traceback_is_truncated_under_limit(self):
        huge = "\n".join(
            f'  File "C:\\app\\module_{i}.py", line {i}, in run' 
            for i in range(20000)
        )
        url = self._build(traceback_text=huge)
        assert len(url) <= crash_handler.MAX_REPORT_URL_LENGTH
        assert "truncated" in url

    def test_small_traceback_not_marked_truncated(self):
        url = self._build()
        assert "truncated" not in url


class TestCrashLogParsing:

    def _block(self, index):
        return (
            f"{'=' * 60}\n"
            f"CRASH: 2026-08-31 10:00:0{index}\n"
            f"Type: RuntimeError{index}\n"
            f"Message: attempt {index}\n"
            f"Traceback:\n"
            f'  File "app.py", line {index}, in main\n'
            f"{'=' * 60}\n"
        )

    def test_parse_last_block_wins(self):
        text = self._block(1) + self._block(2)
        parsed = crash_handler.parse_last_crash_summary(text)
        assert parsed == (
            "RuntimeError2",
            "attempt 2",
            '  File "app.py", line 2, in main',
        )

    def test_parse_without_traceback(self):
        text = (
            f"{'=' * 60}\n"
            "CRASH: 2026-08-31 10:00:00\n"
            "Type: KeyboardInterrupt\n"
            "Message: user abort\n"
            f"{'=' * 60}\n"
        )
        parsed = crash_handler.parse_last_crash_summary(text)
        assert parsed == ("KeyboardInterrupt", "user abort", "")

    def test_parse_unrecognized_text_returns_none(self):
        assert crash_handler.parse_last_crash_summary("garbage") is None

    def test_read_last_crash_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(crash_handler, "CRASH_LOG", tmp_path / "nope.log")
        assert crash_handler.read_last_crash() == ""

    def test_read_last_crash_tails_long_file(self, tmp_path, monkeypatch):
        log = tmp_path / "crash.log"
        log.write_text("x" * 100 + "TAIL", encoding="utf-8")
        monkeypatch.setattr(crash_handler, "CRASH_LOG", log)
        assert crash_handler.read_last_crash(limit=4) == "TAIL"
