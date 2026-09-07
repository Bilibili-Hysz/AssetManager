"""Process-wide admission control for temporary ZIP resources.

ZIP creation has two independent resource dimensions: the number of worker
jobs and the amount of output storage reserved by those jobs.  This module
keeps both dimensions in one process-wide budget and exposes reference counted
reservations so a builder and the response that owns its output can safely
share one lease.
"""
from __future__ import annotations

import threading
from typing import Any

from aiohttp import web


MAX_ZIP_OUTPUT_BYTES = 512 * 1024 * 1024


def _validate_nonnegative_int(value: Any, name: str) -> int:
    """Return *value* when it is a non-negative integer.

    ``bool`` is deliberately rejected even though it subclasses ``int``.
    Keeping this check in one place makes constructor and acquire validation
    agree and, more importantly, ensures invalid requests cannot mutate the
    counters.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


class _ReservationState:
    """Mutable state shared by all handles for one reservation."""

    __slots__ = ("budget", "reserved_bytes", "references")

    def __init__(self, budget: ZipResourceBudget, reserved_bytes: int) -> None:
        self.budget = budget
        self.reserved_bytes = reserved_bytes
        self.references = 1


class ZipReservation:
    """One idempotent handle to an admitted ZIP resource reservation.

    A reservation starts with one live handle.  :meth:`retain` creates another
    independent handle over the same counters.  The budget is returned only
    after every retained handle has released, which lets ownership move from a
    ZIP worker to a temporary HTTP response without a gap in admission.
    """

    __slots__ = ("_state", "_released")

    def __init__(self, state: _ReservationState) -> None:
        self._state = state
        self._released = False

    @property
    def reserved_bytes(self) -> int:
        """The number of output bytes reserved by this lease."""
        return self._state.reserved_bytes

    def retain(self) -> ZipReservation:
        """Return an independent live handle sharing this reservation.

        A released handle cannot be resurrected.  Retaining from another live
        handle remains valid even when a sibling handle has already released.
        """
        budget = self._state.budget
        with budget._lock:
            if self._released:
                raise RuntimeError("ZIP reservation handle has been released")
            self._state.references += 1
            return ZipReservation(self._state)

    def release(self) -> None:
        """Release this handle; repeated calls are harmless."""
        budget = self._state.budget
        with budget._lock:
            if self._released:
                return
            self._released = True
            self._state.references -= 1
            if self._state.references == 0:
                # The state is only reachable through live handles, so this
                # cannot underflow when all operations go through this class.
                budget._active_jobs -= 1
                budget._reserved_bytes -= self._state.reserved_bytes


class ZipResourceBudget:
    """Thread-safe process-level ZIP job and output-byte admission budget."""

    def __init__(
        self,
        max_jobs: int = 4,
        max_reserved_bytes: int = 2 * 1024 * 1024 * 1024,
    ) -> None:
        self._max_jobs = _validate_nonnegative_int(max_jobs, "max_jobs")
        self._max_reserved_bytes = _validate_nonnegative_int(
            max_reserved_bytes, "max_reserved_bytes"
        )
        self._active_jobs = 0
        self._reserved_bytes = 0
        self._lock = threading.Lock()

    @property
    def max_jobs(self) -> int:
        """Configured maximum number of simultaneously admitted jobs."""
        return self._max_jobs

    @property
    def max_reserved_bytes(self) -> int:
        """Configured maximum aggregate output bytes."""
        return self._max_reserved_bytes

    def try_acquire(
        self, reserved_bytes: int = MAX_ZIP_OUTPUT_BYTES
    ) -> ZipReservation | None:
        """Admit a reservation if both process limits have room.

        Invalid input raises ``ValueError`` before the lock or counters are
        touched.  A valid request that does not fit returns ``None`` and also
        leaves the snapshot unchanged.
        """
        requested = _validate_nonnegative_int(reserved_bytes, "reserved_bytes")
        with self._lock:
            if self._active_jobs >= self._max_jobs:
                return None
            if requested > self._max_reserved_bytes - self._reserved_bytes:
                return None
            self._active_jobs += 1
            self._reserved_bytes += requested
            return ZipReservation(_ReservationState(self, requested))

    def snapshot(self) -> dict[str, int]:
        """Return a consistent point-in-time view of the active counters."""
        with self._lock:
            return {
                "active_jobs": self._active_jobs,
                "reserved_bytes": self._reserved_bytes,
            }


_PROCESS_ZIP_BUDGET = ZipResourceBudget()


def get_process_zip_budget() -> ZipResourceBudget:
    """Return the process singleton shared by all LAN server instances."""
    return _PROCESS_ZIP_BUDGET


ZIP_BUDGET_APP_KEY = web.AppKey("zip_budget", ZipResourceBudget)


__all__ = [
    "MAX_ZIP_OUTPUT_BYTES",
    "ZIP_BUDGET_APP_KEY",
    "ZipReservation",
    "ZipResourceBudget",
    "get_process_zip_budget",
]
