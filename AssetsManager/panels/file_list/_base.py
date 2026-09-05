"""File list panel — facade composing the layout, logic and events mixins.

The panel is a QPainter-drawn grid with a QTreeView Details mode.  The class
body is split by responsibility into three mixin modules:

  _base_layout.py  — LayoutMixin: widget creation, layout, chrome styling
  _base_logic.py   — LogicMixin: business logic, data transformation, caches
  _base_events.py  — EventsMixin: signal wiring, event handling, interaction

Navigation and file actions come from the existing ``_navigation`` and
``_actions`` mixins; this module keeps the class identity: signals, state
key, constructor orchestration, view-state persistence and panel lifecycle.

Architecture:
  _common.py       — shared constants (FILTER_CATEGORIES, ZOOM_PRESETS, natural_key)
  _model.py        — FileSystemModel (QAbstractListModel)
  _loader.py       — ThumbnailLoader + async disk-write thread
  _navigation.py   — NavigationMixin (breadcrumb, history, FS watcher)
  _actions.py      — ActionsMixin (context menu, file ops, undo, tags)
  _grid_widget.py  — FileListGridWidget (QWidget canvas)
  __init__.py      — FileListPanel (default) + legacy FileListPanel
"""
import os
from typing import TYPE_CHECKING, cast

# QVariantAnimation stays in this module's namespace: _base_events resolves it
# lazily through _base so tests can monkeypatch the panel's animation class.
from PySide6.QtCore import Qt, Signal, QVariantAnimation  # noqa: F401
from PySide6.QtWidgets import QWidget

from AssetsManager.panels._event_bridge import CategoryRegistrySubscription
from AssetsManager.panels.base import PanelContent
from AssetsManager.panels.file_list._navigation import NavigationMixin
from AssetsManager.panels.file_list._actions import ActionsMixin
from AssetsManager.panels.file_list._base_layout import LayoutMixin
from AssetsManager.panels.file_list._base_logic import LogicMixin
from AssetsManager.panels.file_list._base_events import EventsMixin
from AssetsManager.panels.file_list._common import natural_key

_natural_key = natural_key


