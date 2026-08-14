"""Regression tests for the low-priority dialog defect batch (group G).

Covers:
  - color_picker_dialog A3: _updating flag is exception-safe
  - sidebar_settings_dialog C1: out-of-range depth values are not clamped
  - plugin_manager_dialog E1/E3/E4: card body click, loadable dot, filter reselect
  - startup F1: non-string entries in recent_libraries do not crash
  - _share_api D2: non-JSON response bodies keep the HTTP status
"""
import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QScrollArea

from AssetsManager import i18n
from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.core.plugins.descriptor import (
    PLUGIN_STATE_ACTIVE,
    PLUGIN_STATE_LOADABLE,
    PluginDescriptor,
    PluginRecord,
)
from AssetsManager.dialogs._share_api import ShareApiTask
from AssetsManager.dialogs.color_picker_dialog import ColorPickerDialog
from AssetsManager.dialogs.plugin_manager_dialog import PluginCard, PluginManagerDialog
from AssetsManager.dialogs.sidebar_settings_dialog import SidebarSettingsDialog


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


# ── color_picker_dialog A3 ─────────────────────────────────────

def test_color_picker_updating_flag_restored_when_update_raises(monkeypatch):
    app = _app()
    dialog = ColorPickerDialog(QColor("#ff6b6b"))

    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    try:
        # _update_from_color: first widget update raises.
        monkeypatch.setattr(dialog._wheel, "set_color", boom)
        with pytest.raises(RuntimeError):
            dialog._update_from_color(QColor("#00ff00"))
        assert dialog._updating is False

        # _update_displays: a spinbox update raises mid-way.
        monkeypatch.setattr(dialog._h_spin[1], "setValue", boom)
        with pytest.raises(RuntimeError):
            dialog._update_displays()
        assert dialog._updating is False
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


# ── sidebar_settings_dialog C1 ─────────────────────────────────

def test_sidebar_settings_preserves_out_of_range_depth_values(tmp_path):
    app = _app()
    root = tmp_path / "root"
    (root / "branch-a").mkdir(parents=True)
    dialog = SidebarSettingsDialog(
        root_paths=[str(root)],
        global_depth=10,
        branch_depths={"branch-a": 20},
    )
    try:
        # Global depth spin shows the configured value instead of clamping to 5.
        assert dialog._global_depth.value() == 10
        assert dialog._global_depth.maximum() >= 10

        # Branch spinboxes do the same.
        spin = dialog._branch_spinboxes["branch-a"]
        assert spin.value() == 20
        assert spin.maximum() >= 20

        # Saving writes the original values back unchanged.
        result = dialog.result()
        assert result["global_depth"] == 10
        assert result["branch_depths"] == {"branch-a": 20}
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_sidebar_settings_branch_rows_show_name_and_folder_icon(tmp_path):
    """Each branch row keeps its name text next to the folder icon.

    Regression: a QLabel with both text and a pixmap only renders the
    pixmap, so the old single-label row showed an icon without a name.
    """
    app = _app()
    root = tmp_path / "root"
    (root / "alpha").mkdir(parents=True)
    (root / "beta").mkdir(parents=True)
    dialog = SidebarSettingsDialog(root_paths=[str(root)])
    try:
        labels = [
            label for label in dialog.findChildren(QLabel)
            if label.accessibleName() in {"alpha", "beta"}
        ]
        for name in ("alpha", "beta"):
            matching = [label for label in labels if label.accessibleName() == name]
            assert any(
                label.text() == name
                and (label.pixmap() is None or label.pixmap().isNull())
                for label in matching
            ), f"{name}: branch name label missing"
            assert any(
                label.text() == ""
                and label.pixmap() is not None
                and not label.pixmap().isNull()
                for label in matching
            ), f"{name}: folder icon label missing"
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_sidebar_settings_default_height_shows_branch_depth_controls(tmp_path):
    """The default dialog height keeps the Branch Depths section visible."""
    app = _app()
    root = tmp_path / "root"
    for name in ("alpha", "beta", "gamma", "delta"):
        (root / name).mkdir(parents=True)
    dialog = SidebarSettingsDialog(root_paths=[str(root)])
    try:
        dialog.show()
        app.processEvents()

        scroll = dialog.findChild(QScrollArea)
        reset_btn = next(
            button for button in dialog.findChildren(QPushButton)
            if button.text() == i18n.tr("sidebar_settings.reset")
        )
        assert scroll is not None
        assert scroll.isVisible()
        assert scroll.height() >= scaled_px(120)

        top_left = reset_btn.mapTo(dialog, QPoint(0, 0))
        assert top_left.y() >= 0
        assert top_left.y() + reset_btn.height() <= dialog.height()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


# ── plugin_manager_dialog E1 / E3 / E4 ─────────────────────────

