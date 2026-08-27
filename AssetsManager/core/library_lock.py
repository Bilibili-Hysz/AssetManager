"""Cross-process library lock backed by Qt's QLockFile semantics."""
from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QLockFile


class LibraryAlreadyOpenError(RuntimeError):
    """The requested library is already owned by another process."""


class _PosixRecoveryUnavailable(RuntimeError):
    """The platform cannot provide the synchronization recovery requires."""


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


def _new_lock(path: Path) -> QLockFile:
    """Create a long-lived QLockFile for *path*."""
    lock = QLockFile(str(path))
    # A zero timeout disables Qt's time-based stale recovery. Recovery below
    # is based only on a recorded PID that is provably no longer alive.
    lock.setStaleLockTime(0)
    return lock


@contextmanager
def _posix_stale_recovery_guard(path: Path) -> Iterator[None]:
    """Serialize stale-marker recovery and clean up its transient marker.

    The parent directory is the stable mutex. Holding it for the complete
    context means no process can open the recovery marker while another
    process is removing it, so a removed marker cannot strand waiters on an
    unlinked inode while a new waiter starts on a replacement inode.
    """
    if os.name == "nt":
        raise _PosixRecoveryUnavailable("POSIX stale recovery is unavailable")
    try:
        import fcntl
    except ImportError as error:
        raise _PosixRecoveryUnavailable(
            "fcntl.flock is unavailable on this platform"
        ) from error

    flock = getattr(fcntl, "flock", None)
    lock_ex = getattr(fcntl, "LOCK_EX", None)
    lock_un = getattr(fcntl, "LOCK_UN", None)
    if not callable(flock) or lock_ex is None or lock_un is None:
        raise _PosixRecoveryUnavailable(
            "fcntl.flock is unavailable on this platform"
        )

    guard_path = path.with_name(path.name + ".recovery")
    directory_fd: int | None = None
    directory_locked = False
    marker_created = False
    try:
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(os.fspath(path.parent), directory_flags)
        try:
            flock(directory_fd, lock_ex)
            directory_locked = True
        except OSError as error:
            raise _PosixRecoveryUnavailable(
                "fcntl.flock cannot lock the library directory"
            ) from error

        try:
            # A previous process may have been terminated while holding the
            # directory lock. Remove only that stale marker while admission is
            # still serialized, then publish this recovery window atomically.
            try:
                os.unlink(os.fspath(guard_path))
            except FileNotFoundError:
                pass
            marker_fd = os.open(
                os.fspath(guard_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            marker_created = True
            os.close(marker_fd)
        except OSError as error:
            raise _PosixRecoveryUnavailable(
                "the POSIX recovery marker cannot be created"
            ) from error

        try:
            yield
        finally:
            try:
                os.unlink(os.fspath(guard_path))
            except FileNotFoundError:
                pass
            except OSError:
                # A failed cleanup is harmless to ownership: the next
                # serialized recovery attempt removes the stale marker.
                pass
            marker_created = False
    finally:
        if marker_created:
            try:
                os.unlink(os.fspath(guard_path))
            except (FileNotFoundError, OSError):
                pass
        if directory_locked and directory_fd is not None:
            try:
                flock(directory_fd, lock_un)
            except OSError:
                pass
        if directory_fd is not None:
            os.close(directory_fd)


def _recover_posix_stale_lock(
    path: Path, initial_lock: QLockFile | None = None
) -> tuple[QLockFile, bool]:
    """Recover a dead POSIX marker while preventing competing unlinkers."""
    lock = initial_lock or _new_lock(path)
    try:
        with _posix_stale_recovery_guard(path):
            # A contender may have recovered the marker while this process
            # waited for the guard. Recheck before deciding that it is stale.
            lock = _new_lock(path)
            acquired = lock.tryLock(0)
            if not acquired and lock.error() == QLockFile.LockError.LockFailedError:
                pid, _host, _app = lock.getLockInfo()
                if pid > 0 and not _pid_is_alive(pid):
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    else:
                        lock = _new_lock(path)
                        acquired = lock.tryLock(0)
            return lock, acquired
    except _PosixRecoveryUnavailable:
        # Recovery capability is optional. Keeping the original marker
        # decision makes the caller fail closed as LibraryAlreadyOpenError.
        return lock, False


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
            lock = _new_lock(self.path)
            acquired = lock.tryLock(0)
            if not acquired and lock.error() == QLockFile.LockError.LockFailedError:
                if os.name == "nt":
                    pid, _host, _app = lock.getLockInfo()
                    if pid > 0 and not _pid_is_alive(pid):
                        try:
                            self.path.unlink(missing_ok=True)
                        except OSError:
                            pass
                        else:
                            lock = _new_lock(self.path)
                            acquired = lock.tryLock(0)
                else:
                    lock, acquired = _recover_posix_stale_lock(self.path, lock)

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
