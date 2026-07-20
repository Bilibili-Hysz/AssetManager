"""Undo/redo application service."""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
from contextlib import nullcontext
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

from AssetsManager.application.context import session_operation
from AssetsManager.core.performance import PerformanceRecorder

if TYPE_CHECKING:
    from AssetsManager.application.context import LibrarySession


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

    Stacks are keyed by ``library_root`` so switching libraries does not
    carry undo history across library boundaries.  When ``library_root`` is
    omitted (legacy callers) a shared default stack is used.
    """

    def __init__(self, max_depth: int = 20, library_root: str = "",
                 session: LibrarySession | None = None,
                 performance_recorder: PerformanceRecorder | None = None):
        self._library_root = str(library_root)
        self._session = session
        self._closed = False
        self._lock = threading.Lock()
        self._max_depth = max_depth
        self._undo_dir = tempfile.mkdtemp(prefix="AssetsManager_undo_")
        self._stacks: dict[str, tuple[deque[UndoEntry], list[UndoEntry]]] = {}
        self._stacks[self._library_root] = (
            deque[UndoEntry](maxlen=max_depth), [],
        )
        self._performance_recorder = (
            performance_recorder if performance_recorder is not None and performance_recorder.enabled else None
        )

    def _record_execution(self, command: str, started: float | None, outcome: str) -> None:
        if self._performance_recorder is None or started is None:
            return
        try:
            self._performance_recorder.record(
                "file.undo",
                (perf_counter() - started) * 1000,
                session_token=self._session.event_token if self._session is not None else None,
                path=self._library_root or None,
                attributes={"command": command, "outcome": outcome, "phase": "events_published" if outcome == "success" else "failed"},
            )
        except Exception:
            pass

    @property
    def undo_dir(self) -> Path:
        return Path(self._undo_dir)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Cannot use undo history for a closed LibrarySession")
        if self._session is not None:
            self._session._ensure_access()

    def _resolve_stacks(self):
        """Return (undo_deque, redo_list) for the current library root."""
        self._ensure_open()
        key = self._library_root
        if key not in self._stacks:
            self._stacks[key] = (deque[UndoEntry](maxlen=self._max_depth), [])
        return self._stacks[key]

    @property
    def _undo_stack(self) -> deque[UndoEntry]:
        return self._resolve_stacks()[0]

    @property
    def _redo_stack(self) -> list[UndoEntry]:
        return self._resolve_stacks()[1]

    @session_operation
    def record_rename(self, old_path: str, new_path: str) -> None:
        """Record a rename operation for undo."""
        entry = UndoEntry(type="rename", old=old_path, new=new_path)
        self._push_undo(entry)

    @session_operation
    def record_delete(self, path: str) -> None:
        """Record a delete operation with backup for undo."""
        entry = self.prepare_delete(path)
        if entry is not None:
            self.commit_delete(entry)

    @session_operation
    def prepare_delete(self, path: str) -> UndoEntry | None:
        """Create a delete backup without adding it to undo history."""
        self._ensure_open()
        backup = self._make_backup(path)
        if not backup:
            return None
        return UndoEntry(
            type="delete", path=path, backup=backup,
            is_dir=os.path.isdir(path),
        )

    @session_operation
    def commit_delete(self, entry: UndoEntry) -> None:
        """Add a successfully deleted backup to undo history."""
        self._push_undo(entry)

    @session_operation
    def discard_delete(self, entry: UndoEntry | None) -> None:
        """Remove a delete backup when its filesystem operation failed."""
        self._ensure_open()
        if entry is not None and entry.backup:
            self._clean_backup(entry.backup)

    @session_operation
    def can_undo(self) -> bool:
        with self._lock:
            return bool(self._undo_stack)

    @session_operation
    def can_redo(self) -> bool:
        with self._lock:
            return bool(self._redo_stack)

    @session_operation
    def peek_undo(self) -> UndoEntry | None:
        with self._lock:
            return self._undo_stack[-1] if self._undo_stack else None

    @session_operation
    def peek_redo(self) -> UndoEntry | None:
        with self._lock:
            return self._redo_stack[-1] if self._redo_stack else None

    @session_operation
    def undo(self) -> UndoEntry | None:
        """Pop the last undo entry and push it to redo. Returns the entry to execute."""
        with self._lock:
            if not self._undo_stack:
                return None
            entry = self._undo_stack.pop()
            self._redo_stack.append(entry)
            return entry

    @session_operation
    def redo(self) -> UndoEntry | None:
        """Pop the last redo entry and push it to undo. Returns the entry to execute."""
        with self._lock:
            if not self._redo_stack:
                return None
            entry = self._redo_stack.pop()
            self._undo_stack.append(entry)
            return entry

    @session_operation
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

    @session_operation
    def clear_redo(self) -> None:
        """Clear the redo stack (call after a new operation)."""
        with self._lock:
            for entry in self._redo_stack:
                if entry.backup:
                    self._clean_backup(entry.backup)
            self._redo_stack.clear()

    @session_operation
    def perform_undo(self, file_operations, library_root: str | Path | None = None) -> bool:
        """Undo through file operations, moving history only after success."""
        started = perf_counter() if self._performance_recorder is not None else None
        with self._lock:
            if not self._undo_stack:
                self._record_execution("undo", started, "empty")
                return False
            entry = self._undo_stack[-1]
        suppress = getattr(file_operations, "suppress_command_telemetry", nullcontext)
        with suppress():
            succeeded = self._execute_reverse(file_operations, entry, library_root)
        if not succeeded:
            self._record_execution("undo", started, "error")
            return False
        with self._lock:
            if not self._undo_stack or self._undo_stack[-1] != entry:
                self._record_execution("undo", started, "error")
                return False
            self._undo_stack.pop()
            self._redo_stack.append(entry)
        self._record_execution("undo", started, "success")
        return True

    @session_operation
    def perform_redo(self, file_operations, library_root: str | Path | None = None) -> bool:
        """Redo through file operations, moving history only after success."""
        started = perf_counter() if self._performance_recorder is not None else None
        with self._lock:
            if not self._redo_stack:
                self._record_execution("redo", started, "empty")
                return False
            entry = self._redo_stack[-1]
        suppress = getattr(file_operations, "suppress_command_telemetry", nullcontext)
        with suppress():
            succeeded = self._execute_forward(file_operations, entry, library_root)
        if not succeeded:
            self._record_execution("redo", started, "error")
            return False
        with self._lock:
            if not self._redo_stack or self._redo_stack[-1] != entry:
                self._record_execution("redo", started, "error")
                return False
            self._redo_stack.pop()
            self._undo_stack.append(entry)
        self._record_execution("redo", started, "success")
        return True

    @staticmethod
    def _operation_succeeded(result) -> bool:
        return getattr(result, "ok", True)

    def _execute_reverse(self, file_operations, entry: UndoEntry,
                         library_root: str | Path | None) -> bool:
        try:
            if entry.type == "rename":
                return self._operation_succeeded(
                    file_operations.move(entry.new, entry.old, library_root=library_root)
                )
            if entry.type == "delete" and entry.backup and os.path.exists(entry.backup):
                return self._operation_succeeded(
                    file_operations.restore_backup(entry.backup, entry.path, library_root=library_root)
                )
        except (OSError, ValueError):
            pass
        return False

    def _execute_forward(self, file_operations, entry: UndoEntry,
                         library_root: str | Path | None) -> bool:
        try:
            if entry.type == "rename":
                return self._operation_succeeded(
                    file_operations.move(entry.old, entry.new, library_root=library_root)
                )
            if entry.type == "delete":
                return self._operation_succeeded(
                    file_operations.delete_permanent([entry.path], library_root=library_root)
                )
        except (OSError, ValueError):
            pass
        return False

    def cleanup(self) -> None:
        """Remove the undo backup directory."""
        self._closed = True
        try:
            shutil.rmtree(self._undo_dir, ignore_errors=True)
        except OSError:
            pass

    def _push_undo(self, entry: UndoEntry) -> None:
        with self._lock:
            undo, redo = self._resolve_stacks()
            if len(undo) >= self._max_depth:
                old = undo[0]
                if old.backup:
                    self._clean_backup(old.backup)
            undo.append(entry)
            for redo_entry in redo:
                if redo_entry.backup:
                    self._clean_backup(redo_entry.backup)
            redo.clear()

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
