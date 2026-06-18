"""HSV color wheel and brightness slider for color picker."""
from __future__ import annotations

import math
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QColor, QPainter, QLinearGradient
from PySide6.QtWidgets import QWidget, QSizePolicy
from AssetsManager.core.ui_scale import scaled_px


class HSVWheel(QWidget):
    """Circular HSV color wheel — click/drag to select hue + saturation."""

    color_changed = Signal(QColor)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hue = 0.0
        self._saturation = 1.0
        self._value = 1.0
        self._dragging = False
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

        # Draw hue ring
        for angle in range(360):
            color = QColor.fromHsvF(angle / 360.0, 1.0, self._value)
            painter.setPen(color)
            painter.drawArc(int(cx - radius), int(cy - radius),
                          int(radius * 2), int(radius * 2),
                          (360 - angle) * 16, 16)

        # Draw saturation gradient (center = white, edge = full saturation)
        for r in range(int(radius), 0, -1):
            sat = 1.0 - (r / radius)
            color = QColor.fromHsvF(self._hue, sat, self._value)
            painter.setPen(color)
            painter.drawEllipse(int(cx - r), int(cy - r), r * 2, r * 2)

        # Draw selection indicator
        angle_rad = math.radians(self._hue * 360)
        dist = self._saturation * radius
        sx = cx + dist * math.cos(angle_rad)
        sy = cy - dist * math.sin(angle_rad)
        painter.setPen(Qt.GlobalColor.white)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(int(sx - 6), int(sy - 6), 12, 12)
        painter.setPen(Qt.GlobalColor.black)
        painter.drawEllipse(int(sx - 5), int(sy - 5), 10, 10)

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

        angle = math.degrees(math.atan2(-dy, dx)) % 360
        self._hue = angle / 360.0
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
