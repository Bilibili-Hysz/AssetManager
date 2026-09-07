"""Bounded retry cleanup for explicitly registered ZIP archives.

This module intentionally has no directory scan or crash-recovery behaviour.
Callers register an archive only after they have released their own file handle.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections.abc import Callable, Hashable
from dataclasses import dataclass

_log = logging.getLogger(__name__)


@dataclass
class _PendingCleanup:
    attempt: Callable[[], bool]
    due_at: float
    created_at: float
    retries: int = 0
    retry_delay: float = 0.0
    running: bool = False


class ZipCleanupService:
    """Retry failed archive cleanup without retaining unbounded work.

    A key owns its first registered callback until it completes.  This is
    important because callbacks commonly hold the last reference to a file
    response and replacing one could leak that response's release action.
    """

    def __init__(
        self,
        max_pending: int = 1024,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        start_worker: bool = True,
    ) -> None:
        if isinstance(max_pending, bool) or not isinstance(max_pending, int) or max_pending < 1:
            raise ValueError("max_pending must be at least one")
        if not math.isfinite(base_delay) or base_delay <= 0:
            raise ValueError("base_delay must be finite and positive")
        if not math.isfinite(max_delay) or max_delay < base_delay:
            raise ValueError("max_delay must be at least base_delay")
        self._max_pending = max_pending
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._clock = clock
        self._start_worker = start_worker
        self._condition = threading.Condition()
        self._pending: dict[Hashable, _PendingCleanup] = {}
        self._worker: threading.Thread | None = None
        self._stop_worker = False
        self._completed_count = 0
        self._retry_attempts = 0
        self._last_error_type: str | None = None

    def schedule(self, key: Hashable, attempt: Callable[[], bool]) -> bool:
        """Register a retry callback, preserving the existing callback for a key."""
        hash(key)
        with self._condition:
            if key in self._pending:
                self._ensure_worker_locked()
                self._condition.notify_all()
                return True
            if len(self._pending) >= self._max_pending:
                _log.warning("ZIP cleanup retry queue is full")
                return False
            now = self._clock()
            self._pending[key] = _PendingCleanup(
                attempt=attempt,
                due_at=now + self._base_delay,
                created_at=now,
                retry_delay=self._base_delay,
            )
            self._ensure_worker_locked()
            self._condition.notify_all()
            return True

    def run_due(self) -> int:
        """Run callbacks that are due now and return the number started.

        This is also useful with ``start_worker=False`` and custom clocks.
        Callbacks always execute without the service lock held.
        """
        due: list[tuple[Hashable, _PendingCleanup]] = []
        with self._condition:
            now = self._clock()
            for key, pending in self._pending.items():
                if not pending.running and pending.due_at <= now:
                    pending.running = True
                    due.append((key, pending))
            self._retry_attempts += len(due)
        for key, pending in due:
            succeeded = False
            try:
                succeeded = bool(pending.attempt())
            except Exception as exc:
                with self._condition:
                    self._last_error_type = type(exc).__name__
                _log.warning("ZIP cleanup retry callback raised %s", type(exc).__name__)
            with self._condition:
                # A callback may have called into this service.  Only update
                # the exact entry that was marked running above.
                if self._pending.get(key) is not pending:
                    continue
                pending.running = False
                if succeeded:
                    del self._pending[key]
                    self._completed_count += 1
                else:
                    pending.retries += 1
                    pending.retry_delay = min(self._max_delay, pending.retry_delay * 2)
                    pending.due_at = self._clock() + pending.retry_delay
                self._condition.notify_all()
        return len(due)

    def snapshot(self) -> dict[str, int | float | str | None]:
        """Return operational counters without exposing paths or exception text."""
        with self._condition:
            now = self._clock()
            oldest = (
                max(0.0, now - min(item.created_at for item in self._pending.values()))
                if self._pending
                else 0.0
            )
            return {
                "pending_count": len(self._pending),
                "retry_attempts": self._retry_attempts,
                "completed_count": self._completed_count,
                "oldest_pending_seconds": oldest,
                "last_error_type": self._last_error_type,
            }

    def close(self, wait_timeout: float = 0.2) -> None:
        """Stop the current worker without discarding pending cleanup callbacks."""
        if wait_timeout < 0:
            raise ValueError("wait_timeout must not be negative")
        with self._condition:
            self._stop_worker = True
            worker = self._worker
            self._condition.notify_all()
        if worker is not None and worker is not threading.current_thread():
            worker.join(wait_timeout)

    def _ensure_worker_locked(self) -> None:
        if not self._start_worker:
            return
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop_worker = False
        worker = threading.Thread(target=self._worker_main, daemon=True)
        self._worker = worker
        try:
            worker.start()
        except RuntimeError as exc:
            if self._worker is worker:
                self._worker = None
            self._last_error_type = type(exc).__name__
            _log.warning("ZIP cleanup worker start raised %s", type(exc).__name__)

    def _worker_main(self) -> None:
        try:
            while True:
                with self._condition:
                    if self._stop_worker or not self._pending:
                        if self._worker is threading.current_thread():
                            self._worker = None
                        return
                    now = self._clock()
                    due_values = [item.due_at for item in self._pending.values() if not item.running]
                    if not due_values:
                        # A manual ``run_due`` call has claimed the only entry.
                        # Its completion notifies us, so this has no polling loop.
                        self._condition.wait()
                        continue
                    next_due = min(due_values)
                    timeout = max(0.0, next_due - now)
                    if timeout > 0:
                        self._condition.wait(timeout)
                        continue
                self.run_due()
        finally:
            with self._condition:
                if self._worker is threading.current_thread():
                    self._worker = None
                self._condition.notify_all()


@dataclass(frozen=True)
class _PathFingerprint:
    device: int
    inode: int
    size: int
    modified_ns: int


def _fingerprint(path: str) -> _PathFingerprint | None:
    try:
        stat = os.lstat(path)
    except FileNotFoundError:
        return None
    return _PathFingerprint(stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


class _PathCleanupAttempt:
    """One path deletion intent, retaining an optional release callback."""

    def __init__(
        self, path: str, fingerprint: _PathFingerprint | None, callback: Callable[[], None] | None
    ) -> None:
        self._path = path
        self._fingerprint = fingerprint
        self._callback = callback
        self._lock = threading.Lock()
        self._finished = False
        self._executing = False

    def __call__(self) -> bool:
        with self._lock:
            if self._finished:
                return True
            if self._executing:
                return False
            self._executing = True
        completed = False
        try:
            try:
                current = _fingerprint(self._path)
            except OSError:
                raise
            if current is None:
                completed = True
            elif self._fingerprint is None:
                # We could not establish which file failed its original
                # deletion.  Retrying would risk deleting a replacement.
                raise IdentityUnavailableError()
            elif current != self._fingerprint:
                raise IdentityChangedError()
            else:
                try:
                    os.unlink(self._path)
                except FileNotFoundError:
                    completed = True
                except OSError:
                    raise
                else:
                    completed = True
        finally:
            callback = self._complete() if completed else None
            if not completed:
                self._clear_executing()
        if callback is not None:
            try:
                callback()
            except Exception as exc:
                _log.warning("ZIP cleanup completion callback raised %s", type(exc).__name__)
        return completed

    def _complete(self) -> Callable[[], None] | None:
        with self._lock:
            self._executing = False
            if self._finished:
                return None
            self._finished = True
            callback = self._callback
            self._callback = None
            return callback

    def _clear_executing(self) -> None:
        with self._lock:
            self._executing = False


class IdentityChangedError(Exception):
    """The archive pathname now identifies a different file."""


class IdentityUnavailableError(Exception):
    """The original archive identity could not be read safely."""


_PROCESS_ZIP_CLEANUP_LOCK = threading.Lock()
_PROCESS_ZIP_CLEANUP: ZipCleanupService | None = None


def get_process_zip_cleanup() -> ZipCleanupService:
    """Return the process-lifetime ZIP cleanup service."""
    global _PROCESS_ZIP_CLEANUP
    with _PROCESS_ZIP_CLEANUP_LOCK:
        if _PROCESS_ZIP_CLEANUP is None:
            _PROCESS_ZIP_CLEANUP = ZipCleanupService()
        return _PROCESS_ZIP_CLEANUP


def cleanup_zip_path(path: str | os.PathLike[str], on_cleanup: Callable[[], None] | None = None) -> bool:
    """Try to delete an explicit archive now and schedule a safe retry on failure."""
    normalized = os.path.normcase(os.path.abspath(os.fspath(path)))
    try:
        fingerprint = _fingerprint(normalized)
    except OSError:
        fingerprint = None
    attempt = _PathCleanupAttempt(normalized, fingerprint, on_cleanup)
    try:
        if attempt():
            return True
    except (IdentityChangedError, IdentityUnavailableError, OSError):
        pass
    # Identity-based owner makes different callbacks for a shared path distinct.
    # The object remains strongly held by the queue until cleanup completes.
    get_process_zip_cleanup().schedule((normalized, attempt), attempt)
    return False
