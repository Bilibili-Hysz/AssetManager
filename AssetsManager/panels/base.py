"""Base panel content with signal interface and context support."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton

from AssetsManager import i18n
from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px

tr = i18n.tr


class PanelContent(QWidget):
    """Base for all panels."""

    file_selected = Signal(object)
    directory_selected = Signal(str)
    file_double_clicked = Signal(str)

    # D2: panels override this key; save_state/restore_state then persist
    # through PanelState instead of touching AppSettings directly.
    panel_state_key: str = ""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelContent")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(scaled_px(100))
        self.content_layout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(scaled_px(4), scaled_px(4), scaled_px(4), scaled_px(4))
        self._context = None
        self.status_hint = ""
        self._bus_connections: list[tuple[Any, Any]] = []
        self._domain_subscriptions = []
        self._show_anim = None
        self._pending_timers: list = []

    def showEvent(self, event):
        """Override to add show animation."""
        super().showEvent(event)
        if not self._show_anim:
            self._animate_in()

    def _animate_in(self):
        """Animate panel entrance.

        Note: windowOpacity only affects top-level windows, so this animation
        has no visible effect when the panel is embedded as a child widget.
        Kept as-is: tests/desktop/test_tab_container.py asserts the animation
        lifecycle, and it would apply if a panel is ever shown as a window.
        """
        self._show_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._show_anim.setDuration(themes.motion("normal"))
        self._show_anim.setStartValue(0.0)
        self._show_anim.setEndValue(1.0)
        self._show_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        # V07 contract: honour the shared reduce-motion switch. The animation
        # object stays owned (the lifecycle test asserts parent/stopped) but
        # never starts, so the panel simply appears fully opaque.
        from AssetsManager.widgets.stylekit import StyleKit

        if not StyleKit.reduce_motion():
            self._show_anim.start()

    # ── Signal lifecycle ────────────────────────────────────────

    def _connect_bus(self, signal, slot):
        """Connect a bus signal and track it for automatic disconnection."""
        signal.connect(slot)
        self._bus_connections.append((signal, slot))

    def _connect_domain_event(self, event_type, slot):
        """Connect a domain event through a Qt bridge for UI-safe delivery."""
        from AssetsManager.panels._event_bridge import DomainEventSubscription

        sub = DomainEventSubscription(event_type, slot, self)
        self._domain_subscriptions.append(sub)
        return sub

    def prepare_library_switch(self) -> None:
        """Release work tied to the current library before session close."""

    def _schedule_once(self, interval_ms: int, callback) -> Any:
        """Schedule one owned one-shot timer; cancelable via shutdown."""
        from AssetsManager.core.timers import TimerHandle

        self._pending_timers = [h for h in self._pending_timers if h.is_active()]
        handle = TimerHandle.schedule(self, interval_ms, callback)
        self._pending_timers.append(handle)
        return handle

    def _clear_pending_timers(self) -> None:
        """Cancel every owner-managed one-shot timer."""
        for handle in self._pending_timers:
            handle.cancel()
        self._pending_timers.clear()

    def shutdown(self):
        """Disconnect all tracked bus signals before panel destruction."""
        self._clear_pending_timers()
        if self._show_anim is not None:
            self._show_anim.stop()
        for sub in self._domain_subscriptions:
            try:
                sub.close()
            except RuntimeError:
                pass
        self._domain_subscriptions.clear()
        for signal, slot in self._bus_connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._bus_connections.clear()

    # ── Title bar extra buttons ──────────────────────────────────────

    def title_bar_buttons(self) -> list:
        """Override to add extra buttons to the dock title bar (e.g. settings gear)."""
        from PySide6.QtCore import Qt
        from AssetsManager.core import icons, themes
        from AssetsManager.dialogs.generic_settings_dialog import generic_settings_dialog
        gear = QPushButton()
        gear.setIcon(icons.icon("settings", color="icon_primary", size=scaled_px(16)))
        gear.setIconSize(QSize(scaled_px(16), scaled_px(16)))
        gear.setToolTip(tr("panel.settings"))
        gear.setAccessibleName(tr("panel.settings"))
        gear.setFixedSize(scaled_px(20), scaled_px(20))
        gear.setFlat(True)
        gear.setProperty("semanticIcon", "settings")
        themes.set_button_variant(gear, "ghost")
        gear.setStyleSheet(
            f"color: {themes.color('heading')}; padding: 0; background: transparent; border: none; "
            f"border-radius: {scaled_px(int(themes.prop('border_radius', 'sm')))}px;")
        gear.setCursor(Qt.CursorShape.PointingHandCursor)
        gear.clicked.connect(lambda: generic_settings_dialog(self))
        return [gear]

    # ── Footer bar ────────────────────────────────────────────────

    def footer_bar(self) -> QWidget | None:
        """Override to provide a footer bar widget (e.g. action buttons).
        Returns None by default — dock_factory skips footer if None."""
        return None

    # ── Clone / State ─────────────────────────────────────────

    def clone(self):
        new = self.__class__()
        new.restore_state(self.save_state())
        return new

    def save_state(self) -> dict:
        return {}

    def restore_state(self, state: dict):
        pass

    def panel_state(self):
        """Return the PanelState binding for this panel's AppSettings key."""
        from AssetsManager.panels.panel_state import PanelState

        return PanelState(self.panel_state_key)

    def persist_panel_state(self) -> None:
        """Persist this panel's save_state snapshot under panel_state_key."""
        if self.panel_state_key:
            self.panel_state().persist(self)

    def restore_panel_state(self) -> bool:
        """Restore this panel from panel_state_key; no-op without a key."""
        if not self.panel_state_key:
            return False
        return self.panel_state().load(self)


