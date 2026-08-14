"""HSV color wheel and brightness slider for color picker."""
from __future__ import annotations

import math
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QColor, QPainter, QLinearGradient, QRadialGradient, QPixmap
from PySide6.QtWidgets import QWidget, QSizePolicy
from AssetsManager.core.ui_scale import scaled_px


def _pos_to_hue(dx: float, dy: float) -> float:
    """Map a wheel offset (from the wheel center) to a hue in [0, 1).

    Standard math convention: 0 at 3 o'clock, increasing counterclockwise
    on screen, so 12 o'clock (dy negative) is 0.25.  This is the inverse of
    ``_hue_to_angle`` and matches how the ring is painted, so a click
    selects exactly the color shown under the cursor.
    """
    angle = math.degrees(math.atan2(-dy, dx)) % 360
    return angle / 360.0


def _hue_to_angle(hue: float) -> float:
    """Map a hue in [0, 1) back to the wheel angle in degrees (0 at 3 o'clock)."""
    return hue * 360.0


class HSVWheel(QWidget):
    """Circular HSV color wheel — click/drag to select hue + saturation."""

    color_changed = Signal(QColor)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hue = 0.0
        self._saturation = 1.0
        self._value = 1.0
        self._dragging = False
        # Offscreen cache for the hue ring; rebuilt only when the widget
        # size or the brightness value changes (dragging only changes hue
        # and saturation, so it never invalidates the ring).
        self._wheel_cache: QPixmap | None = None
        self._wheel_cache_size: int = -1
        self._wheel_cache_value: float = -1.0
        self.setMinimumSize(scaled_px(200), scaled_px(200))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    def get_color(self) -> QColor:
        return QColor.fromHsvF(self._hue, self._saturation, self._value)

    def set_color(self, color: QColor):
        self._hue = color.hueF()
        self._saturation = color.saturationF()
        self._value = color.valueF()
        self.update()

    def set_value(self, value: float):
        self._value = max(0.0, min(1.0, value))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        size = min(self.width(), self.height())
        cx, cy = self.width() / 2, self.height() / 2
        radius = size / 2 - 4

        # Draw hue ring (cached offscreen; rebuilt on size/value change).
        # startAngle uses the same convention as _pos_to_hue: 0 at 3 o'clock,
        # increasing counterclockwise on screen — hue angle/360 lands exactly
        # where a click with that hue reads it back.
        self._ensure_wheel_cache(size, radius)
        if self._wheel_cache is not None:
            painter.drawPixmap(int(cx - radius), int(cy - radius), self._wheel_cache)

        # Draw saturation gradient (center = white, edge = full saturation).
        # A single QRadialGradient replaces the previous per-pixel ring loop
        # (~radius drawEllipse calls) — the same look in one draw call, and no
        # concentric-ring banding.
        sat_gradient = QRadialGradient(cx, cy, radius)
        sat_gradient.setColorAt(0.0, QColor.fromHsvF(self._hue, 0.0, self._value))
        sat_gradient.setColorAt(1.0, QColor.fromHsvF(self._hue, 1.0, self._value))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(sat_gradient)
        painter.drawEllipse(int(cx - radius), int(cy - radius), int(radius * 2), int(radius * 2))

        # Draw selection indicator
        angle_rad = math.radians(_hue_to_angle(self._hue))
        dist = self._saturation * radius
        sx = cx + dist * math.cos(angle_rad)
        sy = cy - dist * math.sin(angle_rad)
        painter.setPen(Qt.GlobalColor.white)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(int(sx - 6), int(sy - 6), 12, 12)
        painter.setPen(Qt.GlobalColor.black)
        painter.drawEllipse(int(sx - 5), int(sy - 5), 10, 10)

    def _ensure_wheel_cache(self, size: int, radius: float):
        """Render the hue ring into an offscreen pixmap, cached per size/value.

        The ring depends only on the widget size and the brightness value,
        so dragging (hue/saturation) reuses the cache instead of redrawing
        360 antialiased arcs on every frame.
        """
        if (
            self._wheel_cache is not None
            and self._wheel_cache_size == size
            and self._wheel_cache_value == self._value
        ):
            return
        self._wheel_cache = None
        if size < 4 or radius <= 0:
            return
        dpr = self.devicePixelRatioF()
        pm = QPixmap(round(size * dpr), round(size * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        half = size / 2
        ring = int(radius * 2)
        for angle in range(360):
            color = QColor.fromHsvF(angle / 360.0, 1.0, self._value)
            painter.setPen(color)
            painter.drawArc(int(half - radius), int(half - radius), ring, ring,
                            angle * 16, 16)
        painter.end()
        self._wheel_cache = pm
        self._wheel_cache_size = size
        self._wheel_cache_value = self._value

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._update_from_pos(event.position().toPoint())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._update_from_pos(event.position().toPoint())

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def _update_from_pos(self, pos: QPoint):
        cx, cy = self.width() / 2, self.height() / 2
        dx = pos.x() - cx
        dy = pos.y() - cy
        radius = min(self.width(), self.height()) / 2 - 4

        dist = math.sqrt(dx * dx + dy * dy)
        if dist > radius:
            dist = radius

        self._hue = _pos_to_hue(dx, dy)
        self._saturation = dist / radius
        self.update()
        self.color_changed.emit(self.get_color())


class BrightnessSlider(QWidget):
    """Vertical brightness slider — black to current color."""

    value_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 1.0
        self._hue = 0.0
        self._saturation = 1.0
        self._dragging = False
        self.setFixedWidth(scaled_px(24))
        self.setMinimumHeight(scaled_px(100))
        self.setMouseTracking(True)

    def set_hsv(self, hue: float, saturation: float):
        self._hue = hue
        self._saturation = saturation
        self.update()

    def set_value(self, value: float):
        self._value = max(0.0, min(1.0, value))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw gradient
        gradient = QLinearGradient(0, self.height(), 0, 0)
        gradient.setColorAt(0, QColor.fromHsvF(self._hue, self._saturation, 0))
        gradient.setColorAt(1, QColor.fromHsvF(self._hue, self._saturation, 1))
        painter.fillRect(self.rect(), gradient)

        # Draw indicator
        y = int(self.height() * (1 - self._value))
        painter.setPen(Qt.GlobalColor.white)
        painter.drawLine(0, y, self.width(), y)
        painter.setPen(Qt.GlobalColor.black)
        painter.drawLine(0, y + 1, self.width(), y + 1)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._update_from_y(event.position().y())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._update_from_y(event.position().y())

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def _update_from_y(self, y: float):
        self._value = max(0.0, min(1.0, 1.0 - y / self.height()))
        self.update()
        self.value_changed.emit(self._value)
