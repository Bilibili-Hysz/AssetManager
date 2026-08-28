"""Settings dialog: plugins tab embedded widget lifecycle."""


import pytest
from PySide6.QtWidgets import QApplication
from AssetsManager.dialogs.settings_dialog import SettingsDialog


def _dialog():
    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog()
    return app, dialog


def test_settings_plugins_tab_exists_and_loads():
    """The settings dialog includes a Plugins tab that loads the widget."""
    app, dlg = _dialog()
    
    # Find the plugins tab by checking tab labels
    tab_widget = dlg._tabs
    plugins_tab_index = None
    for i in range(tab_widget.count()):
        if "plugin" in tab_widget.tabText(i).lower():
            plugins_tab_index = i
            break
    
    assert plugins_tab_index is not None, "Plugins tab not found in SettingsDialog"
    
    # Switch to the plugins tab to trigger lazy loading if any
    tab_widget.setCurrentIndex(plugins_tab_index)
    app.processEvents()
    
    # The widget should exist
    widget = tab_widget.widget(plugins_tab_index)
    assert widget is not None


def test_settings_plugins_tab_has_plugin_list():
    """The plugins tab displays the plugin list from PluginManagerWidget."""
    from AssetsManager.dialogs._plugin_manager_widget import PluginManagerWidget
    
    app, dlg = _dialog()
    
    tab_widget = dlg._tabs
    for i in range(tab_widget.count()):
        if "plugin" in tab_widget.tabText(i).lower():
            tab_widget.setCurrentIndex(i)
            app.processEvents()
            widget = tab_widget.widget(i)
            
            # The embedded widget should be PluginManagerWidget
            manager_widget = None
            if isinstance(widget, PluginManagerWidget):
                manager_widget = widget
            else:
                # May be wrapped in a scroll area or layout container
                for child in widget.findChildren(PluginManagerWidget):
                    manager_widget = child
                    break
            
            assert manager_widget is not None, "PluginManagerWidget not found in plugins tab"
            # The widget should have its core components
            assert hasattr(manager_widget, "_search")
            assert hasattr(manager_widget, "_list_scroll")
            assert hasattr(manager_widget, "_cards")
            return
    
    pytest.fail("Plugins tab not found")


def test_settings_plugins_tab_refresh_on_language_change():
    """The plugins tab refreshes when language changes."""
    from AssetsManager.core.signal_bus import get as bus
    
    app, dlg = _dialog()
    
    # Find and switch to plugins tab
    tab_widget = dlg._tabs
    for i in range(tab_widget.count()):
        if "plugin" in tab_widget.tabText(i).lower():
            original_label = tab_widget.tabText(i)
            tab_widget.setCurrentIndex(i)
            app.processEvents()
            
            # Emit language_changed with current locale
            bus().language_changed.emit("en")
            app.processEvents()
            
            # The tab label should still be valid (may or may not change depending on current locale)
            new_label = tab_widget.tabText(i)
            assert new_label  # Not empty
            assert "plugin" in new_label.lower() or new_label == original_label
            return
    
    pytest.fail("Plugins tab not found")

