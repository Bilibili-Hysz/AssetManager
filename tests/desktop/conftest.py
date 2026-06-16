"""Desktop panel test fixtures."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from AssetsManager.application.bootstrap import ApplicationBootstrap


@pytest.fixture(autouse=True)
def _bootstrap_app():
    """Set up ApplicationBootstrap on QApplication for panel tests.

    Panels call ``require_scoped_services()`` which reads
    ``QApplication.property("bootstrap")``. Without this, any panel
    that resolves scoped services raises ``RuntimeError``.
    """
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    yield bootstrap
    app.setProperty("bootstrap", None)
