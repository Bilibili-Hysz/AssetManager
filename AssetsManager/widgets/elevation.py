"""Small, reusable elevation helpers for top-level desktop surfaces.

The helper intentionally targets a handful of container widgets instead of
individual list rows.  This keeps the visual hierarchy clear without adding a
large paint cost to scrolling views.
"""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

from AssetsManager.core.ui_scale import scaled_px


_LEVELS = {
    1: (18, 0, 4, 72),
    2: (24, 0, 8, 88),
    3: (30, 0, 12, 104),
}


def shadow_params(level: int = 1) -> tuple[int, int, int, int]:
    """Return ``(blur, offset_x, offset_y, alpha)`` for a depth level.

    Data-only counterpart to :func:`apply_elevation` for custom-painted
    widgets that cannot carry a QGraphicsEffect (e.g. the thumbnail grid
    canvas).  Custom painters must draw their shadows from these values so
    every surface in the app shares one depth vocabulary.
    """
    return _LEVELS.get(int(level), _LEVELS[1])


def apply_elevation(widget: QWidget, level: int = 1) -> QGraphicsDropShadowEffect:
    """Apply or update a theme-neutral shadow on a top-level surface.

    The returned effect is kept on the widget by Qt. Repeated calls update the
    existing effect instead of stacking multiple graphics effects.
    """
    blur, offset_x, offset_y, opacity = _LEVELS.get(int(level), _LEVELS[1])
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsDropShadowEffect):
        effect = QGraphicsDropShadowEffect(widget)
        widget.setGraphicsEffect(effect)

    effect.setBlurRadius(scaled_px(blur))
    effect.setOffset(scaled_px(offset_x), scaled_px(offset_y))
    effect.setColor(QColor(0, 0, 0, opacity))
    return effect


def refresh_elevation(widget: QWidget, level: int = 1) -> None:
    """Recalculate an existing surface shadow after a UI scale change."""
    effect = widget.graphicsEffect()
    if isinstance(effect, QGraphicsDropShadowEffect):
        apply_elevation(widget, level)
