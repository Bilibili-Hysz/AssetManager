"""Navigation mixin for FileListPanel — breadcrumb, history, filesystem watcher."""
import os
import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QPushButton, QLabel, QMessageBox

from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px

_log = logging.getLogger(__name__)


class NavigationMixin:
    """Provides navigate_to, back/forward/up, breadcrumb, and FS watcher."""

    # Signals expected on the concrete class
    folder_entered = Signal(str)

    # ── FS watcher ────────────────────────────────────────────────

    def _start_fs_watcher(self):
        from PySide6.QtCore import QFileSystemWatcher
        self._fs_watcher = QFileSystemWatcher(self)
        self._fs_watcher.directoryChanged.connect(self._on_fs_changed)

    def _watch_current_dir(self):
        if hasattr(self, '_fs_watcher') and self._current:
            dirs = self._fs_watcher.directories()
            if dirs:
                self._fs_watcher.removePaths(dirs)
            self._fs_watcher.addPath(str(self._current))

    def _on_fs_changed(self, _path):
        self._first_image_cache.clear()
        if hasattr(self, '_loader'):
            self._loader.clear_cache()
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
        # Reset hover state (supports both delegate and canvas)
        if hasattr(self, '_grid_delegate'):
            self._grid_delegate._hover_row = -1
        if hasattr(self, '_canvas'):
            self._canvas._hover_row = -1
            self._canvas.update()
        self._last_click_row = -1
        p = Path(path).resolve()
        if not p.is_dir():
            p = p.parent
        if not p.exists():
            QMessageBox.warning(self, "Error", f"Path not found:\n{path}")
            return
        if set_root:
            self._root = p
            self._model.set_library_root(str(p))
            try:
                self._configure_library_runtime(str(p))
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("Failed to configure library runtime: %s", e)
        old_dir = str(self._current)
        self._view_memory[old_dir] = self._view_mode
        self._history.append(str(self._current))
        self._forward_list.clear()
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
        if self._root and not str(parent).startswith(str(self._root)):
            return
        self._loader.clear_queue()
        self._history.append(str(self._current))
        self._forward_list.clear()
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
        t = themes.get()
        while self._bc_layout.count():
            it = self._bc_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
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
            dot.setStyleSheet(f"color: {t['muted']}; font-size: 12px; background: transparent; border: none;")
            hidden = ancestors[:-5]
            dot.setToolTip("\n".join(str(a) for a in hidden))
            dot.clicked.connect(lambda checked, paths=hidden: self._show_bc_menu(paths, dot))
            self._bc_layout.addWidget(dot)
        for i, anc in enumerate(show):
            if i > 0 or (len(ancestors) > 5 and i == 0):
                sep = QLabel(" > ")
                sep.setStyleSheet(f"color: {t['muted']}; font-size: 12px; background: transparent;")
                self._bc_layout.addWidget(sep)
            name = anc.name or str(anc)
            btn = QPushButton(name)
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"color: {t['muted']}; font-size: 12px; padding: 2px 4px; "
                              f"background: transparent; border: none; border-radius: {scaled_px(3)}px;")
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
