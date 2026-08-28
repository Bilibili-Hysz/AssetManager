"""Toast notification widget — lightweight, auto-dismissing overlay.

Usage:
    Toast.info(parent, "File saved")
    Toast.success(parent, "Share link copied")
    Toast.error(parent, "Connection failed", subtitle="Check your network")

Singleton pattern: Toast.instance(parent) returns the single active toast.
"""
from PySide6.QtCore import (
    QEvent,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import QAccessible, QAccessibleEvent, QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QVBoxLayout,
    QGraphicsOpacityEffect,
)
from shiboken6 import isValid

from AssetsManager.core import icons, themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.widgets.elevation import apply_elevation
from AssetsManager.widgets.stylekit import StyleKit

_LEVEL_COLORS = {
    "info": "accent",
    "success": "success",
    "error": "danger",
}

class Toast(QWidget):
    """Frameless, auto-dismissing toast notification."""

    _instance: "Toast | None" = None
    _MAX_WIDTH = 420
    _EDGE_MARGIN = 8
    _BOTTOM_MARGIN = 24

    def __init__(self, parent: QWidget, message: str, level: str = "info",
                 duration: int = 3000, icon: str = "", subtitle: str = ""):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAccessibleName(message)
        self.setAccessibleDescription(subtitle)
        self._accessibility_alert_pending = False
        self._accessibility_alert_sent = False
        self._parent_destroying = False

        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        color_token = _LEVEL_COLORS.get(level, "accent")
        border_color = sk.token(color_token, sk.token("accent"))
        px = sk.px
        radius_sm = px(int(sk.prop("border_radius", "sm", 8)))

        # ── Left accent bar ────────────────────────────────────
        border_bar = QWidget()
        border_bar.setFixedWidth(px(4))
        border_bar.setStyleSheet(
            f"background: {border_color}; "
            f"border-top-left-radius: {radius_sm}px; border-bottom-left-radius: {radius_sm}px;"
        )

        # ── Icon label (semantic SVG icon) ────────────────────
        icon_label = None
        icon_name = icons.normalize(str(icon or ""), fallback="")
        if icon_name:
            icon_label = QLabel()
            icon_pixmap = icons.icon(icon_name, color=border_color, size=px(16)).pixmap(
                QSize(px(16), px(16)))
            icon_label.setPixmap(icon_pixmap)
            icon_label.setStyleSheet(
                f"background: transparent; padding-right: {scaled_px(4)}px;")
            icon_label.setFixedWidth(px(20))
            icon_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        # ── Message label ──────────────────────────────────────
        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet(sk.label_css("heading", size=12))

        # ── Subtitle label (optional) ──────────────────────────
        sub_label = None
        if subtitle:
            sub_label = QLabel(subtitle)
            sub_label.setWordWrap(True)
            sub_label.setStyleSheet(sk.muted_css(11))

        # ── Text column (message + optional subtitle) ──────────
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(px(2))
        text_col.addWidget(msg_label)
        if sub_label is not None:
            text_col.addWidget(sub_label)

        # ── Icon + text row ────────────────────────────────────
        inner_row = QHBoxLayout()
        inner_row.setContentsMargins(0, 0, 0, 0)
        inner_row.setSpacing(0)
        if icon_label is not None:
            inner_row.addWidget(icon_label)
        inner_row.addLayout(text_col)

        # ── Body widget ────────────────────────────────────────
        body = QWidget()
        body.setStyleSheet(
            f"background: {sk.token('panel')}; border: {scaled_px(1)}px solid {sk.token('border')}; "
            f"border-left: none; border-radius: 0 {radius_sm}px {radius_sm}px 0;")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(px(12), px(10), px(12), px(10))
        body_layout.addLayout(inner_row)

        # ── Outer shell (left bar + body) ──────────────────────
        row = QHBoxLayout(self)
        shadow_margin = px(8)
        row.setContentsMargins(shadow_margin, shadow_margin, shadow_margin, shadow_margin)
        row.setSpacing(0)
        row.addWidget(border_bar)
        row.addWidget(body)
        # Subtle elevation on the opaque card so the toast "floats" above the
        # underlying window. The outer margin reserves room for the shadow.
        apply_elevation(body, level=1)
        self._text_labels = tuple(
            label for label in (msg_label, sub_label) if label is not None
        )
        # Horizontal chrome (shadow margin + accent bar + body margins +
        # optional icon column). Computed from the fixed widths set above
        # instead of widget.width(), which is still 0 before the toast is laid
        # out.
        self._horizontal_chrome = (
            2 * shadow_margin
            + px(4)
            + body_layout.contentsMargins().left()
            + body_layout.contentsMargins().right()
            + (px(20) if icon_label is not None else 0)
        )

        # Rounded corners on the left side of the accent bar
        self.setStyleSheet(
            f"background: transparent; border-radius: {radius_sm}px;")

        # ── Opacity effect + fade animation ────────────────────
        reduce_motion = StyleKit.reduce_motion()
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0 if reduce_motion else 0.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._fade_in_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_in_anim.setDuration(150)
        self._fade_in_anim.setStartValue(0.0)
        self._fade_in_anim.setEndValue(1.0)
        self._fade_in_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._fade_out_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_out_anim.setDuration(300)
        self._fade_out_anim.setStartValue(1.0)
        self._fade_out_anim.setEndValue(0.0)
        self._fade_out_anim.setEasingCurve(QEasingCurve.Type.InQuad)
        self._fade_out_anim.finished.connect(self._on_fade_done)

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.setInterval(duration)
        self._dismiss_timer.timeout.connect(self._start_fade_out)

        parent.installEventFilter(self)
        parent.destroyed.connect(self._on_parent_destroyed)
        self.destroyed.connect(
            lambda _object=None, toast=self: Toast._clear_if_current(toast)
        )
        self._update_size_and_position()

        # Start fade-in (skipped when reduce_motion is active)
        if not reduce_motion:
            self._fade_in_anim.start()

    # ── Public API ──────────────────────────────────────────

    @classmethod
    def instance(cls, parent: QWidget, message: str = "", level: str = "info",
                 duration: int = 3000, icon: str = "", subtitle: str = "") -> "Toast":
        """Return (and optionally replace) the singleton toast."""
        current = cls._instance
        if current is not None:
            if isValid(current):
                current.dismiss_immediately()
            else:
                cls._instance = None
        toast = cls(parent, message, level, duration, icon, subtitle)
        cls._instance = toast
        toast.show()
        toast._dismiss_timer.start()
        return toast

    @classmethod
    def info(cls, parent: QWidget, message: str, duration: int = 3000,
             icon: str = "", subtitle: str = "") -> "Toast":
        return cls.instance(parent, message, "info", duration, icon, subtitle)

    @classmethod
    def success(cls, parent: QWidget, message: str, duration: int = 3000,
                icon: str = "", subtitle: str = "") -> "Toast":
        return cls.instance(parent, message, "success", duration, icon, subtitle)

    @classmethod
    def error(cls, parent: QWidget, message: str, duration: int = 3000,
              icon: str = "", subtitle: str = "") -> "Toast":
        return cls.instance(parent, message, "error", duration, icon, subtitle)

    def dismiss_immediately(self):
        """Remove the toast without animation."""
        self._dismiss_timer.stop()
        self._fade_in_anim.stop()
        self._fade_out_anim.stop()
        if Toast._instance is self:
            Toast._instance = None
        self._detach_parent_filter()
        self.close()
        self.deleteLater()

    # ── Internals ───────────────────────────────────────────

    @classmethod
    def _clear_if_current(cls, toast: "Toast"):
        if cls._instance is toast:
            cls._instance = None

    def _stop_activity(self):
        self._dismiss_timer.stop()
        self._fade_in_anim.stop()
        self._fade_out_anim.stop()

    def _on_parent_destroyed(self, _object=None):
        if self._parent_destroying or not isValid(self):
            return
        self._parent_destroying = True
        self._stop_activity()
        Toast._clear_if_current(self)
        self.hide()

    def _announce_accessibility_alert(self):
        self._accessibility_alert_pending = False
        if self._accessibility_alert_sent or not isValid(self) or not self.isVisible():
            return
        self._accessibility_alert_sent = True
        QAccessible.updateAccessibility(
            QAccessibleEvent(self, QAccessible.Event.Alert)
        )

    def _start_fade_out(self):
        if StyleKit.reduce_motion():
            self._on_fade_done()
            return
        self._fade_out_anim.start()

    def _on_fade_done(self):
        if Toast._instance is self:
            Toast._instance = None
        self._detach_parent_filter()
        self.close()
        self.deleteLater()

    def _detach_parent_filter(self):
        parent = self.parentWidget()
        if parent is not None:
            parent.removeEventFilter(self)

    def _parent_global_rect(self) -> QRect:
        parent = self.parentWidget()
        if parent is None:
            return QRect()
        return QRect(parent.mapToGlobal(QPoint(0, 0)), parent.size())

    def _placement_bounds(self) -> tuple[QRect, QRect]:
        parent_rect = self._parent_global_rect()
        if parent_rect.isEmpty():
            return parent_rect, parent_rect

        screen = QGuiApplication.screenAt(parent_rect.center()) or self.screen()
        screen_rect = screen.availableGeometry() if screen is not None else parent_rect
        bounds = parent_rect.intersected(screen_rect)
        return parent_rect, bounds if not bounds.isEmpty() else parent_rect

    def _update_size_and_position(self):
        _, bounds = self._placement_bounds()
        if bounds.isEmpty():
            return

        edge_margin = scaled_px(self._EDGE_MARGIN)
        usable_width = max(1, bounds.width() - 2 * edge_margin)
        maximum_width = min(scaled_px(self._MAX_WIDTH), usable_width)
        if self.maximumWidth() != maximum_width:
            self.setMaximumWidth(maximum_width)
            text_width = max(1, maximum_width - self._horizontal_chrome)
            for label in self._text_labels:
                label.setMaximumWidth(text_width)
        self.adjustSize()
        self._position_at_bottom_center()

    def _position_at_bottom_center(self):
        parent_rect, bounds = self._placement_bounds()
        if parent_rect.isEmpty() or bounds.isEmpty():
            return

        tw, th = self.width(), self.height()
        edge_margin = scaled_px(self._EDGE_MARGIN)
        bottom_margin = scaled_px(self._BOTTOM_MARGIN)

        horizontal_margin = edge_margin if bounds.width() >= tw + 2 * edge_margin else 0
        vertical_margin = edge_margin if bounds.height() >= th + 2 * edge_margin else 0
        min_x = bounds.left() + horizontal_margin
        max_x = bounds.right() - tw + 1 - horizontal_margin
        min_y = bounds.top() + vertical_margin
        max_y = bounds.bottom() - th + 1 - vertical_margin

        desired_x = parent_rect.center().x() - tw // 2
        desired_y = parent_rect.bottom() - bottom_margin - th + 1
        x = min(max(desired_x, min_x), max_x) if min_x <= max_x else bounds.left()
        y = min(max(desired_y, min_y), max_y) if min_y <= max_y else bounds.top()
        self.move(x, y)

    def eventFilter(self, watched, event):
        if watched is self.parentWidget():
            event_type = event.type()
            if event_type in {QEvent.Type.Hide, QEvent.Type.Close}:
                self.dismiss_immediately()
            elif event_type == QEvent.Type.Destroy:
                self._on_parent_destroyed()
            elif event_type in {
                QEvent.Type.Move,
                QEvent.Type.Resize,
                QEvent.Type.Show,
                QEvent.Type.WindowStateChange,
            }:
                self._update_size_and_position()
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        self._update_size_and_position()
        if not self._accessibility_alert_sent and not self._accessibility_alert_pending:
            self._accessibility_alert_pending = True
            QTimer.singleShot(0, self._announce_accessibility_alert)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_at_bottom_center()
