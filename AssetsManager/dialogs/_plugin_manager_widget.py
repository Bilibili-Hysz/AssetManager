"""Plugin manager widget — embeddable card-based plugin UI for settings tab.

Consumes the shared :mod:`AssetsManager.widgets.plugin_ui` components
(audit I5, finding D6): the card and detail implementations live there so
this embedded view and the standalone :class:`PluginManagerDialog` stay in
lockstep.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from AssetsManager.core import themes
from AssetsManager.core.plugins.manager import PluginManagerService
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.widgets.plugin_ui import PluginCard
from AssetsManager import i18n

tr = i18n.tr


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
