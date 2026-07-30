from pathlib import Path

import pytest

from AssetsManager.window import MainWindow
from AssetsManager.window_lifecycle_coordinator import WindowLifecycleCoordinator
from unittest.mock import Mock


class _Server:
    def is_running(self):
        return True

    def stop(self):
        events.append("lan.stop")


class _Loader:
    def invalidate_tasks(self):
        events.append("loader.invalidate")
        return 7

    def wait_for_runtime(self, generation):
        assert generation == 7
        events.append("loader.wait")


class _FileList:
    def __init__(self):
        self._loader = _Loader()

    def navigate_to(self, path, set_root=False):
        events.append("file-list.navigate")

    def prepare_library_switch(self):
        generation = self._loader.invalidate_tasks()
        self._loader.wait_for_runtime(generation)


class _Timer:
    def stop(self):
        events.append("notes.stop")


class _Info:
    _notes_timer = _Timer()

    def _flush_notes_save(self):
        events.append("notes.flush")

    def prepare_library_switch(self):
        self._flush_notes_save()
        self._notes_timer.stop()


class _LifecyclePanel:
    def __init__(self, name):
        self.name = name

    def prepare_library_switch(self):
        events.append(f"{self.name}.prepare")

    def shutdown(self):
        events.append(f"{self.name}.shutdown")

    def navigate_to(self, _path):
        events.append(f"{self.name}.navigate")


class _Session:
    root = Path("old-root").resolve()
    root_str = str(root)


class _Service:
    def owns_live_session(self, _session):
        return False

    def close_session(self, session):
        events.append("session.close")


class _Bootstrap:
    def cleanup_library(self, _root):
        events.append("session.cleanup")


class _Window:
    def __init__(self):
        self._lan_server = _Server()
        self._library_session = _Session()
        self.file_list = _FileList()
        self.info = _Info()
        self.sidebar = _LifecyclePanel("sidebar")
        self.tag_tree = _LifecyclePanel("tag-tree")
        self._bootstrap = _Bootstrap()
        self.share_states = []
        self._tray_manager = Mock()

    def _update_share_status(self, running):
        self.share_states.append(running)

    def _library_service(self):
        return _Service()

    def _open_library_session(self, path):
        events.append("session.open")
        return _Session()

    def _apply_scoped_services(self, session):
        events.append("scoped.apply")


def test_switch_library_stops_lan_and_invalidates_thumbnails_before_closing(monkeypatch):
    global events
    events = []
    window = _Window()

    WindowLifecycleCoordinator(window, lambda widget: widget is not None).switch_library("new-root")

    assert events == [
        "lan.stop",
        "notes.flush",
        "notes.stop",
        "loader.invalidate",
        "loader.wait",
        "sidebar.prepare",
        "tag-tree.prepare",
        "session.close",
        "session.cleanup",
        "session.open",
        "scoped.apply",
        "sidebar.navigate",
        "file-list.navigate",
    ]
    assert window.share_states == [False]
    window._tray_manager.update_sharing_state.assert_called_once_with(False)


def test_switch_library_continues_window_cleanup_after_lan_and_panel_failures():
    global events
    events = []

    class _FailingServer(_Server):
        def stop(self):
            events.append("lan.stop")
            raise RuntimeError("lan stop failed")

    class _FailingSidebar(_LifecyclePanel):
        def prepare_library_switch(self):
            events.append(f"{self.name}.prepare")
            raise RuntimeError("sidebar failed")

    window = _Window()
    window._lan_server = _FailingServer()
    window.sidebar = _FailingSidebar("sidebar")

    with pytest.raises(RuntimeError, match="lan stop failed"):
        WindowLifecycleCoordinator(window, lambda widget: widget is not None).switch_library(
            "new-root"
        )

    assert events == [
        "lan.stop",
        "notes.flush",
        "notes.stop",
        "loader.invalidate",
        "loader.wait",
        "sidebar.prepare",
        "tag-tree.prepare",
        "session.close",
        "session.cleanup",
    ]
    assert window.share_states == [False]
    window._tray_manager.update_sharing_state.assert_called_once_with(False)


