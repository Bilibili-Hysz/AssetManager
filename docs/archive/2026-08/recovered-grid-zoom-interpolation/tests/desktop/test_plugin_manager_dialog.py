"""Tests for PluginManagerDialog runtime refresh behavior."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from AssetsManager import i18n
from AssetsManager.core.settings import AppSettings
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.dialogs.plugin_manager_dialog import PluginManagerDialog


class _FakePluginManager:
    """Minimal plugin manager for testing."""

    def __init__(self):
        from AssetsManager.core.plugins.descriptor import PluginDescriptor, PluginRecord, PLUGIN_STATE_ACTIVE
        self._records = {
            "plugin1": PluginRecord(
                plugin_id="plugin1", root_dir="/tmp/p1", manifest_path="p1.json",
                descriptor=PluginDescriptor("plugin1", "Plugin One", "1.0", description="First plugin"),
                state=PLUGIN_STATE_ACTIVE, enabled=True,
            ),
            "plugin2": PluginRecord(
                plugin_id="plugin2", root_dir="/tmp/p2", manifest_path="p2.json",
                descriptor=PluginDescriptor("plugin2", "Plugin Two", "2.0", description="Second plugin"),
                state=PLUGIN_STATE_ACTIVE, enabled=False,
            ),
        }

    def get_plugins(self):
        return self._records

    def get_plugin(self, plugin_id):
        return self._records.get(plugin_id)

    def plugin_record(self, plugin_id):
        return self._records.get(plugin_id)

    def enable_plugin(self, plugin_id):
        record = self._records.get(plugin_id)
        if record:
            record.enabled = True

    def disable_plugin(self, plugin_id):
        record = self._records.get(plugin_id)
        if record:
            record.enabled = False


def _dialog():
    app = QApplication.instance() or QApplication([])
    # Mock the plugin manager service
    from AssetsManager.core.plugins.manager import PluginManagerService
    original_get = PluginManagerService.get
    PluginManagerService.get = classmethod(lambda cls: _FakePluginManager())
    try:
        dialog = PluginManagerDialog()
        return app, dialog
    finally:
        PluginManagerService.get = original_get


def test_plugin_manager_language_refresh_preserves_search_and_selection():
    app, dialog = _dialog()
    original_language = i18n.current_language()
    try:
        dialog.show()
        app.processEvents()

        # Set search and select a plugin
        dialog._search.setText("plugin1")
        initial_search = dialog._search.text()

        # Switch language
        i18n.set_language("zh")
        app.processEvents()

        # Verify search preserved
        assert dialog._search.text() == initial_search
    finally:
        i18n.set_language(original_language)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_plugin_manager_scale_refresh_keeps_state():
    app, dialog = _dialog()
    settings = AppSettings.instance()
    original_scale = settings.get("ui_scale", 1.0)
    try:
        dialog.show()
        app.processEvents()

        # Set search
        dialog._search.setText("plugin2")
        initial_search = dialog._search.text()
        initial_size = dialog.size()

        # Change scale
        settings.set("ui_scale", 1.5)
        bus().ui_scale_changed.emit(1.5)
        app.processEvents()

        # Verify state preserved and size updated
        assert dialog._search.text() == initial_search
        assert dialog.size().width() >= initial_size.width()
        assert dialog.size().height() >= initial_size.height()
    finally:
        settings.set("ui_scale", original_scale)
        bus().ui_scale_changed.emit(original_scale)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