class StandardPanel(PanelContent):
    """Industrial slot-based panel scaffolding (Design System 2.0).

    Provides standardized vertical layout slots:
      - Header: Optional panel header / breadcrumbs (for standalone or central canvas)
      - Toolbar: Standard action and search bar (standard height, token-driven spacing)
      - Body: Core content area (Tree, Grid, Table, or ScrollArea) with integrated state overlay
      - Footer: Standard status bar (fixed height metrics.control_height_md = 28px)
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._header_widget: QWidget | None = None
        self._toolbar_widget: QWidget | None = None
        self._body_widget: QWidget | None = None
        self._footer_widget: QWidget | None = None
        self._state_overlay: QWidget | None = None

        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)

        self._connect_lifecycle_bus()

    def _connect_lifecycle_bus(self) -> None:
        """Connect global bus signals for unified theme/lang/scale lifecycle."""
        from AssetsManager.core.signal_bus import get as bus
        self._connect_bus(bus().theme_changed, self._handle_theme_changed)
        self._connect_bus(bus().language_changed, self._handle_language_changed)
        self._connect_bus(bus().ui_scale_changed, self._handle_ui_scale_changed)

    def _handle_theme_changed(self, name: str = "") -> None:
        self.on_theme_changed(name)

    def _handle_language_changed(self, lang: str = "") -> None:
        self.on_language_changed(lang)

    def _handle_ui_scale_changed(self, scale: float = 1.0) -> None:
        self.on_ui_scale_changed(scale)

    def on_theme_changed(self, name: str) -> None:
        pass

    def on_language_changed(self, lang: str) -> None:
        pass

    def on_ui_scale_changed(self, scale: float) -> None:
        pass

    # ── Standard Slots ──────────────────────────────────────────

    def set_header(self, widget: QWidget) -> None:
        """Set or replace the header slot."""
        if self._header_widget is not None:
            self.content_layout.removeWidget(self._header_widget)
            self._header_widget.deleteLater()
        self._header_widget = widget
        self.content_layout.insertWidget(0, widget)

    def set_toolbar(self, widget: QWidget) -> None:
        """Set or replace the toolbar slot."""
        if self._toolbar_widget is not None:
            self.content_layout.removeWidget(self._toolbar_widget)
            self._toolbar_widget.deleteLater()
        self._toolbar_widget = widget
        idx = 1 if self._header_widget is not None else 0
        self.content_layout.insertWidget(idx, widget)

    def set_body(self, widget: QWidget, stretch: int = 1) -> None:
        """Set or replace the main body slot."""
        if self._body_widget is not None:
            self.content_layout.removeWidget(self._body_widget)
            self._body_widget.deleteLater()
        self._body_widget = widget
        idx = 0
        if self._header_widget is not None:
            idx += 1
        if self._toolbar_widget is not None:
            idx += 1
        self.content_layout.insertWidget(idx, widget, stretch)

    def set_footer(self, widget: QWidget) -> None:
        """Set or replace the footer slot."""
        if self._footer_widget is not None:
            self.content_layout.removeWidget(self._footer_widget)
            self._footer_widget.deleteLater()
        self._footer_widget = widget
        self.content_layout.addWidget(widget)

    # ── State Overlay ───────────────────────────────────────────

    def show_state(
        self,
        kind: str = "empty",
        title: str = "",
        subtitle: str = "",
        action_text: str = "",
        on_action: Any = None,
    ) -> None:
        """Show an EmptyStateWidget in place of the body."""
        from AssetsManager.widgets.empty_state import EmptyStateWidget
        if self._state_overlay is None:
            self._state_overlay = EmptyStateWidget(self)
            idx = 0
            if self._header_widget is not None:
                idx += 1
            if self._toolbar_widget is not None:
                idx += 1
            self.content_layout.insertWidget(idx, self._state_overlay, 1)

        from typing import cast
        cast(EmptyStateWidget, self._state_overlay).set_state(
            kind=cast(Any, kind),
            title=title,
            subtitle=subtitle,
            action_text=action_text,
            on_action=on_action,
        )
        self._state_overlay.show()
        if self._body_widget is not None:
            self._body_widget.hide()

    def clear_state(self) -> None:
        """Hide state overlay and restore body content."""
        if self._state_overlay is not None:
            self._state_overlay.hide()
        if self._body_widget is not None:
            self._body_widget.show()

