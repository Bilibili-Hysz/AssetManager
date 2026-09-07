"""Real Qt/session probe for failures after a replacement session has opened."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.window import MainWindow
from AssetsManager.window_lifecycle_coordinator import WindowLifecycleCoordinator
from AssetsManager.widgets.workspace_bar import WorkspaceSection


class _RecordingPanel(QWidget):
    def __init__(self, name: str, events: list[str]):
        super().__init__()
        self.name = name
        self.events = events
        self.failure_point: str | None = None
        self.failure_remaining = 0
        self.bound_roots: list[str] = []
        self.bound_sessions: list[object] = []
        self.navigated_roots: list[str] = []

    def prepare_library_switch(self) -> None:
        self.events.append(f"{self.name}.prepare")

    def set_scoped_services(self, services, *, runtime) -> None:
        root = runtime.session.root_str
        self.events.append(f"{self.name}.bind:{root}")
        if self.failure_point == "bind" and self.failure_remaining:
            self.failure_remaining -= 1
            if not self.failure_remaining:
                self.failure_point = None
            raise RuntimeError("injected scoped bind failure")
        self.bound_roots.append(root)
        self.bound_sessions.append(runtime.session)

    def navigate_to(self, root: str, **_kwargs) -> None:
        self.events.append(f"{self.name}.navigate:{root}")
        if self.failure_point == "navigate" and self.failure_remaining:
            self.failure_remaining -= 1
            if not self.failure_remaining:
                self.failure_point = None
            raise RuntimeError("injected navigation failure")
        self.navigated_roots.append(root)


class _SwitchWindow(QMainWindow):
    """Small real-Qt host that invokes the production MainWindow methods."""

    _open_library_session = MainWindow._open_library_session
    _apply_scoped_services = MainWindow._apply_scoped_services
    _on_switch_library = MainWindow._on_switch_library
    _reselect_workspace_tab = MainWindow._reselect_workspace_tab

    def __init__(self, bootstrap: ApplicationBootstrap, session, events: list[str]):
        super().__init__()
        self._bootstrap = bootstrap
        self._library_session = session
        self._lan_server = None
        self._workspace = WorkspaceSection(self)
        self._lifecycle_coordinator = WindowLifecycleCoordinator(
            self, lambda panel: panel is not None
        )
        self.info = _RecordingPanel("info", events)
        self.file_list = _RecordingPanel("file_list", events)
        self.sidebar = _RecordingPanel("sidebar", events)
        self.tag_tree = _RecordingPanel("tag_tree", events)

    def _library_service(self):
        return self._bootstrap.library_service


@pytest.fixture(autouse=True)
def _disable_reconciliation_workers(monkeypatch):
    from AssetsManager.application.asset_index_reconciliation_service import (
        AssetIndexReconciliationService,
    )

    monkeypatch.setattr(AssetIndexReconciliationService, "start", lambda self: False)


@pytest.mark.parametrize(
    ("panel_name", "failure_point"),
    (("file_list", "bind"), ("sidebar", "navigate"), ("file_list", "navigate")),
)
def test_workspace_signal_rolls_back_post_open_failure_to_the_old_session(
    tmp_path, monkeypatch, panel_name, failure_point
):
    app = QApplication.instance() or QApplication([])
    events: list[str] = []
    notifications: list[str] = []
    signal_paths: list[str] = []
    bootstrap = ApplicationBootstrap()
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    old_session = bootstrap.library_service.open_session(old_root)
    window = _SwitchWindow(bootstrap, old_session, events)
    tabs = window._workspace._tabs
    try:
        # Establish the real pre-switch presentation state. The induced
        # failure below therefore exposes stale old-session bindings instead
        # of merely observing uninitialized panels.
        window._apply_scoped_services(old_session)
        window.sidebar.navigate_to(old_session.root_str)
        window.file_list.navigate_to(old_session.root_str, set_root=True)
        assert all(panel.bound_sessions == [old_session] for panel in (
            window.info, window.file_list, window.sidebar, window.tag_tree
        ))
        failing_panel = getattr(window, panel_name)
        failing_panel.failure_point = failure_point
        failing_panel.failure_remaining = 1

        # Build the real tab state before wiring the handler, so setup does not
        # switch sessions. The later setCurrentIndex is the user-event path.
        tabs.add_library(str(old_root))
        tabs.add_library(str(new_root))
        tabs.setCurrentIndex(tabs.find_tab(str(old_root)))
        window._workspace.library_switched.connect(window._on_switch_library)
        window._workspace.library_switched.connect(signal_paths.append)
        monkeypatch.setattr(
            "AssetsManager.window_lifecycle_coordinator._notify_switch_failed",
            lambda _window, message: notifications.append(message),
        )

        tabs.setCurrentIndex(tabs.find_tab(str(new_root)))

        # The handler catches the original error only after the coordinator
        # restored the old root. Its selection must not re-enter the new tab.
        assert tabs.current_library() == str(old_root.resolve())
        assert window._library_session.root == old_root.resolve()
        assert old_session.is_closed
        restored_old_session = window._library_session
        assert restored_old_session is not old_session
        assert all(panel.bound_sessions[-1] is restored_old_session for panel in (
            window.info, window.file_list, window.sidebar, window.tag_tree
        ))
        assert all(panel.isEnabled() for panel in (
            window.info, window.file_list, window.sidebar, window.tag_tree
        ))
        assert window.sidebar.navigated_roots[-1] == str(old_root.resolve())
        assert window.file_list.navigated_roots[-1] == str(old_root.resolve())
        assert signal_paths == [str(new_root.resolve())]
        assert len(notifications) == 1

        tabs.setCurrentIndex(tabs.find_tab(str(new_root)))
        assert window._library_session.root == new_root.resolve()
        assert all(panel.bound_sessions[-1] is window._library_session for panel in (
            window.info, window.file_list, window.sidebar, window.tag_tree
        ))
        assert signal_paths == [
            str(new_root.resolve()),
            str(new_root.resolve()),
        ]
    finally:
        window._workspace.library_switched.disconnect(window._on_switch_library)
        window.close()
        bootstrap.library_service.close()
        app.processEvents()


def test_post_open_close_failure_keeps_the_new_session_for_a_full_retry(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    events: list[str] = []
    signal_paths: list[str] = []
    bootstrap = ApplicationBootstrap()
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    old_session = bootstrap.library_service.open_session(old_root)
    window = _SwitchWindow(bootstrap, old_session, events)
    tabs = window._workspace._tabs
    original_close = bootstrap.library_service.close_session
    close_failed = False
    try:
        window._apply_scoped_services(old_session)
        window.sidebar.navigate_to(old_session.root_str)
        window.file_list.navigate_to(old_session.root_str, set_root=True)
        window.file_list.failure_point = "bind"
        window.file_list.failure_remaining = 1
        tabs.add_library(str(old_root))
        tabs.add_library(str(new_root))
        tabs.setCurrentIndex(tabs.find_tab(str(old_root)))
        window._workspace.library_switched.connect(window._on_switch_library)
        window._workspace.library_switched.connect(signal_paths.append)
        monkeypatch.setattr(
            "AssetsManager.window_lifecycle_coordinator._notify_switch_failed",
            lambda *_args: None,
        )

        def fail_replacement_close(session):
            nonlocal close_failed
            if session is not old_session and not close_failed:
                close_failed = True
                raise RuntimeError("injected replacement close failure")
            return original_close(session)

        monkeypatch.setattr(bootstrap.library_service, "close_session", fail_replacement_close)
        QTest.mouseClick(
            tabs,
            Qt.MouseButton.LeftButton,
            pos=tabs.tabRect(tabs.find_tab(str(new_root))).center(),
        )

        retained_session = window._library_session
        assert close_failed
        assert retained_session.root == new_root.resolve()
        assert bootstrap.library_service.owns_live_session(retained_session)
        assert tabs.current_library() == str(new_root.resolve())
        assert window._switch_recovery_pending is True
        assert signal_paths == [str(new_root.resolve())]
        assert not any(panel.isEnabled() for panel in (
            window.info, window.file_list, window.sidebar, window.tag_tree
        ))

        QTest.mouseClick(
            tabs,
            Qt.MouseButton.LeftButton,
            pos=tabs.tabRect(tabs.currentIndex()).center(),
        )

        assert window._switch_recovery_pending is False
        assert window._library_session.root == new_root.resolve()
        assert all(panel.bound_sessions[-1] is window._library_session for panel in (
            window.info, window.file_list, window.sidebar, window.tag_tree
        ))
        assert all(panel.isEnabled() for panel in (
            window.info, window.file_list, window.sidebar, window.tag_tree
        ))
        assert signal_paths == [str(new_root.resolve()), str(new_root.resolve())]
    finally:
        window._workspace.library_switched.disconnect(window._on_switch_library)
        window.close()
        bootstrap.library_service.close()
        app.processEvents()


def test_restore_bind_failure_stays_disabled_until_selected_tab_retry(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    events: list[str] = []
    signal_paths: list[str] = []
    bootstrap = ApplicationBootstrap()
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    old_session = bootstrap.library_service.open_session(old_root)
    window = _SwitchWindow(bootstrap, old_session, events)
    tabs = window._workspace._tabs
    try:
        window._apply_scoped_services(old_session)
        window.sidebar.navigate_to(old_session.root_str)
        window.file_list.navigate_to(old_session.root_str, set_root=True)
        window.file_list.failure_point = "bind"
        window.file_list.failure_remaining = 2
        tabs.add_library(str(old_root))
        tabs.add_library(str(new_root))
        tabs.setCurrentIndex(tabs.find_tab(str(old_root)))
        window._workspace.library_switched.connect(window._on_switch_library)
        window._workspace.library_switched.connect(signal_paths.append)
        monkeypatch.setattr(
            "AssetsManager.window_lifecycle_coordinator._notify_switch_failed",
            lambda *_args: None,
        )

        tabs.setCurrentIndex(tabs.find_tab(str(new_root)))

        assert window._library_session.root == old_root.resolve()
        assert window._library_session is not old_session
        assert window._switch_recovery_pending is True
        assert tabs.current_library() == str(old_root.resolve())
        assert not any(panel.isEnabled() for panel in (
            window.info, window.file_list, window.sidebar, window.tag_tree
        ))

        QTest.mouseClick(
            tabs,
            Qt.MouseButton.LeftButton,
            pos=tabs.tabRect(tabs.currentIndex()).center(),
        )

        assert window._switch_recovery_pending is False
        assert window._library_session.root == old_root.resolve()
        assert all(panel.bound_sessions[-1] is window._library_session for panel in (
            window.info, window.file_list, window.sidebar, window.tag_tree
        ))
        assert all(panel.isEnabled() for panel in (
            window.info, window.file_list, window.sidebar, window.tag_tree
        ))
        assert signal_paths == [str(new_root.resolve()), str(old_root.resolve())]
    finally:
        window._workspace.library_switched.disconnect(window._on_switch_library)
        window.close()
        bootstrap.library_service.close()
        app.processEvents()


def test_open_failure_restores_old_tab_without_a_recursive_new_tab_switch(
    tmp_path, monkeypatch
):
    app = QApplication.instance() or QApplication([])
    events: list[str] = []
    signal_paths: list[str] = []
    bootstrap = ApplicationBootstrap()
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    old_session = bootstrap.library_service.open_session(old_root)
    window = _SwitchWindow(bootstrap, old_session, events)
    tabs = window._workspace._tabs
    original_open = window._open_library_session
    try:
        window._apply_scoped_services(old_session)
        window.sidebar.navigate_to(old_session.root_str)
        window.file_list.navigate_to(old_session.root_str, set_root=True)
        tabs.add_library(str(old_root))
        tabs.add_library(str(new_root))
        tabs.setCurrentIndex(tabs.find_tab(str(old_root)))
        window._workspace.library_switched.connect(window._on_switch_library)
        window._workspace.library_switched.connect(signal_paths.append)
        monkeypatch.setattr(
            "AssetsManager.window_lifecycle_coordinator._notify_switch_failed",
            lambda *_args: None,
        )

        def fail_new_root_once(path):
            if Path(path).resolve() == new_root.resolve():
                raise RuntimeError("injected replacement open failure")
            return original_open(path)

        monkeypatch.setattr(window, "_open_library_session", fail_new_root_once)
        tabs.setCurrentIndex(tabs.find_tab(str(new_root)))

        assert old_session.is_closed
        assert window._library_session.root == old_root.resolve()
        assert window._library_session is not old_session
        assert tabs.current_library() == str(old_root.resolve())
        assert signal_paths == [str(new_root.resolve())]
        assert all(panel.bound_sessions[-1] is window._library_session for panel in (
            window.info, window.file_list, window.sidebar, window.tag_tree
        ))
    finally:
        window._workspace.library_switched.disconnect(window._on_switch_library)
        window.close()
        bootstrap.library_service.close()
        app.processEvents()


def test_failed_open_and_restore_retries_from_the_selected_target_tab(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    events: list[str] = []
    signal_paths: list[str] = []
    bootstrap = ApplicationBootstrap()
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    old_session = bootstrap.library_service.open_session(old_root)
    window = _SwitchWindow(bootstrap, old_session, events)
    tabs = window._workspace._tabs
    original_open = window._open_library_session
    failed_roots = {old_root.resolve(), new_root.resolve()}
    try:
        window._apply_scoped_services(old_session)
        window.sidebar.navigate_to(old_session.root_str)
        window.file_list.navigate_to(old_session.root_str, set_root=True)
        tabs.add_library(str(old_root))
        tabs.add_library(str(new_root))
        tabs.setCurrentIndex(tabs.find_tab(str(old_root)))
        window._workspace.library_switched.connect(window._on_switch_library)
        window._workspace.library_switched.connect(signal_paths.append)
        monkeypatch.setattr(
            "AssetsManager.window_lifecycle_coordinator._notify_switch_failed",
            lambda *_args: None,
        )

        def fail_each_root_once(path):
            root = Path(path).resolve()
            if root in failed_roots:
                failed_roots.remove(root)
                raise RuntimeError(f"injected open failure for {root.name}")
            return original_open(path)

        monkeypatch.setattr(window, "_open_library_session", fail_each_root_once)
        tabs.setCurrentIndex(tabs.find_tab(str(new_root)))

        assert old_session.is_closed
        assert window._library_session is None
        assert window._switch_recovery_pending is True
        assert tabs.current_library() == str(new_root.resolve())
        assert not any(panel.isEnabled() for panel in (
            window.info, window.file_list, window.sidebar, window.tag_tree
        ))

        QTest.mouseClick(
            tabs,
            Qt.MouseButton.LeftButton,
            pos=tabs.tabRect(tabs.currentIndex()).center(),
        )

        assert window._library_session.root == new_root.resolve()
        assert window._switch_recovery_pending is False
        assert all(panel.bound_sessions[-1] is window._library_session for panel in (
            window.info, window.file_list, window.sidebar, window.tag_tree
        ))
        assert all(panel.isEnabled() for panel in (
            window.info, window.file_list, window.sidebar, window.tag_tree
        ))
        assert signal_paths == [str(new_root.resolve()), str(new_root.resolve())]
    finally:
        window._workspace.library_switched.disconnect(window._on_switch_library)
        window.close()
        bootstrap.library_service.close()
        app.processEvents()
