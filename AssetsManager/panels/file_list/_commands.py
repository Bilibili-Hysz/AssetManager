"""Small, FileList-local command descriptions for context-menu projection."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt


@dataclass(frozen=True)
class FileListCommandContext:
    """Immutable availability facts captured while a FileList menu is built."""

    paths: tuple[str, ...]
    current_dir: Path
    view_mode: str
    clipboard_has_local_files: bool
    can_mutate: bool
    undo_available: bool
    redo_available: bool


@dataclass(frozen=True)
class FileListCommand:
    """One existing FileList command projected into a context menu."""

    id: str
    label_key: str
    shortcut: str | None
    group: str
    visible_when: Callable[[FileListCommandContext], bool]
    enabled_when: Callable[[FileListCommandContext], bool]
    invoke: Callable[[], None]


def shortcut_command_id(key: int, modifiers: Any) -> str | None:
    """Return the stable FileList command ID for an existing shortcut."""
    ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
    shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
    if key == Qt.Key.Key_Delete:
        return "permanent_delete" if shift else "trash"
    if key == Qt.Key.Key_F2:
        return "rename"
    if key == Qt.Key.Key_Z and ctrl and not shift:
        return "undo"
    if key == Qt.Key.Key_D and ctrl and not shift:
        return "duplicate"
    if key == Qt.Key.Key_N and ctrl and shift:
        return "new_folder"
    if key == Qt.Key.Key_A and ctrl and not shift:
        return "select_all"
    if key == Qt.Key.Key_C and ctrl and not shift:
        return "copy"
    if key == Qt.Key.Key_X and ctrl and not shift:
        return "cut"
    if key == Qt.Key.Key_V and ctrl and not shift:
        return "paste"
    if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
        return "properties" if modifiers & Qt.KeyboardModifier.AltModifier else "open"
    if key == Qt.Key.Key_Y and ctrl and not shift:
        return "redo"
    if key == Qt.Key.Key_F5:
        return "refresh"
    if key == Qt.Key.Key_H and ctrl and not shift:
        return "toggle_hidden"
    if key == Qt.Key.Key_F4:
        return "help"
    return None
