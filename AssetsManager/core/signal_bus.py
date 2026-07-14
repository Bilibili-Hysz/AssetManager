"""Signal bus — global singleton for cross-panel communication.

Performance: keep signals low-frequency (directory change, theme change).
High-frequency events (per-file selection) remain as direct panel-to-panel connections.

Signal Reference:
  directory_changed(str)       — emitted: file_list.py (navigate/go_back/forward/up), sidebar.py, tag_tree.py
                                  connected: sidebar.py::_on_dir_changed, tag_tree.py::_on_directory_changed,
                                             window.py::_on_dir_selected
  file_focused(str)            — emitted: file_list.py (click/tree-click), sidebar.py
                                  connected: window.py::_on_file_focused_safe
  refresh_requested()          — emitted: tag_tree.py (clear filter)
                                  connected: sidebar.py::_populate
  theme_changed(str)           — emitted: themes.py::set_theme
                                  connected: file_list.py::_on_theme_changed, window.py (apply theme)
  library_opened(str)          — **DEPRECATED**: now delivered via domain event
                                   LibraryOpened → _event_bridge.py → panel slot


  sidebar_depth_changed(int,object) — emitted: sidebar.py (depth init/settings)
                                  connected: info.py::_on_sidebar_depth_changed
"""
from PySide6.QtCore import QObject, Signal
from AssetsManager.core.singleton import ThreadSafeSingleton


class _SignalBus(QObject):
    directory_changed = Signal(str)
    file_focused = Signal(str)
    refresh_requested = Signal()
    theme_changed = Signal(str)
    language_changed = Signal(str)
    sidebar_depth_changed = Signal(int, object)
    ui_scale_changed = Signal(float)
    plugin_changed = Signal(str, bool)  # (plugin_id, enabled)


def get():
    return ThreadSafeSingleton.get(_SignalBus)
