"""Reusable status indicator — loading, error, retry, success.

Purely visual widget with no business logic. Displays an optional icon,
title, and subtitle, with a pulsing animation for the loading state.
Respects the global reduce_motion setting.

Usage:
    indicator = StatusIndicator("loading", title="Scanning library…")
    indicator.set_status("error", title="Failed", subtitle="Network timeout")
    indicator.set_status("retry", title="Retry?", subtitle="Connection lost")
"""
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QGraphicsOpacityEffect
from AssetsManager.core import icons, themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.widgets.stylekit import StyleKit


class StatusIndicator(QWidget):
    """Centered icon + title + subtitle with state-driven theming."""

    _FALLBACK_ICON_NAMES = {
        "loading": "clock",
        "success": "check",
        "error": "close",
        "retry": "refresh",
        "idle": "",
    }

    def __init__(self, status: str = "idle", title: str = "",
                 subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("StatusIndicator")

        self._status = status
        self._title = title
        self._subtitle = subtitle
        self._icon_name = ""
        self._icon_color = ""

        self._sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)

        # ── Icon (theme-colored SVG/QIcon pixmap) ─────────────
        self._icon_label = QLabel()
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setStyleSheet("background: transparent;")

        # ── Title ──────────────────────────────────────────────
        self._title_label = QLabel()
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setWordWrap(True)

        # ── Subtitle ───────────────────────────────────────────
        self._subtitle_label = QLabel()
        self._subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle_label.setWordWrap(True)

        # ── Layout ─────────────────────────────────────────────
        col = QVBoxLayout(self)
        col.addStretch()
        col.addWidget(self._icon_label, 0, Qt.AlignmentFlag.AlignHCenter)
        col.addWidget(self._title_label)
        col.addWidget(self._subtitle_label)
        col.addStretch()
        self._layout = col

        # ── Pulse animation (loading state) ────────────────────
        self._pulse_anim = self._sk.make_pulse(
            self._icon_label, duration=1200, low=0.3, high=1.0)
        # make_pulse already sets the graphics effect on _icon_label

        # ── Apply initial state ────────────────────────────────
        self._apply_scale_metrics()
        self.set_status(status, title=title, subtitle=subtitle)

    # ── Public API ──────────────────────────────────────────

    def set_status(self, status: str, title: str | None = None,
                   subtitle: str | None = None):
        """Switch visual state. Re-themes all labels."""
        sk = self._sk
        color = sk.state_color(status)

        self._status = status
        if title is not None:
            self._title = title
        if subtitle is not None:
            self._subtitle = subtitle

        # Icon
        icon_name = self._semantic_icon_name(status)
        self._icon_name = icon_name
        self._icon_color = color
        self._icon_label.clear()
        if icon_name:
            icon_size = sk.px(24)
            state_icon = icons.icon(icon_name, color=color, size=icon_size)
            self._icon_label.setPixmap(
                state_icon.pixmap(QSize(icon_size, icon_size)))
        self._icon_label.setVisible(bool(icon_name))

        # Title
        self._title_label.setText(self._title)
        self._title_label.setStyleSheet(sk.label_css("heading", size=14))

        # Subtitle
        self._subtitle_label.setText(self._subtitle)
        self._subtitle_label.setStyleSheet(sk.muted_css(12))

        self._refresh_accessibility()

        # Animation
        self._sync_pulse()

    def refresh_theme(self):
        """Refresh theme colors and scale-derived visual metrics."""
        self._sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        self._apply_scale_metrics()
        self.set_status(self._status)

    def refresh_scale(self):
        """Re-read the live UI scale and resize all pixel/font metrics."""
        self._sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        self._apply_scale_metrics()
        self.set_status(self._status)

    def refresh_motion_preference(self):
        """Apply the current reduce-motion preference to the live pulse."""
        self._sync_pulse()

    def set_title(self, text: str):
        self._title = text
        self._title_label.setText(text)
        self._refresh_accessibility()

    def set_subtitle(self, text: str):
        self._subtitle = text
        self._subtitle_label.setText(text)
        self._refresh_accessibility()

    # ── Internals ───────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_pulse()

    def hideEvent(self, event):
        self._stop_pulse()
        super().hideEvent(event)

    def closeEvent(self, event):
        self._stop_pulse()
        super().closeEvent(event)

    def _apply_scale_metrics(self):
        """Resize containers before redrawing their scaled contents."""
        px = self._sk.px
        self.setMinimumHeight(px(100))
        self._icon_label.setFixedSize(px(32), px(32))
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(px(6))

    def _semantic_icon_name(self, status: str) -> str:
        """Return a semantic icon name during the StyleKit migration."""
        icon_name = self._sk.state_icon(status)
        if icon_name in self._FALLBACK_ICON_NAMES.values():
            return icon_name
        return self._FALLBACK_ICON_NAMES.get(status, "")

    def _refresh_accessibility(self):
        status_text = self._status.replace("_", " ").strip().capitalize()
        accessible_name = status_text
        if self._title:
            accessible_name = f"{status_text}: {self._title}"
        self.setAccessibleName(accessible_name)
        self.setAccessibleDescription(self._subtitle)
        self._icon_label.setAccessibleName(status_text)
        self._icon_label.setAccessibleDescription(self._title)

    def _start_pulse(self):
        if self._pulse_anim.state() != self._pulse_anim.State.Running:
            self._pulse_anim.start()

    def _sync_pulse(self):
        should_run = (
            self.isVisible()
            and self._status == "loading"
            and not StyleKit.reduce_motion()
        )
        if should_run:
            self._start_pulse()
        else:
            self._stop_pulse()

    def _stop_pulse(self):
        if self._pulse_anim.state() == self._pulse_anim.State.Running:
            self._pulse_anim.stop()
        # Reset opacity to 1.0
        effect = self._icon_label.graphicsEffect()
        if isinstance(effect, QGraphicsOpacityEffect):
            effect.setOpacity(1.0)
