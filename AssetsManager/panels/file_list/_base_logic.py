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

from PySide6.QtCore import Qt, QTimer, QModelIndex, QPoint, QItemSelectionModel, QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import Shiboken

from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.core.workers import BoundedPool, CancellationToken, CancellableRunnable
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

# Bound on the number of in-flight folder cover scans.  The viewport exposes
# at most a handful of directories at a time, so 64 is generous while keeping
# memory and queue depth finite even under rapid scrolling.
_COVER_SCAN_QUEUE_LIMIT = 64


class _CoverScanSignals(QObject):
    """Completion signal bridge for one folder cover scan."""

    done = Signal(str, object, int, object)  # (dir_path, result, generation, task)


class _CoverScanTask(CancellableRunnable):
    """Scan one directory for its first image on a worker thread.

    The worker touches only the filesystem (``find_first_image``) and returns
    ``str | None``; it never creates QPixmap/QWidget.  The panel connects this
    completion signal to its bound slot with an explicit queued connection.
    """

    def __init__(self, dir_path: str, generation: int, cancel_token: CancellationToken) -> None:
        super().__init__(generation=generation, cancel_token=cancel_token)
        self._dir_path = dir_path
        self.signals = _CoverScanSignals()

    def run(self) -> None:
        signals = self.signals
        if self.is_cancelled():
            return
        try:
            result = _first_image_in(self._dir_path)
        except Exception:
            _log.exception("Folder cover scan failed: %s", self._dir_path)
            result = None
        if not self.is_cancelled():
            signals.done.emit(self._dir_path, result, self.generation, self)


