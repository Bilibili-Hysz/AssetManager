"""A4 desktop tests — crash notice dialog: report button and dispatch."""
from PySide6.QtWidgets import QApplication

from AssetsManager.app import (
    build_crash_report_dialog,
    launch_github_crash_report,
)
from AssetsManager.core import crash_handler
from AssetsManager.core.constants import APP_VERSION
from AssetsManager.i18n import tr


def _qapp():
    return QApplication.instance() or QApplication([])


_FAKE_LOG = (
    f"{'=' * 60}\n"
    "CRASH: 2026-08-31 10:00:00\n"
    "Type: RuntimeError\n"
    "Message: token=abcdef123456\n"
    "Traceback:\n"
    '  File "C:\\Users\\alice\\app.py", line 1, in main\n'
    f"{'=' * 60}\n"
)


def test_crash_report_dialog_has_ok_and_report_buttons():
    _qapp()
    box = build_crash_report_dialog(None)
    try:
        labels = [button.text() for button in box.buttons()]
        assert tr("crash.report_button") in labels
        assert len(labels) == 2
        # Identity handle for dispatch is wired.
        assert box.property("report_button") in box.buttons()
    finally:
        box.deleteLater()


def test_launch_github_crash_report_opens_sanitized_url(monkeypatch, tmp_path):
    _qapp()
    fake_log = tmp_path / "crash.log"
    fake_log.write_text(_FAKE_LOG, encoding="utf-8")
    monkeypatch.setattr(crash_handler, "CRASH_LOG", fake_log)

    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

    url = launch_github_crash_report()
    assert opened == [url]
    assert url.startswith(
        "https://github.com/Bilibili-Hysz/AssetManager/issues/new?")
    assert APP_VERSION in url
    from urllib.parse import parse_qs, urlsplit

    body = parse_qs(urlsplit(url).query)["body"][0]
    # Sanitized: secret-shaped token and absolute paths never leave the box.
    assert "abcdef123456" not in body
    assert "C:\\Users\\alice" not in body
    assert "[path]" in body
