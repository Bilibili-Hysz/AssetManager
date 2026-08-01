"""Tests for MainWindow scoped-service injection."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

def test_main_window_injects_one_scoped_bundle_into_all_applicable_panels(monkeypatch):
    """MainWindow owns scoped resolution and gives each panel the same bundle."""
    from unittest.mock import Mock

    from AssetsManager.window import MainWindow

    session = object()
    services = object()
    bootstrap = Mock()
    bootstrap.runtime_for.return_value.services = services
    panels = [Mock(), Mock(), Mock(), Mock()]

    class Window:
        file_list, info, sidebar, tag_tree = panels
        _scoped_services_for_session = MainWindow._scoped_services_for_session

    monkeypatch.setattr("AssetsManager.window._alive", lambda panel: True)

    window = Window()
    window._bootstrap = bootstrap
    MainWindow._apply_scoped_services(window, session)

    bootstrap.runtime_for.assert_called_once_with(session)
    for panel in panels:
        panel.set_scoped_services.assert_called_once_with(services)
        assert panel.set_scoped_services.call_args.args[0] is services


def test_main_window_switch_injects_new_active_bundle_without_clearing_it(monkeypatch):
    from unittest.mock import Mock

    from AssetsManager.window import MainWindow
    from AssetsManager.window_lifecycle_coordinator import WindowLifecycleCoordinator

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
    bootstrap.runtime_for.side_effect = lambda session: Mock(services=(
        old_bundle if session is old_session else new_bundle
    ))
    library_service = bootstrap.library_service
    monkeypatch.setattr("AssetsManager.window._alive", lambda panel: panel is not None)
    window = Window()
    window._bootstrap = bootstrap
    window.file_list._undo_svc = old_bundle.undo_service
    window._lifecycle_coordinator = WindowLifecycleCoordinator(window, lambda panel: panel is not None)

    MainWindow._on_switch_library(window, "new-root")

    library_service.close_session.assert_called_once_with(old_session)
    old_bundle.undo_service.clear.assert_not_called()
    bootstrap.runtime_for.assert_called_once_with(new_session)
    for panel in panels:
        panel.set_scoped_services.assert_called_once_with(new_bundle)
    new_bundle.undo_service.clear.assert_not_called()


def test_normal_window_switch_injects_each_panel_and_cleans_file_list_once(monkeypatch, tmp_path):
    from unittest.mock import Mock

    from AssetsManager.panels.file_list._base import FileListPanel
    from AssetsManager.window import MainWindow
    from AssetsManager.window_lifecycle_coordinator import WindowLifecycleCoordinator

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
                assert self._scoped_services is new_bundle
                assert self._scoped_services.session is new_session
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
    bootstrap.runtime_for.return_value.services = new_bundle
    library_service = bootstrap.library_service
    monkeypatch.setattr("AssetsManager.window._alive", lambda panel: panel is not None)

    window = Window()
    window._bootstrap = bootstrap
    window.file_list = file_list
    window._lifecycle_coordinator = WindowLifecycleCoordinator(window, lambda panel: panel is not None)
    MainWindow._on_switch_library(window, new_root)

    assert file_list._scoped_services is new_bundle
    file_list._loader.orphan_cleanup.assert_called_once_with()
    for panel in panels:
        panel.set_scoped_services.assert_called_once_with(new_bundle)
