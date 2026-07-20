"""Small, opt-in performance event recorder for scoped diagnostics."""
from __future__ import annotations

from collections import deque
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from math import isfinite
from numbers import Real
from threading import Lock
from time import perf_counter, time
from types import MappingProxyType


PerformanceAttribute = str | int | float | bool


@dataclass(frozen=True, slots=True)
class PerformanceEvent:
    """One bounded diagnostic measurement with optional work correlation."""

    name: str
    elapsed_ms: float
    occurred_at: float
    session_token: str | None = None
    generation: int | None = None
    path: str | None = None
    attributes: Mapping[str, PerformanceAttribute] = MappingProxyType({})


class PerformanceRecorder:
    """Thread-safe bounded recorder, disabled unless explicitly enabled."""

    def __init__(self, *, enabled: bool = False, max_events: int = 200) -> None:
        if max_events <= 0:
            raise ValueError("max_events must be positive")
        self._enabled = enabled
        self._events: deque[PerformanceEvent] = deque(maxlen=max_events)
        self._lock = Lock()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def record(
        self,
        name: str,
        elapsed_ms: float,
        *,
        session_token: str | None = None,
        generation: int | None = None,
        path: str | None = None,
        attributes: Mapping[str, PerformanceAttribute] | None = None,
    ) -> None:
        """Append a measurement when enabled, retaining only recent events."""
        if not self._enabled:
            return
        self._validate_context(name, elapsed_ms, session_token, generation, path)
        event = PerformanceEvent(
            name=name,
            elapsed_ms=max(0.0, float(elapsed_ms)),
            occurred_at=time(),
            session_token=session_token,
            generation=generation,
            path=path,
            attributes=MappingProxyType(dict(attributes or {})),
        )
        with self._lock:
            self._events.append(event)

    @contextmanager
    def measure(
        self,
        name: str,
        *,
        session_token: str | None = None,
        generation: int | None = None,
        path: str | None = None,
        attributes: Mapping[str, PerformanceAttribute] | None = None,
    ) -> Iterator[None]:
        """Measure a synchronous block with the monotonic process clock."""
        if not self._enabled:
            yield
            return
        started = perf_counter()
        try:
            yield
        except BaseException:
            # Diagnostics must not replace an exception from the measured work.
            try:
                self.record(
                    name,
                    (perf_counter() - started) * 1000,
                    session_token=session_token,
                    generation=generation,
                    path=path,
                    attributes=attributes,
                )
            except (TypeError, ValueError):
                pass
            raise
        else:
            self.record(
                name,
                (perf_counter() - started) * 1000,
                session_token=session_token,
                generation=generation,
                path=path,
                attributes=attributes,
            )

    def recent(self, limit: int | None = None) -> tuple[PerformanceEvent, ...]:
        """Return an immutable oldest-to-newest snapshot of retained events."""
        with self._lock:
            events = tuple(self._events)
        return events if limit is None else events[-max(0, limit):]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    @staticmethod
    def _validate_context(
        name: str,
        elapsed_ms: float,
        session_token: str | None,
        generation: int | None,
        path: str | None,
    ) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")
        if isinstance(elapsed_ms, bool) or not isinstance(elapsed_ms, Real) or not isfinite(elapsed_ms):
            raise ValueError("elapsed_ms must be a finite number")
        if session_token is not None and not isinstance(session_token, str):
            raise TypeError("session_token must be a string or None")
        if isinstance(generation, bool) or (generation is not None and not isinstance(generation, int)):
            raise TypeError("generation must be an integer or None")
        if path is not None and not isinstance(path, str):
            raise TypeError("path must be a string or None")
