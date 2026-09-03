import logging
from unittest.mock import Mock

import pytest
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

from AssetsManager.widgets.shortcut_manager import ShortcutManager


@pytest.fixture
def manager():
    ShortcutManager._instance = None
    instance = ShortcutManager.instance()
    yield instance
    ShortcutManager._instance = None


def test_instance_returns_singleton(manager):
    assert ShortcutManager.instance() is manager


def test_standard_shortcuts_are_available_by_default(manager):
    """Defaults document only features that exist; descriptions are i18n keys."""
    shortcuts = manager.get_shortcuts()

    assert shortcuts == [
        {"key": "Ctrl+,", "description": "menu.settings", "category": "navigation"},
        {"key": "Ctrl+K", "description": "menu.command_palette", "category": "application"},
        {"key": "Ctrl+B", "description": "menu.toggle_sidebar", "category": "navigation"},
        {"key": "Ctrl+I", "description": "menu.toggle_info", "category": "navigation"},
        {"key": "Ctrl+Q", "description": "menu.exit", "category": "application"},
        {"key": "F1", "description": "menu.keyboard_shortcuts", "category": "application"},
        {"key": "Escape", "description": "shortcuts.close_dialog", "category": "navigation"},
    ]


def test_register_creates_qshortcut_and_adds_metadata(manager):
    context = QWidget()
    callback = Mock()

    shortcut = manager.register(context, "Ctrl+Shift+N", callback, "New folder", "files")

    assert isinstance(shortcut, QShortcut)
    assert shortcut.parent() is context
    assert manager.get_shortcuts()[-1] == {
        "key": "Ctrl+Shift+N",
        "description": "New folder",
        "category": "files",
    }


def test_registered_shortcut_dispatches_callback(manager):
    context = QWidget()
    callback = Mock()
    shortcut = manager.register(context, "Ctrl+L", callback)

    shortcut.activated.emit()

    callback.assert_called_once_with()


def test_unregister_removes_and_disables_shortcut(manager):
    context = QWidget()
    shortcut = manager.register(context, "Ctrl+L", Mock(), "Location", "navigation")

    manager.unregister("Ctrl+L")

    assert not shortcut.isEnabled()
    assert all(item["key"] != "Ctrl+L" for item in manager.get_shortcuts())


def test_get_shortcuts_by_category(manager):
    application_shortcuts = manager.get_shortcuts_by_category("application")

    assert application_shortcuts == [
        {"key": "Ctrl+K", "description": "menu.command_palette", "category": "application"},
        {"key": "Ctrl+Q", "description": "menu.exit", "category": "application"},
        {"key": "F1", "description": "menu.keyboard_shortcuts", "category": "application"},
    ]


def test_duplicate_registration_replaces_existing_shortcut(manager, caplog):
    context = QWidget()
    old_callback = Mock()
    new_callback = Mock()
    old_shortcut = manager.register(context, "Ctrl+K", old_callback, "Old command", "general")

    with caplog.at_level(logging.WARNING, logger="AssetsManager.widgets.shortcut_manager"):
        new_shortcut = manager.register(
            context, "Ctrl+K", new_callback, "Command Palette", "navigation")

    assert any(
        "Shortcut conflict" in record.message and "Ctrl+K" in record.message
        for record in caplog.records
    )
    assert not old_shortcut.isEnabled()
    assert new_shortcut.isEnabled()
    assert len([item for item in manager.get_shortcuts() if item["key"] == "Ctrl+K"]) == 1
    new_shortcut.activated.emit()
    old_callback.assert_not_called()
    new_callback.assert_called_once_with()


def test_register_action_dispatches_menu_action_keystroke(manager):
    """The adopted menu action still fires on the registered key sequence."""
    window = QMainWindow()
    action = QAction("Exit", window)
    window.addAction(action)  # a bare action is not in the shortcut map
    triggered = Mock()
    action.triggered.connect(triggered)

    manager.register_action(action, "Ctrl+Q", "menu.exit", "application")

    assert action.shortcut() == QKeySequence("Ctrl+Q")
    app = QApplication.instance()
    window.show()
    app.processEvents()  # let the shown window become the active window
    try:
        QTest.keySequence(window, QKeySequence("Ctrl+Q"))
        app.processEvents()
    finally:
        window.close()
    triggered.assert_called_once_with()
    assert manager.get_shortcuts_by_category("application") == [
        {"key": "Ctrl+K", "description": "menu.command_palette", "category": "application"},
        {"key": "Ctrl+Q", "description": "menu.exit", "category": "application"},
        {"key": "F1", "description": "menu.keyboard_shortcuts", "category": "application"},
    ]


