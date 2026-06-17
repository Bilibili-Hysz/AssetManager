"""Undo/redo application service."""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class UndoEntry:
    """A single undoable operation."""
    type: str
    old: str = ""
    new: str = ""
    path: str = ""
    backup: str = ""
    is_dir: bool = False


class UndoService:
    """Manages an undo/redo stack for file operations.

    Each operation records enough information to reverse itself.
    Backup copies are stored in a temporary directory.
    """

    def __init__(self, max_depth: int = 20):
        self._lock = threading.Lock()
        self._undo_stack: deque[UndoEntry] = deque(maxlen=max_depth)
        self._redo_stack: list[UndoEntry] = []
        self._max_depth = max_depth
        self._undo_dir = tempfile.mkdtemp(prefix="AssetsManager_undo_")

    def record_rename(self, old_path: str, new_path: str) -> None:
        """Record a rename operation for undo."""
        entry = UndoEntry(type="rename", old=old_path, new=new_path)
        self._push_undo(entry)

    def record_delete(self, path: str) -> None:
        """Record a delete operation with backup for undo."""
        backup = self._make_backup(path)
        if backup:
            entry = UndoEntry(
                type="delete", path=path, backup=backup,
                is_dir=os.path.isdir(path),
            )
            self._push_undo(entry)

    def can_undo(self) -> bool:
        with self._lock:
            return bool(self._undo_stack)

    def can_redo(self) -> bool:
        with self._lock:
            return bool(self._redo_stack)

    def peek_undo(self) -> UndoEntry | None:
        with self._lock:
            return self._undo_stack[-1] if self._undo_stack else None

    def peek_redo(self) -> UndoEntry | None:
        with self._lock:
            return self._redo_stack[-1] if self._redo_stack else None

    def undo(self) -> UndoEntry | None:
        """Pop the last undo entry and push it to redo. Returns the entry to execute."""
        with self._lock:
            if not self._undo_stack:
                return None
            entry = self._undo_stack.pop()
            self._redo_stack.append(entry)
            return entry

    def redo(self) -> UndoEntry | None:
        """Pop the last redo entry and push it to undo. Returns the entry to execute."""
        with self._lock:
            if not self._redo_stack:
                return None
            entry = self._redo_stack.pop()
            self._undo_stack.append(entry)
            return entry

    def clear(self) -> None:
        """Clear both undo and redo stacks."""
        with self._lock:
            for entry in self._undo_stack:
                if entry.backup:
                    self._clean_backup(entry.backup)
            self._undo_stack.clear()
            for entry in self._redo_stack:
                if entry.backup:
                    self._clean_backup(entry.backup)
            self._redo_stack.clear()

    def clear_redo(self) -> None:
        """Clear the redo stack (call after a new operation)."""
        with self._lock:
            self._redo_stack.clear()

    def execute_undo(self, entry: UndoEntry) -> bool:
        """Execute the reverse of an undo entry. Returns True on success."""
        try:
            if entry.type == "rename":
                os.rename(entry.new, entry.old)
                return True
            elif entry.type == "delete":
                if entry.backup and os.path.exists(entry.backup):
                    if entry.is_dir:
                        shutil.copytree(entry.backup, entry.path)
                    else:
                        shutil.copy2(entry.backup, entry.path)
                    return True
        except OSError:
            pass
        return False

    def execute_redo(self, entry: UndoEntry) -> bool:
        """Re-apply an undone operation. Returns True on success."""
        try:
            if entry.type == "rename":
                os.rename(entry.old, entry.new)
                return True
            elif entry.type == "delete":
                if entry.is_dir:
                    shutil.rmtree(entry.path, ignore_errors=True)
                else:
                    os.remove(entry.path)
                return True
        except OSError:
            pass
        return False

    def cleanup(self) -> None:
        """Remove the undo backup directory."""
        try:
            shutil.rmtree(self._undo_dir, ignore_errors=True)
        except OSError:
            pass

    def _push_undo(self, entry: UndoEntry) -> None:
        with self._lock:
            # deque with maxlen automatically evicts oldest when full
            if len(self._undo_stack) >= self._max_depth:
                old = self._undo_stack[0]
                if old.backup:
                    self._clean_backup(old.backup)
            self._undo_stack.append(entry)
            for redo_entry in self._redo_stack:
                if redo_entry.backup:
                    self._clean_backup(redo_entry.backup)
            self._redo_stack.clear()

    def _make_backup(self, path: str) -> str | None:
        try:
            uid = os.urandom(8).hex()
            backup = os.path.join(self._undo_dir, uid)
            if os.path.isdir(path):
                shutil.copytree(path, backup)
            else:
                shutil.copy2(path, backup)
            return backup
        except OSError:
            return None

    def _clean_backup(self, backup: str) -> None:
        try:
            if os.path.isdir(backup):
                shutil.rmtree(backup)
            elif os.path.isfile(backup):
                os.remove(backup)
        except OSError:
            pass
