"""Background image effects — blur, mosaic, and Kuwahara processing.

Effect design notes
-------------------
* All effects preserve the source dimensions exactly; callers scale the
  result to the window themselves.
* Very large sources are downscaled before the expensive pass so paintEvent
  stays interactive (see ``_cap_source_edge``).
* **Blur edge padding is mirror-reflection**, not plain tiling/wrap.  With
  wrap-around copies the blur halo of a bright feature near the image border
  samples *displaced* content at the seam, so the feature's visible glow
  slides (drifts by tens of pixels at high radius, measured).  Mirrored
  tiles are the true continuation of the local texture, which keeps the
  halo symmetric and the feature stationary as the radius changes.
"""
from __future__ import annotations

from array import array
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsScene, QGraphicsPixmapItem, QGraphicsBlurEffect

# Cap the longest source edge before the expensive blur pass. QGraphicsBlur
# cost grows with the number of pixels; a 4K wallpaper can freeze paintEvent
# for seconds. Blur is visually almost identical after downscaling because
# the caller scales the result to the window anyway — tradeoff: the radius is
# expressed in post-downscale pixels, so the blur looks slightly stronger
# relative to the original image.
_MAX_SOURCE_EDGE = 1280

# Kuwahara is a per-pixel quadrant filter: cost is O(pixels) with integral
# images, but the numpy path allocates several full-frame int64 buffers, and
# the pure-Python fallback is a slow pixel loop; a tighter cap keeps both
# fast enough for an on-demand, cached background effect.
_KUWAHARA_MAX_SOURCE_EDGE = 1024
_KUWAHARA_FALLBACK_EDGE = 640

if TYPE_CHECKING:
    # Type-check against numpy's own stubs; the try/except below would
    # otherwise type `np` as ModuleType | None and poison every np.* access.
    import numpy as np

    _HAS_NUMPY = True
else:
    try:
        import numpy as np

        _HAS_NUMPY = True
    except Exception:  # pragma: no cover - environment without numpy
        np = None
        _HAS_NUMPY = False