def test_plugin_card_left_click_emits_clicked():
    app = _app()
    card = PluginCard("pid-1", "Name", "1.0", "desc", PLUGIN_STATE_ACTIVE, True)
    received = []
    card.clicked.connect(received.append)
    try:
        left = QMouseEvent(
            QEvent.Type.MouseButtonRelease, QPointF(5, 5), QPointF(5, 5),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        card.mouseReleaseEvent(left)
        assert received == ["pid-1"]

        # Non-left clicks must not select the card.
        right = QMouseEvent(
            QEvent.Type.MouseButtonRelease, QPointF(5, 5), QPointF(5, 5),
            Qt.MouseButton.RightButton, Qt.MouseButton.RightButton,
            Qt.KeyboardModifier.NoModifier,
        )
        card.mouseReleaseEvent(right)
        assert received == ["pid-1"]
    finally:
        card.deleteLater()
        app.processEvents()


def test_plugin_card_loadable_enabled_uses_green_dot():
    app = _app()
    card = PluginCard("pid-a", "A", "1.0", "", PLUGIN_STATE_LOADABLE, True)
    card_disabled = PluginCard("pid-b", "B", "1.0", "", PLUGIN_STATE_LOADABLE, False)
    try:
        t = themes.get()
        success = t.get("success", "#2ecc71")
        muted = t.get("muted", "#666666")
        assert success in card._status_dot.styleSheet()
        assert muted in card_disabled._status_dot.styleSheet()
    finally:
        card.deleteLater()
        card_disabled.deleteLater()
        app.processEvents()


def test_plugin_manager_filter_hides_selected_and_reselects_first_visible(monkeypatch):
    from AssetsManager.core.plugins.manager import PluginManagerService

    class _Manager:
        def __init__(self):
            self._records = {
                "one": PluginRecord(
                    plugin_id="one", root_dir="C:/plugins/one", manifest_path="one.json",
                    descriptor=PluginDescriptor("one", "One", "1.0"),
                    state=PLUGIN_STATE_ACTIVE, enabled=True,
                ),
                "two": PluginRecord(
                    plugin_id="two", root_dir="C:/plugins/two", manifest_path="two.json",
                    descriptor=PluginDescriptor("two", "Two", "2.0"),
                    state=PLUGIN_STATE_ACTIVE, enabled=True,
                ),
            }

        def plugin_record(self, plugin_id):
            return self._records.get(plugin_id)

        def enable_plugin(self, plugin_id):
            self._records[plugin_id].enabled = True

        def disable_plugin(self, plugin_id):
            self._records[plugin_id].enabled = False

    monkeypatch.setattr(PluginManagerService, "get", lambda: _Manager())
    app = _app()
    dialog = PluginManagerDialog()
    try:
        dialog._select_plugin("two")
        assert dialog._selected_plugin_id == "two"

        dialog._on_filter("one")  # hides "two"
        assert dialog._selected_plugin_id == "one"
        assert dialog._detail._current_pid == "one"
        assert dialog._cards["two"].isHidden()

        dialog._on_filter("")  # clearing the filter keeps the new selection
        assert dialog._selected_plugin_id == "one"
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


# ── startup F1 ─────────────────────────────────────────────────

def test_startup_window_tolerates_non_string_recent_libraries(monkeypatch):
    import warnings

    class _Settings:
        def __init__(self, paths):
            self._paths = paths

        def load(self):
            pass

        def get_list(self, key, default):
            return self._paths if key == "recent_libraries" else default

    monkeypatch.setattr(
        "AssetsManager.dialogs.startup.AppSettings.instance",
        classmethod(lambda _cls: _Settings([123, "x"])),
    )
    from AssetsManager.dialogs.startup import StartupWindow, _LibraryCard

    app = _app()
    window = StartupWindow()
    try:
        # Non-string entries are dropped instead of crashing on Path(123).
        assert len(window._cards) == 1
        assert all(isinstance(card, _LibraryCard) for card in window._cards)
        assert window._cards[0]._path == "x"
    finally:
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            window.close()
            window.deleteLater()
            app.processEvents()


# ── _share_api D2 ──────────────────────────────────────────────

def test_share_api_task_emits_status_dict_for_non_json_body(monkeypatch):
    response = Mock(status_code=200, content=b"<html>not json</html>")
    response.json.side_effect = ValueError("Expecting value")
    monkeypatch.setattr("requests.request", Mock(return_value=response))

    task = ShareApiTask("GET", "http://localhost/api/shares")
    results = []
    task.signals.finished.connect(lambda success, payload: results.append((success, payload)))

    task.run()

    assert len(results) == 1
    success, payload = results[0]
    assert success is False
    assert isinstance(payload, dict)
    assert payload["status"] == 200
    assert "error" in payload
