"""Business logic, data transformation and cache management for the file list panel.

``LogicMixin`` owns non-UI state: scoped-service binding, sort/filter/search,
thumbnail scheduling and its manual caches, details population, command
execution, drag-drop file operations, and scan-driven selection restore.

Widget creation lives in ``_base_layout.py``; signal wiring and interaction
handling live in ``_base_events.py``; ``_base.py`` composes the three.
"""
from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import Qt, QTimer, QModelIndex, QPoint, QItemSelectionModel
from PySide6.QtWidgets import QApplication, QWidget

from AssetsManager.core.ui_scale import scaled_px
from AssetsManager import i18n

from AssetsManager.panels.file_list._model import FileSystemModel
from AssetsManager.panels.file_list._loader import ThumbnailLoader
from AssetsManager.panels.file_list._common import (
    IMAGE_EXTS,
    VIDEO_EXTS,
)
from AssetsManager.panels.file_list._commands import FileListCommandContext
from AssetsManager.panels.file_list._ui_helpers import _first_image_in, _save_search_term
from AssetsManager.panels.file_list._status_helpers import operation_feedback_text

if TYPE_CHECKING:
    from PySide6.QtWidgets import QLabel, QTreeView

    from AssetsManager.panels.file_list._detail_model import DetailModel
    from AssetsManager.panels.file_list._grid_layout import GridLayout
    from AssetsManager.panels.file_list._grid_widget import FileListGridWidget
    from AssetsManager.panels.file_list._thumbnail_delivery import ThumbnailDeliveryCoordinator

_log = logging.getLogger(__name__)
tr = i18n.tr


