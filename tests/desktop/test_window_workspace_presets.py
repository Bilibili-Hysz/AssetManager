"""Unit tests for MainWindow View menu, workspace presets, and dock layout persistence."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDockWidget, QWidget

from AssetsManager.window import MainWindow


def _create_test_window(tmp_path) -> MainWindow:
    """Create a test MainWindow with minimal mocks for isolation."""
    with patch("AssetsManager.window.AppSettings") as mock_settings_cls, \
         patch("AssetsManager.window.dock") as mock_dock:
        settings_instance = MagicMock()
        settings_instance.get.return_value = None
        settings_instance.get_list.return_value = []
        mock_settings_cls.instance.return_value = settings_instance

        sidebar_dock = QDockWidget("Sidebar")
        sidebar_dock.setObjectName("dock_sidebar")
        sidebar_dock.setWidget(QWidget())
        info_dock = QDockWidget("Info")
        info_dock.setObjectName("dock_info")
        info_dock.setWidget(QWidget())

        def mock_create(title, parent, area, panel_type=""):
            if panel_type == "sidebar":
                return sidebar_dock
            return info_dock

        mock_dock.create.side_effect = mock_create

        with patch("AssetsManager.panels.sidebar.SidebarPanel", QWidget), \
             patch("AssetsManager.panels.info.InfoPanel", QWidget):
            win = MainWindow.__new__(MainWindow)
            super(MainWindow, win).__init__()
            win._tools_menu_icon_specs = []
            win.sidebar_dock = sidebar_dock
            win.info_dock = info_dock
            win._lifecycle_coordinator = MagicMock()
            win._bootstrap = MagicMock()
            win._force_quit = False
            win.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, sidebar_dock)
            win.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, info_dock)

            from PySide6.QtWidgets import QMenuBar
            win._menu_bar = QMenuBar()
            win._setup_view_menu(win._menu_bar)
            win._default_dock_state = win.saveState()
            return win


def test_setup_menu_action_order(tmp_path):
    """Ensure _setup_menu completes without AttributeError on any action."""
    _app = QApplication.instance() or QApplication([])
    with patch("AssetsManager.window.AppSettings") as mock_settings_cls, \
         patch("AssetsManager.window.dock") as mock_dock:
        settings_instance = MagicMock()
        settings_instance.get.return_value = None
        settings_instance.get_list.return_value = []
        mock_settings_cls.instance.return_value = settings_instance

        sidebar_dock = QDockWidget("Sidebar")
        sidebar_dock.setObjectName("dock_sidebar")
        info_dock = QDockWidget("Info")
        info_dock.setObjectName("dock_info")
        mock_dock.create.side_effect = [sidebar_dock, info_dock]

        win = MainWindow.__new__(MainWindow)
        super(MainWindow, win).__init__()
        win._tools_menu_icon_specs = []
        from PySide6.QtWidgets import QMenuBar
        win._menu_bar = QMenuBar()
        win._setup_menu()
        assert win._menu_act_settings is not None
        assert win._menu_view is not None
        assert win._menu_tools is not None


def test_view_menu_actions_and_toggles(tmp_path):
    _app = QApplication.instance() or QApplication([])
    win = _create_test_window(tmp_path)
    assert win._menu_view is not None
    assert win._menu_act_toggle_sidebar is not None
    assert win._menu_act_toggle_info is not None
    assert win._menu_act_toggle_sidebar.isChecked()
    assert win._menu_act_toggle_info.isChecked()

    # Toggle sidebar
    win._toggle_sidebar()
    assert win.sidebar_dock.isHidden()
    assert not win._menu_act_toggle_sidebar.isChecked()

    win._toggle_sidebar()
    assert not win.sidebar_dock.isHidden()
    assert win._menu_act_toggle_sidebar.isChecked()

    # Toggle info
    win._toggle_info()
    assert win.info_dock.isHidden()
    assert not win._menu_act_toggle_info.isChecked()

    win._toggle_info()
    assert not win.info_dock.isHidden()
    assert win._menu_act_toggle_info.isChecked()


def test_workspace_presets(tmp_path):
    _app = QApplication.instance() or QApplication([])
    win = _create_test_window(tmp_path)

    # Browse preset: full canvas, hide both docks
    win._apply_preset_browse()
    assert win.sidebar_dock.isHidden()
    assert win.info_dock.isHidden()
    assert not win._menu_act_toggle_sidebar.isChecked()
    assert not win._menu_act_toggle_info.isChecked()

    # Inspect preset: sidebar hidden, info visible
    win._apply_preset_inspect()
    assert win.sidebar_dock.isHidden()
    assert not win.info_dock.isHidden()
    assert not win._menu_act_toggle_sidebar.isChecked()
    assert win._menu_act_toggle_info.isChecked()

    # Default preset: both visible
    win._apply_preset_default()
    assert not win.sidebar_dock.isHidden()
    assert not win.info_dock.isHidden()
    assert win._menu_act_toggle_sidebar.isChecked()
    assert win._menu_act_toggle_info.isChecked()

    # Reset layout restores initial state
    win._apply_preset_browse()
    win._reset_dock_layout()
    assert not win.sidebar_dock.isHidden()
    assert not win.info_dock.isHidden()


def test_dock_state_save_and_restore(tmp_path):
    _app = QApplication.instance() or QApplication([])
    win = _create_test_window(tmp_path)
    stored = {}

    with patch("AssetsManager.window.AppSettings.instance") as mock_inst:
        mock_settings = MagicMock()
        mock_settings.get.side_effect = lambda k, d=None: stored.get(k, d)
        mock_settings.set.side_effect = lambda k, v: stored.update({k: v})
        mock_inst.return_value = mock_settings

        # Mock sub-panels persist methods
        win.file_list = MagicMock()
        win.sidebar = MagicMock()

        # Save layout
        win._save_dock_layout()
        assert "window_dock_state" in stored
        state_hex = stored["window_dock_state"]
        assert isinstance(state_hex, str) and len(state_hex) > 0

        # Change dock state
        win.sidebar_dock.hide()

        # Restore layout
        win._restore_dock_layout()
        assert not win.sidebar_dock.isHidden()
