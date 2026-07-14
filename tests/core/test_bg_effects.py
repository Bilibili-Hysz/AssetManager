"""Tests for background image effects."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPixmap, QColor


def test_apply_blur_returns_pixmap():
    from AssetsManager.core.bg_effects import apply_blur
    pm = QPixmap(20, 20)
    pm.fill(QColor(255, 0, 0))
    result = apply_blur(pm, 2)
    assert isinstance(result, QPixmap)
    assert result.width() == 20
    assert result.height() == 20


def test_apply_blur_radius_zero_returns_original():
    from AssetsManager.core.bg_effects import apply_blur
    pm = QPixmap(10, 10)
    pm.fill(QColor(0, 128, 255))
    result = apply_blur(pm, 0)
    assert result.width() == 10


def test_apply_mosaic_returns_pixmap():
    from AssetsManager.core.bg_effects import apply_mosaic
    pm = QPixmap(50, 50)
    pm.fill(QColor(0, 255, 0))
    result = apply_mosaic(pm, 10)
    assert isinstance(result, QPixmap)
    assert result.width() == 50
    assert result.height() == 50


def test_apply_mosaic_preserves_dimensions():
    from AssetsManager.core.bg_effects import apply_mosaic
    pm = QPixmap(100, 80)
    pm.fill(QColor(255, 255, 0))
    result = apply_mosaic(pm, 20)
    assert result.width() == 100
    assert result.height() == 80


def test_apply_mosaic_small_block():
    from AssetsManager.core.bg_effects import apply_mosaic
    pm = QPixmap(20, 20)
    pm.fill(QColor(100, 100, 100))
    result = apply_mosaic(pm, 2)
    assert result.width() == 20
