"""MicroTabBar — modern macOS / Linear / Craft style floating pill tab bar.

A fluid, accessible, high-DPI aware segmented tab bar featuring:
  - Capsule / runway track (Track) container with anti-aliased rounded edges.
  - Floating translucent pill indicator gliding smoothly via QPropertyAnimation.
  - Easing curve QEasingCurve.Type.OutCubic with 200ms duration.
  - Zero-latency instant switching when animate=False or reduce_motion is enabled.
  - Transparent overlay buttons with accessible labeling and keyboard navigation.
  - Dynamic HighDPI auto-scaling via AssetsManager.core.ui_scale.scaled_px / scaled_pt.
  - Theme-aware color tokens and live update support.
"""
from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QCloseEvent,
    QColor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from AssetsManager.core import themes
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core.ui_scale import scaled_pt, scaled_px
from AssetsManager.widgets.stylekit import StyleKit


class _IntCallable(int):
    """Integer subclass callable as a zero-argument function.

    Provides transparent compatibility whether caller accesses ``tab_bar.current_index``
    as an integer attribute or calls ``tab_bar.current_index()`` as a method.
    """

    def __call__(self) -> int:
        return int(self)


class _ListCallable(list):
    """List subclass callable as a zero-argument function.

    Provides transparent compatibility whether caller accesses ``tab_bar.tabs``
    or ``tab_bar.buttons`` as an attribute or method call.
    """

    def __call__(self) -> list:
        return list(self)