def _cover_view_window(panel: Any) -> tuple[int, int]:
    """Visible + prefetch row window used to gate preview requests.

    Module-level so fake panels used in unit tests (plain ``type()`` shells with
    no LogicMixin methods) can drive ``_load_visible`` / preview logic.
    """
    total = panel._model.rowCount()
    if total == 0:
        return 0, -1
    vh = panel._grid_widget.height()
    sy = panel._grid_widget._scroll_y
    visible = panel._grid_layout.visible_rows(sy, vh)
    visible_rows = [row for row in visible if 0 <= row < total]
    cols = panel._grid_layout.columns
    extra = max(2, cols) * 3
    first = max(0, min(visible_rows[0] if visible_rows else 0, total - 1) - extra)
    last = min(total - 1, max(visible_rows[-1] if visible_rows else 0, 0) + extra)
    return first, last


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
        def _run_in_background(self, func: Any, *args: Any, on_done: Any = None) -> None: ...
        def _session_operation(self, session: Any) -> Any: ...
        def _capture_mutation_context(self) -> Any: ...
        def _consume_refresh_warnings(self, service: Any) -> tuple: ...

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
        # Folder cover scanning runs on a dedicated low-concurrency pool so a
        # cache miss never performs a synchronous scandir on the UI thread.
        self._cover_scan_generation = 0
        self._pending_cover_scans: set[str] = set()
        self._active_cover_tasks: dict[str, _CoverScanTask] = {}
        self._cover_scan_pool: BoundedPool | None = None
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





    def set_scoped_services(self, services, *, runtime=None) -> None:
        """Bind library-scoped services resolved by MainWindow.

        ``runtime`` is part of the uniform ``ScopedServicesConsumer``
        signature; the file list binds no runtime projection router, so the
        kwarg is accepted and ignored.
        """
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
        self._invalidate_cover_scans()
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
        first, last = _cover_view_window(self)
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
        # Delegates to the shared application helper (capped scan).  Called from
        # the cover-scan worker thread, never from the UI thread.
        return _first_image_in(dir_path)

    def _first_image_cached(self, dir_path: str) -> str | None:
        """Return the cached folder cover, scheduling a background scan on miss.

        Cache hits stay fully synchronous.  On a miss the directory is queued
        on the dedicated cover-scan pool and ``None`` is returned immediately:
        the UI thread never blocks behind a ``scandir``.  The result lands in
        the cache and refreshes only the matching visible row when ready.
        """
        if dir_path in self._first_image_cache:
            return self._first_image_cache[dir_path]
        self._request_cover_scan(dir_path)
        return None

    def _ensure_cover_scan_pool(self) -> BoundedPool:
        pool = self._cover_scan_pool
        if pool is None:
            pool = BoundedPool(1)
            self._cover_scan_pool = pool
        return pool

    def _invalidate_cover_scans(self) -> None:
        """Cancel in-flight cover scans and drop their pending registrations.

        Called on navigation, refresh and lifecycle shutdown so a stale worker
        result can never update the cache or refresh a row after the listing
        or session that requested it is gone.  Runs on the UI thread only.
        """
        self._cover_scan_generation += 1
        self._pending_cover_scans.clear()
        for task in self._active_cover_tasks.values():
            # A task may already have finished on the pool: with autoDelete the
            # C++ QRunnable is gone and only the Python wrapper remains.
            if Shiboken.isValid(task):
                try:
                    task.signals.done.disconnect()
                except (RuntimeError, TypeError):
                    pass
        self._active_cover_tasks.clear()
        pool = self._cover_scan_pool
        if pool is not None:
            pool.cancel_all()

    def _drain_cover_scan_pool(self, timeout_ms: int = 2000) -> None:
        """Bound-wait for queued/running cover scans to finish."""
        pool = self._cover_scan_pool
        if pool is not None:
            if not pool.drain(timeout_ms):
                _log.warning("Folder cover scan pool drain timed out after %sms", timeout_ms)

    def _close_cover_scan_pool(self, timeout_ms: int = 2000) -> None:
        """Release the terminal cover pool without blocking panel destruction."""
        pool = self._cover_scan_pool
        if pool is not None:
            pool.close(timeout_ms, owner_label="FileList cover scan")
            self._cover_scan_pool = None

    def _request_cover_scan(self, dir_path: str) -> None:
        """Submit one deduplicated folder cover scan to the dedicated pool."""
        model = self._model
        if getattr(model, "is_shutdown", False):
            return
        if dir_path in self._first_image_cache or dir_path in self._pending_cover_scans:
            return
        if len(self._pending_cover_scans) >= _COVER_SCAN_QUEUE_LIMIT:
            return
        generation = self._cover_scan_generation
        task = _CoverScanTask(dir_path, generation, CancellationToken())
        self._pending_cover_scans.add(dir_path)
        self._active_cover_tasks[dir_path] = task
        task.signals.done.connect(
            self._on_cover_scan_result,
            Qt.ConnectionType.QueuedConnection,
        )
        try:
            self._ensure_cover_scan_pool().start(task)
        except Exception:
            self._pending_cover_scans.discard(dir_path)
            self._active_cover_tasks.pop(dir_path, None)
            raise

    def _on_cover_scan_result(self, dir_path: str, result: str | None, generation: int, task: Any) -> None:
        """Adopt a completed cover scan on the main thread.

        Old results (generation mismatch after navigation/refresh/shutdown,
        closed session, row no longer present) are discarded without touching
        the cache or the visible rows.
        """
        model = self._model
        if getattr(model, "is_shutdown", False):
            return
        if generation != self._cover_scan_generation:
            return
        self._pending_cover_scans.discard(dir_path)
        if self._active_cover_tasks.get(dir_path) is task:
            self._active_cover_tasks.pop(dir_path, None)
        scoped = self._scoped_services
        session = getattr(scoped, "session", None) if scoped is not None else None
        if session is not None and getattr(session, "is_closed", False):
            return
        if len(self._first_image_cache) >= self._first_image_cache_max:
            self._first_image_cache.clear()
        self._first_image_cache[dir_path] = result
        if result:
            self._request_cover_thumbnail(dir_path, result)

    def _request_cover_thumbnail(self, dir_path: str, preview: str) -> None:
        """Request the preview thumbnail for exactly one visible directory row.

        Goes through the existing thumbnail pipeline so delivery paints only
        that row — no model rebuild and no full-viewport invalidation.
        """
        model = self._model
        if getattr(model, "is_shutdown", False) or self._view_mode != "Grid":
            return
        row = model.row_for_path(dir_path)
        if row < 0:
            return
        entry = model.entry_at(row)
        if entry is None:
            return
        try:
            if not entry.is_dir():
                return
        except OSError:
            return
        first, last = _cover_view_window(self)
        if row < first or row > last:
            return
        self._loader.request(row, preview, priority=0, item_path=dir_path)

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

        session = scoped.session
        service = self._get_file_operation_service()
        undo_svc = self._undo_svc
        from AssetsManager.application.file_operation_service import FileOperationResult
        result_holder: list[FileOperationResult] = []
        # The move/copy work runs on the shared background pool (same mode as
        # paste/delete/duplicate); only validation-classification stays on the
        # UI thread so the drop event returns immediately.
        self._show_operation_feedback(session, "drop", running=True)

        def _do_drop() -> None:
            changed_paths: list[Path] = []
            errors: list[str] = []
            warnings: list[Any] = []
            try:
                with self._session_operation(session):
                    for source in in_library:
                        result = service.move_to_directory(
                            [str(source)], str(destination), library_root=root_path,
                        )
                        for changed_path in result.changed_paths:
                            changed_paths.append(changed_path)
                            if undo_svc is not None:
                                undo_svc.record_rename(str(source), str(changed_path))
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
            except Exception as exc:
                _log.exception("Drag-drop worker failed")
                changed_paths.clear()
                warnings.clear()
                errors = [str(exc) or exc.__class__.__name__]
            result_holder.append(
                FileOperationResult(
                    tuple(changed_paths),
                    tuple(errors),
                    tuple(warnings),
                )
            )

        def _on_drop_done() -> None:
            if not self._is_current_operation_session(session):
                return
            result = result_holder[0] if result_holder else FileOperationResult(
                (), ("Drag-drop worker completed without a result",),
            )
            changed_paths = result.changed_paths
            errors = result.errors
            warnings = result.warnings
            for warning in warnings:
                _log.warning(
                    "Drag-drop projection refresh degraded (%s): %s",
                    getattr(warning, "code", "unknown"),
                    getattr(warning, "path", destination),
                )
            self._show_operation_feedback(
                session,
                "drop",
                changed_count=len(changed_paths),
                errors=tuple(errors),
                warnings=tuple(warnings),
            )
            if changed_paths:
                self._request_operation_selection(session, changed_paths)
            self._post_refresh()
            if self._view_mode == "Details":
                self._populate_details()
            self._load_visible()

        self._run_in_background(_do_drop, on_done=_on_drop_done)
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
        # Inline rename commit path.  The view has already closed its editor
        # by the time this runs (grid `_finish` disposes the editor before
        # emitting rename_requested; the details view closes it after
        # setData returns True), so the actual move is backgrounded here —
        # the editor never waits on a slow (e.g. network-drive) service call.
        mutation = self._capture_mutation_context()
        if mutation is None:
            return
        session, service, _undo_service, _lib_root = mutation
        self._show_operation_feedback(session, "rename", running=True)
        result_holder: list[str] = []
        error_holder: list[str] = []
        warnings: list = []

        def _do_rename():
            with self._session_operation(session):
                try:
                    result_holder.append(self._rename_file_path(old_path, new_name))
                    warnings.extend(self._consume_refresh_warnings(service))
                except Exception as error:
                    error_holder.append(str(error) or type(error).__name__)
                    warnings.extend(self._consume_refresh_warnings(service))

        def _on_rename_done():
            if not self._is_current_operation_session(session):
                return
            if result_holder:
                self._request_operation_selection(session, result_holder)
            self._show_operation_feedback(
                session,
                "rename",
                changed_count=1 if result_holder else 0,
                errors=tuple(error_holder),
                warnings=tuple(warnings),
            )
            if error_holder:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(cast(QWidget, self), tr("dialog.error"), error_holder[0])
            if result_holder:
                self._post_refresh()

        self._run_in_background(_do_rename, on_done=_on_rename_done)

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
