import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialogButtonBox

from AssetsManager import i18n
from AssetsManager.core.settings import AppSettings
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.dialogs.settings_dialog import SettingsDialog


def _dialog():
    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog()
    return app, dialog


def _option_button(group, key):
    return next(button for button in group.buttons() if button.property("option_key") == key)


def test_settings_language_refresh_updates_chrome_without_resetting_inputs():
    app, dialog = _dialog()
    original_language = i18n.current_language()
    try:
        dialog.show()
        app.processEvents()
        dialog._tabs.setCurrentIndex(2)
        dialog._bg_path_edit.setText("C:/assets/background.png")
        dialog._bg_enabled_cb.setChecked(not dialog._bg_enabled_cb.isChecked())
        high_quality = _option_button(dialog._thumb_group, "high")
        high_quality.setChecked(True)
        original_path_edit = dialog._bg_path_edit
        original_thumb_button = high_quality

        i18n.set_language("zh")
        app.processEvents()

        assert dialog.windowTitle() == "外观设置"
        assert dialog._tabs.currentIndex() == 2
        assert dialog._bg_path_edit is original_path_edit
        assert dialog._bg_path_edit.text() == "C:/assets/background.png"
        assert _option_button(dialog._thumb_group, "high") is original_thumb_button
        assert original_thumb_button.isChecked()
        assert dialog._tabs.tabText(0) == "外观"
        assert dialog._bg_enabled_cb.text() == "启用背景图片"
        assert dialog._button_box.button(QDialogButtonBox.StandardButton.Ok).text() == "确定"
    finally:
        i18n.set_language(original_language)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_settings_scale_refresh_keeps_current_size_and_values():
    app, dialog = _dialog()
    settings = AppSettings.instance()
    original_scale = settings.get("ui_scale", 1.0)
    try:
        dialog.show()
        app.processEvents()
        settings.set("ui_scale", 1.0)
        bus().ui_scale_changed.emit(1.0)
        app.processEvents()
        dialog._tabs.setCurrentIndex(1)
        dialog._bg_path_edit.setText("C:/assets/background.png")
        initial_size = dialog.size()
        initial_spacing = dialog._appearance_layout.spacing()

        settings.set("ui_scale", 1.5)
        bus().ui_scale_changed.emit(1.5)
        app.processEvents()

        assert dialog.size().width() >= initial_size.width()
        assert dialog.size().height() >= initial_size.height()
        assert dialog._tabs.currentIndex() == 1
        assert dialog._bg_path_edit.text() == "C:/assets/background.png"
        assert dialog._appearance_layout.spacing() == scaled_px(12)
        assert dialog._appearance_layout.spacing() != initial_spacing
        assert dialog.minimumWidth() == scaled_px(460)
        assert dialog.minimumHeight() == scaled_px(520)
        assert dialog._lang_group_box.layout().spacing() == scaled_px(2)
        assert dialog._ui_scale_slider.value() == 150
        assert dialog._ui_scale_label.text() == "150%"
    finally:
        settings.set("ui_scale", original_scale)
        bus().ui_scale_changed.emit(original_scale)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_settings_refresh_signals_disconnect_on_close_and_reconnect_on_show():
    app, dialog = _dialog()
    original_language = i18n.current_language()
    try:
        i18n.set_language("en")
        dialog.show()
        app.processEvents()
        assert dialog.windowTitle() == "Appearance Settings"

        dialog.close()
        i18n.set_language("zh")
        app.processEvents()
        assert dialog.windowTitle() == "Appearance Settings"

        dialog.show()
        app.processEvents()
        i18n.set_language("ja")
        app.processEvents()
        assert dialog.windowTitle() == "外観設定"
    finally:
        i18n.set_language(original_language)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_settings_accept_disconnects_refresh_signals_and_show_reconnects():
    app, dialog = _dialog()
    original_language = i18n.current_language()
    try:
        i18n.set_language("en")
        dialog.show()
        app.processEvents()
        assert dialog._bus_connected
        assert dialog._refresh_bus_connected

        dialog.accept()
        assert not dialog.isVisible()
        assert not dialog._bus_connected
        assert not dialog._refresh_bus_connected

        i18n.set_language("zh")
        app.processEvents()
        assert dialog.windowTitle() == "Appearance Settings"

        dialog.show()
        app.processEvents()
        i18n.set_language("ja")
        app.processEvents()
        assert dialog.windowTitle() == "外観設定"
    finally:
        i18n.set_language(original_language)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
