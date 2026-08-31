"""H2-a1 library health card: field rendering, refresh updates, warning coloring.

The card lives on the settings dialog's maintenance tab and collects its
metrics on a worker thread (run_task) with the real LibrarySettingsAdapter
over a fake session — mirroring test_settings_maintenance.py's adapter
approach while exercising the new observation surface.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shutil
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from AssetsManager import i18n
from AssetsManager.application.library_governance import (
    LibraryHealthSnapshot,
    _DAY_SECONDS,
)
from AssetsManager.application.library_settings_adapter import (
    LibrarySettingsAdapter,
)
from AssetsManager.core.constants import (
    THUMBNAIL_CACHE_WARNING_BYTES,
    WAL_FILE_WARNING_BYTES,
)
from AssetsManager.dialogs.settings_dialog import SettingsDialog


def _session(tmp_path: Path, conn: sqlite3.Connection):
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    session = SimpleNamespace(
        root=tmp_path / "library",
        data_dir=data_dir,
        thumb_dir=data_dir / ".thumbnails",
        event_token="health-session-token",
        is_closed=False,
        connection_for=lambda root=None: conn,
    )
    session.root.mkdir(exist_ok=True)
    return session


def _conn(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        str(tmp_path / "assetmanager.db"), check_same_thread=False)
    conn.execute(
        "CREATE TABLE activity_log (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "username TEXT NOT NULL DEFAULT 'guest', action TEXT NOT NULL, "
        "details TEXT NOT NULL DEFAULT '', ip TEXT NOT NULL DEFAULT 'unknown', "
        "timestamp REAL NOT NULL)")
    conn.execute("CREATE TABLE assets (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE library_favorites (id INTEGER PRIMARY KEY)")
    return conn


def _adapter(tmp_path: Path):
    """Real LibrarySettingsAdapter over a faked scoped-services bundle."""
    conn = _conn(tmp_path)
    session = _session(tmp_path, conn)
    services = SimpleNamespace(
        session=session,
        integrity_service=SimpleNamespace(
            running=False, last_report=None, last_schedule_error=None),
        maintenance_service=SimpleNamespace(
            running=False, last_result=None, last_schedule_error=None),
    )
    return LibrarySettingsAdapter(services), session, conn


def _prefill(session, conn):
    """Seed files and rows so every health metric has a value."""
    (session.data_dir / "assetmanager.db").write_bytes(b"0" * 2048)
    (session.data_dir / "assetmanager.db-wal").write_bytes(b"0" * 4096)
    thumbs = session.thumb_dir
    thumbs.mkdir()
    (thumbs / "a.webp").write_bytes(b"0" * 512)
    (thumbs / "b.webp").write_bytes(b"0" * 512)
    derivatives = session.data_dir / "derivatives"
    (derivatives / "poster").mkdir(parents=True)
    (derivatives / "poster" / "c.webp").write_bytes(b"0" * 256)
    now = time.time()
    conn.execute(
        "INSERT INTO activity_log (action, timestamp) VALUES ('old', ?)",
        (now - 2.0 * _DAY_SECONDS,))
    conn.execute(
        "INSERT INTO activity_log (action, timestamp) VALUES ('new', ?)", (now,))
    conn.execute("INSERT INTO assets DEFAULT VALUES")
    conn.execute("INSERT INTO assets DEFAULT VALUES")
    conn.execute("INSERT INTO assets DEFAULT VALUES")
    conn.execute("INSERT INTO library_favorites DEFAULT VALUES")
    conn.execute("INSERT INTO library_favorites DEFAULT VALUES")
    conn.commit()


def _dialog(adapter):
    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog()
    dialog.set_library_settings_adapter(adapter)
    return app, dialog


def _wait_until(dialog, predicate, timeout=5.0):
    """Pump the event loop until the queued run_task completion lands."""
    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_health_card_renders_all_fields_and_refresh_updates(tmp_path):
    original_language = i18n.current_language()
    i18n.set_language("en")
    adapter, session, conn = _adapter(tmp_path)
    _prefill(session, conn)
    app, dialog = _dialog(adapter)
    try:
        dialog.show()
        app.processEvents()

        assert dialog._health_group.title() == "Library Health"
        assert dialog._health_status.text() == "Health info not collected yet."
        assert dialog._health_refresh_btn.isEnabled()
        assert dialog._health_open_dir_btn.isEnabled()

        dialog._health_refresh_btn.click()
        assert dialog._health_status.text() == "Collecting health info..."
        assert _wait_until(
            dialog,
            lambda: "Database:" in dialog._health_status.text(),
        )

        text = dialog._health_status.text()
        assert "Database: 2.0 KB (WAL 4.0 KB)" in text
        assert "Thumbnail cache: 1.0 KB (2 files)" in text
        assert "Derivatives: 256 B (1 files)" in text
        assert "Activity log: 2 rows (oldest 2.0 days ago, kept 90 days)" in text
        assert "Favorites: 2" in text
        assert "Asset index: 3 rows" in text

        # A refresh after new data lands updates the observed numbers.
        (session.thumb_dir / "d.webp").write_bytes(b"0" * 256)
        conn.execute("INSERT INTO assets DEFAULT VALUES")
        conn.commit()
        dialog._health_refresh_btn.click()
        assert _wait_until(
            dialog,
            lambda: "Thumbnail cache: 1.2 KB (3 files)" in dialog._health_status.text(),
        )
        assert "Asset index: 4 rows" in dialog._health_status.text()
    finally:
        i18n.set_language(original_language)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_health_card_threshold_warning_coloring(tmp_path, monkeypatch):
    original_language = i18n.current_language()
    i18n.set_language("en")
    adapter, _session_obj, _conn_obj = _adapter(tmp_path)
    app, dialog = _dialog(adapter)
    try:
        dialog.show()
        app.processEvents()

        # Threshold semantics live on the snapshot: at/above → warning token.
        over = LibraryHealthSnapshot(
            db_bytes=1, wal_bytes=WAL_FILE_WARNING_BYTES,
            thumbnail_bytes=THUMBNAIL_CACHE_WARNING_BYTES)
        under = LibraryHealthSnapshot(
            db_bytes=1, wal_bytes=WAL_FILE_WARNING_BYTES - 1,
            thumbnail_bytes=THUMBNAIL_CACHE_WARNING_BYTES - 1)
        assert over.warnings == ("wal", "thumbnail_cache")
        assert under.warnings == ()

        def _collect(self):
            return LibraryHealthSnapshot(
                db_bytes=1, wal_bytes=WAL_FILE_WARNING_BYTES,
                thumbnail_bytes=THUMBNAIL_CACHE_WARNING_BYTES,
                activity_rows=5, favorites_count=1, asset_rows=2)

        monkeypatch.setattr(LibrarySettingsAdapter, "collect_health_snapshot", _collect)
        dialog._health_refresh_btn.click()
        assert _wait_until(
            dialog,
            lambda: 'style="color:' in dialog._health_status.text(),
        )
        text = dialog._health_status.text()
        # Both over-threshold rows carry the theme warning color; the other
        # rows stay plain.
        assert text.count('style="color:') == 2
        assert "Derivatives: 0 B (0 files)" in text
    finally:
        i18n.set_language(original_language)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
        monkeypatch.undo()


def test_open_data_dir_opens_existing_directory(tmp_path, monkeypatch):
    original_language = i18n.current_language()
    i18n.set_language("en")
    adapter, session, _conn_obj = _adapter(tmp_path)
    app, dialog = _dialog(adapter)
    opened = []
    monkeypatch.setattr(
        QDesktopServices, "openUrl",
        staticmethod(lambda url: opened.append(url.toLocalFile()) or True))
    try:
        dialog.show()
        app.processEvents()
        assert dialog._health_open_dir_btn.isEnabled()

        dialog._health_open_dir_btn.click()
        assert [Path(p) for p in opened] == [session.data_dir]

        # A vanished data directory disables the button via the refresh path.
        shutil.rmtree(session.data_dir)
        dialog._refresh_maintenance_status()
        assert not dialog._health_open_dir_btn.isEnabled()
    finally:
        i18n.set_language(original_language)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
        monkeypatch.undo()


def test_health_card_without_adapter_disables_buttons():
    original_language = i18n.current_language()
    try:
        i18n.set_language("en")
        app = QApplication.instance() or QApplication([])
        dialog = SettingsDialog()
        try:
            assert dialog._health_status.text() == "Health info not collected yet."
            assert not dialog._health_refresh_btn.isEnabled()
            assert not dialog._health_open_dir_btn.isEnabled()
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()
    finally:
        i18n.set_language(original_language)


def test_collect_library_health_degrades_independently(tmp_path):
    """A missing table or file never hides the other metrics."""
    adapter, session, conn = _adapter(tmp_path)
    _prefill(session, conn)
    conn.execute("DROP TABLE library_favorites")
    conn.commit()
    (session.data_dir / "assetmanager.db-wal").unlink()

    snapshot = adapter.collect_health_snapshot()

    assert snapshot.db_bytes == 2048
    assert snapshot.wal_bytes is None
    assert snapshot.thumbnail_bytes == 1024
    assert snapshot.thumbnail_files == 2
    assert snapshot.derivatives_bytes == 256
    assert snapshot.derivatives_files == 1
    assert snapshot.activity_rows == 2
    assert snapshot.activity_oldest_age_days is not None
    assert snapshot.favorites_count is None
    assert snapshot.asset_rows == 3


def test_collect_library_health_handles_dead_connection(tmp_path):
    adapter, session, conn = _adapter(tmp_path)
    _prefill(session, conn)
    conn.close()
    snapshot = adapter.collect_health_snapshot()
    assert snapshot.activity_rows is None
    assert snapshot.favorites_count is None
    assert snapshot.asset_rows is None
    # Filesystem metrics are still collected.
    assert snapshot.thumbnail_files == 2


def test_prune_activity_button_reports_deleted_rows(tmp_path):
    """H2-a3: the manual prune entry runs through the maintenance runner."""
    original_language = i18n.current_language()
    i18n.set_language("en")
    adapter, session, _conn_obj = _adapter(tmp_path)
    _prefill(session, _conn_obj)
    recorder = SimpleNamespace(prune=Mock(return_value=7))
    adapter._services.file_operation_service = SimpleNamespace(
        activity_recorder=recorder)
    app, dialog = _dialog(adapter)
    try:
        dialog.show()
        app.processEvents()

        assert dialog._health_prune_btn.text() == "Clean Up Expired Activity"
        assert dialog._health_prune_btn.isEnabled()

        dialog._health_prune_btn.click()
        assert _wait_until(
            dialog,
            lambda: "Pruned 7 activity rows." in dialog._health_status.text(),
        )
        # The manual entry relies on the recorder's retention default (90 d).
        recorder.prune.assert_called_once_with()
        assert dialog._health_prune_btn.isEnabled()
    finally:
        i18n.set_language(original_language)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_prune_activity_disabled_without_adapter():
    original_language = i18n.current_language()
    try:
        i18n.set_language("en")
        app = QApplication.instance() or QApplication([])
        dialog = SettingsDialog()
        try:
            assert not dialog._health_prune_btn.isEnabled()
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()
    finally:
        i18n.set_language(original_language)
