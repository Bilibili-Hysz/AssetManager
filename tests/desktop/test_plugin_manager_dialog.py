

from PySide6.QtWidgets import QApplication

from AssetsManager import i18n
from AssetsManager.core.plugins.descriptor import (
    PLUGIN_STATE_ACTIVE,
    PluginDescriptor,
    PluginRecord,
)
from AssetsManager.core.settings import AppSettings
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.dialogs.plugin_manager_dialog import PluginManagerDialog


class _PluginManager:
    def __init__(self):
        self._records = {
            "one": PluginRecord(
                plugin_id="one", root_dir="C:/plugins/one", manifest_path="one.json",
                descriptor=PluginDescriptor("one", "One", "1.0", description="First plugin"),
                state=PLUGIN_STATE_ACTIVE, enabled=True,
            ),
            "two": PluginRecord(
                plugin_id="two", root_dir="C:/plugins/two", manifest_path="two.json",
                descriptor=PluginDescriptor("two", "Two", "2.0", description="Second plugin"),
                state=PLUGIN_STATE_ACTIVE, enabled=True,
            ),
        }
        self.toggle_calls = []

    def plugin_record(self, plugin_id):
        return self._records.get(plugin_id)

    def enable_plugin(self, plugin_id):
        self.toggle_calls.append((plugin_id, True))
        self._records[plugin_id].enabled = True

    def disable_plugin(self, plugin_id):
        self.toggle_calls.append((plugin_id, False))
        self._records[plugin_id].enabled = False


def _dialog(monkeypatch):
    from AssetsManager.core.plugins.manager import PluginManagerService

    manager = _PluginManager()
    monkeypatch.setattr(PluginManagerService, "get", lambda: manager)
    app = QApplication.instance() or QApplication([])
    return app, PluginManagerDialog(), manager


def test_plugin_manager_language_refresh_preserves_cards_filter_and_selection(monkeypatch):
    app, dialog, manager = _dialog(monkeypatch)
    original_language = i18n.current_language()
    try:
        dialog.show()
        app.processEvents()
        dialog._select_plugin("two")
        dialog._search.setText("two")
        card = dialog._cards["two"]

        i18n.set_language("zh")
        app.processEvents()

        assert dialog._cards["two"] is card
        assert dialog._selected_plugin_id == "two"
        assert dialog._search.text() == "two"
        assert card.isVisible()
        assert not dialog._cards["one"].isVisible()
        assert dialog._title_label.text() == i18n.tr("plugins.title", default="Plugin Manager")
        assert dialog._detail._toggle_btn.text() == i18n.tr("plugins.disable", default="Disable")
        assert manager.toggle_calls == []
    finally:
        i18n.set_language(original_language)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_plugin_manager_scale_refresh_keeps_state_and_updates_card_constraints(monkeypatch):
    app, dialog, manager = _dialog(monkeypatch)
    settings = AppSettings.instance()
    original_scale = settings.get("ui_scale", 1.0)
    try:
        dialog.show()
        app.processEvents()
        dialog._select_plugin("two")
        dialog._search.setText("two")
        initial_size = dialog.size()
        card = dialog._cards["two"]

        settings.set("ui_scale", 1.5)
        bus().ui_scale_changed.emit(1.5)
        app.processEvents()

        assert dialog.size() == initial_size
        assert dialog._selected_plugin_id == "two"
        assert dialog._search.text() == "two"
        assert card.height() == scaled_px(72)
        assert card._toggle.size().width() == scaled_px(44)
        assert manager.toggle_calls == []
    finally:
        settings.set("ui_scale", original_scale)
        bus().ui_scale_changed.emit(original_scale)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
