"""Cross-process library lock backed by Qt's QLockFile semantics."""
from __future__ import annotations

import os
import threading
from pathlib import Path

from PySide6.QtCore import QLockFile


class LibraryAlreadyOpenError(RuntimeError):
    """The requested library is already owned by another process."""


_registry_guard = threading.Lock()
_held_locks: dict[str, tuple[QLockFile, int]] = {}


def _pid_is_alive(pid: int) -> bool:
    """Return True when a process with *pid* currently exists.

    Used to distinguish a live library lock from a stale one left behind by a
    crashed or force-killed process. When liveness cannot be determined the
    result is ``True`` (fail closed — the lock is treated as live).
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        try:
            # PROCESS_QUERY_LIMITED_INFORMATION — succeeds for any normal
            # process we can see; returns NULL once the PID has been reaped.
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        except Exception:
            return True
        if not handle:
            return False
        try:
            ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            pass
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


class LibraryLock:
    """Small infrastructure wrapper that keeps Qt out of application code.

    Multiple service objects in one process share the same underlying
    QLockFile. The file lock therefore represents application ownership, not
    the identity of a particular ``LibraryService`` object; another process
    still receives ``LibraryAlreadyOpenError``.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        # Normalize the registry key so relative/absolute and case/slash
        # spellings of one lock file share the same in-process lease instead
        # of reporting a false LibraryAlreadyOpenError.
        self._key = os.path.normcase(os.path.abspath(os.fspath(self.path)))
        self._released = False
        with _registry_guard:
            shared = _held_locks.get(self._key)
            if shared is not None:
                self._lock = shared[0]
                _held_locks[self._key] = (self._lock, shared[1] + 1)
                return

            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock = QLockFile(str(self.path))
            # Never infer liveness from the PID marker or delete it ourselves
            # blindly. Qt's long-lived-resource mode uses a zero stale timeout
            # and reports a live lock to the caller instead; recover only when
            # the recorded PID is provably gone (crashed / force-killed).
            lock.setStaleLockTime(0)
            acquired = lock.tryLock(0)
            if not acquired and lock.error() == QLockFile.LockError.LockFailedError:
                pid, _host, _app = lock.getLockInfo()
                if pid > 0 and not _pid_is_alive(pid):
                    try:
                        self.path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    else:
                        lock = QLockFile(str(self.path))
                        lock.setStaleLockTime(0)
                        acquired = lock.tryLock(0)

            if acquired:
                self._lock = lock
                _held_locks[self._key] = (lock, 1)
                return

            error = lock.error()
            if error == QLockFile.LockError.PermissionError:
                raise PermissionError(f"Cannot acquire library lock: {self.path}")
            if error == QLockFile.LockError.LockFailedError:
                raise LibraryAlreadyOpenError(
                    f"Library is already open: {self.path}"
                )
            raise RuntimeError(
                f"Unable to acquire library lock: {self.path} ({error.name})"
            )

    def release(self) -> bool:
        """Release the OS lock, returning whether Qt accepted the unlock."""
        if self._released:
            return True
        with _registry_guard:
            shared = _held_locks.get(self._key)
            if shared is None or shared[0] is not self._lock:
                # Registry loss/mismatch means the process cannot prove that
                # this handle was released. Keep the object retryable and fail
                # closed instead of reporting a false successful unlock.
                return False
            if shared[1] > 1:
                _held_locks[self._key] = (self._lock, shared[1] - 1)
                self._released = True
                return True
            if not self._lock.isLocked():
                _held_locks.pop(self._key, None)
                self._released = True
                return True
            self._lock.unlock()
            if self._lock.isLocked():
                return False
            _held_locks.pop(self._key, None)
            self._released = True
            return True

    def __del__(self) -> None:
        """Avoid leaking a process-local lease for legacy unclosed services."""
        if getattr(self, "_released", True):
            return
        try:
            self.release()
        except Exception:
            # Destructors must never make interpreter shutdown fail.
            pass
