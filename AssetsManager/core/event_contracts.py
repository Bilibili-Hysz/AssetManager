"""Core event contracts — infrastructure types shared by core and domain.

``domain.events.DomainEvent`` inherits from :class:`DomainEventBase` so the
core plugin host can validate plugin event hooks without importing the
domain layer.  Core modules therefore depend on this file only; the domain
layer owns the concrete events and the bus implementation.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class DomainEventBase:
    """Marker base for every domain event record."""

    timestamp: float = field(default_factory=time.time)


class EventSubscriptionPort(Protocol):
    """Minimal handle returned by an event bus subscription."""

    def close(self) -> None: ...


class EventBusPort(Protocol):
    """Event-bus surface needed by core plugin registration."""

    def subscribe(
        self, event_type: type, handler: Callable[..., Any]
    ) -> EventSubscriptionPort: ...
