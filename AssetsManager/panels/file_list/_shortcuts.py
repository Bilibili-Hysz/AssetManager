"""Keyboard shortcut dispatcher for the file list panel."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt


def handle_key(panel, event) -> bool:
    """Dispatch a key event to the appropriate panel action.

    Returns True if the event was handled.
    """
    key = event.key()
    mods = event.modifiers()
    ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
    shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
    is_details = panel._view_mode == "Details"

    if key == Qt.Key.Key_Delete:
        if shift:
            panel._delete_selected_permanent()
        else:
            panel._delete_selected()
        return True
    if key == Qt.Key.Key_Backspace:
        panel._go_up()
        return True
    if key == Qt.Key.Key_F2:
        panel._inline_rename()
        return True
    if key == Qt.Key.Key_Z and ctrl and not shift:
        panel._undo()
        return True
    if key == Qt.Key.Key_D and ctrl and not shift:
        panel._duplicate_selected()
        return True
    if key == Qt.Key.Key_N and ctrl and shift:
        panel._new_folder()
        return True
    if key == Qt.Key.Key_A and ctrl and not shift:
        if is_details:
            panel._detail_view.selectAll()
        else:
            panel._grid_widget.select_all()
        panel._update_status()
        return True
    if key == Qt.Key.Key_C and ctrl and not shift:
        panel._copy_selected()
        return True
    if key == Qt.Key.Key_X and ctrl and not shift:
        panel._cut_selected()
        return True
    if key == Qt.Key.Key_V and ctrl and not shift:
        panel._paste()
        return True
    if key == Qt.Key.Key_F and ctrl and not shift:
        panel._search.setFocus()
        panel._search.selectAll()
        return True
    if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
        if mods & Qt.KeyboardModifier.AltModifier:
            paths = panel._selected_paths()
            if paths:
                panel._show_properties(paths[0])
            return True
        if is_details:
            sel = panel._detail_view.selectionModel().selectedRows()
            if sel:
                path = panel._detail_model.data(sel[0], Qt.ItemDataRole.UserRole)
                if path:
                    if os.path.isdir(path):
                        panel.navigate_to(path)
                    else:
                        panel.file_double_clicked.emit(path)
        else:
            sel = panel._grid_widget.selection_model_rows()
            if sel:
                ent = panel._model.entry_at(next(iter(sel)))
                if ent:
                    if ent.is_dir():
                        panel.navigate_to(ent.path)
                    else:
                        panel.file_double_clicked.emit(ent.path)
        return True
    if key == Qt.Key.Key_Escape:
        if is_details:
            panel._detail_view.clearSelection()
        else:
            panel._grid_widget.clear_selection()
        panel._search.clear()
        panel._update_status()
        return True
    if key == Qt.Key.Key_Y and ctrl and not shift:
        panel._redo()
        return True
    if key == Qt.Key.Key_F5:
        panel._do_refresh()
        return True
    if key == Qt.Key.Key_H and ctrl and not shift:
        panel._toggle_hidden()
        return True
    return False
