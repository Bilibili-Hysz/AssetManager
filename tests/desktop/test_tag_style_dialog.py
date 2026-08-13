"""Tests for the tag style editor dialog (gap G2-1)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit

from AssetsManager.dialogs.tag_style_dialog import TagStyleDialog


def test_tag_style_dialog_initial_values():
    app = QApplication.instance() or QApplication([])
    dialog = TagStyleDialog("hero", color="#ff0000", icon="star", category="character")
    try:
        assert dialog._tag == "hero"
        assert dialog._color == "#ff0000"
        assert dialog._category == "character"
        icon_combo = dialog.findChild(QComboBox)
        assert icon_combo is not None
        assert icon_combo.currentData() == "star"
        category_input = dialog.findChild(QLineEdit)
        assert category_input is not None
        assert category_input.text() == "character"
    finally:
        dialog.deleteLater()
        app.processEvents()


def test_tag_style_dialog_emits_saved_with_edited_values():
    app = QApplication.instance() or QApplication([])
    dialog = TagStyleDialog("hero")
    captured = []
    dialog.saved.connect(lambda t, c, i, cat: captured.append((t, c, i, cat)))
    try:
        dialog._color = "#00ff00"
        dialog._category_input.setText("work")
        dialog._on_ok()
        assert captured == [("hero", "#00ff00", "", "work")]
    finally:
        dialog.deleteLater()
        app.processEvents()


def test_tag_style_dialog_clear_color():
    app = QApplication.instance() or QApplication([])
    dialog = TagStyleDialog("hero", color="#ff0000")
    try:
        assert dialog._color == "#ff0000"
        dialog._clear_color()
        assert dialog._color == ""
    finally:
        dialog.deleteLater()
        app.processEvents()
