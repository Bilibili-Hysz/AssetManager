"""Plugin manager widget — embeddable card-based plugin UI for settings tab.

Extracted from PluginManagerDialog to support both standalone dialog and
embedded tab usage.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from AssetsManager.core import themes
from AssetsManager.core import icons
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.plugins.descriptor import (
    PLUGIN_STATE_ACTIVE,
    PLUGIN_STATE_DISABLED,
    PLUGIN_STATE_ERROR,
    PLUGIN_STATE_LOADED,
)
from AssetsManager.core.plugins.manager import PluginManagerService
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.widgets.stylekit import StyleKit
from AssetsManager import i18n

_log = logging.getLogger(__name__)
tr = i18n.tr


# ── Plugin card widget ────────────────────────────────────────

class PluginCard(QFrame):
    """A single plugin card with status, toggle, and click-to-select."""

    clicked = Signal(str)  # plugin_id

    def __init__(self, plugin_id: str, name: str, version: str,
                 description: str, state: str, enabled: bool, parent=None):
        super().__init__(parent)
        self._plugin_id = plugin_id
        self._enabled = enabled
        self._state = state
        self._selected = False
        self._name = name
        self._version = version
        self._description = description

        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._layout = QHBoxLayout(self)

        # Status indicator (colored dot)
        self._status_dot = QLabel()
        self._layout.addWidget(self._status_dot, 0, Qt.AlignmentFlag.AlignVCenter)

        # Plugin info (name + description)
        self._info_layout = QVBoxLayout()

        self._name_label = QLabel(name)
        self._info_layout.addWidget(self._name_label)

        desc_text = description[:60] + ("..." if len(description) > 60 else "") if description else plugin_id
        self._desc_label = QLabel(desc_text)
        self._info_layout.addWidget(self._desc_label)

        self._layout.addLayout(self._info_layout, 1)

        # Version badge
        self._version_label = QLabel(f"v{version}" if version else "")
        self._layout.addWidget(self._version_label, 0, Qt.AlignmentFlag.AlignVCenter)

        # Toggle button
        self._toggle = QToolButton()
        self._toggle.setCheckable(True)
        self._toggle.setChecked(enabled)
        self._toggle.setAccessibleName(tr("plugins.toggle", default="Toggle Enabled"))
        self._toggle.setToolTip(tr("plugins.toggle", default="Toggle Enabled"))
        self._toggle.toggled.connect(self._on_toggle)
        self._layout.addWidget(self._toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        self.refresh_presentation()

    def refresh_presentation(self):
        t = themes.get()
        self.setFixedHeight(scaled_px(72))
        br_sm = scaled_px(int(themes.prop("border_radius", "sm")))
        sp_xs = scaled_px(int(themes.prop("spacing", "xs")))
        sp_md = scaled_px(int(themes.prop("spacing", "md")))
        self._layout.setContentsMargins(sp_md, scaled_px(int(themes.prop("spacing", "sm"))), sp_md, scaled_px(int(themes.prop("spacing", "sm"))))
        self._layout.setSpacing(sp_md)
        self._info_layout.setSpacing(scaled_px(2))

        # Status dot
        dot_size = scaled_px(8)
        self._status_dot.setFixedSize(dot_size, dot_size)
        if self._state == PLUGIN_STATE_ERROR:
            color = t["danger"]
        elif self._state in (PLUGIN_STATE_ACTIVE, PLUGIN_STATE_LOADED):
            color = t["success"]
        elif self._state == PLUGIN_STATE_DISABLED:
            color = t["muted"]
        else:
            color = t["muted"]
        self._status_dot.setStyleSheet(
            f"background: {color}; border-radius: {dot_size // 2}px;")

        # Card styling
        bg = t["header"] if self._selected else t["panel"]
        self.setStyleSheet(
            f"PluginCard {{ background: {bg}; border: {scaled_px(1)}px solid {t['border']}; border-radius: {br_sm}px; }}"
            f"PluginCard:hover {{ background: {t['header']}; }}"
        )

        # Name + description
        self._name_label.setStyleSheet(
            f"font-size: {scaled_pt(int(themes.prop('font_size', 'md')))}px; "
            f"font-weight: bold; color: {t['heading']}; background: transparent; border: none;")
        self._desc_label.setStyleSheet(
            f"font-size: {scaled_pt(int(themes.prop('font_size', 'sm')))}px; "
            f"color: {t['muted']}; background: transparent; border: none;")

        # Version badge
        self._version_label.setStyleSheet(
            f"font-size: {scaled_pt(int(themes.prop('font_size', 'xs')))}px; "
            f"color: {t['muted']}; background: {alpha(t['muted'], 0.12)}; "
            f"padding: {sp_xs}px {scaled_px(8)}px; border-radius: {br_sm}px;")

        # Toggle button
        self._toggle.setFixedSize(scaled_px(36), scaled_px(24))
        toggle_bg = t["success"] if self._enabled else t["muted"]
        self._toggle.setStyleSheet(
            f"QToolButton {{ background: {toggle_bg}; border: none; border-radius: {scaled_px(12)}px; }}"
            f"QToolButton:hover {{ background: {alpha(toggle_bg, 0.9)}; }}"
        )

    def set_selected(self, selected: bool):
        self._selected = selected
        self.refresh_presentation()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._plugin_id)
        super().mousePressEvent(event)

    def _on_toggle(self, checked: bool):
        pass  # Handled by parent via PluginManagerWidget.toggle_requested


# ── Plugin detail panel ───────────────────────────────────────

class PluginDetailPanel(QFrame):
    """Right panel showing selected plugin details."""

    toggle_requested = Signal(str, bool)  # plugin_id, new_enabled

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)

        # Plugin name
        self._name_label = QLabel("")
        self._layout.addWidget(self._name_label)

        # Status badge
        self._status_badge = QLabel("")
        self._layout.addWidget(self._status_badge)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        self._separator = sep
        self._layout.addWidget(sep)

        # Info fields
        self._fields_widget = QWidget()
        self._fields_layout = QVBoxLayout(self._fields_widget)
        self._fields_layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self._fields_widget)

        # Description
        self._desc_label = QLabel("")
        self._desc_label.setWordWrap(True)
        self._layout.addWidget(self._desc_label)

        # Diagnostics (error messages)
        self._diag_label = QLabel("")
        self._diag_label.setWordWrap(True)
        self._diag_label.setVisible(False)
        self._layout.addWidget(self._diag_label)

        self._layout.addStretch()

        # Action buttons
        self._button_layout = QHBoxLayout()

        self._toggle_btn = QPushButton(tr("plugins.toggle", default="Toggle Enabled"))
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setAccessibleName(tr("plugins.toggle", default="Toggle Enabled"))
        themes.set_button_variant(self._toggle_btn, "primary")
        self._toggle_btn.clicked.connect(self._on_toggle)
        self._button_layout.addWidget(self._toggle_btn)

        self._layout.addLayout(self._button_layout)

        self._current_pid = None
        self._current_enabled = False
        self.refresh_presentation()

    def refresh_presentation(self):
        t = themes.get()
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        br_sm = scaled_px(int(themes.prop("border_radius", "sm")))
        sp_sm = scaled_px(int(themes.prop("spacing", "sm")))
        sp_lg = scaled_px(int(themes.prop("spacing", "lg")))
        self._layout.setContentsMargins(sp_lg, sp_lg, sp_lg, sp_lg)
        self._layout.setSpacing(scaled_px(int(themes.prop("spacing", "md"))))
        self._fields_layout.setSpacing(scaled_px(6))
        self._button_layout.setSpacing(sp_sm)
        self._name_label.setStyleSheet(sk.label_css("heading", size=18, bold=True))
        self._separator.setStyleSheet(f"color: {sk.token('border_subtle')};")
        self._desc_label.setStyleSheet(sk.label_css("body", size=12))
        danger = t["danger"]
        self._diag_label.setStyleSheet(
            f"font-size: {scaled_pt(int(themes.prop('font_size', 'sm')))}px; color: {danger}; background: {alpha(danger, 0.08)}; "
            f"border: {scaled_px(1)}px solid {alpha(danger, 0.19)}; border-radius: {br_sm}px; padding: {sp_sm}px;")
        self._toggle_btn.setStyleSheet(
            sk.button_css("primary", font_size_key="sm",
                          padding_y=sp_sm, padding_x=sp_lg))
        self._update_toggle_text()

    def show_plugin(self, plugin_id: str, record):
        """Display plugin details."""
        self._current_pid = plugin_id
        desc = record.descriptor
        t = themes.get()

        # Name
        name = desc.name if desc else plugin_id
        self._name_label.setText(name)

        # Status badge
        state = record.state
        if state == PLUGIN_STATE_ERROR:
            badge_text = tr("plugins.state.error", default="Error")
            badge_color = t["danger"]
        elif state in (PLUGIN_STATE_ACTIVE, PLUGIN_STATE_LOADED):
            badge_text = tr("plugins.state.active", default="Active")
            badge_color = t["success"]
        elif state == PLUGIN_STATE_DISABLED:
            badge_text = tr("plugins.state.disabled", default="Disabled")
            badge_color = t["muted"]
        else:
            badge_text = tr("plugins.state.loadable", default="Loadable")
            badge_color = t["muted"]

        self._status_badge.setText(badge_text)
        br_sm = scaled_px(int(themes.prop("border_radius", "sm")))
        sp_xs = scaled_px(int(themes.prop("spacing", "xs")))
        self._status_badge.setStyleSheet(
            f"font-size: {scaled_pt(int(themes.prop('font_size', 'xs')))}px; "
            f"color: {badge_color}; background: {alpha(badge_color, 0.15)}; "
            f"padding: {sp_xs}px {scaled_px(8)}px; border-radius: {br_sm}px;")
        self._status_badge.setVisible(True)

        # Fields
        self._clear_fields()
        if desc:
            if desc.version:
                self._add_field(tr("plugins.field.version", default="Version"), desc.version)
            if desc.author:
                self._add_field(tr("plugins.field.author", default="Author"), desc.author)
            self._add_field(tr("plugins.field.id", default="ID"), plugin_id)

        # Description
        description = desc.description if desc and desc.description else tr("plugins.no_description", default="No description available.")
        self._desc_label.setText(description)

        # Diagnostics
        if record.error_message:
            self._diag_label.setText(f"⚠️ {record.error_message}")
            self._diag_label.setVisible(True)
        else:
            self._diag_label.setVisible(False)

        # Toggle state
        self._current_enabled = record.enabled
        self._update_toggle_text()

    def _add_field(self, label: str, value: str):
        t = themes.get()
        fs_sm = scaled_pt(int(themes.prop("font_size", "sm")))
        row = QHBoxLayout()
        row.setSpacing(scaled_px(int(themes.prop("spacing", "sm"))))

        lbl = QLabel(f"{label}:")
        lbl.setStyleSheet(
            f"font-size: {fs_sm}px; font-weight: bold; color: {t['muted']}; "
            f"background: transparent; border: none; min-width: {scaled_px(80)}px;"
        )
        row.addWidget(lbl)

        val = QLabel(str(value))
        val.setStyleSheet(
            f"font-size: {fs_sm}px; color: {t['heading']}; background: transparent; border: none;"
        )
        val.setWordWrap(True)
        row.addWidget(val, 1)

        container = QWidget()
        container.setLayout(row)
        container.setStyleSheet("background: transparent;")
        self._fields_layout.addWidget(container)

    def _clear_fields(self):
        while self._fields_layout.count():
            item = self._fields_layout.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.deleteLater()

    def _update_toggle_text(self):
        if self._current_enabled:
            label = tr("plugins.disable", default="Disable")
            icon_name = "close"
        else:
            label = tr("plugins.enable", default="Enable")
            icon_name = "check"
        self._toggle_btn.setText(label)
        self._toggle_btn.setIcon(
            icons.icon(icon_name, color="icon_on_accent", size=scaled_px(15)))
        self._toggle_btn.setIconSize(QSize(scaled_px(15), scaled_px(15)))
        self._toggle_btn.setAccessibleName(label)
        self._toggle_btn.setToolTip(label)

    def _on_toggle(self):
        if self._current_pid:
            self._current_enabled = not self._current_enabled
            self._update_toggle_text()
            self.toggle_requested.emit(self._current_pid, self._current_enabled)


# ── Main widget ───────────────────────────────────────────────

class PluginManagerWidget(QWidget):
    """Embeddable plugin manager with vertical card layout."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._manager = PluginManagerService.get()
        self._cards: dict[str, PluginCard] = {}
        self._selected_plugin_id: str | None = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(scaled_px(int(themes.prop("spacing", "md"))))

        # Search
        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("plugins.search", default="Search plugins..."))
        self._search.textChanged.connect(self._on_filter)
        self._layout.addWidget(self._search)

        # Plugin list scroll area
        self._list_scroll = QScrollArea()
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(scaled_px(6))
        self._list_layout.addStretch()
        self._list_scroll.setWidget(self._list_widget)
        self._layout.addWidget(self._list_scroll)

        self._load_plugins()

    def refresh_presentation(self):
        for card in self._cards.values():
            card.refresh_presentation()

    def _load_plugins(self):
        records = self._manager._records
        self._cards.clear()

        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.deleteLater()

        for pid, record in records.items():
            desc = record.descriptor
            name = desc.name if desc else pid
            version = desc.version if desc else ""
            description = desc.description or "" if desc else ""

            card = PluginCard(pid, name, version, description, record.state, record.enabled)
            card.clicked.connect(self._on_card_clicked)
            card._toggle.toggled.connect(lambda checked, p=pid: self._on_toggle_plugin(p, checked))
            self._cards[pid] = card
            self._list_layout.insertWidget(self._list_layout.count() - 1, card)

        if self._cards:
            first_pid = next(iter(self._cards))
            self._select_plugin(first_pid)

    def _on_filter(self, text: str):
        text_lower = text.lower()
        for pid, card in self._cards.items():
            record = self._manager.plugin_record(pid)
            desc = record.descriptor if record else None
            name = (desc.name if desc else pid).lower()
            description = (desc.description or "" if desc else "").lower()
            visible = not text or text_lower in name or text_lower in pid.lower() or text_lower in description
            card.setVisible(visible)

        selected_id = self._selected_plugin_id
        selected = self._cards.get(selected_id) if selected_id else None
        if selected and not selected.isVisible():
            for pid, card in self._cards.items():
                if card.isVisible():
                    self._select_plugin(pid)
                    break

    def _on_card_clicked(self, plugin_id: str):
        self._select_plugin(plugin_id)

    def _select_plugin(self, plugin_id: str):
        if self._selected_plugin_id == plugin_id:
            return
        if self._selected_plugin_id:
            old = self._cards.get(self._selected_plugin_id)
            if old:
                old.set_selected(False)
        self._selected_plugin_id = plugin_id
        card = self._cards.get(plugin_id)
        if card:
            card.set_selected(True)

    def _on_toggle_plugin(self, plugin_id: str, new_enabled: bool):
        if new_enabled:
            self._manager.enable_plugin(plugin_id)
        else:
            self._manager.disable_plugin(plugin_id)
        record = self._manager.plugin_record(plugin_id)
        if record:
            card = self._cards.get(plugin_id)
            if card:
                card._enabled = record.enabled
                card._state = record.state
                card.refresh_presentation()
