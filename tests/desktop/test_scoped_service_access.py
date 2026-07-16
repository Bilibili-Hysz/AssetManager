"""Tests for presentation scoped service access policy.

Verifies that get/require semantics are correct:
- get: quiet return (None if unavailable)
- require: raise if unavailable
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.panels._service_access import (
    get_scoped_services,
    require_scoped_services,
)


@pytest.fixture(autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setProperty("bootstrap", None)
    yield app
    app.setProperty("bootstrap", None)
    app.processEvents()


def test_get_scoped_services_returns_none_without_bootstrap(qapp):
    result = get_scoped_services("/some/path")
    assert result is None


def test_require_scoped_services_raises_without_bootstrap(qapp):
    with pytest.raises(RuntimeError, match="TestPanel requires scoped library services"):
        require_scoped_services("/some/path", consumer="TestPanel")


def test_get_scoped_services_returns_services_with_bootstrap(qapp, tmp_path):
    (tmp_path / "file.txt").write_text("x")
    bootstrap = ApplicationBootstrap()
    qapp.setProperty("bootstrap", bootstrap)
    bootstrap.library_service.open_session(tmp_path)

    result = get_scoped_services(tmp_path)
    assert result is not None
    assert result.session.root == tmp_path.resolve()


def test_require_scoped_services_returns_services_with_bootstrap(qapp, tmp_path):
    (tmp_path / "file.txt").write_text("x")
    bootstrap = ApplicationBootstrap()
    qapp.setProperty("bootstrap", bootstrap)
    bootstrap.library_service.open_session(tmp_path)

    result = require_scoped_services(tmp_path, consumer="TestPanel")
    assert result is not None
    assert result.session.root == tmp_path.resolve()


def test_require_scoped_services_raises_for_unopened_library_with_bootstrap(qapp, tmp_path):
    import unittest.mock as mock

    bootstrap = ApplicationBootstrap()
    qapp.setProperty("bootstrap", bootstrap)
    # Mock open_session to simulate a resolution failure
    with mock.patch.object(
        bootstrap.library_service, "open_session", side_effect=RuntimeError("DB init failed")
    ):
        with pytest.raises(RuntimeError, match="requires scoped library services"):
            require_scoped_services(tmp_path, consumer="TestPanel")


def test_main_window_injects_one_scoped_bundle_into_all_applicable_panels(qapp, monkeypatch):
    """MainWindow owns scoped resolution and gives each panel the same bundle."""
    from unittest.mock import Mock

    from AssetsManager.window import MainWindow

    session = object()
    services = object()
    bootstrap = Mock()
    bootstrap.for_library.return_value = services
    qapp.setProperty("bootstrap", bootstrap)

    panels = [Mock(), Mock(), Mock(), Mock()]

    class Window:
        file_list, info, sidebar, tag_tree = panels
        _scoped_services_for_session = MainWindow._scoped_services_for_session

    monkeypatch.setattr("AssetsManager.window._alive", lambda panel: True)

    MainWindow._apply_scoped_services(Window(), session)

    bootstrap.for_library.assert_called_once_with(session)
    for panel in panels:
        panel.set_scoped_services.assert_called_once_with(services)
        assert panel.set_scoped_services.call_args.args[0] is services