def test_switch_library_reports_panel_failure_after_successful_lan_stop_once():
    global events
    events = []

    class _FailingSidebar(_LifecyclePanel):
        def prepare_library_switch(self):
            events.append(f"{self.name}.prepare")
            raise RuntimeError("sidebar failed")

    window = _Window()
    window.sidebar = _FailingSidebar("sidebar")

    with pytest.raises(RuntimeError, match="sidebar failed"):
        WindowLifecycleCoordinator(window, lambda widget: widget is not None).switch_library(
            "new-root"
        )

    assert events == [
        "lan.stop",
        "notes.flush",
        "notes.stop",
        "loader.invalidate",
        "loader.wait",
        "sidebar.prepare",
        "tag-tree.prepare",
        "session.close",
        "session.cleanup",
    ]
    assert window.share_states == [False]
    window._tray_manager.update_sharing_state.assert_called_once_with(False)


def test_switch_library_status_failure_does_not_skip_cleanup_or_tray():
    global events
    events = []

    class _FailureWindow(_Window):
        def _update_share_status(self, running):
            events.append(f"status.{running}")
            raise RuntimeError("status failed")

        def _open_library_session(self, path):
            raise AssertionError("replacement must not open")

    window = _FailureWindow()

    with pytest.raises(RuntimeError, match="status failed"):
        WindowLifecycleCoordinator(window, lambda widget: widget is not None).switch_library(
            "new-root"
        )

    assert events == [
        "lan.stop",
        "status.False",
        "notes.flush",
        "notes.stop",
        "loader.invalidate",
        "loader.wait",
        "sidebar.prepare",
        "tag-tree.prepare",
        "session.close",
        "session.cleanup",
    ]
    window._tray_manager.update_sharing_state.assert_called_once_with(False)


def test_switch_library_stop_error_wins_over_compensation_tray_failure():
    global events
    events = []

    class _FailingServer(_Server):
        def stop(self):
            events.append("lan.stop")
            raise RuntimeError("lan stop failed")

    class _FailureWindow(_Window):
        def __init__(self):
            super().__init__()
            self._lan_server = _FailingServer()
            self._tray_manager.update_sharing_state.side_effect = RuntimeError("tray failed")

        def _open_library_session(self, path):
            raise AssertionError("replacement must not open")

    window = _FailureWindow()

    with pytest.raises(RuntimeError, match="lan stop failed"):
        WindowLifecycleCoordinator(window, lambda widget: widget is not None).switch_library(
            "new-root"
        )

    assert events == [
        "lan.stop",
        "notes.flush",
        "notes.stop",
        "loader.invalidate",
        "loader.wait",
        "sidebar.prepare",
        "tag-tree.prepare",
        "session.close",
        "session.cleanup",
    ]
    assert window.share_states == [False]
    window._tray_manager.update_sharing_state.assert_called_once_with(False)


def test_switch_library_panel_getter_failure_does_not_skip_later_cleanup():
    global events
    events = []

    class _FailureWindow(_Window):
        def __init__(self):
            self._lan_server = _Server()
            self._library_session = _Session()
            self.file_list = _FileList()
            self.info = _Info()
            self._sidebar = _LifecyclePanel("sidebar")
            self.tag_tree = _LifecyclePanel("tag-tree")
            self._bootstrap = _Bootstrap()
            self.share_states = []
            self._tray_manager = Mock()

        @property
        def sidebar(self):
            raise RuntimeError("sidebar getter failed")

        def _open_library_session(self, path):
            raise AssertionError("replacement must not open")

    window = _FailureWindow()

    with pytest.raises(RuntimeError, match="sidebar getter failed"):
        WindowLifecycleCoordinator(window, lambda widget: widget is not None).switch_library(
            "new-root"
        )

    assert events == [
        "lan.stop",
        "notes.flush",
        "notes.stop",
        "loader.invalidate",
        "loader.wait",
        "tag-tree.prepare",
        "session.close",
        "session.cleanup",
    ]
    window._tray_manager.update_sharing_state.assert_called_once_with(False)


