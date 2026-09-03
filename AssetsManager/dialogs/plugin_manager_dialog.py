"""Plugin Manager Dialog — modern card-based plugin management UI."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from AssetsManager.core import themes
from AssetsManager.core.plugins.manager import PluginManagerService
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.widgets.elevation import refresh_elevation
from AssetsManager.widgets.plugin_ui import PluginCard, PluginDetailPanel
from AssetsManager.widgets.stylekit import StyleKit
from AssetsManager.dialogs.tabbed_dialog import TabbedDialog
from AssetsManager import i18n

_log = logging.getLogger(__name__)
tr = i18n.tr


# ── Main dialog ───────────────────────────────────────────────

class PluginManagerDialog(TabbedDialog):
    """Modern plugin manager with card-based layout."""

    supports_runtime_refresh = True

    def __init__(self, parent: QWidget | None = None):
        self._manager = PluginManagerService.get()
        self._cards: dict[str, PluginCard] = {}
        self._selected_plugin_id: str | None = None
        super().__init__(parent, title=tr("plugins.title", default="Plugin Manager"),
                         min_size=(scaled_px(780), scaled_px(500)))
        self.resize(scaled_px(900), scaled_px(620))
        self._load_plugins()

    def _build_ui(self):

        self._main_layout = QHBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        # ── Left panel (plugin list) ─────────────────────────
        self._left_panel = QWidget()
        self._left_layout = QVBoxLayout(self._left_panel)

        # Title + count
        title_row = QHBoxLayout()
        self._title_label = QLabel(tr("plugins.title", default="Plugin Manager"))
        title_row.addWidget(self._title_label)

        self._count_label = QLabel("")
        title_row.addWidget(self._count_label)
        title_row.addStretch()
        self._left_layout.addLayout(title_row)

        # Search
        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("plugins.search", default="Search plugins..."))
        self._search.textChanged.connect(self._on_filter)
        self._left_layout.addWidget(self._search)

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
        self._left_layout.addWidget(self._list_scroll, 1)

        self._main_layout.addWidget(self._left_panel)

        # ── Right panel (detail) ─────────────────────────────
        self._detail = PluginDetailPanel()
        self._detail.toggle_requested.connect(self._on_toggle_plugin)
        self._main_layout.addWidget(self._detail, 1)
        self._refresh_presentation()

    def _on_theme_changed(self, name):
        super()._on_theme_changed(name)
        self._refresh_presentation()

    def retranslate_ui(self):
        self.setWindowTitle(tr("plugins.title", default="Plugin Manager"))
        self._title_label.setText(tr("plugins.title", default="Plugin Manager"))
        self._search.setPlaceholderText(tr("plugins.search", default="Search plugins..."))
        self._refresh_selected_detail()

    def refresh_scaled_geometry(self, _scale: float | None = None):
        self._refresh_presentation()

    def _refresh_presentation(self):
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        self._left_panel.setFixedWidth(scaled_px(360))
        self._left_panel.setStyleSheet(f"background: {sk.token('header')};")
        sp_md = scaled_px(int(themes.prop("spacing", "md")))
        sp_lg = scaled_px(int(themes.prop("spacing", "lg")))
        self._left_layout.setContentsMargins(sp_md, sp_lg, sp_md, sp_md)
        self._left_layout.setSpacing(scaled_px(10))
        self._list_layout.setSpacing(scaled_px(6))
        self._title_label.setStyleSheet(
            f"font-size: {scaled_pt(int(themes.prop('font_size', 'xl')))}px; font-weight: bold; color: {themes.color('heading')}; background: transparent;")
        self._count_label.setStyleSheet(
            f"font-size: {scaled_pt(int(themes.prop('font_size', 'sm')))}px; color: {themes.color('muted')}; background: transparent;")
        for card in self._cards.values():
            card.refresh_presentation()
        self._detail.refresh_presentation()
        refresh_elevation(self._detail, level=2)
        self._refresh_selected_detail()

    def _refresh_selected_detail(self):
        if self._selected_plugin_id is None:
            self._detail._name_label.setText(tr("plugins.select_hint", default="Select a plugin"))
            self._detail._update_toggle_text()
            return
        record = self._manager.plugin_record(self._selected_plugin_id)
        if record:
            self._detail.show_plugin(self._selected_plugin_id, record)

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

        # If the filter hid the selected card, switch to the first visible one
        # so the detail panel never shows a plugin that is no longer listed.
        selected_id = self._selected_plugin_id
        selected = self._cards.get(selected_id) if selected_id else None
        if selected is not None and selected.isHidden():
            first_visible = next(
                (card for card in self._cards.values() if not card.isHidden()),
                None,
            )
            if first_visible is not None:
                self._select_plugin(first_visible.plugin_id)

    def _on_card_clicked(self, plugin_id: str):
        card = self._cards.get(plugin_id)
        if card and card.is_enabled != self._is_plugin_enabled(plugin_id):
            self._on_toggle_plugin(plugin_id, card.is_enabled)
        self._select_plugin(plugin_id)

    def _select_plugin(self, plugin_id: str):
        self._selected_plugin_id = plugin_id
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
