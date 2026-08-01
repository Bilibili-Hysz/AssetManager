"""Desktop panel test fixtures."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from AssetsManager.application.bootstrap import ApplicationBootstrap


@pytest.fixture(autouse=True)
def _bootstrap_app():
    """Set up ApplicationBootstrap on QApplication for panel tests.

    Tests may use this bootstrap to open canonical sessions and explicitly
    inject ``bootstrap.runtime_for(session).services`` into panels.
    """
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    yield bootstrap
    for widget in app.topLevelWidgets():
        shutdown = getattr(widget, "shutdown", None)
        if callable(shutdown):
            shutdown()
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.setProperty("bootstrap", None)