def test_switch_library_is_running_failure_does_not_skip_cleanup():
    global events
    events = []

    class _FailingServer:
        def is_running(self):
            raise RuntimeError("is_running failed")

    class _FailureWindow(_Window):
        def __init__(self):
            super().__init__()
            self._lan_server = _FailingServer()

        def _open_library_session(self, path):
            raise AssertionError("replacement must not open")

    window = _FailureWindow()

    with pytest.raises(RuntimeError, match="is_running failed"):
        WindowLifecycleCoordinator(window, lambda widget: widget is not None).switch_library(
            "new-root"
        )

    assert events == [
        "notes.flush",
        "notes.stop",
        "loader.invalidate",
        "loader.wait",
        "sidebar.prepare",
        "tag-tree.prepare",
        "session.close",
        "session.cleanup",
    ]


def test_switch_library_is_noop_for_active_canonical_root(tmp_path):
    global events
    events = []

    class _ActiveSession:
        root = tmp_path.resolve()
        root_str = str(root)

    class _Window:
        _lan_server = _Server()
        _library_session = _ActiveSession()
        info = _Info()
        file_list = _FileList()
        sidebar = None
        tag_tree = None

        def _library_service(self):
            raise AssertionError("active session must not close")

        def _open_library_session(self, _path):
            raise AssertionError("active session must not reopen")

    class _LiveService:
        def owns_live_session(self, session):
            return session is _Window._library_session

    window = _Window()
    window._library_service = lambda: _LiveService()
    WindowLifecycleCoordinator(window, lambda widget: widget is not None).switch_library(
        str(tmp_path)
    )

    assert events == []


def test_switch_library_reopens_closed_same_root_session(tmp_path):
    global events
    events = []

    class _ClosedSession:
        root = tmp_path.resolve()
        root_str = str(root)

    closed_session = _ClosedSession()
    replacement = _Session()
    replacement.root = tmp_path.resolve()
    replacement.root_str = str(replacement.root)

    class _Window:
        _lan_server = None
        _library_session = closed_session
        info = None
        file_list = None
        sidebar = None
        tag_tree = None
        _bootstrap = _Bootstrap()

        def _library_service(self):
            class _Service:
                def owns_live_session(self, _session):
                    return False

                def close_session(self, session):
                    assert session is closed_session
                    events.append("session.close")

            return _Service()

        def _open_library_session(self, path):
            assert Path(path).resolve() == self._library_session.root
            events.append("session.open")
            self._library_session = replacement
            return replacement

        def _apply_scoped_services(self, _session):
            events.append("scoped.apply")

    WindowLifecycleCoordinator(_Window(), lambda widget: widget is not None).switch_library(
        str(tmp_path)
    )

    assert events == ["session.close", "session.cleanup", "session.open", "scoped.apply"]


def test_main_window_delegates_library_switch_to_lifecycle_coordinator():
    coordinator = Mock()

    class _Window:
        _lifecycle_coordinator = coordinator

    MainWindow._on_switch_library(_Window(), "new-root")

    coordinator.switch_library.assert_called_once_with("new-root")


def test_shutdown_resources_stops_public_panel_lifecycles_in_order():
    global events
    events = []

    class _Panel:
        def __init__(self, name):
            self.name = name

        def shutdown(self):
            events.append(f"{self.name}.shutdown")

    class _Window:
        _lan_server = _Server()
        info = _Panel("info")
        file_list = _Panel("file-list")
        sidebar = _Panel("sidebar")
        tag_tree = _Panel("tag-tree")

        def _save_dock_layout(self):
            events.append("dock.save")

        def _save_workspace_tabs(self):
            events.append("workspace.save")

    WindowLifecycleCoordinator(_Window(), lambda widget: widget is not None).shutdown_resources()

    assert events == [
        "lan.stop",
        "info.shutdown",
        "sidebar.shutdown",
        "tag-tree.shutdown",
        "dock.save",
        "workspace.save",
        "file-list.shutdown",
    ]


