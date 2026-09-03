"""Unit tests for DominantPaletteStrip widget."""
from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from AssetsManager.widgets.dominant_palette_strip import DominantPaletteStrip


def test_palette_strip_renders_swatches():
    _app = QApplication.instance() or QApplication([])
    colors = ["#ff5500", "#00aaff", "#22cc88"]
    strip = DominantPaletteStrip(colors)
    assert not strip.isHidden()
    assert len(strip._pill_buttons) == 3
    assert "#FF5500" in strip._pill_buttons[0].toolTip()


def test_palette_strip_caps_at_five_colors():
    _app = QApplication.instance() or QApplication([])
    colors = [f"#{i:02x}{i:02x}{i:02x}" for i in range(10, 80, 10)]
    assert len(colors) == 7
    strip = DominantPaletteStrip(colors)
    assert len(strip._pill_buttons) == 5


def test_palette_strip_click_copies_hex_and_emits_signal():
    _app = QApplication.instance() or QApplication([])
    strip = DominantPaletteStrip(["#e11d48"])
    emitted = []
    strip.color_clicked.connect(emitted.append)

    strip._pill_buttons[0].click()
    assert emitted == ["#e11d48"]
    assert QGuiApplication.clipboard().text() == "#E11D48"


def test_palette_strip_empty_hides():
    _app = QApplication.instance() or QApplication([])
    strip = DominantPaletteStrip(["#123456"])
    assert not strip.isHidden()
    strip.set_colors([])
    assert strip.isHidden()
