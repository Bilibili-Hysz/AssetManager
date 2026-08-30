"""ActivityPanelDialog — offscreen panel behavior (H1-b E-C3).

The panel reads the library's real ``activity_log`` through a canonical
session (same table the LAN feed and the desktop recorders write), so these
tests cover the full read path: rows render newest-first, the day-range
filter drops old rows, empty libraries show the inline empty state, and read
failures degrade to the inline error hint instead of raising.
"""
import sqlite3
from time import time
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from AssetsManager import i18n
from AssetsManager.application.activity_recorder import ActivityRecorder
from AssetsManager.core.database import db_write_lock
from AssetsManager.dialogs.activity_panel import (
    _FILTER_30D,
    _FILTER_7D,
    _FILTER_ALL,
    _FILTER_TODAY,
    ActivityPanelDialog,
    _cutoff_timestamp,
)


@pytest.fixture(autouse=True)
def _chinese_ui():
    """Pin the UI language so the translated-label assertions are stable."""
    original = i18n.current_language()
    i18n.set_language("zh")
    yield
    i18n.set_language(original)


@pytest.fixture
def session(tmp_path):
    """One canonical library session with its activity_log table (v29)."""
    from AssetsManager.application.bootstrap import ApplicationBootstrap

    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    opened = bootstrap.library_service.open_session(tmp_path)
    try:
        yield opened
    finally:
        bootstrap.library_service.close_session(opened)
        app.processEvents()


def _dialog(session):
    return ActivityPanelDialog(session)


def _insert_row(session, *, action, details="", timestamp=None):
    conn = session.connection_for(session.root)
    with db_write_lock(conn):
        conn.execute(
            "INSERT INTO activity_log (username, action, details, ip, timestamp) "
            "VALUES (?, ?, ?, 'local', ?)",
            ("desktop", action, details, timestamp if timestamp is not None else time()),
        )
        conn.commit()


def test_panel_lists_recorded_rows_newest_first(session):
    app = QApplication.instance() or QApplication([])
    recorder = ActivityRecorder(lambda: session.connection_for(session.root))
    recorder.record("tag_add", "first row")
    recorder.record("file_delete", details="2 targets: a, b")

    dialog = _dialog(session)
    try:
        dialog.show()
        app.processEvents()

        assert dialog.windowTitle() == "活动日志"
        assert dialog._table.rowCount() == 2
        # Newest first: the second-recorded row leads.
        assert dialog._table.item(0, 1).text() == "file_delete"
        assert dialog._table.item(0, 3).text() == "2 targets: a, b"
        assert dialog._table.item(1, 1).text() == "tag_add"
        assert dialog._table.item(1, 2).text() == "desktop"
        assert dialog._status_label.text() == ""
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_day_filter_drops_rows_older_than_range(session):
    app = QApplication.instance() or QApplication([])
    _insert_row(session, action="fresh_action")
    _insert_row(session, action="stale_action", timestamp=time() - 40 * 24 * 60 * 60)

    dialog = _dialog(session)
    try:
        # Default filter is "last 7 days": only the fresh row shows.
        assert dialog._filter_combo.currentIndex() != _FILTER_ALL
        assert dialog._table.rowCount() == 1
        assert dialog._table.item(0, 1).text() == "fresh_action"

        # Switching to "all" reveals the stale row too.
        dialog._filter_combo.setCurrentIndex(_FILTER_ALL)
        app.processEvents()
        assert dialog._table.rowCount() == 2
        assert dialog._table.item(1, 1).text() == "stale_action"

        # Back to "today": the fresh row still shows, the 40-day-old one
        # stays hidden.
        dialog._filter_combo.setCurrentIndex(_FILTER_TODAY)
        app.processEvents()
        assert dialog._table.rowCount() == 1
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_empty_library_shows_inline_empty_state(tmp_path):
    from AssetsManager.application.bootstrap import ApplicationBootstrap

    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    opened = bootstrap.library_service.open_session(tmp_path)
    dialog = _dialog(opened)
    try:
        dialog.show()
        app.processEvents()

        assert dialog._table.rowCount() == 0
        assert dialog._status_label.text() == "所选范围内没有活动记录。"
    finally:
        dialog.close()
        dialog.deleteLater()
        bootstrap.library_service.close_session(opened)
        app.processEvents()


def test_read_failure_degrades_to_inline_hint(session):
    app = QApplication.instance() or QApplication([])
    dialog = _dialog(session)
    try:
        dialog.show()
        app.processEvents()
        assert dialog._table.rowCount() == 0

        # Point the panel at a session whose connection acquisition fails.
        dialog._session = SimpleNamespace(
            root=session.root,
            connection_for=lambda root: (_ for _ in ()).throw(
                RuntimeError("session closed")),
        )
        dialog._refresh()  # must not raise

        assert dialog._table.rowCount() == 0
        assert dialog._status_label.text() == "活动日志读取失败，数据表可能不可用。"
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_cutoff_timestamp_boundaries():
    now = 1_700_000_000.0
    assert _cutoff_timestamp(_FILTER_ALL, now=now) is None
    # "Today" cuts at local midnight of `now` (same naive-local convention
    # as the panel display).
    from datetime import datetime

    midnight = datetime.fromtimestamp(now).replace(  # noqa: DTZ006
        hour=0, minute=0, second=0, microsecond=0).timestamp()
    assert _cutoff_timestamp(_FILTER_TODAY, now=now) == midnight
    assert _cutoff_timestamp(_FILTER_7D, now=now) == pytest.approx(
        now - 7 * 24 * 60 * 60)
    assert _cutoff_timestamp(_FILTER_30D, now=now) == pytest.approx(
        now - 30 * 24 * 60 * 60)


def test_panel_uses_unmanaged_connection_for_plain_sqlite(tmp_path):
    """The read path also works against a plain migrated file database."""
    app = QApplication.instance() or QApplication([])
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import CURRENT_SCHEMA_VERSION, migrate

    db_path = tmp_path / "library.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(database._SCHEMA)
        assert migrate(conn) == CURRENT_SCHEMA_VERSION
        conn.execute(
            "INSERT INTO activity_log (username, action, details, ip, timestamp) "
            "VALUES ('desktop', 'plain_action', '', 'local', ?)",
            (time(),),
        )
        conn.commit()

        fake_session = SimpleNamespace(root=tmp_path, connection_for=lambda root: conn)
        dialog = _dialog(fake_session)
        try:
            dialog._filter_combo.setCurrentIndex(_FILTER_ALL)
            dialog._refresh()

            assert dialog._table.rowCount() == 1
            assert dialog._table.item(0, 1).text() == "plain_action"
        finally:
            dialog.close()
            dialog.deleteLater()
        app.processEvents()
    finally:
        conn.close()
