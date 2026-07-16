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


def test_require_scoped_services_does_not_open_a_library(qapp, tmp_path):
    bootstrap = ApplicationBootstrap()
    qapp.setProperty("bootstrap", bootstrap)

    with pytest.raises(RuntimeError, match="session_not_open"):
        require_scoped_services(tmp_path, consumer="TestPanel")

    assert bootstrap.library_service.current_session is None


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


def test_main_window_switch_injects_new_active_bundle_without_clearing_it(qapp, monkeypatch):
    from unittest.mock import Mock

    from AssetsManager.window import MainWindow

    old_session = Mock(root_str="old-root")
    new_session = Mock(root_str="new-root")
    old_bundle = Mock()
    new_bundle = Mock()
    panels = [Mock(), Mock(), Mock(), Mock()]

    class Window:
        file_list, info, sidebar, tag_tree = panels
        _library_session = old_session
        _lan_server = None
        _scoped_services_for_session = MainWindow._scoped_services_for_session
        _apply_scoped_services = MainWindow._apply_scoped_services

        def _library_service(self):
            return library_service

        def _open_library_session(self, path):
            self._library_session = new_session
            return new_session

    bootstrap = Mock()
    bootstrap.for_library.side_effect = lambda session: (
        old_bundle if session is old_session else new_bundle
    )
    library_service = bootstrap.library_service
    qapp.setProperty("bootstrap", bootstrap)
    monkeypatch.setattr("AssetsManager.window._alive", lambda panel: panel is not None)
    window = Window()
    window.file_list._undo_svc = old_bundle.undo_service

    MainWindow._on_switch_library(window, "new-root")

    library_service.close_session.assert_called_once_with(old_session)
    old_bundle.undo_service.clear.assert_not_called()
    bootstrap.for_library.assert_called_once_with(new_session)
    for panel in panels:
        panel.set_scoped_services.assert_called_once_with(new_bundle)
    new_bundle.undo_service.clear.assert_not_called()


def test_normal_window_switch_injects_each_panel_and_cleans_file_list_once(qapp, monkeypatch, tmp_path):
    from unittest.mock import Mock

    from AssetsManager.panels.file_list._base import FileListPanel
    from AssetsManager.window import MainWindow

    old_session = Mock(root_str="old-root")
    new_root = str(tmp_path.resolve())
    new_session = Mock(root_str=new_root)
    new_bundle = Mock(session=new_session)
    new_session.root = tmp_path.resolve()
    panels = [Mock(), Mock(), Mock()]

    class FileList:
        _scoped_services = None
        _root = None
        _model = Mock()
        _loader = Mock()
        _controller = Mock()
        _undo_svc = None
        set_scoped_services = FileListPanel.set_scoped_services
        _configure_library_runtime = FileListPanel._configure_library_runtime

        def navigate_to(self, path, *, set_root=False):
            if set_root:
                self._configure_library_runtime(path)

    file_list = FileList()

    class Window:
        info, sidebar, tag_tree = panels
        _library_session = old_session
        _lan_server = None
        _scoped_services_for_session = MainWindow._scoped_services_for_session
        _apply_scoped_services = MainWindow._apply_scoped_services

        def _library_service(self):
            return library_service

        def _open_library_session(self, path):
            self._library_session = new_session
            return new_session

    bootstrap = Mock()
    bootstrap.for_library.return_value = new_bundle
    library_service = bootstrap.library_service
    qapp.setProperty("bootstrap", bootstrap)
    monkeypatch.setattr("AssetsManager.window._alive", lambda panel: panel is not None)

    window = Window()
    window.file_list = file_list
    MainWindow._on_switch_library(window, new_root)

    assert file_list._scoped_services is new_bundle
    file_list._loader.orphan_cleanup.assert_called_once_with()
    for panel in panels:
        panel.set_scoped_services.assert_called_once_with(new_bundle)
