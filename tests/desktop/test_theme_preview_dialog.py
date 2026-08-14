"""Theme preview dialog tests — custom theme write-back and built-in read-only flow."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from AssetsManager.core import themes
from AssetsManager.core.theme_loader import ThemeLoader
from AssetsManager.dialogs.theme_preview_dialog import ThemePreviewDialog
from AssetsManager.widgets.theme_preview import ThemePreviewRenderer, ThemePreviewWidget

_REQUIRED_COLORS = {
    "base": "#1a1a1a", "panel": "#252525", "header": "#2d2d2d",
    "border": "#444444", "heading": "#e0e0e0", "body": "#c0c0c0",
    "muted": "#666666", "accent": "#4a60b0", "success": "#40b870",
    "warning": "#f5b040", "danger": "#f06060", "favorite": "#f0d060",
    "recent": "#70b8e0",
}


def _write_theme(path, name, *, dark=True, accent="#4a60b0", extra=None):
    data = {
        "name": name,
        "dark": dark,
        "description": f"{name} test theme",
        "colors": {**_REQUIRED_COLORS, "accent": accent},
        "properties": {"border_radius": {"sm": 8}},
    }
    if extra:
        data.update(extra)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


@pytest.fixture
def dialog_harness(tmp_path, monkeypatch):
    """Isolated loader with one built-in and one custom theme."""
    _write_theme(tmp_path / "D_navy.json", "Navy")
    _write_theme(
        tmp_path / "U_custom.json", "Custom", extra={"version": 1, "background": {"enabled": False}},
    )
    loader = ThemeLoader(themes_dir=str(tmp_path))
    loader.scan_directory()

    applied = []
    reloaded = []
    monkeypatch.setattr(themes, "_get_loader", lambda: loader)
    monkeypatch.setattr(themes, "set_theme", lambda name: applied.append(name))
    monkeypatch.setattr(themes, "reload_themes", lambda: reloaded.append(True))

    app = QApplication.instance() or QApplication([])
    dialog = ThemePreviewDialog()
    return app, dialog, loader, applied, reloaded


def _select_theme(dialog, name):
    for i in range(dialog._theme_list.count()):
        item = dialog._theme_list.item(i)
        if item and item.data(Qt.ItemDataRole.UserRole) == name:
            dialog._theme_list.setCurrentItem(item)
            return
    raise AssertionError(f"theme {name!r} not found in dialog list")


def test_apply_persists_edited_custom_theme(tmp_path, dialog_harness):
    app, dialog, loader, applied, reloaded = dialog_harness
    try:
        _select_theme(dialog, "Custom")
        assert dialog._current_theme_name == "Custom"
        assert not dialog._preview_is_dirty()

        dialog._preview.color_changed.emit("accent", "#d9952e")
        assert dialog._preview_is_dirty()

        dialog._on_apply()

        saved = json.loads((tmp_path / "U_custom.json").read_text(encoding="utf-8"))
        assert saved["colors"]["accent"] == "#d9952e"
        # Metadata outside colors/properties is preserved.
        assert saved["version"] == 1
        assert saved["background"] == {"enabled": False}
        assert applied == ["Custom"]
        assert reloaded == [True]
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_apply_builtin_with_dirty_edits_asks_before_discarding(
    tmp_path, dialog_harness, monkeypatch
):
    app, dialog, loader, applied, reloaded = dialog_harness
    questions = []

    def fake_question(*args, **kwargs):
        questions.append(args)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_question))
    builtin_before = (tmp_path / "D_navy.json").read_text(encoding="utf-8")

    try:
        _select_theme(dialog, "Navy")
        dialog._preview.color_changed.emit("accent", "#d9952e")
        assert dialog._preview_is_dirty()

        dialog._on_apply()

        assert len(questions) == 1
        assert (tmp_path / "D_navy.json").read_text(encoding="utf-8") == builtin_before
        assert applied == ["Navy"]
        assert reloaded == []
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_renderer_applies_every_loaded_theme():
    widget = ThemePreviewWidget()
    renderer = ThemePreviewRenderer()
    loader = themes._get_loader()

    for name in themes.names():
        raw = loader.get_theme(name)
        assert raw is not None
        flat = dict(raw.get("colors", {}))
        flat["properties"] = raw.get("properties", {})
        renderer.apply_theme(widget, flat)
        qss = widget.styleSheet()
        assert "QPushButton" in qss
        assert raw["colors"]["accent"] in qss
