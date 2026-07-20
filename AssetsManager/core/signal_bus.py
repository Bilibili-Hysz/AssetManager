"""Signal bus — global singleton for Qt presentation coordination.

Performance: keep signals low-frequency (directory change, theme change).
High-frequency events (per-file selection) remain as direct panel-to-panel connections.

Signal Reference:
  directory_changed(str)       — FileList/Sidebar/TagTree navigation → Window/TagTree coordination
  file_focused(str)            — FileList/Sidebar selection → Window selection coordination
  refresh_requested()          — TagTree filter clear → Sidebar presentation rebuild
  theme_changed(str)           — theme settings → widgets, panels, docks, and windows restyle
  language_changed(str)        — i18n settings → widgets, panels, docks, and windows relabel
  sidebar_depth_changed(int,object) — Sidebar depth settings → Info project-depth presentation
  ui_scale_changed(float)      — UI scale settings → panels and window geometry/restyle

  These signals are presentation-only. Application mutations use domain events.
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


def get():
    return ThreadSafeSingleton.get(_SignalBus)
