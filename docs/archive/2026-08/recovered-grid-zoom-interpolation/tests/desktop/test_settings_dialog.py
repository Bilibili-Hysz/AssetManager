"""Tests for SettingsDialog runtime refresh behavior."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from AssetsManager import i18n
from AssetsManager.core.settings import AppSettings
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.dialogs.settings_dialog import SettingsDialog


def _dialog():
    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog()
    return app, dialog


def test_settings_language_refresh_preserves_tab_and_inputs():
    app, dialog = _dialog()
    original_language = i18n.current_language()
    try:
        dialog.show()
        app.processEvents()

        # Navigate to general tab and set a value
        dialog._tabs.setCurrentIndex(1)
        dialog._bg_path_edit.setText("C:/assets/background.png")
        initial_tab = dialog._tabs.currentIndex()
        initial_text = dialog._bg_path_edit.text()

        # Switch language
        i18n.set_language("zh")
        app.processEvents()

        # Verify tab and input preserved
        assert dialog._tabs.currentIndex() == initial_tab
        assert dialog._bg_path_edit.text() == initial_text
    finally:
        i18n.set_language(original_language)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_settings_scale_refresh_keeps_state():
    app, dialog = _dialog()
    settings = AppSettings.instance()
    original_scale = settings.get("ui_scale", 1.0)
    try:
        dialog.show()
        app.processEvents()

        # Set a value
        dialog._bg_path_edit.setText("C:/assets/background.png")
        initial_text = dialog._bg_path_edit.text()
        initial_size = dialog.size()

        # Change scale
        settings.set("ui_scale", 1.5)
        bus().ui_scale_changed.emit(1.5)
        app.processEvents()

        # Verify state preserved and size updated
        assert dialog._bg_path_edit.text() == initial_text
        assert dialog.size().width() >= initial_size.width()
        assert dialog.size().height() >= initial_size.height()
    finally:
        settings.set("ui_scale", original_scale)
        bus().ui_scale_changed.emit(original_scale)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
