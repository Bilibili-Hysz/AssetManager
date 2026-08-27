"""Qt bridge for domain events consumed by presentation widgets."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Qt

from AssetsManager.application.asset_filters import subscribe_category_registry_changed
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import DomainEvent


class DomainEventSubscription(QObject):
    """Forward domain events through a Qt signal before invoking UI code."""

    event_received = Signal(object)

    def __init__(self, event_type: type[DomainEvent], slot, parent: QObject | None = None):
        super().__init__(parent)
        self._closed = False
        # Queued delivery: domain events may be published from worker threads
        # (e.g. metadata writes inside FileInfoTask), so the slot must always
        # run on the subscription's thread (the GUI thread) — a direct
        # connection would execute UI code on the publishing thread.
        self.event_received.connect(slot, Qt.ConnectionType.QueuedConnection)
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


class CategoryRegistrySubscription(QObject):
    """Forward category publications through a queued Qt signal."""

    changed = Signal()

    def __init__(self, slot, parent: QObject | None = None):
        super().__init__(parent)
        self._closed = False
        self.changed.connect(slot, Qt.ConnectionType.QueuedConnection)
        self._subscription = subscribe_category_registry_changed(self._on_changed)

    def _on_changed(self) -> None:
        self.changed.emit()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._subscription.close()
        try:
            self.changed.disconnect()
        except (RuntimeError, TypeError):
            pass


class RuntimeEventSubscription(QObject):
    """Forward runtime invalidations through a Qt signal before UI code runs."""

    event_received = Signal(object)

    def __init__(self, runtime, slot, parent: QObject | None = None):
        super().__init__(parent)
        self._closed = False
        self.event_received.connect(slot, Qt.ConnectionType.QueuedConnection)
        self._subscription = runtime.event_router.subscribe(self._on_invalidation)

    def _on_invalidation(self, invalidation) -> None:
        self.event_received.emit(invalidation)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._subscription.close()
        try:
            self.event_received.disconnect()
        except (RuntimeError, TypeError):
            pass
