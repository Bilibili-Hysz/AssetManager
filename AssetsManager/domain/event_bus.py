"""Event bus — decoupled event publishing and subscribing.

The EventBus allows domain services and application services to communicate
without direct coupling. Handlers are simple callables that receive a
DomainEvent instance.

Usage:
    from AssetsManager.domain.event_bus import get_event_bus
    bus = get_event_bus()
    bus.subscribe(TagsChanged, lambda e: print(f"Tags changed: {e.new_tags}"))
    bus.publish(TagsChanged(file_path="/path/to/file", new_tags=("hero",)))
"""
from __future__ import annotations

import logging
import threading
import weakref
from collections import defaultdict
from typing import Callable

from AssetsManager.domain.events import DomainEvent

_log = logging.getLogger(__name__)


_instance: EventBus | None = None
_instance_lock = threading.Lock()


class EventSubscription:
    """Idempotent handle returned by ``EventBus.subscribe()``."""

    def __init__(self, bus: EventBus, event_type: type[DomainEvent], handler: Callable):
        self._bus = bus
        self._event_type = event_type
        self._handler = handler
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._bus.unsubscribe(self._event_type, self._handler)


class WeakEventSubscription(EventSubscription):
    """Subscription that does not keep a bound-method owner alive."""

    def __init__(self, bus: EventBus, event_type: type[DomainEvent], handler: Callable):
        self._weak_method = weakref.WeakMethod(handler)
        super().__init__(bus, event_type, self._dispatch)

    def _dispatch(self, event: DomainEvent) -> None:
        method = self._weak_method()
        if method is None:
            self.close()
            return
        method(event)


def get_event_bus() -> EventBus:
    """Return the global EventBus singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = EventBus()
    return _instance


class EventBus:
    """In-process event bus for domain events.

    Thread-safe: subscribe/unsubscribe/publish can be called from any thread.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._handlers: dict[type[DomainEvent], list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: type[DomainEvent], handler: Callable) -> EventSubscription:
        """Subscribe a handler to a specific event type."""
        with self._lock:
            self._handlers[event_type].append(handler)
        return EventSubscription(self, event_type, handler)

    def subscribe_weak(self, event_type: type[DomainEvent], handler: Callable) -> WeakEventSubscription:
        """Subscribe a bound method without keeping its owner alive."""
        subscription = WeakEventSubscription(self, event_type, handler)
        with self._lock:
            self._handlers[event_type].append(subscription._dispatch)
        return subscription

    def unsubscribe(self, event_type: type[DomainEvent], handler: Callable) -> None:
        """Unsubscribe a handler from a specific event type."""
        with self._lock:
            handlers = self._handlers.get(event_type, [])
            if handler in handlers:
                handlers.remove(handler)

    def publish(self, event: DomainEvent) -> None:
        """Publish an event to all subscribed handlers.

        Handlers are called synchronously in subscription order.
        Exceptions in one handler do not prevent other handlers from running.
        The handler list is snapshot-locked to avoid mutation during iteration.
        """
        event_type = type(event)
        with self._lock:
            handlers = list(self._handlers.get(event_type, []))
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                _log.exception(
                    "Event handler failed for %s", event_type.__name__
                )

    def clear(self) -> None:
        """Remove all subscriptions."""
        with self._lock:
            self._handlers.clear()

    def handler_count(self, event_type: type[DomainEvent]) -> int:
        """Return the number of handlers subscribed to an event type."""
        with self._lock:
            return len(self._handlers.get(event_type, []))
