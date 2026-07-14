"""Tests for domain event → panel bridging (Phase 3 convergence)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from AssetsManager.panels._event_bridge import DomainEventSubscription
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import LibraryOpened


def test_domain_event_subscription_forwards_library_opened():
    """DomainEventSubscription must deliver LibraryOpened on the Qt thread."""
    app = QApplication.instance() or QApplication([])
    received: list[object] = []

    def slot(event):
        received.append(event)

    sub = DomainEventSubscription(LibraryOpened, slot)
    try:
        get_event_bus().publish(LibraryOpened(library_root="/tmp/library"))
        app.processEvents()

        assert len(received) == 1
        assert received[0].library_root == "/tmp/library"
    finally:
        sub.close()