def test_shutdown_resources_continues_after_lan_failure_and_reraises_first_error():
    global events
    events = []

    class _FailingServer(_Server):
        def stop(self):
            events.append("lan.stop")
            raise RuntimeError("lan stop failed")

    class _Window:
        _lan_server = _FailingServer()
        info = _LifecyclePanel("info")
        file_list = _LifecyclePanel("file-list")
        sidebar = _LifecyclePanel("sidebar")
        tag_tree = _LifecyclePanel("tag-tree")

        def _save_dock_layout(self):
            events.append("dock.save")

        def _save_workspace_tabs(self):
            events.append("workspace.save")

    with pytest.raises(RuntimeError, match="lan stop failed"):
        WindowLifecycleCoordinator(_Window(), lambda widget: widget is not None).shutdown_resources()

    assert events == [
        "lan.stop",
        "info.shutdown",
        "sidebar.shutdown",
        "tag-tree.shutdown",
        "dock.save",
        "workspace.save",
        "file-list.shutdown",
    ]


def test_shutdown_resources_continues_after_panel_failure_and_reraises_lan_error():
    global events
    events = []

    class _FailingServer(_Server):
        def stop(self):
            events.append("lan.stop")
            raise RuntimeError("lan stop failed")

    class _FailingPanel(_LifecyclePanel):
        def shutdown(self):
            events.append(f"{self.name}.shutdown")
            raise RuntimeError("sidebar failed")

    class _Window:
        _lan_server = _FailingServer()
        info = _LifecyclePanel("info")
        file_list = _LifecyclePanel("file-list")
        sidebar = _FailingPanel("sidebar")
        tag_tree = _LifecyclePanel("tag-tree")

        def _save_dock_layout(self):
            events.append("dock.save")

        def _save_workspace_tabs(self):
            events.append("workspace.save")

    with pytest.raises(RuntimeError, match="lan stop failed"):
        WindowLifecycleCoordinator(_Window(), lambda widget: widget is not None).shutdown_resources()

    assert events == [
        "lan.stop",
        "info.shutdown",
        "sidebar.shutdown",
        "tag-tree.shutdown",
        "dock.save",
        "workspace.save",
        "file-list.shutdown",
    ]


def test_shutdown_resources_continues_after_dock_layout_getter_failure():
    global events
    events = []

    class _Window:
        _lan_server = _Server()
        info = _LifecyclePanel("info")
        file_list = _LifecyclePanel("file-list")
        sidebar = _LifecyclePanel("sidebar")
        tag_tree = _LifecyclePanel("tag-tree")

        @property
        def _save_dock_layout(self):
            events.append("dock.get")
            raise RuntimeError("dock getter failed")

        def _save_workspace_tabs(self):
            events.append("workspace.save")

    with pytest.raises(RuntimeError, match="dock getter failed"):
        WindowLifecycleCoordinator(_Window(), lambda widget: widget is not None).shutdown_resources()

    assert events == [
        "lan.stop",
        "info.shutdown",
        "sidebar.shutdown",
        "tag-tree.shutdown",
        "dock.get",
        "workspace.save",
        "file-list.shutdown",
    ]


def test_main_window_delegates_resource_shutdown_to_lifecycle_coordinator():
    coordinator = Mock()

    class _Window:
        _lifecycle_coordinator = coordinator

    MainWindow._shutdown_resources(_Window())

    coordinator.shutdown_resources.assert_called_once_with()


def test_open_library_defers_session_creation_to_workspace_switch(monkeypatch, tmp_path):
    from AssetsManager import window as window_module

    callbacks = []

    class _Signal:
        def connect(self, callback):
            callbacks.append(callback)

    class _Startup:
        def __init__(self, _parent):
            self.library_opened = _Signal()
            self.shown = False
            self.closed = False

        def show(self):
            self.shown = True

        def close(self):
            self.closed = True

    startup = _Startup(None)
    monkeypatch.setattr(window_module, "StartupWindow", lambda parent: startup)
    monkeypatch.setattr("AssetsManager.core.settings.AppSettings.instance", classmethod(lambda cls: Mock()))
    monkeypatch.setattr("AssetsManager.core.library_manager.record_visit", Mock())
    workspace = Mock()

    class _Window:
        _workspace = workspace

        def _open_library_session(self, _path):
            raise AssertionError("workspace switch must create the session")

    MainWindow._open_library(_Window())
    callbacks[0](str(tmp_path))

    workspace.add_library.assert_called_once_with(str(tmp_path))
    assert startup.closed is True
