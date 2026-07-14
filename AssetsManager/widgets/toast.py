"""Toast notification widget — lightweight, auto-dismissing overlay.

Usage:
    Toast.info(parent, "File saved")
    Toast.success(parent, "Share link copied")
    Toast.error(parent, "Connection failed")

Singleton pattern: Toast.instance(parent) returns the single active toast.
"""
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QGraphicsOpacityEffect
from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager import i18n

tr = i18n.tr

_LEVEL_COLORS = {
    "info": "accent",
    "success": "success",
    "error": "danger",
}

_INSTANCE: "Toast | None" = None


class Toast(QWidget):
    """Frameless, auto-dismissing toast notification."""

    _instance: "Toast | None" = None

    def __init__(self, parent: QWidget, message: str, level: str = "info",
                 duration: int = 3000):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        t = themes.get()
        color_token = _LEVEL_COLORS.get(level, "accent")
        border_color = t.get(color_token, t["accent"])

        self._label = QLabel(message)
        self._label.setStyleSheet(
            f"color: {t['heading']}; font-size: {scaled_pt(12)}px; "
            f"background: transparent; padding: 0 {scaled_px(8)}px;")
        self._label.setWordWrap(True)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        border_bar = QWidget()
        border_bar.setFixedWidth(scaled_px(4))
        border_bar.setStyleSheet(f"background: {border_color};")
        row.addWidget(border_bar)

        body = QWidget()
        body.setStyleSheet(
            f"background: {t['panel']}; border: 1px solid {t['border']}; "
            f"border-left: none; border-radius: 0 {scaled_px(8)}px {scaled_px(8)}px 0;")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(
            scaled_px(12), scaled_px(10), scaled_px(12), scaled_px(10))
        body_layout.addWidget(self._label)
        row.addWidget(body)

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_anim.setDuration(300)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InQuad)
        self._fade_anim.finished.connect(self._on_fade_done)

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.setInterval(duration)
        self._dismiss_timer.timeout.connect(self._start_fade_out)

        self.adjustSize()
        self._position_at_bottom_center()

    # ── Public API ──────────────────────────────────────────

    @classmethod
    def instance(cls, parent: QWidget, message: str = "", level: str = "info",
                 duration: int = 3000) -> "Toast":
        """Return (and optionally replace) the singleton toast."""
        if cls._instance is not None:
            cls._instance.dismiss_immediately()
        toast = cls(parent, message, level, duration)
        cls._instance = toast
        toast.show()
        toast._dismiss_timer.start()
        return toast

    @classmethod
    def info(cls, parent: QWidget, message: str, duration: int = 3000) -> "Toast":
        return cls.instance(parent, message, "info", duration)

    @classmethod
    def success(cls, parent: QWidget, message: str, duration: int = 3000) -> "Toast":
        return cls.instance(parent, message, "success", duration)

    @classmethod
    def error(cls, parent: QWidget, message: str, duration: int = 3000) -> "Toast":
        return cls.instance(parent, message, "error", duration)

    def dismiss_immediately(self):
        """Remove the toast without animation."""
        self._dismiss_timer.stop()
        self._fade_anim.stop()
        if Toast._instance is self:
            Toast._instance = None
        self.close()
        self.deleteLater()

    # ── Internals ───────────────────────────────────────────

    def _start_fade_out(self):
        self._fade_anim.start()

    def _on_fade_done(self):
        if Toast._instance is self:
            Toast._instance = None
        self.close()
        self.deleteLater()

    def _position_at_bottom_center(self):
        parent = self.parentWidget()
        if not parent:
            return
        pw, ph = parent.width(), parent.height()
        tw, th = self.width(), self.height()
        x = (pw - tw) // 2
        y = ph - th - scaled_px(24)
        self.move(x, max(0, y))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_at_bottom_center()
