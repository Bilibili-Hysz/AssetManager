"""Keyboard shortcut dispatcher for the file list panel."""
from __future__ import annotations

from PySide6.QtCore import Qt
from AssetsManager.panels.file_list._commands import shortcut_command_id


def handle_key(panel, event) -> bool:
    """Dispatch a key event to the appropriate panel action.

    Returns True if the event was handled.
    """
    key = event.key()
    mods = event.modifiers()
    is_details = panel._view_mode == "Details"

    search = getattr(panel, "_search", None)
    if (
        search is not None
        and search.hasFocus()
        and key != Qt.Key.Key_Escape
        and not (key == Qt.Key.Key_F and mods & Qt.KeyboardModifier.ControlModifier)
    ):
        # Keys typed into the search box must reach the QLineEdit; only
        # Escape (clear) and Ctrl+F (re-focus) are panel commands.
        return False

    if key == Qt.Key.Key_Backspace:
        panel._go_up()
        return True
    command_id = shortcut_command_id(key, mods)
    if command_id is not None:
        panel._invoke_command(command_id, shortcut=True)
        return True
    if key == Qt.Key.Key_F and mods & Qt.KeyboardModifier.ControlModifier:
        panel._search.setFocus()
        panel._search.selectAll()
        return True
    if key == Qt.Key.Key_Escape:
        if is_details:
            panel._detail_view.clearSelection()
        else:
            panel._grid_widget.clear_selection()
        panel._search.clear()
        panel._update_status()
        return True
    return False
