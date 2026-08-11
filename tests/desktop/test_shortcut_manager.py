from unittest.mock import Mock

import pytest
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import QWidget

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
    shortcuts = manager.get_shortcuts()

    assert shortcuts == [
        {"key": "Ctrl+K", "description": "Command Palette", "category": "navigation"},
        {"key": "Ctrl+P", "description": "File Picker", "category": "navigation"},
        {"key": "Ctrl+B", "description": "Toggle Sidebar", "category": "view"},
        {"key": "Ctrl+,", "description": "Settings", "category": "navigation"},
        {"key": "Ctrl+Q", "description": "Quit", "category": "application"},
        {"key": "F1", "description": "Help", "category": "application"},
        {"key": "Escape", "description": "Close dialog/palette", "category": "navigation"},
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
        {"key": "Ctrl+Q", "description": "Quit", "category": "application"},
        {"key": "F1", "description": "Help", "category": "application"},
    ]


def test_duplicate_registration_replaces_existing_shortcut(manager):
    context = QWidget()
    old_callback = Mock()
    new_callback = Mock()
    old_shortcut = manager.register(context, "Ctrl+K", old_callback, "Old command", "general")

    new_shortcut = manager.register(context, "Ctrl+K", new_callback, "Command Palette", "navigation")

    assert not old_shortcut.isEnabled()
    assert new_shortcut.isEnabled()
    assert len([item for item in manager.get_shortcuts() if item["key"] == "Ctrl+K"]) == 1
    new_shortcut.activated.emit()
    old_callback.assert_not_called()
    new_callback.assert_called_once_with()
