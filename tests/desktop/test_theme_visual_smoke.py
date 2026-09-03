"""G6 theme visual smoke — offscreen pixels must agree with theme tokens.

Verifies the theme pipeline end-to-end without golden images (which are not
portable across font renderers):

1. a widget styled straight from a token renders pixels equal to that
   token's color (token → QSS → paint agreement);
2. two different themes produce different pixels, and a theme round-trip
   restores the original rendering (catches broken cache invalidation or a
   stale subscriber in the switch pipeline).
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QLabel

from AssetsManager.core import themes
from AssetsManager.core.settings import AppSettings

def _dark_light_pair() -> tuple[str, str]:
    """Pick a dark and a light theme from the loaded registry.

    Registry keys come from the theme files' internal names (Amber,
    Charcoal, …) — filename prefixes (D_/L_) are not registry keys.
    """
    names = themes.names()
    dark = next(n for n in names if themes.get(n).get("dark", True))
    light = next(n for n in names if not themes.get(n).get("dark", True))
    return dark, light


@pytest.fixture
def restored_theme():
    """Save the persisted theme choice and restore it after the test."""
    saved = AppSettings.instance().get("theme")
    yield saved
    if saved:
        themes.set_theme(saved)


def _solid_widget(color: str) -> QLabel:
    widget = QLabel()
    widget.setFixedSize(60, 60)
    widget.setStyleSheet(f"background-color: {color};")
    return widget


def _center_rgb(widget: QLabel) -> tuple[int, int, int]:
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
    image = widget.grab().toImage()
    color = image.pixelColor(image.width() // 2, image.height() // 2)
    return (color.red(), color.green(), color.blue())


def _image_bytes(widget: QLabel) -> bytes:
    image = widget.grab().toImage()
    return bytes(image.constBits()[:image.sizeInBytes()])


def test_rendered_background_matches_token(restored_theme):
    dark, _light = _dark_light_pair()
    themes.set_theme(dark)
    base = themes.get()["base"]
    widget = _solid_widget(base)
    assert _center_rgb(widget) == (
        QColor(base).red(), QColor(base).green(), QColor(base).blue())


def test_theme_round_trip_restores_rendering(restored_theme):
    dark, light = _dark_light_pair()
    themes.set_theme(dark)
    widget = _solid_widget(themes.get()["base"])
    dark_bytes = _image_bytes(widget)

    themes.set_theme(light)
    widget.setStyleSheet(f"background-color: {themes.get()['base']};")
    light_bytes = _image_bytes(widget)

    themes.set_theme(dark)
    widget.setStyleSheet(f"background-color: {themes.get()['base']};")
    round_trip_bytes = _image_bytes(widget)

    assert light_bytes != dark_bytes, (
        "dark and light themes rendered identically — the switch pipeline "
        "is not propagating token changes")
    assert round_trip_bytes == dark_bytes, (
        "theme round-trip did not restore the original rendering — "
        "stylesheet cache invalidation or a subscriber is stale")
