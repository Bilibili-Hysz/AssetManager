"""Navigation mixin for FileListPanel — breadcrumb, history, filesystem watcher."""
import os
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, cast

from PySide6.QtCore import Qt, QTimer, QFileSystemWatcher
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QWidget

from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.panels.file_list._loader import ThumbnailLoader
from AssetsManager.panels.file_list._model import FileSystemModel
from AssetsManager.widgets.stylekit import StyleKit

_log = logging.getLogger(__name__)

_FS_REFRESH_DEBOUNCE_MS = 500


class NavigationMixin:
    """Provides navigate_to, back/forward/up, breadcrumb, and FS watcher."""

    if TYPE_CHECKING:
        _model: FileSystemModel
        _loader: ThumbnailLoader
        _fs_watcher: QFileSystemWatcher
        _first_image_cache: dict[str, str | None]
        _last_click_row: int
        _current: Path
        _root: Path | None
        _history: list[str]
        _forward_list: list[str]
        _view_memory: dict[str, str]
        _view_mode: str
        _view_combo: QComboBox
        _bc_layout: QHBoxLayout
        folder_entered: Any

        def _configure_library_runtime(self, root: str) -> None: ...
        def _populate_details(self) -> None: ...
        def _post_refresh(self) -> None: ...
        def _clear_selection_for_navigation(self) -> None: ...
        def _update_status(self) -> None: ...
        def _load_visible(self) -> None: ...
        def _run_in_background(self, func: Callable[[], None]) -> None: ...

    # ── FS watcher ────────────────────────────────────────────────

    def _start_fs_watcher(self):
        self._fs_watcher = QFileSystemWatcher(cast(QWidget, self))
        self._fs_watcher.directoryChanged.connect(self._on_fs_changed)
        self._fs_refresh_timer = QTimer(cast(QWidget, self))
        self._fs_refresh_timer.setSingleShot(True)
        self._fs_refresh_timer.setInterval(_FS_REFRESH_DEBOUNCE_MS)
        self._fs_refresh_timer.timeout.connect(self._flush_fs_changed)
        self._pending_fs_changed_path: str | None = None

    def _watch_current_dir(self):
        if hasattr(self, '_fs_watcher') and self._current:
            dirs = self._fs_watcher.directories()
            if dirs:
                self._fs_watcher.removePaths(dirs)
            self._fs_watcher.addPath(str(self._current))

    def _on_fs_changed(self, path):
        """Coalesce bursty watcher notifications into one model refresh."""
        if self._model.is_shutdown:
            return
        domain_timer = getattr(self, "_file_op_timer", None)
        if domain_timer is not None and domain_timer.isActive():
            # A scoped domain event already owns the pending refresh. The
            # watcher will observe the same filesystem mutation shortly after
            # the event and must not schedule a second full model reset.
            return
        self._pending_fs_changed_path = str(path)
        timer = getattr(self, "_fs_refresh_timer", None)
        if timer is not None:
            timer.start(_FS_REFRESH_DEBOUNCE_MS)
            return
        self._flush_fs_changed()

    def _flush_fs_changed(self):
        """Refresh only the directory that is still being displayed.

        Keep the thumbnail loader's memory cache warm across a filesystem
        refresh.  The model scan and thumbnail delivery path will replace
        changed entries, while unchanged cards can be painted immediately.
        """
        if self._model.is_shutdown:
            return

        changed_path = self._pending_fs_changed_path
        self._pending_fs_changed_path = None
        if not changed_path or not getattr(self, "_current", None):
            return

        changed_key = os.path.normcase(os.path.abspath(changed_path))
        current_key = os.path.normcase(os.path.abspath(str(self._current)))
        if changed_key != current_key:
            return

        self._first_image_cache.pop(str(self._current), None)
        if hasattr(self, "_loader"):
            self._loader.clear_queue()
        self._post_refresh()
        self._update_status()

    # ── Navigation ────────────────────────────────────────────────

    @property
    def current_path(self):
        return str(self._current)

    @property
    def _lib_root(self):
        """Library root for DB/store access. None when no library opened."""
        return str(self._root) if self._root else None

    def navigate_to(self, path, *, set_root=False):
        self._loader.clear_queue()
        self._last_click_row = -1
        p = Path(path).resolve()
        if not p.is_dir():
            p = p.parent
        if not p.exists():
            QMessageBox.warning(cast(QWidget, self), "Error", f"Path not found:\n{path}")
            return
        if set_root:
            self._root = p
            try:
                self._configure_library_runtime(str(p))
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("Failed to configure library runtime: %s", e)
        old_dir = str(self._current)
        self._view_memory[old_dir] = self._view_mode
        self._history.append(str(self._current))
        self._forward_list.clear()
        if p != self._current:
            self._clear_selection_for_navigation()
        self._current = p
        self._model.set_directory(str(p))
        if hasattr(self, '_first_image_cache'):
            self._first_image_cache.clear()
        if not self._restore_view_mode(str(p)) and self._view_mode == "Details":
            self._populate_details()
        self._render_bc()
        self._update_status()
        # Don't call _show_empty_if_needed() here — model is async, row count is 0
        # The grid shows "Folder is empty" only after scan completes with 0 results
        self.folder_entered.emit(str(p))
        bus().directory_changed.emit(str(p))
        self._watch_current_dir()
        QTimer.singleShot(80, self._load_visible)
        if set_root:
            QTimer.singleShot(120, lambda: self._schedule_library_stats_update(str(p)))

    def _schedule_library_stats_update(self, lib_root: str):
        """Refresh the opened library's aggregate size without blocking the UI."""
        services = getattr(self, "_scoped_services", None)
        session = getattr(services, "session", None)
        metadata_service = getattr(services, "metadata_service", None)
        if session is None or metadata_service is None:
            _log.warning("Skipping library stats update without scoped services: %s", lib_root)
            return

        root = str(Path(lib_root).resolve())
        session_root = str(Path(session.root).resolve())
        if root != session_root:
            _log.warning(
                "Skipping library stats update for stale runtime snapshot: %s (session: %s)",
                root,
                session_root,
            )
            return

        def _update() -> None:
            try:
                with session.operation():
                    total_size, _ = metadata_service.get_dir_size(root, root, force=True)
                    metadata_service.set_library_total_size(root, total_size)
            except Exception:
                _log.exception("Failed to update library stats for %s", root)

        self._run_in_background(_update)

    def _go_back(self):
        if self._history:
            prev = Path(self._history.pop())
            if self._root:
                prev_s = str(prev)
                root_s = str(self._root)
                if prev_s != root_s and not prev_s.startswith(root_s + os.sep):
                    return
            self._loader.clear_queue()
            self._forward_list.append(str(self._current))
            self._clear_selection_for_navigation()
            self._current = prev
            self._model.set_directory(str(prev))
            self._restore_view_mode(str(prev))
            self._render_bc()
            if self._view_mode == "Details":
                self._populate_details()
            self._update_status()
            self._watch_current_dir()
            self.folder_entered.emit(str(prev))
            bus().directory_changed.emit(str(prev))
            self._load_visible()

    def _go_forward(self):
        if self._forward_list:
            nxt = Path(self._forward_list.pop())
            self._loader.clear_queue()
            self._history.append(str(self._current))
            self._clear_selection_for_navigation()
            self._current = nxt
            self._model.set_directory(str(nxt))
            self._restore_view_mode(str(nxt))
            self._render_bc()
            if self._view_mode == "Details":
                self._populate_details()
            self._update_status()
            self._watch_current_dir()
            self.folder_entered.emit(str(nxt))
            bus().directory_changed.emit(str(nxt))
            self._load_visible()

    def _go_up(self):
        parent = self._current.parent
        if parent == self._current:
            return
        if self._root:
            parent_s = str(parent)
            root_s = str(self._root)
            if parent_s != root_s and not parent_s.startswith(root_s + os.sep):
                return
        self._loader.clear_queue()
        self._history.append(str(self._current))
        self._forward_list.clear()
        self._clear_selection_for_navigation()
        self._current = parent
        self._model.set_directory(str(parent))
        self._restore_view_mode(str(parent))
        self._render_bc()
        if self._view_mode == "Details":
            self._populate_details()
        self._update_status()
        self._watch_current_dir()
        self.folder_entered.emit(str(parent))
        bus().directory_changed.emit(str(parent))
        self._load_visible()

    def _restore_view_mode(self, path: str) -> bool:
        saved_mode = self._view_memory.get(path)
        if not saved_mode or saved_mode == self._view_mode:
            return False
        index = self._view_combo.findData(saved_mode)
        if index < 0:
            return False
        self._view_combo.setCurrentIndex(index)
        return True

    # ── Breadcrumb ───────────────────────────────────────────────

    def _render_bc(self):
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        while self._bc_layout.count():
            item = self._bc_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        ancestors = [self._current]
        p = self._current.parent
        while p != p.parent:
            ancestors.insert(0, p)
            p = p.parent
        show = ancestors[-5:] if len(ancestors) > 5 else ancestors
        if len(ancestors) > 5:
            dot = QPushButton(" … ")
            dot.setFlat(True)
            dot.setCursor(Qt.CursorShape.PointingHandCursor)
            dot.setStyleSheet(
                f"color: {sk.token('muted')}; font-size: {sk.pt(12)}px; "
                f"background: transparent; border: none;")
            hidden = ancestors[:-5]
            dot.setToolTip("\n".join(str(a) for a in hidden))
            dot.clicked.connect(lambda checked, paths=hidden: self._show_bc_menu(paths, dot))
            self._bc_layout.addWidget(dot)
        for i, anc in enumerate(show):
            if i > 0 or (len(ancestors) > 5 and i == 0):
                sep = QLabel(" > ")
                sep.setStyleSheet(sk.muted_css(12))
                self._bc_layout.addWidget(sep)
            name = anc.name or str(anc)
            btn = QPushButton(name)
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"color: {sk.token('muted')}; font-size: {sk.pt(12)}px; "
                f"padding: {sk.px(2)}px {sk.px(4)}px; background: transparent; "
                f"border: none; border-radius: {sk.px(3)}px;")
            btn.setToolTip(str(anc))
            bpath = str(anc)
            btn.clicked.connect(lambda checked, p=bpath: self.navigate_to(p))
            self._bc_layout.addWidget(btn)
        self._bc_layout.addStretch()

    def _show_bc_menu(self, paths, btn):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(btn)
        for p in paths:
            name = p.name or str(p)
            menu.addAction(str(name), lambda checked, path=p: self.navigate_to(str(path)))
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
