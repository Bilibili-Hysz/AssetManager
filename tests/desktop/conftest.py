"""Desktop panel test fixtures."""
import os
from contextlib import contextmanager

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.panels.file_list import FileListPanel


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


@contextmanager
def _scoped_file_list_panel(tmp_path):
    """Build a FileListPanel bound to a fresh library session at ``tmp_path``.

    The panel is pre-navigated to the library root and the initial scan is
    awaited; panel shutdown and session close happen on exit.
    """
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path)
    services = bootstrap.runtime_for(session).services
    panel = FileListPanel()
    panel.set_scoped_services(services)
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()
    try:
        yield panel, session, bootstrap, services
    finally:
        panel.shutdown()
        bootstrap.library_service.close_session(session)
        app.processEvents()


@pytest.fixture
def file_list_panel(tmp_path):
    """FileListPanel bound to a fresh library rooted at ``tmp_path``.

    Services come from a dedicated ``ApplicationBootstrap`` session; the panel
    starts on the library root with the initial scan already completed.
    """
    with _scoped_file_list_panel(tmp_path) as (panel, _session, _bootstrap, _services):
        yield panel


@pytest.fixture
def file_list_panel_ctx(tmp_path):
    """``(panel, session, bootstrap, services)`` for tests that need handles.

    Same construction as :func:`file_list_panel`; use when the test must touch
    the session, the bootstrap, or the injected scoped services directly.
    """
    with _scoped_file_list_panel(tmp_path) as ctx:
        yield ctx


@pytest.fixture
def plain_panel():
    """Bare FileListPanel without scoped services; shutdown on teardown."""
    app = QApplication.instance() or QApplication([])
    panel = FileListPanel()
    yield panel
    panel.shutdown()
    panel.deleteLater()
    app.processEvents()
