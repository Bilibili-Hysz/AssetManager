"""H2-b broken-link card: scan renders, single/batch relink, refresh flow.

Mirrors test_settings_health.py: the real LibrarySettingsAdapter over a fake
session, offscreen Qt, event-loop pumping for the run_task completions. The
card lives on the settings dialog's maintenance tab; relinking must move the
metadata to the new path and then re-scan so the list refreshes itself.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from AssetsManager import i18n
from AssetsManager.application.library_settings_adapter import (
    LibrarySettingsAdapter,
)
from AssetsManager.core import database
from AssetsManager.core.db_migrations import migrate
from AssetsManager.dialogs.settings_dialog import SettingsDialog


def _session(tmp_path: Path, conn: sqlite3.Connection):
    lib = tmp_path / "library"
    lib.mkdir(exist_ok=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    return SimpleNamespace(
        root=lib,
        data_dir=data_dir,
        thumb_dir=data_dir / ".thumbnails",
        event_token="relink-session-token",
        is_closed=False,
        connection_for=lambda root=None: conn,
    )


def _conn(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        str(tmp_path / "assetmanager.db"), check_same_thread=False)
    conn.executescript(database._SCHEMA)
    migrate(conn)
    return conn


def _adapter(tmp_path: Path):
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


def _seed_lost_pair(conn, session, *, name="hero.png", size=100,
                    mtime=None, tag="art", notes="prod notes"):
    """Index one file that then gets moved outside the app.

    ``mtime`` overrides the index row's recorded mtime (simulating an editor
    rewriting the file after the move, which downgrades the pairing to the
    weak name+size rule). Returns ``(old_path, new_path)`` — the external
    move already happened when this helper returns.
    """
    lib = Path(session.root)
    old = lib / name
    old.write_bytes(b"A" * size)
    stat = old.stat()
    new = lib / "moved" / name
    new.parent.mkdir(exist_ok=True)
    os.rename(old, new)
    old_path = str(old.resolve())
    conn.execute(
        "INSERT INTO assets (file_path, name, extension, kind, size, mtime, "
        "parent_path, library_root) VALUES (?,?,?,?,?,?,?,?)",
        (old_path, name, ".png", "file", size,
         stat.st_mtime if mtime is None else mtime,
         str(lib.resolve()), str(lib.resolve())))
    conn.execute(
        "INSERT INTO file_meta (file_path, notes, rating) VALUES (?,?,?)",
        (old_path, notes, 4))
    conn.execute(
        "INSERT INTO file_tags (file_path, tag) VALUES (?,?)",
        (old_path, tag))
    conn.commit()
    return old_path, new


def _dialog(adapter):
    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog()
    dialog.set_library_settings_adapter(adapter)
    return app, dialog


def _wait_until(predicate, timeout=5.0):
    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _row_widgets(dialog):
    return [
        dialog._relink_list.itemWidget(dialog._relink_list.item(row))
        for row in range(dialog._relink_list.count())
    ]


def test_scan_renders_rows_and_single_relink_refreshes(tmp_path):
    original_language = i18n.current_language()
    i18n.set_language("en")
    adapter, session, conn = _adapter(tmp_path)
    old_path, new_path = _seed_lost_pair(conn, session)
    app, dialog = _dialog(adapter)
    try:
        dialog.show()
        app.processEvents()

        assert dialog._relink_group.title() == "Broken Links"
        assert dialog._relink_status.text().startswith("Not scanned yet.")
        assert dialog._relink_scan_btn.isEnabled()
        assert dialog._relink_list.isHidden()

        dialog._relink_scan_btn.click()
        assert dialog._relink_status.text() == "Scanning for broken links..."
        assert _wait_until(
            lambda: not dialog._relink_list.isHidden()
            and dialog._relink_list.count() == 1)

        row = _row_widgets(dialog)[0]
        assert old_path in row.path_label.text()
        assert str(new_path) in row.path_label.text()
        assert "→" in row.path_label.text()
        assert "High confidence" in row.path_label.text()
        assert row.relink_button is not None
        assert row.relink_button.text() == "Relink"
        # One high-confidence pair → batch button appears.
        assert not dialog._relink_all_btn.isHidden()
        assert dialog._relink_all_btn.isEnabled()

        row.relink_button.click()
        assert _wait_until(
            lambda: "Relinked 1 pair(s)." in dialog._relink_status.text())
        # The automatic re-scan refreshed the list: the pair is healed.
        assert _wait_until(
            lambda: "No broken links found." in dialog._relink_status.text())
        assert dialog._relink_list.count() == 0
        assert dialog._relink_all_btn.isHidden()

        moved = conn.execute(
            "SELECT file_path, notes, rating FROM file_meta").fetchall()
        assert moved == [(str(new_path.resolve()), "prod notes", 4)]
        index_rows = conn.execute(
            "SELECT file_path FROM assets").fetchall()
        assert index_rows == [(str(new_path.resolve()),)]
    finally:
        i18n.set_language(original_language)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_low_confidence_pair_has_no_batch_button_but_relinks_per_row(tmp_path):
    original_language = i18n.current_language()
    i18n.set_language("en")
    adapter, session, conn = _adapter(tmp_path)
    lib = Path(session.root)
    # Orphan whose newcomer shares name+size but not mtime (editor rewrite):
    # only the weak rule pairs it, so batch application must stay hidden.
    # The newcomer lives in a different directory — the old path stays
    # vacant so the row is genuinely lost.
    old = lib / "shot.png"
    old.write_bytes(b"B" * 50)
    conn.execute(
        "INSERT INTO assets (file_path, name, extension, kind, size, mtime, "
        "parent_path, library_root) VALUES (?,?,?,?,?,?,?,?)",
        (str(old.resolve()), "shot.png", ".png", "file", 50, 1000.0,
         str(lib.resolve()), str(lib.resolve())))
    conn.execute(
        "INSERT INTO file_meta (file_path, notes, rating) VALUES (?,?,?)",
        (str(old.resolve()), "keep", 2))
    conn.commit()
    os.unlink(old)
    moved_dir = lib / "moved"
    moved_dir.mkdir(exist_ok=True)
    newcomer = moved_dir / "shot.png"
    newcomer.write_bytes(b"C" * 50)

    app, dialog = _dialog(adapter)
    try:
        dialog.show()
        app.processEvents()
        dialog._relink_scan_btn.click()
        assert _wait_until(
            lambda: not dialog._relink_list.isHidden()
            and dialog._relink_list.count() == 1)

        row = _row_widgets(dialog)[0]
        assert "Low confidence" in row.path_label.text()
        assert dialog._relink_all_btn.isHidden()

        row.relink_button.click()
        assert _wait_until(
            lambda: "Relinked 1 pair(s)." in dialog._relink_status.text()
            and dialog._relink_list.count() == 0)
        assert conn.execute(
            "SELECT file_path, notes FROM file_meta").fetchall() == [
            (str(newcomer.resolve()), "keep")]
    finally:
        i18n.set_language(original_language)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_relink_all_applies_only_high_confidence_pairs(tmp_path):
    original_language = i18n.current_language()
    i18n.set_language("en")
    adapter, session, conn = _adapter(tmp_path)
    high_old, high_new = _seed_lost_pair(conn, session, name="high.png")
    low_old, low_new = _seed_lost_pair(
        conn, session, name="low.png", mtime=1000.0)
    app, dialog = _dialog(adapter)
    try:
        dialog.show()
        app.processEvents()
        dialog._relink_scan_btn.click()
        assert _wait_until(lambda: dialog._relink_list.count() == 2)
        badges = " | ".join(
            widget.path_label.text() for widget in _row_widgets(dialog))
        assert "High confidence" in badges
        assert "Low confidence" in badges

        dialog._relink_all_btn.click()
        assert _wait_until(
            lambda: "Relinked 1 pair(s)." in dialog._relink_status.text())
        # Refreshed list: the low-confidence pair stays for manual review.
        assert _wait_until(lambda: dialog._relink_list.count() == 1)
        remaining = _row_widgets(dialog)[0]
        assert "Low confidence" in remaining.path_label.text()
        assert low_old in remaining.path_label.text()

        conn_paths = sorted(
            row[0] for row in conn.execute("SELECT file_path FROM assets"))
        assert conn_paths == sorted([low_old, str(high_new.resolve())])
    finally:
        i18n.set_language(original_language)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_result_list_is_capped_and_says_so(tmp_path, monkeypatch):
    original_language = i18n.current_language()
    i18n.set_language("en")
    import AssetsManager.dialogs.settings_dialog as settings_module
    monkeypatch.setattr(settings_module, "_RELINK_ROW_LIMIT", 2)
    adapter, session, conn = _adapter(tmp_path)
    for index in range(3):
        _seed_lost_pair(conn, session, name=f"file{index}.png",
                        size=10 + index)
    app, dialog = _dialog(adapter)
    try:
        dialog.show()
        app.processEvents()
        dialog._relink_scan_btn.click()
        assert _wait_until(lambda: dialog._relink_list.count() == 2)
        assert "Showing first 2 rows only." in dialog._relink_status.text()
        assert all(
            widget.relink_button is not None
            for widget in _row_widgets(dialog))
    finally:
        i18n.set_language(original_language)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
        monkeypatch.undo()


def test_relink_buttons_disabled_without_adapter():
    original_language = i18n.current_language()
    try:
        i18n.set_language("en")
        app = QApplication.instance() or QApplication([])
        dialog = SettingsDialog()
        try:
            assert dialog._relink_status.text().startswith("Not scanned yet.")
            assert not dialog._relink_scan_btn.isEnabled()
            assert not dialog._relink_all_btn.isEnabled()
        finally:
            dialog.close()
            dialog.deleteLater()
            app.processEvents()
    finally:
        i18n.set_language(original_language)