class LogicMixin:
    """Business logic, data transformation and cache management."""

    if TYPE_CHECKING:
        # Host surface owned by FileListPanel / sibling mixins.
        _grid_widget: FileListGridWidget
        _grid_layout: GridLayout
        _thumbnail_delivery: ThumbnailDeliveryCoordinator
        _detail_view: QTreeView
        _detail_model: DetailModel
        _operation_feedback: QLabel
        _operation_feedback_timer: QTimer
        _lib_root: str | None
        _undo_svc: Any
        _view_mode: str
        file_double_clicked: Any

        def navigate_to(self, path: str, *, set_root: bool = False) -> None: ...
        def _refresh_state_icons(self) -> None: ...
        def _sort_key(self) -> str: ...
        def _filter_key(self) -> str: ...
        def _update_status(self) -> None: ...
        def _quick_share_from_context(self, paths: list[str], global_pos: QPoint) -> None: ...
        def _show_filelist_shortcuts(self) -> None: ...
        def _command_context(self, paths: list[str]) -> FileListCommandContext: ...
        def _rename_file_path(self, old_path: str, new_name: str, *, add_undo: bool = True) -> str: ...
        def _copy_to_clipboard(self) -> None: ...
        def _cut_to_clipboard(self) -> None: ...
        def _selected_paths(self) -> list[str]: ...
        def _copy_paths(self, paths: Any, cut: bool) -> None: ...
        def _inline_rename(self) -> None: ...
        def _rename(self, path: str) -> None: ...
        def _duplicate_selected(self) -> None: ...
        def _delete(self, paths: list[str], *, add_undo: bool = True) -> None: ...
        def _delete_permanent(self, paths: list[str]) -> None: ...
        def _undo(self) -> None: ...
        def _redo(self) -> None: ...
        def _show_properties(self, path: str) -> None: ...
        def _open_in_explorer(self, path: str) -> None: ...
        def _paste(self) -> None: ...
        def _new_folder(self) -> None: ...

    def _init_state(self) -> None:
        """Initialize per-instance view state, model and thumbnail loader."""
        self._current = Path.home() / "Documents"
        self._root = None
        self._history: list[str] = []
        self._cached_total_sz: int = -1
        self._forward_list: list[str] = []
        self._thumb_size = scaled_px(96)
        self._view_memory: dict[str, str] = {}
        self._first_image_cache: dict[str, str | None] = {}
        self._first_image_cache_max = 5000
        self._last_click_row: int = -1
        self._last_tree_item: QModelIndex | None = None
        self._drag_origin_pos = None
        self._drag_started = False
        self._scoped_services = None
        self._thumbnail_service = None
        self._file_ops_port = None
        self._tags_service = None
        self._tags_port = None
        self._operation_feedback_generation = 0

        # Controller for non-UI business logic
        from AssetsManager.controllers.file_list_controller import FileListController
        self._controller = FileListController()

        self._model = FileSystemModel()
        self._loader = ThumbnailLoader(size=self._thumb_size)
        self._pending_scan_generation: int | None = None
        self._pending_selection_paths: set[str] | None = None
        self._pending_detail_paths: set[str] | None = None
        self._presentation_generation = -1
        self._search_timer: QTimer | None = None





    def set_scoped_services(self, services):
        """Bind library-scoped services resolved by MainWindow."""
        self._operation_feedback_generation = getattr(self, "_operation_feedback_generation", 0) + 1
        clear_feedback = getattr(self, "_clear_operation_feedback", None)
        if callable(clear_feedback):
            clear_feedback()
        self._scoped_services = services
        # Desktop ports: the panel holds injected port objects instead of
        # reaching into the scoped bundle for tag/metadata/file-operation
        # services (metadata flows through the model's own service binding).
        from AssetsManager.application.desktop_ports import RootBoundTagService
        self._file_ops_port = services.file_operation_service
        self._tags_service = services.tag_service
        self._tags_port = RootBoundTagService(services.session.root_str, services.tag_service)
        # Capture the service object together with the session bundle.  This
        # is intentionally a snapshot, not a later lookup through a mutable
        # application container; async thumbnail work must retain the service
        # belonging to the generation that created it.
        self._thumbnail_service = services.thumbnail_service
        self._root = services.session.root
        self._model.set_library_root(services.session.root_str, services.session)
        self._model.set_metadata_service(services.metadata_service)
        performance_recorder = getattr(services, "performance_recorder", None)
        session_token = services.session.event_token
        set_model_context = getattr(self._model, "set_performance_context", None)
        if callable(set_model_context):
            set_model_context(performance_recorder, session_token)
        set_grid_context = getattr(self, "_set_grid_performance_context", None)
        if set_grid_context is not None:
            set_grid_context(
                getattr(services, "performance_recorder", None),
                services.session.event_token,
                self._model.scan_generation,
            )
        self._loader.bind_runtime(
            services.thumbnail_service,
            services.session.thumb_dir_str,
            services.session.root_str,
            performance_recorder,
            session_token,
        )
        self._loader.orphan_cleanup()
        if hasattr(services, "undo_service"):
            self._undo_svc = services.undo_service
        self._controller.set_file_operations(
            services.file_operation_service, self._undo_svc)

    def set_runtime(self, runtime):
        """Bind the immutable service snapshot owned by ``LibraryRuntime``."""
        self.set_scoped_services(runtime.services_snapshot)

    def _get_scoped_services(self):
        return self._scoped_services

    def _is_current_operation_session(self, session) -> bool:
        scoped = self._scoped_services
        return bool(
            not getattr(self._model, "is_shutdown", False)
            and scoped is not None
            and getattr(scoped, "session", None) is session
            and not getattr(session, "is_closed", False)
        )

    def _show_operation_feedback(
        self,
        session,
        operation: str,
        *,
        changed_count: int = 0,
        errors: tuple[str, ...] = (),
        warnings: tuple[object, ...] = (),
        running: bool = False,
    ) -> None:
        """Display session-bound operation feedback without affecting command state."""
        if (
            not self._is_current_operation_session(session)
        ):
            return
        text = operation_feedback_text(
            operation=operation,
            changed_count=changed_count,
            errors=errors,
            warnings=warnings,
            running=running,
        )
        self._operation_feedback.setText(text)
        self._operation_feedback.show()
        if running:
            self._operation_feedback_timer.stop()
        else:
            self._operation_feedback_timer.start()

    def _clear_operation_feedback(self) -> None:
        feedback = getattr(self, "_operation_feedback", None)
        if feedback is not None:
            feedback.clear()
            feedback.hide()

    def _set_grid_performance_context(self, recorder, session_token: str, generation: int) -> None:
        self._grid_widget.set_performance_context(recorder, session_token, generation)

    def _get_file_operation_service(self):
        if self._file_ops_port is None:
            raise RuntimeError("FileListPanel scoped services not injected")
        return self._file_ops_port

    def _get_tag_service(self):
        if not self._lib_root:
            raise RuntimeError("FileListPanel requires a library root for TagService")
        if self._tags_service is None:
            raise RuntimeError("FileListPanel scoped services not injected")
        return self._tags_service

    def _configure_library_runtime(self, root: str):
        """Bind file-list runtime helpers to a library root."""
        scoped = self._scoped_services
        if scoped is None:
            raise RuntimeError("FileListPanel scoped services not injected before navigate_to")
        if Path(scoped.session.root).resolve() != Path(root).resolve():
            raise RuntimeError("FileListPanel scoped services do not match navigation root")
        self._model.set_library_root(scoped.session.root_str, scoped.session)

    def refresh_contents(self):
        """Refresh the active directory after an application-wide update."""
        self._model.refresh()

    def _view_selected_rows(self) -> list[QModelIndex]:
        """Native grid implementation of the list-view selection API."""
        rows = []
        for row in self._grid_widget.selection_model_rows():
            idx = self._model.index(row, 0)
            if idx.isValid():
                rows.append(idx)
        return rows

    def _view_edit_index(self, idx: QModelIndex) -> bool:
        """Native grid implementation of the list-view inline-rename API."""
        if idx.isValid() and hasattr(self._grid_widget, '_start_rename'):
            self._grid_widget._start_rename(idx.row())
            return True
        return False

    def _update_thumb_cache_dir(self):
        if self._root:
            self._configure_library_runtime(str(self._root))
        else:
            self._loader.bind_runtime(None, "", "", None, None)

    def _toggle_sort_dir(self):
        self._model.set_sort_ascending(not self._model.sort_ascending)
        self._refresh_state_icons()
        self._model.set_sort(self._sort_key(), self._model.sort_ascending)
        if self._view_mode == "Details":
            self._populate_details()
        self._load_visible()

    def _toggle_hidden(self):
        self._model.set_show_hidden(not self._model.show_hidden)
        self._refresh_state_icons()
        self._post_refresh()

    def _post_refresh(self):
        if self._view_mode == "Details":
            self._capture_detail_selection()
        else:
            self._capture_grid_selection()
        self._model.refresh()
        if self._view_mode != "Details":
            self._grid_widget.update_layout(self._model.rowCount(), self._grid_widget.width())
            self._load_visible()
        self._refresh_state_icons()
        self._update_status()

    def _clear_selection_for_navigation(self) -> None:
        """Avoid carrying view selection into a different directory's scan."""
        self._pending_selection_paths = None
        self._pending_detail_paths = None
        self._pending_operation_selection = None
        self._grid_widget.clear_selection()
        self._detail_view.clearSelection()

    def _request_operation_selection(self, session, paths) -> None:
        """Restore the first successful result only in its originating session and directory."""
        self._pending_operation_selection = None
        scoped = self._scoped_services
        if scoped is None or getattr(scoped, "session", None) is not session:
            return
        if getattr(session, "is_closed", False):
            return
        current_dir = self._current.resolve()
        targets = tuple(
            str(Path(path).resolve())
            for path in paths
            if Path(path).resolve().parent == current_dir
        )
        if targets:
            self._pending_operation_selection = (session, current_dir, targets[:1])

    def _deletion_selection_candidates(self, paths) -> tuple[str, ...]:
        """Prefer the next visible survivor, then the previous visible survivor."""
        deleted = {str(Path(path).resolve()) for path in paths}
        entries = self._detail_model.entries if self._view_mode == "Details" else self._model.entries
        visible_paths = [str(Path(entry.path).resolve()) for entry in entries]
        deleted_rows = [row for row, path in enumerate(visible_paths) if path in deleted]
        if not deleted_rows:
            return ()
        first = min(deleted_rows)
        last = max(deleted_rows)
        return tuple(
            path
            for path in [*visible_paths[last + 1:], *reversed(visible_paths[:first])]
            if path not in deleted
        )

    def _do_refresh(self):
        self._loader.clear_queue()
        self._loader.clear_cache()
        self._post_refresh()

    @staticmethod
    def _save_search_term(term: str):
        _save_search_term(term)

    def _load_visible(self):
        if getattr(self._model, "is_shutdown", False):
            return
        total = self._model.rowCount()
        if total == 0:
            return
        if self._view_mode != "Grid":
            return
        vh = self._grid_widget.height()
        sy = self._grid_widget._scroll_y
        visible = self._grid_layout.visible_rows(sy, vh)
        visible_rows = [row for row in visible if 0 <= row < total]
        cols = self._grid_layout.columns
        extra = max(2, cols) * 3
        first = max(0, min(visible_rows[0] if visible_rows else 0, total - 1) - extra)
        last = min(total - 1, max(visible_rows[-1] if visible_rows else 0, 0) + extra)
        visible_set = set(visible_rows)
        prefetch_rows = [row for row in range(first, last + 1) if row not in visible_set]
        candidates = []
        retained_paths = set()
        for i in [*visible_rows, *prefetch_rows]:
            ent = self._model.entry_at(i)
            if not ent:
                continue
            priority = 0 if i in visible_set else 1
            if ent.is_dir():
                preview = self._first_image_cached(ent.path)
                if preview:
                    candidates.append((i, preview, priority, ent.path))
                    retained_paths.add(preview)
            elif ent.is_file() and Path(ent.name).suffix.lower() in IMAGE_EXTS | VIDEO_EXTS:
                candidates.append((i, ent.path, priority, None))
                retained_paths.add(ent.path)
        self._loader.retain_deferred(retained_paths)
        for row, path, priority, item_path in candidates:
            self._loader.request(row, path, priority=priority, item_path=item_path)

    def _on_thumbnail_ready(self, row: int, path: str, img):
        if getattr(self._model, "is_shutdown", False):
            return
        self._thumbnail_delivery.handle_ready(row, path, img)

    def _flush_thumb_batch(self):
        self._thumbnail_delivery.flush()

    def _start_fade_timer(self):
        """Start fade-in animation timer. Override in subclass."""

    @staticmethod
    def _first_image_in(dir_path: str) -> str | None:
        return _first_image_in(dir_path)

    def _first_image_cached(self, dir_path: str) -> str | None:
        if dir_path in self._first_image_cache:
            return self._first_image_cache[dir_path]
        result = self._first_image_in(dir_path)
        if len(self._first_image_cache) >= self._first_image_cache_max:
            self._first_image_cache.clear()
        self._first_image_cache[dir_path] = result
        return result

    def _on_dir_size_ready(self, dir_path: str, size_str: str, gen: int = 0):
        """Handle async directory size result — update subtitle and refresh affected row."""
        if getattr(self._model, "is_shutdown", False):
            return
        self._model.discard_pending_dir_size(dir_path)
        if gen and gen != self._model.dir_size_generation:
            return
        if self._model.subtitle_for(dir_path) is None:
            return
        if self._model.subtitle_for(dir_path) == size_str:
            # Same rendered value: skip the dataChanged emission that would
            # otherwise trigger another in-place texture patch / rebuild.
            return
        self._model.set_subtitle(dir_path, size_str)
        row = self._model.row_for_path(dir_path)
        if row >= 0:
            idx = self._model.index(row, 0)
            if idx.isValid():
                self._model.dataChanged.emit(idx, idx, [FileSystemModel.SUBTITLE_ROLE])

    def _populate_details(self):
        self._capture_detail_selection()
        store = self._tags_port if self._lib_root else None
        self._detail_model.set_source(self._model, store=store, lib_root=self._lib_root)
        self._restore_detail_selection()
        self._update_status()

    def _on_detail_dir_size_ready(self, dir_path: str, size_str: str, gen: int = 0):
        if getattr(self._model, "is_shutdown", False):
            return
        if gen and gen != self._model.dir_size_generation:
            return
        self._model.discard_pending_dir_size(dir_path)
        self._model.set_subtitle(dir_path, size_str)
        self._model.set_dir_size(dir_path, size_str)
        # Find the row for this directory and emit dataChanged for Size column only
        for i, entry in enumerate(self._detail_model.entries):
            if entry.path == dir_path:
                idx = self._detail_model.index(i, 2)  # Size column
                if idx.isValid():
                    self._detail_model.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DisplayRole])
                break

    def _on_drop(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        if not paths:
            return False
        scoped = self._get_scoped_services()
        root_path = self._lib_root
        if scoped is None or root_path is None:
            return False
        # Compare resolved paths throughout: QUrl.toLocalFile() yields forward
        # slashes while str(Path) uses the platform separator, so raw string
        # comparison would misclassify every drop on Windows.
        destination = Path(self._current).resolve()
        root = Path(root_path).resolve()
        resolved_sources = [Path(path).resolve() for path in paths]
        sources = [p for p in resolved_sources if p.parent != destination]
        if not sources:
            return False
        in_library = [p for p in sources if p.is_relative_to(root)]
        external = [p for p in sources if p not in in_library]

        service = self._get_file_operation_service()
        changed_paths = []
        errors = []
        warnings = []
        try:
            for source in in_library:
                result = service.move_to_directory(
                    [str(source)], str(destination), library_root=root_path,
                )
                for changed_path in result.changed_paths:
                    changed_paths.append(changed_path)
                    if self._undo_svc is not None:
                        self._undo_svc.record_rename(str(source), str(changed_path))
                for error in result.errors:
                    _log.error("Drag-drop move failed: %s", error)
                    errors.append(error)
                warnings.extend(getattr(result, "warnings", ()))
            if external:
                result = service.copy_to_directory(
                    [str(p) for p in external], str(destination), library_root=root_path,
                )
                changed_paths.extend(getattr(result, "changed_paths", ()))
                for error in result.errors:
                    _log.error("Drag-drop copy failed: %s", error)
                    errors.append(error)
                warnings.extend(getattr(result, "warnings", ()))
        except (ValueError, OSError) as exc:
            # The service only collects OSError per item; root-scope violations
            # surface as ValueError and must not escape the drop handler.
            _log.error("Drag-drop failed: %s", exc)
            errors.append(str(exc))
        for warning in warnings:
            _log.warning(
                "Drag-drop projection refresh degraded (%s): %s",
                getattr(warning, "code", "unknown"),
                getattr(warning, "path", destination),
            )
        self._show_operation_feedback(
            scoped.session,
            "drop",
            changed_count=len(changed_paths),
            errors=tuple(errors),
            warnings=tuple(warnings),
        )
        self._request_operation_selection(scoped.session, changed_paths)
        self._post_refresh()
        if self._view_mode == "Details":
            self._populate_details()
        self._load_visible()
        return True

    def _capture_detail_selection(self):
        if not hasattr(self, '_detail_model') or not hasattr(self, '_detail_view'):
            return
        sel = self._detail_view.selectionModel().selectedRows()
        paths = {
            path for path in (
                self._detail_model.data(i, Qt.ItemDataRole.UserRole) for i in sel if i.isValid()
            ) if isinstance(path, str)
        }
        if paths:
            self._pending_detail_paths = paths

    def _capture_grid_selection(self):
        if not hasattr(self, '_grid_widget'):
            return
        paths = {
            path for path in (
                self._model.path_at(r) for r in self._grid_widget.selection_model_rows()
            ) if path
        }
        if paths:
            self._pending_selection_paths = paths

    def _consume_operation_selection(self) -> tuple[str, ...]:
        intent = getattr(self, "_pending_operation_selection", None)
        if intent is None:
            return ()
        self._pending_operation_selection = None
        session, current_dir, paths = intent
        scoped = self._scoped_services
        if (
            scoped is None
            or getattr(scoped, "session", None) is not session
            or getattr(session, "is_closed", False)
            or self._current.resolve() != current_dir
        ):
            return ()
        return paths

    def _copy_selected(self):
        self._copy_to_clipboard()

    def _cut_selected(self):
        self._cut_to_clipboard()

    def _invoke_command(
        self,
        command_id: str,
        context: FileListCommandContext | None = None,
        global_pos: QPoint | None = None,
        *,
        shortcut: bool = False,
    ) -> None:
        """Invoke an existing FileList action through its stable command ID."""
        context = context or self._command_context(self._selected_paths())
        paths = context.paths
        path = paths[0] if paths else None
        if command_id == "open" and path:
            self._navigate_or_open(path)
        elif command_id == "copy":
            self._copy_paths(paths, False)
        elif command_id == "cut":
            self._copy_paths(paths, True)
        elif command_id == "copy_path" and path:
            QApplication.clipboard().setText(path)
        elif command_id == "rename" and path:
            if shortcut:
                self._inline_rename()
            else:
                self._rename(path)
        elif command_id == "duplicate":
            self._duplicate_selected()
        elif command_id == "trash":
            self._delete(list(paths))
        elif command_id == "permanent_delete":
            self._delete_permanent(list(paths))
        elif command_id == "undo":
            self._undo()
        elif command_id == "redo":
            self._redo()
        elif command_id == "properties" and path:
            self._show_properties(path)
        elif command_id == "reveal":
            target = str(Path(path).parent) if path and not os.path.isdir(path) else path or str(self._current)
            self._open_in_explorer(target)
        elif command_id == "quick_share":
            self._quick_share_from_context(list(paths), global_pos or QPoint())
        elif command_id == "paste":
            self._paste()
        elif command_id == "new_folder":
            self._new_folder()
        elif command_id == "select_all":
            self._select_all()
        elif command_id == "refresh":
            self._do_refresh()
        elif command_id == "toggle_hidden":
            self._toggle_hidden()
        elif command_id == "help":
            self._show_filelist_shortcuts()

    def _load_visible_if_active(self):
        """Ignore delayed scan presentation work after panel shutdown."""
        if not getattr(self._model, "is_shutdown", False):
            self._load_visible()

    def _navigate_or_open(self, path: str):
        if os.path.isdir(path):
            self.navigate_to(path)
        else:
            self.file_double_clicked.emit(path)

    def _rename_path(self, old_path: str, new_name: str):
        session = getattr(self._get_scoped_services(), "session", None)
        self._show_operation_feedback(session, "rename", running=True)
        try:
            new_path = self._rename_file_path(old_path, new_name)
            self._request_operation_selection(session, [new_path])
            self._show_operation_feedback(session, "rename", changed_count=1)
            self._post_refresh()
        except OSError as e:
            self._show_operation_feedback(session, "rename", errors=(str(e),))
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(cast(QWidget, self), tr("dialog.error"), str(e))

    def _restore_detail_selection(self):
        paths = self._pending_detail_paths
        if paths is None:
            return
        self._pending_detail_paths = None
        self._select_detail_paths(paths)

    def _restore_grid_selection(self):
        paths = self._pending_selection_paths
        if paths is None:
            return
        self._pending_selection_paths = None
        self._select_grid_paths(paths)

    def _restore_operation_selection(self, paths: tuple[str, ...]) -> None:
        if self._view_mode == "Details":
            self._pending_detail_paths = set(paths)
            self._restore_detail_selection()
        else:
            self._pending_selection_paths = set(paths)
            self._restore_grid_selection()

    def _select_all(self):
        if self._view_mode == "Details":
            self._detail_view.selectAll()
        else:
            self._grid_widget.select_all()
        self._update_status()

    def _select_detail_paths(self, paths: set[str]) -> None:
        sm = self._detail_view.selectionModel()
        sm.clearSelection()
        for row, entry in enumerate(self._detail_model.entries):
            if entry.path in paths:
                idx = self._detail_model.index(row, 0)
                if idx.isValid():
                    sm.select(idx, QItemSelectionModel.SelectionFlag.Select
                              | QItemSelectionModel.SelectionFlag.Rows)

    def _select_grid_paths(self, paths: set[str]) -> None:
        self._grid_widget.set_selection_rows({
            row
            for path in paths
            if (row := self._model.row_for_path(path)) >= 0
        })

    def _selected_detail_paths(self) -> list[str]:
        sel = self._detail_view.selectionModel().selectedRows()
        return [p for p in (
            self._detail_model.data(i, Qt.ItemDataRole.UserRole)
            for i in sel if i.isValid()
        ) if isinstance(p, str)]
