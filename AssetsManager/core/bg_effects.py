"""Background image effects — blur and mosaic processing."""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsScene, QGraphicsPixmapItem, QGraphicsBlurEffect


def apply_blur(pixmap: QPixmap, radius: int) -> QPixmap:
    """Apply blur effect using Qt's QGraphicsBlurEffect.

    Args:
        pixmap: Source pixmap.
        radius: Blur radius in pixels (1-50). Higher = more blur.

    Returns:
        New QPixmap with blur applied.
    """
    if radius < 1:
        return pixmap
    w, h = pixmap.width(), pixmap.height()
    if w == 0 or h == 0:
        return pixmap

    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(pixmap)
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius)
    item.setGraphicsEffect(effect)
    scene.addItem(item)

    result = QPixmap(w, h)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    scene.render(painter, QRectF(0, 0, w, h), QRectF(0, 0, w, h))
    painter.end()
    return result


def apply_mosaic(pixmap: QPixmap, block_size: int) -> QPixmap:
    """Apply mosaic (pixelation) effect to a QPixmap.

    Args:
        pixmap: Source pixmap.
        block_size: Size of each mosaic block in pixels (2-50).

    Returns:
        New QPixmap with mosaic applied.
    """
    if block_size < 2:
        return pixmap
    w, h = pixmap.width(), pixmap.height()
    if w == 0 or h == 0:
        return pixmap
    small = pixmap.scaled(
        max(1, w // block_size), max(1, h // block_size),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
    return small.scaled(
        w, h,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