class FileListPanel(NavigationMixin, ActionsMixin, LayoutMixin, LogicMixin, EventsMixin, PanelContent):
    file_selected = Signal(object)
    file_double_clicked = Signal(str)
    folder_entered = Signal(str)

    panel_state_key = "file_list_view_state"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.content_layout.setContentsMargins(1, 0, 1, 1)

        # Actions mixin state (clipboard, undo)
        self._init_actions()
        self._init_state()
        self._build_ui()
        self._connect_signals()
        self._category_registry_disconnected = False
        self._category_registry_subscription = CategoryRegistrySubscription(
            self._on_category_registry_changed,
            self,
        )

    def clone(self):
        new = FileListPanel()
        new.restore_state(self.save_state())
        return new

    def save_state(self) -> dict:
        """Snapshot view mode, sort/filter, and per-directory view memory."""
        return {
            "current": str(self._current),
            "view": self._view_mode,
            "sort": self._model._sort_key,
            "ascending": self._model.sort_ascending,
            "filter": self._model._filter_text,
            "category": self._model._filter_cat,
            "hidden": self._model.show_hidden,
            # The toolbar always lives inside the panel's layout, so a parent
            # exists whenever save_state runs; the cast carries that invariant.
            "toolbar_visible": self._toolbar_widget.isVisibleTo(
                cast(QWidget, self._toolbar_widget.parentWidget())
            ),
            "view_memory": dict(self._view_memory),
        }

    def restore_state(self, state: dict) -> None:
        """Apply a saved view snapshot without re-opening a library root."""
        if not isinstance(state, dict):
            return
        view = state.get("view")
        if isinstance(view, str):
            index = self._view_combo.findData(view)
            if index >= 0:
                self._view_combo.setCurrentIndex(index)
        self._model.set_sort(
            str(state.get("sort", "name")),
            bool(state.get("ascending", True)),
        )
        self._model.set_filter(
            str(state.get("filter", "")),
            str(state.get("category", "All")),
        )
        self._model.set_show_hidden(bool(state.get("hidden", False)))
        toolbar_visible = state.get("toolbar_visible")
        if isinstance(toolbar_visible, bool):
            self._set_toolbar_visible(toolbar_visible)
        memory = state.get("view_memory")
        if isinstance(memory, dict):
            self._view_memory = {str(k): str(v) for k, v in memory.items()}
        current = state.get("current")
        if isinstance(current, str) and current and os.path.isdir(current):
            self.navigate_to(current, set_root=False)

    @staticmethod
    def _schedule_library_stats_update(_lib_root: str):
        pass  # implemented in concrete subclass

    def prepare_library_switch(self):
        """Drain all session-bound background work before its session closes."""
        clear_timers = getattr(self, "_clear_pending_timers", None)
        if callable(clear_timers):
            clear_timers()
        cancel_stats = getattr(self, "_cancel_library_stats_update", None)
        if callable(cancel_stats):
            # Cooperative cancel: the whole-library stats walk drops its
            # session lease within milliseconds instead of walking to the end.
            cancel_stats()
        fs_refresh_timer = getattr(self, "_fs_refresh_timer", None)
        if fs_refresh_timer is not None:
            fs_refresh_timer.stop()
        if hasattr(self, "_pending_fs_changed_path"):
            self._pending_fs_changed_path = None
        invalidate_covers = getattr(self, "_invalidate_cover_scans", None)
        if callable(invalidate_covers):
            invalidate_covers()
        drain_covers = getattr(self, "_drain_cover_scan_pool", None)
        if callable(drain_covers):
            drain_covers()
        generation = self._loader.invalidate_tasks()
        self._loader.wait_for_runtime(generation)
        self._model.prepare_library_switch()

    def shutdown(self):
        """Clean up bus connections and worker threads."""
        self._category_registry_disconnected = True
        subscription = self._category_registry_subscription
        if subscription is not None:
            subscription.close()
            self._category_registry_subscription = None
        self._operation_feedback_generation += 1
        invalidate_covers = getattr(self, "_invalidate_cover_scans", None)
        if callable(invalidate_covers):
            invalidate_covers()
        close_covers = getattr(self, "_close_cover_scan_pool", None)
        if callable(close_covers):
            close_covers()
        clear_timers = getattr(self, "_clear_pending_timers", None)
        if callable(clear_timers):
            clear_timers()
        cancel_stats = getattr(self, "_cancel_library_stats_update", None)
        if callable(cancel_stats):
            cancel_stats()
        for timer_name in ("_search_timer", "_scroll_debounce", "_file_op_timer", "_operation_feedback_timer", "_fs_refresh_timer"):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                timer.stop()
        if hasattr(self, "_pending_fs_changed_path"):
            self._pending_fs_changed_path = None
        watcher = getattr(self, "_fs_watcher", None)
        if watcher is not None:
            watched = watcher.directories()
            if watched:
                watcher.removePaths(watched)
        delivery = getattr(self, "_thumbnail_delivery", None)
        if delivery is not None:
            delivery.clear()
        grid = getattr(self, "_grid_widget", None)
        if grid is not None:
            cancel_timers = getattr(grid, "cancel_pending_timers", None)
            if callable(cancel_timers):
                cancel_timers()
            grid.stop_animations()
        for animation_name in ("_zoom_anim", "_scroll_anim"):
            animation = getattr(self, animation_name, None)
            if animation is not None:
                for signal_name in ("valueChanged", "finished"):
                    signal = getattr(animation, signal_name, None)
                    if signal is not None:
                        try:
                            signal.disconnect()
                        except (RuntimeError, TypeError):
                            pass
                animation.stop()
        self._scroll_animating = False
        self._scroll_animation_setting_value = False
        self._loader.stop()
        self._model.shutdown()
        self._model.clear_scoped_services()
        self._controller.set_file_operations(None, None)
        self._scoped_services = None
        self._thumbnail_service = None
        self._file_ops_port = None
        self._tags_service = None
        self._tags_port = None
        self._undo_svc = None
        self._clear_operation_feedback()
        super().shutdown()


if TYPE_CHECKING:
    from AssetsManager.panels.file_list._host import FileListActionsHost, FileListHost

    # Lock the mixin host contracts: FileListPanel must provide the surfaces
    # NavigationMixin and ActionsMixin rely on (see _host.py).
    _host_contract: FileListHost = FileListPanel()
    _actions_host_contract: FileListActionsHost = FileListPanel()