class MicroTabBar(QWidget):
    """Modern macOS / Linear / Craft style floating pill tab bar."""

    current_changed = Signal(int)
    # Qt camelCase alias
    currentChanged = current_changed

    def __init__(
        self,
        tabs: list[str] | QWidget | None = None,
        parent: QWidget | None = None,
    ) -> None:
        # Handle MicroTabBar(parent) signature if caller passed QWidget as first arg
        if isinstance(tabs, QWidget) and parent is None:
            parent = tabs
            tabs = None

        super().__init__(parent)

        self._tabs: list[str] = []
        self._buttons: list[QPushButton] = []
        self._current_index: int = -1

        # Smooth physical sliding indicator animation
        self._indicator_geometry: QRect = QRect()
        self._indicator_anim: QPropertyAnimation = QPropertyAnimation(self, b"indicator_geometry")
        self._indicator_anim.setDuration(themes.motion("normal"))
        self._indicator_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Widget flags and setup
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        # Layout setup
        self._layout = QHBoxLayout(self)
        self._apply_layout_metrics()

        # Theme and UI scale subscriptions
        self._bus_connections: list[tuple[Any, Any]] = []
        self._connect_bus_signals()

        # Initialize tabs if provided
        if tabs:
            # Only list[str] reaches here with a truthy value: the QWidget
            # overload was rewritten to None above.
            self.set_tabs(cast("list[str]", tabs))
        else:
            self._apply_style()

    # ── Qt Property for Indicator Geometry ───────────────────────────

    def _get_indicator_geometry(self) -> QRect:
        return self._indicator_geometry

    def _set_indicator_geometry(self, rect: QRect | QRectF) -> None:
        if isinstance(rect, QRectF):
            self._indicator_geometry = rect.toRect()
        else:
            self._indicator_geometry = rect
        self.update()

    indicator_geometry = Property(QRect, _get_indicator_geometry, _set_indicator_geometry)

    # ── Geometry & Layout Metrics ────────────────────────────────────

    def _apply_layout_metrics(self) -> None:
        pad = scaled_px(3)
        spacing = scaled_px(2)
        self._layout.setContentsMargins(pad, pad, pad, pad)
        self._layout.setSpacing(spacing)
        self.setMinimumHeight(scaled_px(28))

    def sizeHint(self) -> QSize:
        h = scaled_px(32)
        if self._layout is not None and self._buttons:
            s = self._layout.sizeHint()
            return QSize(max(scaled_px(80), s.width()), max(h, s.height()))
        return QSize(scaled_px(120), h)

    def minimumSizeHint(self) -> QSize:
        return QSize(scaled_px(60), scaled_px(28))

    # ── Public API ───────────────────────────────────────────────────

    def count(self) -> int:
        """Return the number of tabs."""
        return len(self._tabs)

    def tab_count(self) -> int:
        """Alias for count()."""
        return len(self._tabs)

    def button_count(self) -> int:
        """Return the number of tab buttons."""
        return len(self._buttons)

    @property
    def tabs(self) -> _ListCallable:
        """Return the list of tab titles."""
        return _ListCallable(self._tabs)

    @property
    def buttons(self) -> _ListCallable:
        """Return the list of QPushButton instances."""
        return _ListCallable(self._buttons)

    @property
    def current_index(self) -> _IntCallable:
        """Return the current active tab index."""
        return _IntCallable(self._current_index)

    @current_index.setter
    def current_index(self, index: int) -> None:
        self.set_current_index(index)

    def currentIndex(self) -> int:
        """Return the current active tab index (Qt convention)."""
        return self._current_index

    def setCurrentIndex(self, index: int) -> None:
        """Set the current tab index (Qt convention)."""
        self.set_current_index(index)

    def tab_text(self, index: int) -> str:
        """Return the text title of the tab at index."""
        if 0 <= index < len(self._tabs):
            return self._tabs[index]
        return ""

    def set_tab_text(self, index: int, text: str) -> None:
        """Update the text title of the tab at index."""
        if not (0 <= index < len(self._tabs)):
            return
        self._tabs[index] = text
        self._buttons[index].setText(text)
        self._buttons[index].setAccessibleName(f"Tab: {text}")
        self.updateGeometry()
        self.update()

    def set_tabs(self, tabs: list[str]) -> None:
        """Replace all tabs with the given list of titles."""
        # Clean up existing buttons
        for btn in self._buttons:
            self._layout.removeWidget(btn)
            btn.setParent(None)
            btn.deleteLater()
        self._buttons.clear()
        self._tabs = list(tabs)

        for title in self._tabs:
            btn = self._create_tab_button(title)
            self._buttons.append(btn)
            self._layout.addWidget(btn)

        self._apply_style()

        if self._tabs:
            self._current_index = 0
            self._update_button_states()
            self._indicator_geometry = self._target_indicator_rect(0)
        else:
            self._current_index = -1
            self._indicator_geometry = QRect()

        self.updateGeometry()
        self.update()

    def add_tab(self, title: str) -> int:
        """Append a new tab with the given title. Return the index of the new tab."""
        index = len(self._tabs)
        self._tabs.append(title)
        btn = self._create_tab_button(title)
        self._buttons.append(btn)
        self._layout.addWidget(btn)
        self._apply_style()

        if self._current_index == -1:
            self._current_index = 0
            self._update_button_states()
            self._indicator_geometry = self._target_indicator_rect(0)

        self.updateGeometry()
        self.update()
        return index

    def remove_tab(self, index: int) -> None:
        """Remove the tab at index."""
        if not (0 <= index < len(self._tabs)):
            return
        self._tabs.pop(index)
        btn = self._buttons.pop(index)
        self._layout.removeWidget(btn)
        btn.setParent(None)
        btn.deleteLater()

        if not self._tabs:
            self._current_index = -1
            self._indicator_geometry = QRect()
        elif self._current_index >= len(self._tabs):
            self.set_current_index(len(self._tabs) - 1, animate=False)
        else:
            self._update_button_states()
            self._update_indicator(animate=False)

        self.updateGeometry()
        self.update()

    def clear(self) -> None:
        """Remove all tabs."""
        self.set_tabs([])

    def set_current_index(self, index: int, animate: bool = True) -> None:
        """Set the active tab index with optional smooth sliding animation.

        Parameters:
            index: Zero-based tab index. If out of bounds, the call is safely ignored.
            animate: Whether to animate the indicator gliding to the new tab position.
        """
        if not (0 <= index < len(self._tabs)):
            return

        if self._current_index == index:
            # Already active. Ensure indicator correctly hugs the target.
            self._update_indicator(animate=False)
            return

        self._current_index = index
        self._update_button_states()
        self._update_indicator(animate=animate)
        self.current_changed.emit(index)

    # ── Internal Logic ───────────────────────────────────────────────

    def _create_tab_button(self, title: str) -> QPushButton:
        btn = QPushButton(title, self)
        btn.setCheckable(True)
        btn.setFlat(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        btn.setAccessibleName(f"Tab: {title}")
        btn.clicked.connect(lambda _, b=btn: self._on_button_clicked(b))
        return btn

    def _on_button_clicked(self, btn: QPushButton) -> None:
        try:
            index = self._buttons.index(btn)
            self.set_current_index(index, animate=True)
        except ValueError:
            pass

    def _update_button_states(self) -> None:
        for idx, btn in enumerate(self._buttons):
            btn.setChecked(idx == self._current_index)

    def _target_indicator_rect(self, index: int) -> QRect:
        if not (0 <= index < len(self._buttons)):
            return QRect()
        btn = self._buttons[index]
        geom = btn.geometry()
        if geom.isValid() and geom.width() > 0 and geom.height() > 0:
            return geom

        # Force layout computation if not yet realized
        if self._layout is not None:
            self._layout.setGeometry(self.rect())
            self._layout.activate()
            geom = btn.geometry()
            if geom.isValid() and geom.width() > 0 and geom.height() > 0:
                return geom

        # Fallback approximation based on dimensions
        pad = scaled_px(3)
        w = self.width() if self.width() > 10 else self.sizeHint().width()
        h = self.height() if self.height() > 10 else self.sizeHint().height()
        n = len(self._buttons)
        if n > 0:
            avail_w = max(0, w - 2 * pad)
            btn_w = avail_w // n
            btn_h = max(0, h - 2 * pad)
            return QRect(pad + index * btn_w, pad, btn_w, btn_h)
        return QRect()

    def _update_indicator(self, animate: bool = True) -> None:
        if not (0 <= self._current_index < len(self._buttons)):
            self._indicator_anim.stop()
            self._indicator_geometry = QRect()
            self.update()
            return

        target = self._target_indicator_rect(self._current_index)
        if target.isNull() or target.width() <= 0:
            return

        should_animate = (
            animate
            and not StyleKit.reduce_motion()
            and not self._indicator_geometry.isNull()
            and self._indicator_geometry.isValid()
            and self._indicator_geometry.width() > 0
        )

        if should_animate:
            self._indicator_anim.stop()
            self._indicator_anim.setStartValue(self._indicator_geometry)
            self._indicator_anim.setEndValue(target)
            self._indicator_anim.start()
        else:
            self._indicator_anim.stop()
            self._indicator_geometry = target
            self.update()

    # ── Styling & Theming ────────────────────────────────────────────

    def _apply_style(self) -> None:
        t = themes.get()
        font_pt = scaled_pt(themes.font_size("caption"))
        br_sm = scaled_px(int(themes.prop("border_radius", "sm")))
        hover_bg = alpha(t["hover_overlay"], themes.prop("opacity", "hover"))

        button_qss = (
            f"QPushButton {{ "
            f"  background: transparent; "
            f"  border: none; "
            f"  border-radius: {br_sm}px; "
            f"  color: {t['muted']}; "
            f"  padding: {scaled_px(3)}px {scaled_px(10)}px; "
            f"  font-size: {font_pt}px; "
            f"  font-weight: 500; "
            f"}} "
            f"QPushButton:hover:!checked {{ "
            f"  color: {t['body']}; "
            f"  background: {hover_bg}; "
            f"}} "
            f"QPushButton:checked {{ "
            f"  color: {t['heading']}; "
            f"  background: transparent; "
            f"  font-weight: 600; "
            f"}} "
            f"QPushButton:focus {{ "
            f"  outline: none; "
            f"}} "
        )
        for btn in self._buttons:
            btn.setStyleSheet(button_qss)
        self.update()

    def refresh_theme(self, _name: str = "") -> None:
        """Refresh styling on application theme change."""
        self._apply_style()

    def refresh_scale(self, _scale: float = 1.0) -> None:
        """Refresh metrics and styling on UI scale change."""
        self._apply_layout_metrics()
        self._apply_style()
        if 0 <= self._current_index < len(self._buttons):
            self._indicator_geometry = self._target_indicator_rect(self._current_index)
        self.updateGeometry()
        self.update()

    # ── Signal Bus Lifecycle ─────────────────────────────────────────

    def _connect_bus_signals(self) -> None:
        try:
            bus_inst = bus()
            bus_inst.theme_changed.connect(self.refresh_theme)
            self._bus_connections.append((bus_inst.theme_changed, self.refresh_theme))
            bus_inst.ui_scale_changed.connect(self.refresh_scale)
            self._bus_connections.append((bus_inst.ui_scale_changed, self.refresh_scale))
        except Exception:
            pass

    def shutdown(self) -> None:
        """Disconnect global signal bus connections."""
        for sig, slot in self._bus_connections:
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._bus_connections.clear()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.shutdown()
        super().closeEvent(event)

    # ── Events & Painting ────────────────────────────────────────────

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._indicator_anim.stop()
        if 0 <= self._current_index < len(self._buttons):
            if self._layout is not None:
                self._layout.activate()
            self._indicator_geometry = self._target_indicator_rect(self._current_index)
        else:
            self._indicator_geometry = QRect()
        self.update()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if 0 <= self._current_index < len(self._buttons):
            if self._layout is not None:
                self._layout.activate()
            self._indicator_geometry = self._target_indicator_rect(self._current_index)
            self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            for idx, btn in enumerate(self._buttons):
                if btn.geometry().contains(pos):
                    self.set_current_index(idx, animate=True)
                    break
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            if self._current_index > 0:
                self.set_current_index(self._current_index - 1, animate=True)
                event.accept()
                return
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            if self._current_index < len(self._tabs) - 1:
                self.set_current_index(self._current_index + 1, animate=True)
                event.accept()
                return
        elif key == Qt.Key.Key_Home:
            if len(self._tabs) > 0 and self._current_index != 0:
                self.set_current_index(0, animate=True)
                event.accept()
                return
        elif key == Qt.Key.Key_End:
            if len(self._tabs) > 0 and self._current_index != len(self._tabs) - 1:
                self.set_current_index(len(self._tabs) - 1, animate=True)
                event.accept()
                return
        super().keyPressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Render the antialiased runway track and rounded translucent pill indicator."""
        painter = QPainter(self)
        if not painter.isActive():
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        t = themes.get()

        # 1. Bottom layer: Antialiased runway slot (Track)
        stroke = max(1.0, float(scaled_px(1)))
        half_stroke = stroke / 2.0
        w = float(self.width())
        h = float(self.height())

        track_rect = QRectF(half_stroke, half_stroke, max(1.0, w - stroke), max(1.0, h - stroke))
        track_radius = track_rect.height() / 2.0

        track_bg = QColor(alpha(t["input_bg"], 0.75))
        track_border = QColor(alpha(t["border"], 0.55))

        painter.setPen(QPen(track_border, stroke))
        painter.setBrush(QBrush(track_bg))
        painter.drawRoundedRect(track_rect, track_radius, track_radius)

        # 2. Upper layer: Rounded semi-transparent pill indicator
        if (
            0 <= self._current_index < len(self._buttons)
            and not self._indicator_geometry.isNull()
            and self._indicator_geometry.isValid()
            and self._indicator_geometry.width() > 0
        ):
            ind_geom = self._indicator_geometry
            ind_rect = QRectF(
                float(ind_geom.x()) + half_stroke,
                float(ind_geom.y()) + half_stroke,
                max(1.0, float(ind_geom.width()) - stroke),
                max(1.0, float(ind_geom.height()) - stroke),
            )
            ind_radius = ind_rect.height() / 2.0

            accent_color = t["accent"]
            indicator_fill = QColor(alpha(accent_color, 0.24))
            indicator_border = QColor(alpha(accent_color, 0.52))

            painter.setPen(QPen(indicator_border, stroke))
            painter.setBrush(QBrush(indicator_fill))
            painter.drawRoundedRect(ind_rect, ind_radius, ind_radius)

        painter.end()


__all__ = ["MicroTabBar"]