def _cap_source_edge(pixmap: QPixmap, cap: int) -> QPixmap:
    """Downscale so the longest edge is at most ``cap`` (aspect preserved)."""
    w, h = pixmap.width(), pixmap.height()
    if max(w, h) <= cap:
        return pixmap
    scale = cap / max(w, h)
    return pixmap.scaled(
        max(1, round(w * scale)), max(1, round(h * scale)),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _flipped(pixmap: QPixmap, horizontal: bool, vertical: bool) -> QPixmap:
    """Return a mirrored copy (QPixmap has no mirror API; QImage does)."""
    return QPixmap.fromImage(pixmap.toImage().mirrored(horizontal, vertical))


def _mirror_pad(pixmap: QPixmap, pad: int) -> QPixmap:
    """Extend a pixmap with mirror-reflected copies (BORDER_REFLECT style).

    The canvas is the source surrounded by 8 reflected tiles.  Blurring the
    canvas and cropping the centre gives edge pixels the same sampling
    environment as interior pixels: the halo stays symmetric and features do
    not drift when the blur radius changes (contrast with wrap-around tiles).
    """
    w, h = pixmap.width(), pixmap.height()
    padded = QPixmap(w + 2 * pad, h + 2 * pad)
    padded.fill(Qt.GlobalColor.transparent)
    painter = QPainter(padded)
    h_flip = _flipped(pixmap, True, False)
    v_flip = _flipped(pixmap, False, True)
    hv_flip = _flipped(pixmap, True, True)
    painter.drawPixmap(pad, pad, pixmap)
    painter.drawPixmap(pad - w, pad, h_flip)      # left
    painter.drawPixmap(pad + w, pad, h_flip)      # right
    painter.drawPixmap(pad, pad - h, v_flip)      # top
    painter.drawPixmap(pad, pad + h, v_flip)      # bottom
    painter.drawPixmap(pad - w, pad - h, hv_flip)  # top-left corner
    painter.drawPixmap(pad + w, pad - h, hv_flip)  # top-right corner
    painter.drawPixmap(pad - w, pad + h, hv_flip)  # bottom-left corner
    painter.drawPixmap(pad + w, pad + h, hv_flip)  # bottom-right corner
    painter.end()
    return padded


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

    pixmap = _cap_source_edge(pixmap, _MAX_SOURCE_EDGE)
    w, h = pixmap.width(), pixmap.height()

    pad = 2 * radius
    padded = _mirror_pad(pixmap, pad)

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


def apply_kuwahara(pixmap: QPixmap, radius: int) -> QPixmap:
    """Apply the Kuwahara filter: smooths flat areas, preserves edges.

    Classic Kuwahara: around every pixel, four overlapping square windows
    (quadrants of side ``radius + 1``, each with the pixel at one corner)
    are considered; the mean colour of the window with the lowest RGB
    variance is emitted.  Flat regions therefore average out (painterly
    look) while strong edges keep their boundary.

    Fast path uses numpy integral images (O(pixels)); a pure-Python integral
    image fallback keeps the effect working on installs without numpy (see
    ``_HAS_NUMPY``), at a reduced resolution cap.

    Args:
        pixmap: Source pixmap.
        radius: Quadrant half-size in pixels (1-50). Higher = smoother.

    Returns:
        New QPixmap with Kuwahara applied.
    """
    if radius < 1:
        return pixmap
    w, h = pixmap.width(), pixmap.height()
    if w == 0 or h == 0:
        return pixmap
    if _HAS_NUMPY:
        source = _cap_source_edge(pixmap, _KUWAHARA_MAX_SOURCE_EDGE)
        return _kuwahara_numpy(source, radius)
    source = _cap_source_edge(pixmap, _KUWAHARA_FALLBACK_EDGE)
    return _kuwahara_pure(source, radius)


def _kuwahara_numpy(pixmap: QPixmap, radius: int) -> QPixmap:
    """numpy implementation: 4-vectorized window queries on integral images."""
    img = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    # PySide6 6.11: bits()/constBits() hand out a memoryview over the buffer.
    # (Their declared return type is the wider bytes | bytearray | memoryview
    # union, but only memoryview exposes nbytes — see the cast below.)
    mv = cast("memoryview", img.bits())
    if mv.nbytes != img.sizeInBytes():
        raise ValueError("unexpected QImage buffer size")
    # ARGB32 memory order on little-endian is B,G,R,A — consistent both ways.
    view = np.frombuffer(mv, dtype=np.uint8, count=img.sizeInBytes()).reshape(h, w, 4)
    bgr = view[:, :, :3].astype(np.int64)
    alpha = view[:, :, 3].copy()

    side = radius + 1

    def integral(channels: np.ndarray) -> np.ndarray:
        acc = np.zeros((h + 1, w + 1, 3), dtype=np.int64)
        acc[1:, 1:, :] = channels
        np.cumsum(acc, axis=0, out=acc)
        np.cumsum(acc, axis=1, out=acc)
        return acc

    s = integral(bgr)
    s2 = integral(bgr * bgr)

    yy = np.arange(h)[:, None]
    xx = np.arange(w)[None, :]
    top = np.maximum(0, yy - side + 1)   # (h,1)
    left = np.maximum(0, xx - side + 1)  # (1,w)
    bottom_same = yy + 1
    right_same = xx + 1

    def rect(acc, top_r, left_c, bottom_r, right_c):
        return (
            acc[bottom_r, right_c]
            - acc[top_r, right_c]
            - acc[bottom_r, left_c]
            + acc[top_r, left_c]
        )

    windows = (
        # (top, left, bottom, right) with pixel at window corner
        (top, left, bottom_same, right_same),            # TL: pixel bottom-right
        (top, xx, bottom_same, np.minimum(w, xx + side)),  # TR
        (yy, left, np.minimum(h, yy + side), right_same),  # BL
        (yy, xx, np.minimum(h, yy + side), np.minimum(w, xx + side)),  # BR
    )

    sums: list[np.ndarray] = []
    variances: list[np.ndarray] = []
    for top_r, left_c, bottom_r, right_c in windows:
        total = rect(s, top_r, left_c, bottom_r, right_c)     # (h,w,3)
        total_sq = rect(s2, top_r, left_c, bottom_r, right_c)
        count = ((bottom_r - top_r) * (right_c - left_c)).astype(np.float64)[..., None]
        mean = total / count
        var = (total_sq / count - mean * mean).sum(axis=2)    # (h,w)
        sums.append(mean)
        variances.append(var)

    choice = np.argmin(np.stack(variances, axis=0), axis=0)  # (h,w)
    out = np.empty((h, w, 3), dtype=np.float64)
    for idx in range(4):
        mask = choice == idx
        out[mask] = sums[idx][mask]

    res = np.empty((h, w, 4), dtype=np.uint8)
    res[:, :, :3] = np.clip(out, 0, 255).astype(np.uint8)
    res[:, :, 3] = alpha
    qi = QImage(res.data, w, h, 4 * w, QImage.Format.Format_ARGB32)
    return QPixmap.fromImage(qi.copy())


def _kuwahara_pure(pixmap: QPixmap, radius: int) -> QPixmap:
    """Pure-Python fallback (no numpy): same algorithm, flat prefix arrays.

    Slower than the numpy path, so the caller caps the source at a lower
    edge (``_KUWAHARA_FALLBACK_EDGE``).  Runs once per effect change and is
    cached by the window, like every other background effect.
    """
    img = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()

    # QColor.getRgb() is typed `object` in the PySide6 stubs but always
    # returns a 4-tuple of ints at runtime.
    pixels = [
        list(cast("tuple[int, int, int, int]", img.pixelColor(x, y).getRgb()))
        for y in range(h) for x in range(w)
    ]

    def prefix(field: int) -> array:
        # acc[r*(w+1)+c] = sum of pixels with row < r and col < c.
        acc = array("q", [0]) * ((w + 1) * (h + 1))
        for y in range(h):
            row_sum = 0
            row_base = (y + 1) * (w + 1)
            prev_base = y * (w + 1)
            for x in range(w):
                row_sum += pixels[y * w + x][field]
                acc[row_base + x + 1] = acc[prev_base + x + 1] + row_sum
        return acc

    sums = [prefix(f) for f in range(3)]
    sumsq = [prefix(f) for f in range(3)]

    def rect(acc: array, x0: int, y0: int, x1: int, y1: int) -> int:
        # exclusive x1, y1; acc index = y*(w+1) + x
        return (
            acc[y1 * (w + 1) + x1]
            - acc[y0 * (w + 1) + x1]
            - acc[y1 * (w + 1) + x0]
            + acc[y0 * (w + 1) + x0]
        )

    side = radius + 1
    out = QImage(w, h, QImage.Format.Format_ARGB32)
    out.fill(Qt.GlobalColor.transparent)
    for y in range(h):
        y0_tl = max(0, y - side + 1)
        y1_br = min(h, y + side)
        for x in range(w):
            x0_tl = max(0, x - side + 1)
            x1_br = min(w, x + side)
            windows = (
                (x0_tl, y0_tl, x + 1, y + 1),
                (x, y0_tl, x1_br, y + 1),
                (x0_tl, y, x + 1, y1_br),
                (x, y, x1_br, y1_br),
            )
            best_var = None
            best_rgb = (0, 0, 0)
            for x0, y0, x1, y1 in windows:
                count = (x1 - x0) * (y1 - y0)
                r = rect(sums[0], x0, y0, x1, y1)
                g = rect(sums[1], x0, y0, x1, y1)
                b = rect(sums[2], x0, y0, x1, y1)
                r2 = rect(sumsq[0], x0, y0, x1, y1)
                g2 = rect(sumsq[1], x0, y0, x1, y1)
                b2 = rect(sumsq[2], x0, y0, x1, y1)
                mean_r, mean_g, mean_b = r / count, g / count, b / count
                var = (r2 / count - mean_r * mean_r
                       + g2 / count - mean_g * mean_g
                       + b2 / count - mean_b * mean_b)
                if best_var is None or var < best_var:
                    best_var = var
                    best_rgb = (int(mean_r), int(mean_g), int(mean_b))
            src = img.pixelColor(x, y)
            out.setPixelColor(x, y, QColor(*best_rgb, src.alpha()))
    return QPixmap.fromImage(out)