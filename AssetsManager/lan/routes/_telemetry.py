"""Shared route telemetry for the LAN API.

Every instrumented route funnels its single performance event through
:func:`record_route_event` so the recorder contract cannot drift between
files: recorder-presence/enablement early exit, monotonic elapsed time,
``session_token``/``path`` correlation, and swallow-on-error semantics
(diagnostics must never alter a response, a transfer, or a security
outcome — the same contract the previously duplicated per-file
``_record_*_route`` helpers implemented).
"""
from __future__ import annotations

from time import perf_counter
from typing import Any

__all__ = ["record_route_event"]


def record_route_event(
    lan: Any,
    name: str,
    *,
    started: float,
    status: int,
    outcome: str,
    path: Any = None,
    kind: str | None = None,
    phase: str | None = None,
    **extra: Any,
) -> None:
    """Record one route event when the LAN performance recorder is enabled.

    ``None`` values in ``kind``/``phase``/``extra`` are dropped so callers can
    pass optional context directly; concrete falsy values are kept (e.g.
    ``cache_hit=False`` is a meaningful attribute). Event names and attribute
    keys are part of the locked telemetry contract.
    """
    recorder = getattr(lan, "performance_recorder", None)
    if recorder is None or not recorder.enabled:
        return
    attributes: dict[str, Any] = {"outcome": outcome, "status": status}
    if phase is not None:
        attributes["phase"] = phase
    if kind is not None:
        attributes["kind"] = kind
    for key, value in extra.items():
        if value is not None:
            attributes[key] = value
    try:
        recorder.record(
            name,
            (perf_counter() - started) * 1000,
            session_token=getattr(lan, "session_token", None),
            path=str(path) if path is not None else None,
            attributes=attributes,
        )
    except Exception:
        # Diagnostics must not alter response construction or transfer semantics.
        pass
