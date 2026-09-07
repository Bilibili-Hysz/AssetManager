"""Regression tests for the low-priority window-framework fixes.

Covers:
- workspace restore resilience against non-string settings entries (C1)
- window geometry/maximized persistence helpers (A1)
The timer-dangling guards (A4/B1) use Shiboken.isValid and are not unit-tested.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton

import AssetsManager.window as window_module
from AssetsManager.widgets.workspace_bar import WorkspaceSection


def _app():
    return QApplication.instance() or QApplication([])


class _FakeSettings:
    """Duck-typed AppSettings stand-in: in-memory, no disk I/O."""

    def __init__(self):
        self._data = {}

    def set(self, key, value):
        self._data[key] = value

    def save(self):
        pass

    def get(self, key, default=None):
        return self._data.get(key, default)


def _patch_settings(monkeypatch, fake):
    monkeypatch.setattr(
        window_module.AppSettings, "instance", classmethod(lambda cls: fake)
    )


# ── C1: workspace restore resilience ─────────────────────────────


def test_restore_tabs_skips_non_string_entries(tmp_path):
    _app()
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    section = WorkspaceSection()
    try:
        section.restore_tabs([str(first), 123, None, {"a": 1}, str(second)])

        assert section.tab_paths() == [str(first.resolve()), str(second.resolve())]
        assert section.current_library() == str(second.resolve())
    finally:
        section.deleteLater()
        _app().processEvents()


def test_restore_tabs_skips_missing_paths_silently(tmp_path):
    _app()
    existing = tmp_path / "existing"
    existing.mkdir()

    section = WorkspaceSection()
    try:
        section.restore_tabs([str(tmp_path / "missing"), str(existing)])

        assert section.tab_paths() == [str(existing.resolve())]
    finally:
        section.deleteLater()
        _app().processEvents()


# ── A1: window geometry persistence ──────────────────────────────


def test_window_geometry_save_restore_round_trip(monkeypatch):
    _app()
    fake = _FakeSettings()
    _patch_settings(monkeypatch, fake)

    win = QMainWindow()
    win.resize(777, 555)
    before_size = win.size()
    window_module._save_window_geometry(win)
    win.deleteLater()

    restored = QMainWindow()
    window_module._restore_window_geometry(restored)
    # The size round-trips exactly; the reported position can shift by the
    # platform window-frame offset (decorations), so compare size only.
    assert restored.size() == before_size
    restored.deleteLater()
    _app().processEvents()


def test_save_window_geometry_records_maximized_flag_and_hex(monkeypatch):
    _app()
    fake = _FakeSettings()
    _patch_settings(monkeypatch, fake)

    win = QMainWindow()
    win.showMaximized()
    window_module._save_window_geometry(win)
    win.deleteLater()

    assert fake._data.get("window_maximized") is True
    geom = fake._data.get("window_geometry")
    assert isinstance(geom, str) and len(geom) > 0
    # The hex must decode and be a plausible QByteArray.
    assert len(bytes.fromhex(geom)) > 0


def test_restore_window_geometry_reapplies_maximized(monkeypatch):
    _app()
    fake = _FakeSettings()
    fake.set("window_maximized", True)
    _patch_settings(monkeypatch, fake)

    win = QMainWindow()
    window_module._restore_window_geometry(win)
    # PF-5: the restore no longer calls showMaximized() directly — during
    # MainWindow.__init__ the widget tree does not exist yet and the C-level
    # resize/show dispatch can abort the process. The flag is deferred;
    # the constructor applies it after _setup_ui().
    assert getattr(win, "_pending_maximized", False) is True
    assert not win.isMaximized()
    win.deleteLater()
    _app().processEvents()


def test_restore_window_geometry_unmaximized_sets_no_pending_flag(monkeypatch):
    _app()
    fake = _FakeSettings()
    fake.set("window_maximized", False)
    _patch_settings(monkeypatch, fake)

    win = QMainWindow()
    window_module._restore_window_geometry(win)
    assert not getattr(win, "_pending_maximized", False)
    win.deleteLater()
    _app().processEvents()


def test_restore_window_geometry_ignores_malformed_hex(monkeypatch):
    _app()
    fake = _FakeSettings()
    fake.set("window_geometry", "not-hex!!")
    _patch_settings(monkeypatch, fake)

    win = QMainWindow()
    window_module._restore_window_geometry(win)  # must not raise
    win.deleteLater()
    _app().processEvents()


def test_restore_window_geometry_ignores_non_string_geometry(monkeypatch):
    _app()
    fake = _FakeSettings()
    fake.set("window_geometry", 12345)
    _patch_settings(monkeypatch, fake)

    win = QMainWindow()
    window_module._restore_window_geometry(win)  # must not raise
    win.deleteLater()
    _app().processEvents()


def test_import_progress_dialog_cancel_and_window_close_signals():
    app = _app()
    dialog = window_module._ImportProgressDialog("working", "cancel", 0, 0)
    cancelled = []
    dialog.canceled.connect(lambda: cancelled.append(True))
    assert isinstance(dialog.findChild(QPushButton), QPushButton)
    dialog.findChild(QPushButton).click()
    assert cancelled == [True]
    dialog.deleteLater()

    dismissed = []
    dialog = window_module._ImportProgressDialog("working", "cancel", 0, 0)
    dialog.user_closed.connect(lambda: dismissed.append(True))
    dialog.close()
    app.processEvents()
    assert dismissed == [True]
    dialog.deleteLater()
    app.processEvents()


def test_main_window_import_cleanup_closes_pool_and_is_idempotent():
    class _Token:
        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    class _Pool:
        def __init__(self):
            self.calls = []

        def close(self, timeout_ms, *, owner_label):
            self.calls.append((timeout_ms, owner_label))
            return True

    token = _Token()
    pool = _Pool()
    window = SimpleNamespace(
        _import_generation=4,
        _import_token=token,
        _import_pool=pool,
        _import_task=object(),
        _import_dialog=None,
    )
    window.cleanup = window_module.MainWindow._cleanup_import.__get__(window)

    assert window.cleanup() is True
    assert token.cancelled is True
    assert pool.calls == [(3_000, "MainWindow import")]
    assert window._import_token is None
    assert window._import_pool is None
    assert window._import_task is None
    assert window.cleanup(4) is False
