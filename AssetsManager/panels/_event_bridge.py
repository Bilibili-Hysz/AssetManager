"""Qt bridge for domain events consumed by presentation widgets."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import DomainEvent


class DomainEventSubscription(QObject):
    """Forward domain events through a Qt signal before invoking UI code."""

    event_received = Signal(object)

    def __init__(self, event_type: type[DomainEvent], slot, parent: QObject | None = None):
        super().__init__(parent)
        self._closed = False
        self.event_received.connect(slot)
        self._subscription = get_event_bus().subscribe_weak(event_type, self._on_domain_event)

    def _on_domain_event(self, event: DomainEvent) -> None:
        self.event_received.emit(event)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._subscription.close()
        try:
            self.event_received.disconnect()
        except (RuntimeError, TypeError):
            pass
