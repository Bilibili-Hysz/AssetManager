"""Plugin Manager Dialog — modern card-based plugin management UI."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
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
from AssetsManager.core.plugins.descriptor import (
    PLUGIN_STATE_ACTIVE,
    PLUGIN_STATE_DISABLED,
    PLUGIN_STATE_ERROR,
    PLUGIN_STATE_LOADED,
)
from AssetsManager.core.plugins.manager import PluginManagerService
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.dialogs.tabbed_dialog import TabbedDialog
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

        t = themes.get()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(scaled_px(72))
        self._update_style(t)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(scaled_px(12), scaled_px(8), scaled_px(12), scaled_px(8))
        layout.setSpacing(scaled_px(12))

        # Status indicator (colored dot)
        self._status_dot = QLabel()
        self._status_dot.setFixedSize(scaled_px(10), scaled_px(10))
        self._update_dot()
        layout.addWidget(self._status_dot, 0, Qt.AlignmentFlag.AlignVCenter)

        # Plugin info (name + description)
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        name_label = QLabel(name)
        name_label.setStyleSheet(
            f"font-size: {scaled_pt(13)}px; font-weight: bold; color: {t['heading']}; background: transparent; border: none;"
        )
        info_layout.addWidget(name_label)

        desc_text = description[:60] + ("..." if len(description) > 60 else "") if description else plugin_id
        desc_label = QLabel(desc_text)
        desc_label.setStyleSheet(
            f"font-size: {scaled_pt(11)}px; color: {t['muted']}; background: transparent; border: none;"
        )
        info_layout.addWidget(desc_label)

        layout.addLayout(info_layout, 1)

        # Version badge
        ver_label = QLabel(f"v{version}" if version else "")
        ver_label.setStyleSheet(
            f"font-size: {scaled_pt(10)}px; color: {t['muted']}; "
            f"background: {t['header']}; border: 1px solid {t['border']}; "
            f"border-radius: {scaled_px(3)}px; padding: {scaled_px(2)}px {scaled_px(6)}px;"
        )
        layout.addWidget(ver_label, 0, Qt.AlignmentFlag.AlignVCenter)

        # Toggle button
        self._toggle = QToolButton()
        self._toggle.setCheckable(True)
        self._toggle.setChecked(enabled)
        self._toggle.setFixedSize(scaled_px(44), scaled_px(24))
        self._toggle.toggled.connect(self._on_toggle)
        self._update_toggle_style(t)
        layout.addWidget(self._toggle, 0, Qt.AlignmentFlag.AlignVCenter)

    def _update_dot(self):
        t = themes.get()
        if self._state == PLUGIN_STATE_ERROR:
            color = t.get("danger", "#e74c3c")
        elif self._state in (PLUGIN_STATE_ACTIVE, PLUGIN_STATE_LOADED):
            color = t.get("success", "#2ecc71")
        elif self._state == PLUGIN_STATE_DISABLED:
            color = t.get("muted", "#666666")
        else:
            color = t.get("muted", "#999999")
        self._status_dot.setStyleSheet(
            f"background: {color}; border-radius: {scaled_px(5)}px; border: none;"
        )

    def _update_toggle_style(self, t):
        accent = t.get("accent", "#4a60b0")
        muted = t.get("muted", "#666666")
        self._toggle.setStyleSheet(
            f"QToolButton {{ background: {muted}; border-radius: {scaled_px(12)}px; border: none; }}"
            f"QToolButton:checked {{ background: {accent}; }}"
        )

    def _update_style(self, t):
        if self._selected:
            self.setStyleSheet(
                f"PluginCard {{ background: {t['accent']}20; border: 1px solid {t['accent']}; "
                f"border-radius: {scaled_px(6)}px; }}"
            )
        else:
            self.setStyleSheet(
                f"PluginCard {{ background: {t['panel']}; border: 1px solid {t['border']}; "
                f"border-radius: {scaled_px(6)}px; }}"
                f"PluginCard:hover {{ border-color: {t['accent']}80; }}"
            )

    def set_selected(self, selected: bool):
        t = themes.get()
        self._selected = selected
        self._update_style(t)

    def _on_toggle(self, checked: bool):
        self._enabled = checked
        self.clicked.emit(self._plugin_id)

    @property
    def plugin_id(self) -> str:
        return self._plugin_id

    @property
    def is_enabled(self) -> bool:
        return self._toggle.isChecked()


# ── Detail panel ──────────────────────────────────────────────

class PluginDetailPanel(QWidget):
    """Right-side detail panel showing plugin info and actions."""

    toggle_requested = Signal(str, bool)  # plugin_id, enable

    def __init__(self, parent=None):
        super().__init__(parent)
        t = themes.get()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(scaled_px(16), scaled_px(16), scaled_px(16), scaled_px(16))
        layout.setSpacing(scaled_px(12))

        # Plugin name header
        self._name_label = QLabel(tr("plugins.select_hint", default="Select a plugin"))
        self._name_label.setStyleSheet(
            f"font-size: {scaled_pt(18)}px; font-weight: bold; color: {t['heading']};"
        )
        self._name_label.setWordWrap(True)
        layout.addWidget(self._name_label)

        # Status badge
        self._status_badge = QLabel("")
        self._status_badge.setStyleSheet(
            f"font-size: {scaled_pt(11)}px; font-weight: bold; "
            f"border-radius: {scaled_px(3)}px; padding: {scaled_px(2)}px {scaled_px(8)}px;"
        )
        layout.addWidget(self._status_badge)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {t['border']};")
        layout.addWidget(sep)

        # Info fields
        self._fields_widget = QWidget()
        self._fields_layout = QVBoxLayout(self._fields_widget)
        self._fields_layout.setContentsMargins(0, 0, 0, 0)
        self._fields_layout.setSpacing(scaled_px(6))
        layout.addWidget(self._fields_widget)

        # Description
        self._desc_label = QLabel("")
        self._desc_label.setWordWrap(True)
        self._desc_label.setStyleSheet(
            f"font-size: {scaled_pt(12)}px; color: {t['body']}; padding: {scaled_px(4)}px 0;"
        )
        layout.addWidget(self._desc_label)

        # Diagnostics (error messages)
        self._diag_label = QLabel("")
        self._diag_label.setWordWrap(True)
        self._diag_label.setStyleSheet(
            f"font-size: {scaled_pt(11)}px; color: {t.get('danger', '#e74c3c')}; "
            f"background: {t.get('danger', '#e74c3c')}15; border: 1px solid {t.get('danger', '#e74c3c')}30; "
            f"border-radius: {scaled_px(4)}px; padding: {scaled_px(8)}px;"
        )
        self._diag_label.setVisible(False)
        layout.addWidget(self._diag_label)

        layout.addStretch()

        # Action buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(scaled_px(8))

        self._toggle_btn = QPushButton(tr("plugins.toggle", default="Toggle Enabled"))
        self._toggle_btn.setStyleSheet(
            f"QPushButton {{ background: {t['accent']}; color: {t.get('on_accent', 'white')}; border: none; "
            f"padding: {scaled_px(8)}px {scaled_px(16)}px; border-radius: {scaled_px(4)}px; "
            f"font-size: {scaled_pt(12)}px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {t['accent']}cc; }}"
        )
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.clicked.connect(self._on_toggle)
        btn_layout.addWidget(self._toggle_btn)

        layout.addLayout(btn_layout)

        self._current_pid = None
        self._current_enabled = False

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
            badge_color = t.get("danger", "#e74c3c")
        elif state in (PLUGIN_STATE_ACTIVE, PLUGIN_STATE_LOADED):
            badge_text = tr("plugins.state.active", default="Active")
            badge_color = t.get("success", "#2ecc71")
        elif state == PLUGIN_STATE_DISABLED:
            badge_text = tr("plugins.state.disabled", default="Disabled")
            badge_color = t.get("muted", "#666666")
        else:
            badge_text = state
            badge_color = t.get("muted", "#999999")

        self._status_badge.setText(badge_text)
        self._status_badge.setStyleSheet(
            f"font-size: {scaled_pt(11)}px; font-weight: bold; color: white; "
            f"background: {badge_color}; border-radius: {scaled_px(3)}px; "
            f"padding: {scaled_px(2)}px {scaled_px(8)}px;"
        )

        # Fields
        self._clear_fields()
        if desc:
            self._add_field(tr("plugins.detail.id"), desc.id)
            self._add_field(tr("plugins.detail.version"), desc.version)
            if desc.description:
                self._add_field(tr("plugins.detail.description"), desc.description)
            self._add_field(tr("plugins.detail.kind"), desc.kind)
            if desc.permissions:
                self._add_field(tr("plugins.detail.permissions"), ", ".join(sorted(desc.permissions)))
            if desc.display_fields:
                fields = [f"{df.key} ({df.type})" for df in desc.display_fields]
                self._add_field(tr("plugins.detail.display_fields"), ", ".join(fields))
        self._add_field(tr("plugins.detail.root"), record.root_dir)

        # Description
        if desc and desc.description:
            self._desc_label.setText(desc.description)
            self._desc_label.setVisible(True)
        else:
            self._desc_label.setVisible(False)

        # Diagnostics
        if record.diagnostics:
            diag_lines = [f"[{d.level}] {d.code}: {d.message}" for d in record.diagnostics]
            self._diag_label.setText("\n".join(diag_lines))
            self._diag_label.setVisible(True)
        else:
            self._diag_label.setVisible(False)

        # Toggle button
        self._current_enabled = record.enabled
        self._update_toggle_text()

    def _add_field(self, label: str, value: str):
        t = themes.get()
        row = QHBoxLayout()
        row.setSpacing(scaled_px(8))

        lbl = QLabel(f"{label}:")
        lbl.setStyleSheet(
            f"font-size: {scaled_pt(11)}px; font-weight: bold; color: {t['muted']}; "
            f"background: transparent; border: none; min-width: {scaled_px(80)}px;"
        )
        row.addWidget(lbl)

        val = QLabel(str(value))
        val.setStyleSheet(
            f"font-size: {scaled_pt(11)}px; color: {t['heading']}; background: transparent; border: none;"
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
            self._toggle_btn.setText(tr("plugins.disable", default="Disable"))
        else:
            self._toggle_btn.setText(tr("plugins.enable", default="Enable"))

    def _on_toggle(self):
        if self._current_pid:
            self._current_enabled = not self._current_enabled
            self._update_toggle_text()
            self.toggle_requested.emit(self._current_pid, self._current_enabled)


# ── Main dialog ───────────────────────────────────────────────

class PluginManagerDialog(TabbedDialog):
    """Modern plugin manager with card-based layout."""

    def __init__(self, parent: QWidget | None = None):
        self._manager = PluginManagerService.get()
        self._cards: dict[str, PluginCard] = {}
        super().__init__(parent, title=tr("plugins.title", default="Plugin Manager"),
                         min_size=(scaled_px(780), scaled_px(500)))
        self.resize(scaled_px(900), scaled_px(620))
        self._load_plugins()

    def _build_ui(self):
        t = self._t
        self.setStyleSheet(self._dialog_qss())

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Left panel (plugin list) ─────────────────────────
        left_panel = QWidget()
        left_panel.setFixedWidth(scaled_px(360))
        left_panel.setStyleSheet(f"background: {t['header']};")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(scaled_px(12), scaled_px(16), scaled_px(12), scaled_px(12))
        left_layout.setSpacing(scaled_px(10))

        # Title + count
        title_row = QHBoxLayout()
        title = QLabel(tr("plugins.title", default="Plugin Manager"))
        title.setStyleSheet(
            f"font-size: {scaled_pt(16)}px; font-weight: bold; color: {t['heading']}; background: transparent;"
        )
        title_row.addWidget(title)

        self._count_label = QLabel("")
        self._count_label.setStyleSheet(
            f"font-size: {scaled_pt(11)}px; color: {t['muted']}; background: transparent;"
        )
        title_row.addWidget(self._count_label)
        title_row.addStretch()
        left_layout.addLayout(title_row)

        # Search
        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("plugins.search", default="Search plugins..."))
        self._search.textChanged.connect(self._on_filter)
        left_layout.addWidget(self._search)

        # Plugin list scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(scaled_px(6))
        self._list_layout.addStretch()
        scroll.setWidget(self._list_widget)
        left_layout.addWidget(scroll, 1)

        main_layout.addWidget(left_panel)

        # ── Right panel (detail) ─────────────────────────────
        self._detail = PluginDetailPanel()
        self._detail.toggle_requested.connect(self._on_toggle_plugin)
        main_layout.addWidget(self._detail, 1)

    def _load_plugins(self):
        records = self._manager._records
        self._cards.clear()

        # Clear existing cards
        while self._list_layout.count() > 1:  # Keep the stretch
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
            self._cards[pid] = card
            self._list_layout.insertWidget(self._list_layout.count() - 1, card)

        count = len(records)
        active = sum(1 for r in records.values() if r.enabled)
        self._count_label.setText(f"{active}/{count}")

        # Auto-select first
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

    def _on_card_clicked(self, plugin_id: str):
        card = self._cards.get(plugin_id)
        if card and card.is_enabled != self._is_plugin_enabled(plugin_id):
            self._on_toggle_plugin(plugin_id, card.is_enabled)
        self._select_plugin(plugin_id)

    def _select_plugin(self, plugin_id: str):
        for pid, card in self._cards.items():
            card.set_selected(pid == plugin_id)

        record = self._manager.plugin_record(plugin_id)
        if record:
            self._detail.show_plugin(plugin_id, record)

    def _is_plugin_enabled(self, plugin_id: str) -> bool:
        record = self._manager.plugin_record(plugin_id)
        return record.enabled if record else False

    def _on_toggle_plugin(self, plugin_id: str, enable: bool):
        if enable:
            self._manager.enable_plugin(plugin_id)
        else:
            self._manager.disable_plugin(plugin_id)

        # Refresh the affected card
        card = self._cards.get(plugin_id)
        record = self._manager.plugin_record(plugin_id)
        if card and record:
            card._enabled = record.enabled
            card._state = record.state
            card._update_dot()
            card._toggle.setChecked(record.enabled)

        # Update count
        records = self._manager._records
        active = sum(1 for r in records.values() if r.enabled)
        self._count_label.setText(f"{active}/{len(records)}")

        # Refresh detail if this plugin is selected
        if record:
            self._detail.show_plugin(plugin_id, record)
