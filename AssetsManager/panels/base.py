"""Base panel content with signal interface and context support."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton

from AssetsManager import i18n
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
        self._show_anim.setDuration(200)
        self._show_anim.setStartValue(0.0)
        self._show_anim.setEndValue(1.0)
        self._show_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
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

    def shutdown(self):
        """Disconnect all tracked bus signals before panel destruction."""
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
        t = themes.get()
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
            f"color: {t['heading']}; padding: 0; background: transparent; border: none; "
            f"border-radius: {scaled_px(int(themes.prop('border_radius', 'sm')))}px;")
        gear.setCursor(Qt.CursorShape.PointingHandCursor)
        gear.clicked.connect(lambda: generic_settings_dialog(self))
        return [gear]

    # ── Footer bar ────────────────────────────────────────────────

    def footer_bar(self) -> QWidget | None:
        """Override to provide a footer bar widget (e.g. action buttons).
        Returns None by default — dock_factory skips footer if None."""
        return None

    # ── Browser context ──────────────────────────────────────────

    def set_browser_context(self, ctx):
        self._context = ctx

    def get_browser_context(self):
        return self._context

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

    # ── Header ───────────────────────────────────────────────

    def set_title(self, title: str):
        self.setWindowTitle(title)

    # ── Status ───────────────────────────────────────────────

    def set_status_hint(self, text: str):
        self.status_hint = text

    # ── Settings ─────────────────────────────────────────────

    def refresh_visual_settings(self):
        pass

    def apply_app_settings(self, changes=None):
        pass

    def retranslate_ui(self):
        pass
