"""Signal wiring and user-interaction handling for the file list panel.

``EventsMixin`` connects model, loader, bus and domain signals in
``_connect_signals`` and owns every interaction path: event filtering,
wheel scroll/zoom animation, drag routing, toolbar combo slots, grid and
detail selection/click slots, scan lifecycle presentation, language/theme/
scale reactions, and panel shutdown.

Widget creation lives in ``_base_layout.py``; business logic and caches
live in ``_base_logic.py``; ``_base.py`` composes the three.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import (
    Qt, QEvent, QSize, QTimer, QPoint,
    QEasingCurve, QFileInfo, QItemSelectionModel,
)
from PySide6.QtWidgets import QWidget

from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager import i18n

from AssetsManager.panels.file_list._common import ZOOM_PRESETS
from AssetsManager.panels.file_list._ui_helpers import _is_external_drop

if TYPE_CHECKING:
    from pathlib import Path

    from PySide6.QtWidgets import QComboBox, QLineEdit, QTreeView

    from AssetsManager.panels.file_list._detail_model import DetailModel
    from AssetsManager.panels.file_list._grid_layout import GridLayout
    from AssetsManager.panels.file_list._grid_widget import FileListGridWidget
    from AssetsManager.panels.file_list._loader import ThumbnailLoader
    from AssetsManager.panels.file_list._model import FileSystemModel
    from AssetsManager.panels.file_list._thumbnail_delivery import ThumbnailDeliveryCoordinator

tr = i18n.tr


class EventsMixin:
    """Signal/slot connections, event handling and user interaction."""

    if TYPE_CHECKING:
        # Host surface owned by FileListPanel / sibling mixins.
        _model: FileSystemModel
        _loader: ThumbnailLoader
        _grid_widget: FileListGridWidget
        _grid_layout: GridLayout
        _thumbnail_delivery: ThumbnailDeliveryCoordinator
        _detail_view: QTreeView
        _detail_model: DetailModel
        _sort_combo: QComboBox
        _filter_combo: QComboBox
        _view_combo: QComboBox
        _zoom_combo: QComboBox
        _search: QLineEdit
        _search_timer: QTimer | None
        _thumb_size: int
        _current: Path
        _lib_root: str | None
        _scoped_services: Any
        _view_memory: dict[str, str]
        _operation_feedback_generation: int
        file_selected: Any
        file_double_clicked: Any

        def _connect_bus(self, signal: Any, slot: Any) -> None: ...
        def _connect_domain_event(self, event_type: Any, slot: Any) -> Any: ...
        def _schedule_once(self, interval_ms: int, callback: Any) -> Any: ...
        def _clear_pending_timers(self) -> None: ...
        def _start_fs_watcher(self) -> None: ...
        def _on_tree_click(self, index: Any, col: int = 0) -> None: ...
        def _on_tree_double_click(self, index: Any, col: int = 0) -> None: ...
        def navigate_to(self, path: str, *, set_root: bool = False) -> None: ...
        def _invalidate_size_cache(self) -> None: ...
        def _on_dir_size_ready(self, dir_path: str, size_str: str, gen: int = 0) -> None: ...
        def _on_detail_dir_size_ready(self, dir_path: str, size_str: str, gen: int = 0) -> None: ...
        def _on_thumbnail_ready(self, row: int, path: str, img: Any) -> None: ...
        def _on_thumbnail_failed(self, path: str) -> None: ...
        def _update_status(self) -> None: ...
        def _load_visible(self) -> None: ...
        def _load_visible_if_active(self) -> None: ...
        def _clear_operation_feedback(self) -> None: ...
        def _capture_grid_selection(self) -> None: ...
        def _capture_detail_selection(self) -> None: ...
        def _restore_detail_selection(self) -> None: ...
        def _restore_grid_selection(self) -> None: ...
        def _restore_operation_selection(self, paths: tuple[str, ...]) -> None: ...
        def _consume_operation_selection(self) -> tuple[str, ...]: ...
        def _post_refresh(self) -> None: ...
        def _get_scoped_services(self) -> Any: ...
        def _get_file_operation_service(self) -> Any: ...
        def _show_operation_feedback(
            self,
            session: Any,
            operation: str,
            *,
            changed_count: int = 0,
            errors: tuple[str, ...] = (),
            warnings: tuple[object, ...] = (),
            running: bool = False,
        ) -> None: ...
        def _request_operation_selection(self, session: Any, paths: Any) -> None: ...
        _view_mode: str
        def _on_drop(self, event: Any) -> bool: ...
        def shutdown(self) -> None: ...
        def _populate_details(self) -> None: ...
        def _select_grid_paths(self, paths: set[str]) -> None: ...
        def _select_detail_paths(self, paths: set[str]) -> None: ...
        def _selected_detail_paths(self) -> list[str]: ...
        def _sort_key(self) -> str: ...
        def _filter_key(self) -> str: ...
        def _refresh_state_icons(self) -> None: ...
        def _save_search_term(self, term: str) -> None: ...
        def _toast(self, text: str) -> None: ...
        def _show_context_menu(self, paths: list[str], global_pos: QPoint) -> None: ...
        def _rename_path(self, old_path: str, new_name: str) -> None: ...
        def _apply_chrome_style(self) -> None: ...
        def _apply_detail_theme(self) -> None: ...
        def _retranslate_controls(self) -> None: ...

    def _connect_signals(self) -> None:
        """Wire model, loader, bus, domain and view signals after UI exists."""
        self._model.modelReset.connect(self._invalidate_size_cache)
        self._model.dir_size_ready.connect(self._on_dir_size_ready)
        self._model.dir_size_ready.connect(self._on_detail_dir_size_ready)

        self._sort_combo.currentTextChanged.connect(self._on_sort_changed)
        self._filter_combo.currentTextChanged.connect(self._on_filter_changed)
        self._view_combo.currentIndexChanged.connect(self._on_view_changed)
        self._zoom_combo.currentTextChanged.connect(self._on_zoom_changed)
        self._search.textChanged.connect(self._on_search_changed)
        self._loader.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._loader.thumbnail_failed.connect(self._on_thumbnail_failed)
        self._connect_bus(bus().theme_changed, self._on_theme_changed)

        # Scroll debounce — 100ms after scroll stops before loading thumbnails
        self._scroll_debounce = QTimer(cast(QWidget, self))
        self._scroll_debounce.setSingleShot(True)
        self._scroll_debounce.setInterval(100)
        self._scroll_debounce.timeout.connect(self._load_visible)
        self._scroll_animating = False
        self._scroll_animation_generation = 0
        self._scroll_animation_setting_value = False

        self._operation_feedback_timer = QTimer(cast(QWidget, self))
        self._operation_feedback_timer.setSingleShot(True)
        self._operation_feedback_timer.setInterval(4000)
        self._operation_feedback_timer.timeout.connect(self._clear_operation_feedback)

        self._grid_widget.clicked.connect(self._on_grid_click)
        self._grid_widget.double_clicked.connect(self._on_grid_double_click)
        self._grid_widget.context_menu.connect(self._on_grid_context)
        self._grid_widget.selection_changed.connect(self._update_status)
        self._grid_widget.selection_changed.connect(self._on_grid_selection_changed)
        self._grid_widget.rename_requested.connect(self._rename_grid_row)
        self._model.rename_requested.connect(self._rename_grid_row)
        self._model.modelAboutToBeReset.connect(self._capture_grid_selection)
        self._model.modelAboutToBeReset.connect(self._capture_detail_selection)
        self._model.modelReset.connect(self._on_grid_model_reset)
        self._model.scan_started.connect(self._on_scan_started)
        self._model.scan_committed.connect(self._on_scan_committed)
        self._model.state_changed.connect(self._on_file_list_state_changed)

        # Reconnect scroll debounce to grid widget's scrollbar
        self._scroll_debounce.timeout.disconnect()
        self._grid_widget._scrollbar.valueChanged.connect(self._on_scroll_value_changed)
        self._scroll_debounce.timeout.connect(self._load_visible)

        self._detail_model.rename_requested.connect(self._rename_detail_row)
        self._detail_model.layoutAboutToBeChanged.connect(self._capture_detail_selection)
        self._detail_model.layoutChanged.connect(self._restore_detail_selection)
        self._detail_view.selectionModel().selectionChanged.connect(self._on_detail_selection_changed)
        self._detail_view.customContextMenuRequested.connect(self._on_detail_context)
        self._detail_view.clicked.connect(self._on_tree_click)
        self._detail_view.doubleClicked.connect(self._on_tree_double_click)

        self._connect_bus(bus().language_changed, self._refresh_language)
        self._connect_bus(bus().ui_scale_changed, self._on_ui_scale_changed)
        self.initialize_navigation()

        from AssetsManager.domain.events import FileSystemChanged
        self._file_op_timer = QTimer(cast(QWidget, self))
        self._file_op_timer.setSingleShot(True)
        self._file_op_timer.setInterval(500)
        self._file_op_timer.timeout.connect(self._post_refresh)
        self._connect_domain_event(FileSystemChanged, self._on_file_operation)





    def initialize_navigation(self):
        """Start filesystem watching after views exist."""
        self._start_fs_watcher()

    def _on_theme_changed(self, _name):
        self._apply_chrome_style()
        self._grid_widget.refresh_theme()
        self._apply_detail_theme()

    def _on_view_changed(self, _index):
        mode = self._view_mode
        self._view_memory[str(self._current)] = mode
        self._loader.set_size(self._thumb_size)
        is_detail = mode == "Details"
        paths = (
            {
                path for row in self._grid_widget.selection_model_rows()
                if (path := self._model.path_at(row)) is not None
            }
            if is_detail
            else set(self._selected_detail_paths())
        )
        self._grid_widget.setVisible(not is_detail)
        self._detail_view.setVisible(is_detail)
        if not is_detail:
            self._grid_widget.update_layout(self._model.rowCount(), self._grid_widget.width())
            self._select_grid_paths(paths)
            self._detail_view.clearSelection()
            self._load_visible()
        else:
            self._populate_details()
            self._select_detail_paths(paths)
            self._select_grid_paths(set())
        self._update_status()

    def _on_zoom_changed(self, val):
        from AssetsManager.panels.file_list._base import QVariantAnimation
        target = int(val.replace("px", ""))
        anchor_pos = getattr(self, "_pending_zoom_anchor", None)
        self._pending_zoom_anchor = None
        if not hasattr(self, '_zoom_anim'):
            self._zoom_anim = None
        self._zoom_generation = getattr(self, "_zoom_generation", 0) + 1
        generation = self._zoom_generation
        anim = self._zoom_anim
        if anim is not None and anim.state() == QVariantAnimation.State.Running:
            anim.stop()
        start = self._thumb_size
        if start == target:
            # Rebase an interrupted transition before committing its current
            # size, otherwise the previous target's scroll anchor can snap.
            if self._grid_widget.is_zoom_active():
                self._grid_widget.begin_zoom(target, anchor_pos)
                self._on_zoom_done(generation)
            return

        self._grid_widget.begin_zoom(target, anchor_pos)
        if self._grid_widget.reduce_motion_enabled() is True:
            self._thumb_size = target
            self._grid_widget.set_zoom_thumb_size(target)
            self._on_zoom_done(generation, target)
            return

        if anim is None:
            # Reuse a single animation object so rapid zoom changes do not
            # accumulate child QObject instances.
            anim = QVariantAnimation(cast(QWidget, self))
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.valueChanged.connect(self._on_zoom_frame)
            anim.finished.connect(
                lambda: self._on_zoom_done(
                    getattr(self, "_zoom_generation", 0),
                    getattr(self, "_zoom_anim_target", None),
                )
            )
            self._zoom_anim = anim
        self._zoom_anim_target = target
        distance = abs(target - start)
        duration = min(220, 150 + round(distance * 1.1))
        anim.setDuration(duration)
        anim.setStartValue(start)
        anim.setEndValue(target)
        anim.start()

    def _on_zoom_frame(self, size: int):
        try:
            if getattr(self._model, "is_shutdown", False):
                return
            self._thumb_size = size
            self._grid_widget.set_zoom_thumb_size(size)
        except RuntimeError:
            animation = getattr(self, "_zoom_anim", None)
            if animation is not None:
                animation.stop()

    def _on_zoom_done(self, generation: int | None = None, target_size: int | None = None):
        try:
            if getattr(self._model, "is_shutdown", False):
                return
            if generation is not None and generation != getattr(self, "_zoom_generation", 0):
                return
            if target_size is not None:
                self._thumb_size = target_size
            self._loader.set_size(self._thumb_size)
            self._grid_widget.set_thumb_size(self._thumb_size)
            self._grid_widget.update_layout(self._model.rowCount(), self._grid_widget.width())
            # finish_zoom commits the target-size textures pre-rendered during the
            # animation and marks any remaining stale rows dirty for the paced rebuild.
            self._grid_widget.finish_zoom()
            self._load_visible()
        except RuntimeError:
            animation = getattr(self, "_zoom_anim", None)
            if animation is not None:
                animation.stop()

    def _wheel_zoom_evt(self, event, source=None):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            idx = self._zoom_combo.currentIndex()
            target_idx = idx
            if delta > 0 and idx < len(ZOOM_PRESETS) - 1:
                target_idx = idx + 1
            elif delta < 0 and idx > 0:
                target_idx = idx - 1
            if target_idx != idx:
                anchor_pos = None
                if source is self._grid_widget and callable(getattr(event, "position", None)):
                    candidate = event.position().toPoint()
                    if self._grid_widget.rect().contains(candidate):
                        anchor_pos = candidate
                self._pending_zoom_anchor = anchor_pos
                try:
                    self._zoom_combo.setCurrentIndex(target_idx)
                finally:
                    self._pending_zoom_anchor = None
            return
        self._grid_widget._scrollbar.wheelEvent(event)

    def _on_sort_changed(self):
        self._model.set_sort(self._sort_key(), self._model.sort_ascending)
        if self._view_mode == "Details":
            self._populate_details()
        self._load_visible()

    def _on_filter_changed(self):
        cat = self._filter_key()
        text = self._search.text().lower()
        self._model.set_filter(text=text, category=cat)
        self._refresh_state_icons()
        self._update_status()
        if self._view_mode == "Details":
            self._populate_details()
        self._load_visible()

    def _on_search_changed(self, text):
        """Debounce search to avoid O(n) scandir on every keystroke."""
        self._model.set_filter_text(text.lower())
        timer = self._search_timer
        if timer is None:
            timer = QTimer(cast(QWidget, self))
            self._search_timer = timer
            timer.setSingleShot(True)
            timer.timeout.connect(self._apply_search)
        timer.start(200)

    def _apply_search(self):
        self._model.set_filter(
            text=self._search.text().lower(),
            category=self._filter_key())
        self._refresh_state_icons()
        self._update_status()
        if self._view_mode == "Details":
            self._populate_details()
        self._load_visible()
        self._save_search_term(self._search.text())
        # Show search result count
        text = self._search.text().strip()
        if text:
            count = self._model.rowCount()
            self._toast(tr("filelist.search.results", count=count, text=text))

    def _toggle_advanced_filter(self):
        """Show/hide the advanced-filter popup anchored to its toolbar button."""
        popup = getattr(self, "_advanced_popup", None)
        if popup is None:
            return
        if popup.isVisible():
            popup.hide()
            return
        button = self._advanced_btn
        popup.adjustSize()
        popup.move(button.mapToGlobal(QPoint(0, button.height() + scaled_px(4))))
        popup.show()
        popup.raise_()

    def _structured_search_params(self) -> dict[str, object]:
        """Read the advanced-filter widgets into structured search kwargs.

        ``size_*`` come back in bytes (the spinboxes edit MiB) and
        ``mtime_*`` in epoch seconds (local-time midnight / end-of-day),
        matching the assets-index column semantics.
        """
        from PySide6.QtCore import QDateTime, QTime

        params: dict[str, object] = {}
        after = self._adv_mtime_after.date()
        before = self._adv_mtime_before.date()
        if after != self._adv_mtime_after.minimumDate():
            params["mtime_after"] = QDateTime(after, QTime(0, 0)).toSecsSinceEpoch()
        if before != self._adv_mtime_before.minimumDate():
            params["mtime_before"] = QDateTime(before, QTime(23, 59, 59)).toSecsSinceEpoch()
        if self._adv_size_min.value() > 0:
            params["size_min"] = self._adv_size_min.value() * 1024 * 1024
        if self._adv_size_max.value() > 0:
            params["size_max"] = self._adv_size_max.value() * 1024 * 1024
        extensions = [
            ext.lower().lstrip(".")
            for ext in (raw.strip() for raw in self._adv_extensions.text().split(","))
            if ext.lstrip(".")
        ]
        if extensions:
            params["extensions"] = extensions
        return params

    def _apply_advanced_filter(self):
        """Apply structured predicates to the view and query the shared service.

        Presentation stays on the existing filter pipeline (the model narrows
        the current listing and grid/details/status refresh as with a text
        search). The library-wide match count comes from the shared
        application SearchService so desktop and LAN execute the identical
        structured query.
        """
        params = self._structured_search_params()
        self._model.set_structured_filter(**params)
        self._advanced_popup.hide()
        self._update_status()
        if self._view_mode == "Details":
            self._populate_details()
        self._load_visible()
        service = getattr(self, "_search_service", None)
        if service is None or not self._lib_root:
            # No scoped search service (bare panel/tests): local-only report.
            self._toast(tr("filelist.advanced.results",
                           count=self._model.rowCount(), total=self._model.rowCount()))
            return
        name_substring = self._search.text().strip().lower()

        def _query_library():
            try:
                return service.search_structured_detailed(
                    self._lib_root, name_substring=name_substring, **params)
            except Exception:
                # The local filtered view is authoritative for presentation;
                # a failed library-wide count only degrades the toast.
                return None

        self._run_in_background(_query_library, on_done=self._on_advanced_library_count)

    def _on_advanced_library_count(self, result_set):
        total = result_set.count if result_set is not None else self._model.rowCount()
        self._toast(tr("filelist.advanced.results",
                       count=self._model.rowCount(), total=total))

    def _clear_advanced_filter(self):
        """Reset the advanced-filter widgets and drop the model predicates."""
        self._adv_mtime_after.setDate(self._adv_mtime_after.minimumDate())
        self._adv_mtime_before.setDate(self._adv_mtime_before.minimumDate())
        self._adv_size_min.setValue(0)
        self._adv_size_max.setValue(0)
        self._adv_extensions.clear()
        self._model.set_structured_filter()
        self._advanced_popup.hide()
        self._update_status()
        if self._view_mode == "Details":
            self._populate_details()
        self._load_visible()

    def eventFilter(self, obj, event):
        if not hasattr(self, '_grid_widget') or self._grid_widget is None:
            return QWidget.eventFilter(cast(QWidget, self), obj, event)
        t = event.type()

        if t == QEvent.Type.DragEnter:
            return self._on_drag_enter(event)
        if t == QEvent.Type.DragMove:
            return self._accept_drag(event)
        if t == QEvent.Type.Drop:
            return self._on_drop(event)
        if t == QEvent.Type.KeyPress:
            return self._handle_key(event)

        # Tolerate construction-time events before the detail view exists.
        detail_view = getattr(self, "_detail_view", None)
        if detail_view is not None and (obj is detail_view or obj is detail_view.viewport()):
            return QWidget.eventFilter(cast(QWidget, self), obj, event)

        if obj is self._grid_widget or obj is self._search:
            if t == QEvent.Type.Wheel:
                if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                    self._wheel_zoom_evt(event, obj)
                    return True
                self._smooth_scroll(event)
                return True
            if t in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove,
                     QEvent.Type.MouseButtonRelease):
                return QWidget.eventFilter(cast(QWidget, self), obj, event)
            return QWidget.eventFilter(cast(QWidget, self), obj, event)

        return QWidget.eventFilter(cast(QWidget, self), obj, event)

    def _on_scroll_value_changed(self) -> None:
        if self._scroll_animation_setting_value:
            return
        if self._scroll_animating:
            self._scroll_animation_generation += 1
            self._scroll_animating = False
            animation = getattr(self, "_scroll_anim", None)
            if animation is not None:
                animation.stop()
        self._scroll_debounce.start()

    def _begin_smooth_scroll(self) -> int:
        self._scroll_animation_generation += 1
        self._scroll_animating = True
        self._scroll_debounce.stop()
        return self._scroll_animation_generation

    def _finish_smooth_scroll(self, generation: int) -> None:
        if generation != self._scroll_animation_generation:
            return
        self._scroll_animating = False
        self._scroll_debounce.start()

    def _set_scroll_animation_value(self, scrollbar, value) -> None:
        self._scroll_animation_setting_value = True
        try:
            scrollbar.setValue(int(value))
        except RuntimeError:
            animation = getattr(self, "_scroll_anim", None)
            if animation is not None:
                animation.stop()
        finally:
            self._scroll_animation_setting_value = False

    def _smooth_scroll(self, event):
        from AssetsManager.panels.file_list._base import QVariantAnimation
        sb = self._grid_widget._scrollbar
        target = sb.value() - event.angleDelta().y()
        anim = getattr(self, '_scroll_anim', None)
        if anim is not None and anim.state() == QVariantAnimation.State.Running:
            target = anim.endValue() - event.angleDelta().y()
            anim.stop()
        generation = self._begin_smooth_scroll()
        self._grid_widget.set_scrolling()
        if anim is None:
            # Reuse a single animation object instead of leaking one per wheel event.
            anim = QVariantAnimation(cast(QWidget, self))
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.valueChanged.connect(lambda v: self._set_scroll_animation_value(sb, v))
            anim.finished.connect(self._on_smooth_scroll_finished)
            self._scroll_anim = anim
        self._scroll_anim_generation = generation
        anim.setDuration(120)
        anim.setStartValue(sb.value())
        anim.setEndValue(target)
        anim.start()

    def _handle_key(self, event):
        from AssetsManager.panels.file_list._shortcuts import handle_key
        return handle_key(self, event)

    def _on_drag_enter(self, event):
        if self._is_external_drop(event):
            event.acceptProposedAction()
            return True
        return False

    def _accept_drag(self, event):
        if self._is_external_drop(event):
            event.acceptProposedAction()
            return True
        return False

    def _reset_drag_state(self):
        """Clear all drag tracking state."""
        self._drag_origin_pos = None
        self._drag_started = False

    def closeEvent(self, event):
        self.shutdown()
        QWidget.closeEvent(cast(QWidget, self), event)

    @staticmethod
    def _is_external_drop(event) -> bool:
        return _is_external_drop(event)

    def _on_detail_context(self, pos: QPoint):
        idx = self._detail_view.indexAt(pos)
        if idx.isValid() and not self._detail_view.selectionModel().isSelected(idx):
            self._detail_view.selectionModel().clearSelection()
            self._detail_view.selectionModel().select(
                idx,
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
            )
        sel = self._detail_view.selectionModel().selectedRows()
        paths = [self._detail_model.data(i, Qt.ItemDataRole.UserRole) for i in sel if i.isValid()]
        self._show_context_menu(
            [path for path in paths if isinstance(path, str)],
            self._detail_view.viewport().mapToGlobal(pos),
        )

    def _on_detail_selection_changed(self):
        if self._pending_scan_generation == self._model.scan_generation:
            self._pending_detail_paths = set(self._selected_detail_paths())
        self._update_status()
        sel = self._detail_view.selectionModel().selectedRows()
        if sel:
            path = self._detail_model.data(sel[0], Qt.ItemDataRole.UserRole)
            if isinstance(path, str):
                info = QFileInfo(path)
                self.file_selected.emit(info)
                bus().file_focused.emit(str(path))

    def _on_file_list_state_changed(self, _state: str, generation: int, _error) -> None:
        if generation == self._model.scan_generation:
            self._update_status()

    def _on_file_operation(self, event):
        if getattr(self._model, "is_shutdown", False):
            return
        scoped = self._scoped_services
        if scoped is None or event.session_token != scoped.session.event_token:
            return
        fs_timer = getattr(self, "_fs_refresh_timer", None)
        if fs_timer is not None:
            fs_timer.stop()
        if hasattr(self, "_pending_fs_changed_path"):
            self._pending_fs_changed_path = None
        self._file_op_timer.start()

    def _on_grid_click(self, row: int):
        self._last_click_row = row
        path = self._model.path_at(row)
        if path:
            info = QFileInfo(path)
            self.file_selected.emit(info)
            bus().file_focused.emit(str(path))

    def _on_grid_context(self, global_pos: QPoint):
        sel_rows = self._grid_widget.selection_model_rows()
        paths = [self._model.path_at(r) for r in sel_rows]
        self._show_context_menu([p for p in paths if p], global_pos)

    def _on_grid_double_click(self, row: int):
        ent = self._model.entry_at(row)
        if ent:
            if ent.is_dir():
                self.navigate_to(ent.path)
            else:
                self.file_double_clicked.emit(ent.path)

    def _on_grid_model_reset(self):
        self._thumbnail_delivery.clear()
        self._grid_widget.set_performance_generation(self._model.scan_generation)
        if self._pending_scan_generation == self._model.scan_generation:
            # Both async-refresh resets can be delivered after the model has
            # left its committing state. Preserve paths until scan_committed.
            if not self._model.is_committing_scan:
                self._grid_widget.update_layout(0, self._grid_widget.width())
            return
        if self._view_mode == "Details":
            # The first reset of an async refresh clears source entries. Keep
            # the captured paths until the populated scan result arrives.
            if self._model.rowCount():
                self._populate_details()
            return
        self._grid_widget.update_layout(self._model.rowCount(), self._grid_widget.width())
        if self._view_mode == "Grid":
            self._restore_grid_selection()

    def _on_grid_selection_changed(self) -> None:
        if self._pending_scan_generation == self._model.scan_generation:
            self._pending_selection_paths = {
                path for row in self._grid_widget.selection_model_rows()
                if (path := self._model.path_at(row)) is not None
            }

    def _on_scan_committed(self, generation: int):
        """Present each populated scan generation once after its model reset completes."""
        if generation != self._pending_scan_generation:
            return
        self._pending_scan_generation = None
        if generation <= self._presentation_generation:
            return
        self._presentation_generation = generation
        result_paths = self._consume_operation_selection()
        scan_reused = self._model.last_scan_reused
        self._model.clear_last_scan_reused()
        if scan_reused:
            self._grid_widget.set_performance_generation(generation)
            # A reused scan emits scan_committed without a model reset; clear the
            # grid's scan-reset guard so a later sort/filter still captures the
            # path texture cache instead of dropping it and rebuilding all cards.
            self._grid_widget.mark_scan_settled()
            # The reused scan skips the model reset, so the grid may still show
            # the 0-row layout left by an in-flight sort/filter reset. Repopulate
            # it with the preserved (possibly re-sorted) entry count.
            self._grid_widget.update_layout(self._model.rowCount(), self._grid_widget.width())
            if result_paths:
                self._restore_operation_selection(result_paths)
            self._update_status()
            return
        if self._view_mode == "Grid":
            self._restore_grid_selection()
        if not self._model.rowCount():
            self._grid_widget.discard_pending_presentation(generation)
            return
        self._grid_widget.update_layout(self._model.rowCount(), self._grid_widget.width())
        visible_rows = self._grid_layout.visible_rows(
            self._grid_widget._scroll_y, self._grid_widget.height())
        self._grid_widget.begin_presentation(generation, visible_rows)
        if self._view_mode == "Details":
            self._populate_details()
        else:
            self._schedule_once(80, self._load_visible_if_active)
        if result_paths:
            self._restore_operation_selection(result_paths)

    def _on_scan_started(self, generation: int):
        self._pending_scan_generation = generation

    def _on_smooth_scroll_finished(self):
        try:
            self._finish_smooth_scroll(getattr(self, "_scroll_anim_generation", 0))
        except RuntimeError:
            animation = getattr(self, "_scroll_anim", None)
            if animation is not None:
                animation.stop()

    def _on_ui_scale_changed(self, _scale: float) -> None:
        """Re-measure canvas text and Details chrome after a live scale change."""
        self._apply_chrome_style()
        self._grid_widget.refresh_scale()
        self._grid_widget.update_layout(self._model.rowCount(), self._grid_widget.width())
        self._detail_view.setIconSize(QSize(scaled_px(18), scaled_px(18)))
        self._detail_view.header().setMinimumHeight(scaled_px(30))
        self._apply_detail_theme()

    def _quick_share_from_context(self, paths: list[str], global_pos):
        """Delegate Quick Share to the canonical LAN share-link creator."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        win = app.activeWindow()
        if win is None:
            for w in app.topLevelWidgets():
                if w.isVisible() and hasattr(w, '_open_share_link_dialog'):
                    win = w
                    break
        open_share_link_dialog = getattr(win, "_open_share_link_dialog", None)
        if callable(open_share_link_dialog):
            open_share_link_dialog(paths=paths)

    def _refresh_language(self, _code=""):
        self._retranslate_controls()
        self._detail_model.headerDataChanged.emit(
            Qt.Orientation.Horizontal, 0, len(self._detail_model.HEADER_KEYS) - 1)
        self._update_status()

    def _rename_detail_row(self, row: int, new_name: str):
        if not (0 <= row < len(self._detail_model.entries)):
            return
        self._rename_path(self._detail_model.entries[row].path, new_name)

    def _rename_grid_row(self, row: int, new_name: str):
        ent = self._model.entry_at(row)
        if not ent:
            return
        self._rename_path(ent.path, new_name)
