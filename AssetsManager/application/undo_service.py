"""Undo/redo application service."""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
from contextlib import nullcontext
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter, time
from typing import TYPE_CHECKING

from AssetsManager.application.context import session_operation
from AssetsManager.application.file_operation_service import acquire_path_locks
from AssetsManager.core.performance import PerformanceRecorder

if TYPE_CHECKING:
    from AssetsManager.application.context import LibrarySession

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class UndoEntry:
    """A single undoable operation."""
    type: str
    old: str = ""
    new: str = ""
    path: str = ""
    backup: str = ""
    is_dir: bool = False
    # True when the last undo of this entry restored the file but its
    # projection snapshot could not be re-applied (degraded restore).
    # The entry still moves to the redo stack; the flag keeps the outcome
    # from being recorded as a fully clean success.
    degraded: bool = False


class UndoService:
    """Manages an undo/redo stack for file operations.

    Stacks are keyed by ``library_root`` so switching libraries does not
    carry undo history across library boundaries.  When ``library_root`` is
    omitted (legacy callers) a shared default stack is used.
    """

    _UNDO_DIR_PREFIX = "AssetsManager_undo_"
    _OWNER_MARKER = ".assetsmanager-owner"
    _STALE_AFTER_SECONDS = 7 * 24 * 60 * 60
    _MAX_STARTUP_CLEANUP = 256
    # 1 MiB of free space kept after a backup so a copy can never exhaust
    # the temp volume (which would break unrelated processes on the same
    # drive).  A file is only backed up when free >= size + this margin.
    _MIN_FREE_MARGIN = 1024 * 1024
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _ERROR_ACCESS_DENIED = 5
    _ERROR_INVALID_PARAMETER = 87
    _active_undo_dirs: set[str] = set()
    _active_dirs_lock = threading.Lock()
    _startup_cleanup_done = False
    _startup_cleanup_lock = threading.Lock()

    @classmethod
    def _run_startup_cleanup(cls) -> None:
        """Run the process-wide startup scan once."""
        with cls._startup_cleanup_lock:
            if cls._startup_cleanup_done:
                return
            cls.cleanup_stale_undo_dirs()
            cls._startup_cleanup_done = True

    @classmethod
    def cleanup_stale_undo_dirs(
        cls,
        temp_dir: str | Path | None = None,
        *,
        max_age_seconds: float | None = None,
        now: float | None = None,
    ) -> int:
        """Remove only provably stale, app-owned undo directories.

        The scan is deliberately limited to direct children of the system
        temporary directory.  Recent directories and directories marked as
        owned by a live process are retained so startup cleanup cannot race
        with another active application instance.
        """
        root = Path(temp_dir) if temp_dir is not None else Path(tempfile.gettempdir())
        age_limit = cls._STALE_AFTER_SECONDS if max_age_seconds is None else max_age_seconds
        current_time = time() if now is None else now
        removed = 0
        try:
            entries = os.scandir(root)
        except OSError:
            return 0

        try:
            for entry in entries:
                if not entry.name.startswith(cls._UNDO_DIR_PREFIX):
                    continue
                try:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    resolved = os.path.abspath(entry.path)
                    with cls._active_dirs_lock:
                        if resolved in cls._active_undo_dirs:
                            continue
                    age = current_time - entry.stat(follow_symlinks=False).st_mtime
                    if age < age_limit:
                        continue
                    if cls._owned_by_live_process(Path(entry.path)):
                        continue
                    shutil.rmtree(entry.path)
                    try:
                        Path(f"{entry.path}{cls._OWNER_MARKER}").unlink()
                    except OSError:
                        pass
                except (OSError, ValueError):
                    # A directory can disappear or change while startup scans it.
                    # Uncertainty is treated as a reason to retain it.
                    continue
                removed += 1
                if removed >= cls._MAX_STARTUP_CLEANUP:
                    break
        finally:
            entries.close()
        return removed

    @classmethod
    def _windows_process_is_live(cls, pid: int) -> bool:
        """Return whether a Windows PID should be treated as live.

        ``OpenProcess`` returns access denied for processes that exist but are
        not queryable by this user.  Only ``ERROR_INVALID_PARAMETER`` is a
        definitive indication that the PID does not exist; all other failures
        retain the directory under the conservative cleanup policy.
        """
        try:
            import ctypes

            # getattr: typeshed omits ctypes.windll on non-win32 platforms
            # (same pattern as core/library_lock.py); this branch only runs
            # for Windows-registry PIDs.
            kernel32 = getattr(ctypes, "windll").kernel32
            handle = kernel32.OpenProcess(
                cls._PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if handle:
                kernel32.CloseHandle(handle)
                return True
            error_code = kernel32.GetLastError()
        except (AttributeError, OSError, TypeError):
            # API availability or call-shape uncertainty is treated as live.
            return True

        if error_code == cls._ERROR_INVALID_PARAMETER:
            return False
        if error_code == cls._ERROR_ACCESS_DENIED:
            return True
        # Unknown failures, including an unavailable error code, are unsafe
        # grounds for deletion and therefore retain the directory.
        return True

    @classmethod
    def _owned_by_live_process(cls, undo_dir: Path) -> bool:
        # New instances use a sidecar so the backup directory contains only
        # actual undo payloads.  Keep recognizing the original in-directory
        # marker for directories created by the first cleanup implementation.
        markers = (
            Path(f"{undo_dir}{cls._OWNER_MARKER}"),
            undo_dir / cls._OWNER_MARKER,
        )
        for marker in markers:
            try:
                pid = int(marker.read_text(encoding="ascii").strip())
            except (OSError, ValueError):
                continue
            if pid <= 0:
                continue
            if os.name == "nt":
                if cls._windows_process_is_live(pid):
                    return True
                continue
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            except OSError:
                return True
            return True
        return False

    def __init__(self, max_depth: int = 20, library_root: str = "",
                 session: LibrarySession | None = None,
                 performance_recorder: PerformanceRecorder | None = None):
        self._library_root = str(library_root)
        self._session = session
        self._closed = False
        self._lock = threading.Lock()
        self._max_depth = max_depth
        self._run_startup_cleanup()
        self._undo_dir = tempfile.mkdtemp(prefix=self._UNDO_DIR_PREFIX)
        resolved_undo_dir = str(Path(self._undo_dir).resolve())
        with self._active_dirs_lock:
            self._active_undo_dirs.add(resolved_undo_dir)
        try:
            Path(f"{self._undo_dir}{self._OWNER_MARKER}").write_text(
                str(os.getpid()), encoding="ascii"
            )
        except OSError:
            pass
        self._stacks: dict[str, tuple[deque[UndoEntry], list[UndoEntry]]] = {}
        self._stacks[self._library_root] = (
            deque[UndoEntry](maxlen=max_depth), [],
        )
        self._failed_entries: set[int] = set()
        self._degraded_entries: set[int] = set()
        self._last_backup_error: str | None = None
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
    def record_delete(self, path: str) -> bool:
        """Record a delete operation with backup for undo.

        Returns ``True`` when the backup was created and the delete is
        undoable.  Returns ``False`` when the backup could not be made
        (copy failure, insufficient free disk space, ...); the concrete
        reason is available in :attr:`last_backup_error` so the caller
        can tell the user the delete cannot be undone instead of
        silently dropping history.
        """
        entry = self.prepare_delete(path)
        if entry is None:
            return False
        self.commit_delete(entry)
        return True

    @property
    def last_backup_error(self) -> str | None:
        """Reason the most recent delete backup failed, or ``None``.

        Set by the last :meth:`prepare_delete` / :meth:`record_delete`
        attempt; cleared by the next successful one.  Only the most
        recent failure is retained, so a caller that prepared several
        paths should treat this as "at least one backup failed".
        """
        return self._last_backup_error

    @session_operation
    def prepare_delete(self, path: str) -> UndoEntry | None:
        """Create a delete backup without adding it to undo history."""
        self._ensure_open()
        with acquire_path_locks(Path(path)):
            backup = self._make_backup(path)
            if not backup:
                return None
            self._snapshot_projection(path, backup)
        return UndoEntry(
            type="delete", path=path, backup=backup,
            is_dir=os.path.isdir(path),
        )

    def _snapshot_projection(self, path: str, backup: str) -> None:
        """Persist file_tags/file_meta/library_favorites rows next to the backup.

        The projection SELECTs run under the shared connection's
        ``db_write_lock`` so they cannot interleave with an in-flight write
        transaction.  Failures are deliberately not silent: a
        ``<backup>.projection.failed`` marker is written next to the backup
        so the restore path can tell "legacy backup without snapshot
        support" (no snapshot, no marker: restore proceeds unchanged) apart
        from "new backup whose snapshot was expected but failed" (marker
        present: restore reports a degraded projection restore instead of
        pretending the tags/notes survived).
        """
        if self._session is None:
            return
        snapshot_path = f"{backup}.projection.json"
        failed_marker_path = f"{backup}.projection.failed"
        try:
            from AssetsManager.core.database import db_write_lock
            from AssetsManager.core.path_resolver import sql_like_descendant_pattern

            conn = self._session.connection_for(self._session.root)
            old = str(Path(path).resolve())
            descendant_pattern = sql_like_descendant_pattern(old)
            with db_write_lock(conn):
                tag_rows = conn.execute(
                    "SELECT file_path, tag FROM file_tags "
                    "WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                    (old, descendant_pattern),
                ).fetchall()
                meta_rows = conn.execute(
                    "SELECT file_path, notes, cached_size, cached_mtime, cached_file_count, urls "
                    "FROM file_meta WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                    (old, descendant_pattern),
                ).fetchall()
                favorites_table = conn.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type='table' AND name='library_favorites'"
                ).fetchone()
                favorite_rows = []
                if favorites_table is not None:
                    favorite_rows = conn.execute(
                        "SELECT owner_key, file_path, created_at FROM library_favorites "
                        "WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                        (old, descendant_pattern),
                    ).fetchall()
            payload = {
                "format": "assetsmanager.undo-projection",
                "version": 1,
                "base": old,
                "file_tags": tag_rows,
                "file_meta": meta_rows,
                "library_favorites": favorite_rows,
            }
            with open(snapshot_path, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False)
        except Exception as exc:
            _log.warning("Failed to snapshot projection for %s: %s", path, exc)
            self._mark_projection_snapshot_failed(failed_marker_path, path, exc)

    @staticmethod
    def _mark_projection_snapshot_failed(
        failed_marker_path: str, path: str, exc: BaseException
    ) -> None:
        """Leave a durable marker so restore cannot pretend the snapshot exists."""
        try:
            with open(failed_marker_path, "w", encoding="ascii") as stream:
                stream.write(type(exc).__name__)
        except OSError as marker_exc:
            _log.error(
                "Could not write projection failure marker for %s: %s",
                path, marker_exc,
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
        """Undo through file operations, moving history only after success.

        The executed entry is removed from the undo stack unconditionally
        after the filesystem operation succeeds, so a concurrent push cannot
        leave the stack out of sync with the filesystem.
        """
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
            try:
                self._undo_stack.remove(entry)
            except ValueError:
                pass
            if entry not in self._redo_stack:
                if id(entry) in self._degraded_entries:
                    entry = replace(entry, degraded=True)
                self._redo_stack.append(entry)
            self._failed_entries.discard(id(entry))
            self._degraded_entries.discard(id(entry))
        self._record_execution("undo", started, "success")
        return True

    @session_operation
    def perform_redo(self, file_operations, library_root: str | Path | None = None) -> bool:
        """Redo through file operations, moving history only after success.

        The executed entry is removed from the redo stack unconditionally
        after the filesystem operation succeeds, so a concurrent push cannot
        leave the stack out of sync with the filesystem.
        """
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
            try:
                self._redo_stack.remove(entry)
            except ValueError:
                pass
            if entry not in self._undo_stack:
                # Redo re-executes the delete itself; a degraded annotation
                # described the previous restore and is no longer current.
                if id(entry) in self._degraded_entries or entry.degraded:
                    self._degraded_entries.discard(id(entry))
                    entry = replace(entry, degraded=False)
                self._undo_stack.append(entry)
            self._failed_entries.discard(id(entry))
        self._record_execution("redo", started, "success")
        return True

    @staticmethod
    def _operation_succeeded(result) -> bool:
        """Return whether *result* represents successful execution.

        A degraded restore (filesystem copy succeeded, projection snapshot
        did not) still counts as success for stack movement — the file is
        back — but it must not be recorded as a fully clean success: the
        degraded outcome is logged here and the caller annotates the
        history entry via :meth:`_mark_degraded`.
        """
        ok = bool(getattr(result, "ok", True))
        if ok and getattr(result, "degraded", False):
            _log.warning(
                "Operation succeeded with a degraded projection restore; "
                "the undo history entry is annotated as degraded"
            )
        return ok

    def _execute_reverse(self, file_operations, entry: UndoEntry,
                         library_root: str | Path | None) -> bool:
        try:
            if entry.type == "rename":
                if os.path.lexists(entry.old):
                    self._mark_failed(entry)
                    _log.warning(
                        "Undo rename blocked: target already exists: %s", entry.old
                    )
                    return False
                succeeded = self._operation_succeeded(
                    file_operations.move(entry.new, entry.old, library_root=library_root)
                )
                if not succeeded:
                    self._mark_failed(entry)
                return succeeded
            if entry.type == "delete":
                if not (entry.backup and os.path.exists(entry.backup)):
                    self._mark_failed(entry)
                    return False
                if os.path.lexists(entry.path):
                    self._mark_failed(entry)
                    _log.warning(
                        "Undo delete restore blocked: path recreated by user: %s", entry.path
                    )
                    return False
                result = file_operations.restore_backup(
                    entry.backup, entry.path, library_root=library_root
                )
                succeeded = self._operation_succeeded(result)
                if not succeeded:
                    self._mark_failed(entry)
                elif getattr(result, "degraded", False):
                    self._mark_degraded(entry)
                return succeeded
        except (OSError, ValueError):
            self._mark_failed(entry)
        return False

    def _execute_forward(self, file_operations, entry: UndoEntry,
                         library_root: str | Path | None) -> bool:
        try:
            if entry.type == "rename":
                if os.path.lexists(entry.new):
                    self._mark_failed(entry)
                    _log.warning(
                        "Redo rename blocked: target already exists: %s", entry.new
                    )
                    return False
                succeeded = self._operation_succeeded(
                    file_operations.move(entry.old, entry.new, library_root=library_root)
                )
                if not succeeded:
                    self._mark_failed(entry)
                return succeeded
            if entry.type == "delete":
                succeeded = self._operation_succeeded(
                    file_operations.delete_permanent(
                        [entry.path], library_root=library_root
                    )
                )
                if not succeeded:
                    self._mark_failed(entry)
                return succeeded
        except (OSError, ValueError):
            self._mark_failed(entry)
        return False

    def _mark_failed(self, entry: UndoEntry) -> None:
        with self._lock:
            self._failed_entries.add(id(entry))

    def _mark_degraded(self, entry: UndoEntry) -> None:
        """Flag an entry whose undo restored the file only partially."""
        with self._lock:
            self._degraded_entries.add(id(entry))

    def skip_poisoned_undo(self) -> UndoEntry | None:
        """Drop the top undo entry when a previous execution attempt failed.

        A failed entry would otherwise remain at the top of the LIFO stack and
        block every later undo.  Skipping discards the entry (and its backup).
        """
        with self._lock:
            if not self._undo_stack:
                return None
            entry = self._undo_stack[-1]
            if id(entry) not in self._failed_entries:
                return None
            self._undo_stack.pop()
            self._failed_entries.discard(id(entry))
        self._clean_backup(entry.backup)
        return entry

    def skip_poisoned_redo(self) -> UndoEntry | None:
        """Drop the top redo entry when a previous execution attempt failed."""
        with self._lock:
            if not self._redo_stack:
                return None
            entry = self._redo_stack[-1]
            if id(entry) not in self._failed_entries:
                return None
            self._redo_stack.pop()
            self._failed_entries.discard(id(entry))
        self._clean_backup(entry.backup)
        return entry

    def cleanup(self) -> None:
        """Remove the undo backup directory."""
        self._closed = True
        resolved_undo_dir = str(Path(self._undo_dir).resolve())
        with self._active_dirs_lock:
            self._active_undo_dirs.discard(resolved_undo_dir)
        try:
            shutil.rmtree(self._undo_dir, ignore_errors=True)
        except OSError:
            pass
        try:
            Path(f"{self._undo_dir}{self._OWNER_MARKER}").unlink()
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
        """Copy ``path`` into the undo directory and return the backup path.

        Returns ``None`` when the copy cannot be made; the reason is then
        recorded in :attr:`last_backup_error` and logged so the delete
        caller can tell the user the operation cannot be undone.  No
        hard per-file size cap is applied: the backup directory lives in
        the system temporary directory and undo must keep working for
        large assets, so the free-space check below is the guard.
        """
        self._last_backup_error = None
        try:
            size = self._path_size(path)
            free = shutil.disk_usage(self._undo_dir).free
            if free < size + self._MIN_FREE_MARGIN:
                self._fail_backup(
                    f"not enough free disk space to back up {path} "
                    f"(need {size} bytes, only {free} free)"
                )
                return None
            backup = os.path.join(self._undo_dir, os.urandom(8).hex())
            if os.path.isdir(path):
                shutil.copytree(path, backup)
            else:
                shutil.copy2(path, backup)
            return backup
        except OSError as exc:
            self._fail_backup(f"failed to back up {path}: {exc}")
            return None

    @staticmethod
    def _path_size(path: str) -> int:
        """Total byte size of a file or directory tree (best effort).

        Returns 0 when the size cannot be determined; the subsequent
        copy then still surfaces a concrete error through
        :meth:`_fail_backup`.
        """
        if os.path.isdir(path):
            total = 0
            for root, _dirs, files in os.walk(path):
                for name in files:
                    try:
                        total += os.path.getsize(os.path.join(root, name))
                    except OSError:
                        continue
            return total
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    def _fail_backup(self, message: str) -> None:
        self._last_backup_error = message
        _log.warning("Undo backup failed: %s", message)

    def _clean_backup(self, backup: str) -> None:
        try:
            snapshot_path = f"{backup}.projection.json"
            if os.path.isfile(snapshot_path):
                os.remove(snapshot_path)
            failed_marker = f"{backup}.projection.failed"
            if os.path.isfile(failed_marker):
                os.remove(failed_marker)
            if os.path.isdir(backup):
                shutil.rmtree(backup)
            elif os.path.isfile(backup):
                os.remove(backup)
        except OSError:
            pass