def test_register_action_does_not_create_competing_qshortcut(manager):
    """Adopting a menu action must not leave a competing QShortcut behind:
    two owners for one key make Qt treat the sequence as ambiguous."""
    window = QMainWindow()
    action = QAction("Settings", window)

    manager.register_action(action, "Ctrl+,", "menu.settings", "navigation")

    assert all(
        entry["shortcut"] is None or entry["shortcut"] is action
        for entry in manager._shortcuts.values()
    )
    assert action.shortcut() == QKeySequence("Ctrl+,")


def test_register_action_replaces_conflicting_shortcut_with_warning(manager, caplog):
    context = QWidget()
    old_shortcut = manager.register(context, "F1", Mock(), "Old help", "general")
    action = QAction("Keyboard Shortcuts", None)

    with caplog.at_level(logging.WARNING, logger="AssetsManager.widgets.shortcut_manager"):
        manager.register_action(action, "F1", "menu.keyboard_shortcuts", "application")

    assert any(
        "Shortcut conflict" in record.message and "F1" in record.message
        for record in caplog.records
    )
    assert not old_shortcut.isEnabled()
    assert action.shortcut() == QKeySequence("F1")


def test_main_window_menu_shortcuts_are_registered(manager):
    """MainWindow._register_window_shortcuts adopts the three menu actions
    into the registry and gives each a real QAction shortcut."""
    from AssetsManager.window import MainWindow

    class _Window:
        _register_window_shortcuts = MainWindow._register_window_shortcuts

    window = _Window()
    window._menu_act_exit = QAction("Exit")
    window._menu_act_settings = QAction("Settings")
    window._menu_act_shortcuts = QAction("Keyboard Shortcuts")

    window._register_window_shortcuts()

    assert window._menu_act_exit.shortcut() == QKeySequence("Ctrl+Q")
    assert window._menu_act_settings.shortcut() == QKeySequence("Ctrl+,")
    assert window._menu_act_shortcuts.shortcut() == QKeySequence("F1")
    assert [
        (item["key"], item["description"])
        for item in manager.get_shortcuts()
        if item["key"] in ("Ctrl+Q", "Ctrl+,", "F1")
    ] == [
        ("Ctrl+,", "menu.settings"),
        ("Ctrl+Q", "menu.exit"),
        ("F1", "menu.keyboard_shortcuts"),
    ]


def test_shortcuts_help_text_lists_registry_and_filelist_entries():
    """The help page is generated from the ShortcutManager registry plus the
    FileList key table, so it cannot drift from what is actually wired."""
    from AssetsManager import i18n
    from AssetsManager.window import build_shortcuts_help_text

    ShortcutManager._instance = None
    try:
        text = build_shortcuts_help_text()
        registry_entries = ShortcutManager.instance().get_shortcuts()
    finally:
        ShortcutManager._instance = None

    # Global group: every registry entry appears with its translated
    # description (i18n keys resolve, not raw keys).
    for entry in registry_entries:
        assert entry["key"] in text
    assert i18n.tr("menu.exit") in text
    assert i18n.tr("menu.settings") in text
    assert i18n.tr("shortcuts.close_dialog") in text
    # FileList group: real panel keys incl. ones the old hand-written list
    # missed (Ctrl+D / Ctrl+Shift+N / Alt+Enter / Backspace / Ctrl+H).
    for key in ("Ctrl+D", "Ctrl+Shift+N", "Alt+Enter", "Backspace", "Ctrl+H"):
        assert key in text
    # Fabricated entries must stay out (no File Picker / Ctrl+Tab);
    # Ctrl+K Command Palette is real (window.py) and must appear.
    assert "Ctrl+K" in text
    assert "Ctrl+Tab" not in text
