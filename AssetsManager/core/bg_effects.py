"""Background image effects — blur and mosaic processing."""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsScene, QGraphicsPixmapItem, QGraphicsBlurEffect

# Cap the longest source edge before the expensive blur pass. QGraphicsBlur
# cost grows with the number of pixels; a 4K wallpaper can freeze paintEvent
# for seconds. Blur is visually almost identical after downscaling because
# the caller scales the result to the window anyway — tradeoff: the radius is
# expressed in post-downscale pixels, so the blur looks slightly stronger
# relative to the original image.
_MAX_SOURCE_EDGE = 1280


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

    # Downsample very large sources (e.g. 4K wallpapers) before the effect
    # pass so paintEvent stays interactive; see _MAX_SOURCE_EDGE above.
    if max(w, h) > _MAX_SOURCE_EDGE:
        scale = _MAX_SOURCE_EDGE / max(w, h)
        pixmap = pixmap.scaled(
            max(1, round(w * scale)), max(1, round(h * scale)),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        w, h = pixmap.width(), pixmap.height()

    pad = 2 * radius
    padded = QPixmap(w + 2 * pad, h + 2 * pad)
    padded.fill(Qt.GlobalColor.transparent)
    painter = QPainter(padded)
    for dx in (-pad, 0, pad):
        for dy in (-pad, 0, pad):
            painter.drawPixmap(pad + dx, pad + dy, pixmap)
    painter.end()

    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(padded)
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius)
    item.setGraphicsEffect(effect)
    scene.addItem(item)

    pw, ph = padded.width(), padded.height()
    result = QPixmap(pw, ph)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    scene.render(painter, QRectF(0, 0, pw, ph), QRectF(0, 0, pw, ph))
    painter.end()
    return result.copy(pad, pad, w, h)


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
