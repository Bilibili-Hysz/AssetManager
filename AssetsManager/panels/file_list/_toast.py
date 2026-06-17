"""Toast — lightweight auto-dismiss notification widget."""
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QGraphicsOpacityEffect

from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px


class Toast(QWidget):
    """A small notification that fades out after a short duration."""

    def __init__(self, text: str, parent=None, duration_ms: int = 2000):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        t = themes.get()
        self.setStyleSheet(
            f"background: {t['header']}; color: {t['heading']}; "
            f"border: 1px solid {t['border']}; border-radius: {scaled_px(6)}px; "
            f"padding: 6px 14px; font-size: 11px;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(text)
        layout.addWidget(label)

        self.adjustSize()
        self._position()
        self.show()

        # Fade out animation
        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._opacity.setOpacity(1.0)

        self._fade_timer = QTimer(self)
        self._fade_timer.setSingleShot(True)
        self._fade_timer.setInterval(duration_ms)
        self._fade_timer.timeout.connect(self._start_fade)
        self._fade_timer.start()

    def _position(self):
        """Position at bottom-right of parent."""
        if self.parent():
            pr = self.parent().rect()
            self.move(pr.right() - self.width() - 16, pr.bottom() - self.height() - 16)

    def _start_fade(self):
        self._anim = QPropertyAnimation(self._opacity, b"opacity")
        self._anim.setDuration(300)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim.finished.connect(self.close)
        self._anim.start()
