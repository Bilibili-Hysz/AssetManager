"""Tests for the compact, accessible TagChip widget."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from AssetsManager.core import themes
from AssetsManager.widgets.tag_chip import create_tag_chip


def _relative_luminance(color: str) -> float:
    rgb = QColor(color).getRgbF()[:3]

    def linearize(channel: float) -> float:
        if channel <= 0.04045:
            return channel / 12.92
        return ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linearize(channel) for channel in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast_ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted(
        (_relative_luminance(foreground), _relative_luminance(background)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def test_tag_chip_uses_on_accent_foreground_and_accessible_contrast():
    app = QApplication.instance() or QApplication([])
    tokens = themes.get()
    chip = create_tag_chip("Landscape", on_remove=lambda _tag: None)
    chip.show()
    app.processEvents()
    try:
        label = chip.findChild(QLabel, "TagChipLabel")
        close_btn = chip.findChild(QPushButton, "TagChipClose")
        assert tokens["on_accent"] in label.styleSheet()
        assert tokens["on_accent"] in close_btn.styleSheet()
        assert _contrast_ratio(
            tokens["on_accent"], tokens["accent"]
        ) >= 4.5
        assert chip.accessibleName() == "Tag: Landscape"
        assert close_btn.accessibleName() == "Remove tag: Landscape"
    finally:
        chip.close()
        chip.deleteLater()
        app.processEvents()


def test_tag_chip_close_icon_uses_on_accent(monkeypatch):
    app = QApplication.instance() or QApplication([])
    captured = {}

    from AssetsManager.widgets import tag_chip

    original_icon = tag_chip.icons.icon

    def capture_icon(name, **kwargs):
        captured.update(name=name, **kwargs)
        return original_icon(name, **kwargs)

    monkeypatch.setattr(tag_chip.icons, "icon", capture_icon)
    chip = create_tag_chip("Portrait", on_remove=lambda _tag: None)
    try:
        assert captured["name"] == "close"
        assert captured["color"] == "icon_on_accent"
    finally:
        chip.close()
        chip.deleteLater()
        app.processEvents()


def test_tag_chip_remove_callback_keeps_tag_argument():
    app = QApplication.instance() or QApplication([])
    removed = []
    chip = create_tag_chip("Favorite", on_remove=removed.append)
    chip.show()
    app.processEvents()
    try:
        close_btn = chip.findChild(QPushButton, "TagChipClose")
        close_btn.click()
        assert removed == ["Favorite"]
    finally:
        chip.close()
        chip.deleteLater()
        app.processEvents()


def test_tag_chip_has_hover_and_visible_keyboard_focus_styles():
    app = QApplication.instance() or QApplication([])
    tokens = themes.get()
    chip = create_tag_chip("Keyboard", on_remove=lambda _tag: None)
    close_btn = chip.findChild(QPushButton, "TagChipClose")
    try:
        chip.show()
        app.processEvents()
        assert chip.focusPolicy() == chip.focusPolicy().NoFocus
        assert close_btn.focusPolicy() != close_btn.focusPolicy().NoFocus
        assert "QWidget#TagChip:hover" in chip.styleSheet()
        assert "QPushButton#TagChipClose:hover" in close_btn.styleSheet()
        assert "QPushButton#TagChipClose:focus" in close_btn.styleSheet()
        assert (
            f"border: 1px solid {tokens['on_accent']}"
            in close_btn.styleSheet()
        )
        assert "border: 1px solid transparent" in close_btn.styleSheet()

        close_btn.clearFocus()
        app.processEvents()
        normal = close_btn.grab().toImage()
        normal_bytes = bytes(normal.constBits()[:normal.sizeInBytes()])
        chip.activateWindow()
        close_btn.setFocus(Qt.FocusReason.TabFocusReason)
        app.processEvents()
        assert close_btn.hasFocus()
        focused = close_btn.grab().toImage()
        focused_bytes = bytes(focused.constBits()[:focused.sizeInBytes()])
        assert focused_bytes != normal_bytes

        QTest.mouseMove(close_btn, close_btn.rect().center())
        app.processEvents()
        assert close_btn.underMouse()
    finally:
        chip.close()
        chip.deleteLater()
        app.processEvents()
