"""Unified worker framework for background Qt tasks.

``ThumbnailLoader`` proved the pattern this module generalizes: every
long-running task carries a generation and a cancellation token, and owners
submit through a bounded pool that can be cancelled and drained with an
explicit timeout.  ``prepare_library_switch`` / ``shutdown`` paths use the
timeout (never an unbounded ``waitForDone``) so the UI thread cannot hang
behind a directory walk.
"""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QRunnable, QThreadPool


_log = logging.getLogger(__name__)
_retained_pools: dict[int, QThreadPool] = {}
_retained_pools_lock = threading.Lock()


def _reap_pool(pool: QThreadPool, owner_label: str) -> None:
    """Release a timed-out private pool away from the GUI teardown thread."""
    try:
        pool.waitForDone()
    except Exception:
        _log.exception("Timed-out worker pool reaper failed for %s", owner_label)
    finally:
        with _retained_pools_lock:
            _retained_pools.pop(id(pool), None)


def retained_pool_count() -> int:
    """Return private pools awaiting background reaping for lifecycle tests."""
    with _retained_pools_lock:
        return len(_retained_pools)


class CancellationToken:
    """Thread-safe cooperative cancellation flag."""

    def __init__(self) -> None:
        self._cancelled = False
        self._lock = threading.Lock()

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True

    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise TaskCancelled()


class TaskCancelled(Exception):
    """Raised when a worker observes its cancellation token set."""


class CancellableRunnable(QRunnable):
    """QRunnable carrying a generation and cancellation token.

    Subclasses call :meth:`is_cancelled` inside loops and before emitting
    signals.  The default auto-delete behavior is preserved.
    """

    def __init__(
        self,
        generation: int = 0,
        cancel_token: CancellationToken | None = None,
    ) -> None:
        super().__init__()
        self.generation = generation
        self.cancel_token = cancel_token or CancellationToken()

    def is_cancelled(self) -> bool:
        return self.cancel_token.is_cancelled()


class BoundedPool:
    """A private QThreadPool with generation-aware cooperative cancellation.

    Using a private pool (instead of ``QThreadPool.globalInstance``) means an
    owner can drain only its own work and can guarantee a timeout instead of
    blocking on unrelated global tasks.
    """

    def __init__(self, max_thread_count: int = 1) -> None:
        self._pool: QThreadPool | None = QThreadPool()
        self._pool.setMaxThreadCount(max(1, int(max_thread_count)))
        self._tokens: list[CancellationToken] = []
        self._tokens_lock = threading.Lock()
        self._closed = False

    def _require_pool(self) -> QThreadPool:
        pool = self._pool
        if pool is None:
            raise RuntimeError("BoundedPool is closed")
        return pool

    @property
    def max_thread_count(self) -> int:
        return self._require_pool().maxThreadCount()

    def start(self, runnable: CancellableRunnable) -> None:
        """Queue *runnable* and track its cancellation token."""
        with self._tokens_lock:
            if self._closed:
                raise RuntimeError("BoundedPool is closed")
            self._tokens.append(runnable.cancel_token)
            self._require_pool().start(runnable)

    def cancel_all(self) -> None:
        """Cancel every tracked token without waiting for completion.

        Tracked tokens are dropped after cancellation so a long-lived pool
        does not accumulate one entry per historical task submission.
        Submissions made after ``cancel_all`` re-register their own tokens
        and are unaffected; a submission racing with this call either lands
        in the cancelled batch or starts under the owner's fresh token.
        """
        with self._tokens_lock:
            tokens = list(self._tokens)
            self._tokens.clear()
        for token in tokens:
            token.cancel()

    def drain(self, timeout_ms: int = 5000) -> bool:
        """Wait at most *timeout_ms* for queued/running tasks to finish."""
        return bool(self._require_pool().waitForDone(int(timeout_ms)))

    def close(self, timeout_ms: int = 5000, *, owner_label: str = "BoundedPool") -> bool:
        """Cancel work and release the private pool without blocking GUI teardown.

        A timed-out native pool is retained by a daemon reaper until its workers
        finish, so dropping the owner's wrapper cannot invoke a blocking pool
        destructor on the caller thread.
        """
        with self._tokens_lock:
            if self._closed:
                return self._pool is None
            self._closed = True
            tokens = list(self._tokens)
            self._tokens.clear()
            pool = self._require_pool()
        for token in tokens:
            token.cancel()
        if pool.waitForDone(int(timeout_ms)):
            self._pool = None
            return True
        with _retained_pools_lock:
            _retained_pools[id(pool)] = pool
        self._pool = None
        _log.warning(
            "Worker pool close timed out for %s after %sms (%s active thread(s)); reaping in background",
            owner_label,
            timeout_ms,
            pool.activeThreadCount(),
        )
        threading.Thread(
            target=_reap_pool,
            args=(pool, owner_label),
            name=f"{owner_label}-pool-reaper",
            daemon=True,
        ).start()
        return False

    def active_thread_count(self) -> int:
        pool = self._pool
        return 0 if pool is None else pool.activeThreadCount()


def should_continue(token: CancellationToken | None) -> bool:
    """Return True while *token* is unset or absent."""
    return token is None or not token.is_cancelled()
