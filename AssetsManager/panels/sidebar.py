"""Sidebar panel — virtual favorites/recent headers integrated into tree.

Features:
- Favorites and Recent Folders as top-level virtual tree items
- Real filesystem roots below virtual sections
- Lazy-loading tree with expandable directories
- Search/filter bar (applies to filesystem items only)
- Right-click context menu on all item types
- Keyboard: Ctrl+F, Ctrl+Shift+F, Escape
"""
import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QObject, QRunnable, QThreadPool
from PySide6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QLineEdit, QPushButton, QHBoxLayout,
    QMenu, QInputDialog, QApplication, QAbstractItemView, QLabel, QWidget,
)
from PySide6.QtGui import QKeyEvent, QBrush, QColor

from AssetsManager.panels.base import PanelContent
from AssetsManager import i18n
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.core import themes
from AssetsManager.dialogs.sidebar_favorites import SidebarFavorites
from AssetsManager.dialogs.sidebar_recent import SidebarRecentFolders

tr = i18n.tr

ICONS = ["⭐", "📁", "📂", "🔖", "💾", "🖥", "🎨", "📌", "🏠", "🔥"]

VTYPE_FAV_HEADER = "fav_header"
VTYPE_REC_HEADER = "rec_header"
VTYPE_FAV_CHILD = "fav_child"
VTYPE_REC_CHILD = "rec_child"
VTYPE_FS = "fs"


def _fs_level(item: QTreeWidgetItem) -> int:
    """Return how many FS levels deep this item is (1 = top-level FS item)."""
    level = 0
    it = item
    while it:
        vt = it.data(0, Qt.ItemDataRole.UserRole + 1)
        if vt == VTYPE_FS:
            level += 1
        it = it.parent()
    return level


class _PreloadSignals(QObject):
    done = Signal(object)


class _PreloadTask(QRunnable):
    def __init__(self, root_paths, max_depth=2):
        super().__init__()
        self.setAutoDelete(False)  # prevent GC before signal delivery
        self._root_paths = root_paths
        self._max_depth = max_depth
        self.signals = _PreloadSignals()

    def run(self):
        results = []
        for root_path in self._root_paths:
            self._scan_recursive(root_path, 0, results)
        self.signals.done.emit(results)

    def _scan_recursive(self, path, depth, results):
        if depth >= self._max_depth:
            return
        try:
            entries = sorted(os.scandir(path),
                             key=lambda e: (not e.is_dir(), e.name.lower()))
            results.append((path, [(e.name, e.path, e.is_dir()) for e in entries
                                   if not e.name.startswith(".")]))
            for entry in entries:
                if entry.is_dir() and not entry.name.startswith("."):
                    self._scan_recursive(entry.path, depth + 1, results)
        except OSError:
            pass


class SidebarPanel(PanelContent):
    directory_selected = Signal(str)

    ROOTS = [str(Path.home()), str(Path.home() / "Documents"),
             str(Path.home() / "Downloads"), str(Path.home() / "Pictures")]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._favs = SidebarFavorites()
        self._recents = SidebarRecentFolders()
        self._library_root: str | None = None
        self._scoped_services = None
        self._search_pending = ""
        self._search_timer = None
        self._match_count = 0
        from AssetsManager.controllers.sidebar_controller import SidebarController
        self._controller = SidebarController()

        # ── Search bar + toolbar ─────────────────────────────────

        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("sidebar.filter_placeholder"))
        self._search.textChanged.connect(self._on_search_text)
        self._search.setClearButtonEnabled(True)
        self._search.installEventFilter(self)
        self.setFocusProxy(self._search)

        from PySide6.QtCore import QTimer
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._do_search)

        # ── Tree (stretch=1) ────────────────────────────────────

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(16)
        self._tree.setAnimated(True)
        self._tree.setExpandsOnDoubleClick(False)
        self._tree.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self._tree.setAcceptDrops(True)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._tree_menu)
        self._tree.itemClicked.connect(self._on_tree_click)
        self._tree.itemDoubleClicked.connect(self._on_tree_double_click)
        self._tree.itemExpanded.connect(self._on_expand)
        self._tree.installEventFilter(self)
        self._drag_highlight_item: QTreeWidgetItem | None = None

        t = themes.get()
        bar = QHBoxLayout()
        bar.setContentsMargins(scaled_px(4), scaled_px(4), scaled_px(4), scaled_px(2))
        bar.addWidget(self._search)
        self._expand_btn = QPushButton("+")
        self._expand_btn.setToolTip(tr("sidebar.expand_all"))
        self._expand_btn.clicked.connect(self._tree.expandAll)
        self._collapse_btn = QPushButton("−")
        self._collapse_btn.setToolTip(tr("sidebar.collapse_all"))
        self._collapse_btn.clicked.connect(self._tree.collapseAll)
        for btn in (self._expand_btn, self._collapse_btn):
            btn.setFixedSize(scaled_px(26), scaled_px(26))
            btn.setFlat(True)
            btn.setStyleSheet(
                f"color: {t['body']}; padding: 0; font-size: {scaled_pt(14)}px; font-weight: bold; "
                f"background: transparent; border-radius: {scaled_px(6)}px; "
                f"border: 1px solid {alpha(t['border'], 0.375)};")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            bar.addWidget(btn)
        self.content_layout.addLayout(bar)

        self.content_layout.addWidget(self._tree, 1)

        # ── Status bar ──────────────────────────────────────────

        self._status_bar = QWidget()
        self._status_bar.setFixedHeight(scaled_px(28))
        sl = QHBoxLayout(self._status_bar)
        sl.setContentsMargins(scaled_px(10), scaled_px(4), scaled_px(10), scaled_px(4))
        sl.setSpacing(scaled_px(8))
        self._status = QLabel("")
        sl.addWidget(self._status)
        sl.addStretch()
        self._apply_status_style()
        self.content_layout.addWidget(self._status_bar)

        self._depth = 2
        self._branch_depths: dict[str, int] = {}
        self._restore_depth_cfg()
        self._show_favs = True
        self._show_recs = True
        self._show_filter = True
        self._fav_expanded: bool | None = None
        self._rec_expanded: bool | None = None
        self._state = {"depth": 2, "expanded": set()}
        self._populate()
        self._connect_bus(bus().refresh_requested, self._populate)
        self._connect_bus(bus().theme_changed, self._on_theme_changed)
        self._connect_bus(bus().language_changed, self._on_theme_changed)
        self._connect_bus(bus().ui_scale_changed, self._on_theme_changed)

    def _restore_depth_cfg(self):
        from AssetsManager.core.settings import AppSettings
        try:
            cfg = AppSettings.instance().get("sidebar_depth_cfg")
            if isinstance(cfg, dict):
                self._depth = cfg.get("depth", 2)
                self._branch_depths = cfg.get("branch_depths", {}) or {}
                bus().sidebar_depth_changed.emit(self._depth, dict(self._branch_depths))
        except Exception:
            pass

    def set_scoped_services(self, services):
        """Bind the library bundle resolved by MainWindow."""
        self._scoped_services = services
        self._library_root = services.session.root_str
        self._favs.set_library_root(self._library_root)
        self._recents.set_library_root(self._library_root)
        self._populate()

    @staticmethod
    def _set_vtype(item: QTreeWidgetItem, vtype: str, path: str = ""):
        item.setData(0, Qt.ItemDataRole.UserRole, path)
        item.setData(0, Qt.ItemDataRole.UserRole + 1, vtype)

    @staticmethod
    def _get_vtype(item: QTreeWidgetItem) -> str:
        return item.data(0, Qt.ItemDataRole.UserRole + 1) or VTYPE_FS

    @staticmethod
    def _bold_item(item: QTreeWidgetItem, color: str = ""):
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        if color:
            item.setForeground(0, QBrush(QColor(color)))

    def _populate(self):
        self._tree.clear()

        # ── Virtual: Favorites header ──────────────────────────
        if self._show_favs:
            favs = self._favs.list_all()
            fav_count = len(favs)
            fav_header = QTreeWidgetItem([tr("sidebar.favorites", count=fav_count)])
            self._set_vtype(fav_header, VTYPE_FAV_HEADER)
            self._bold_item(fav_header, themes.get()["favorite"])
            self._tree.addTopLevelItem(fav_header)

            for fav in favs:
                icon = fav.get("icon", "⭐")
                name = fav.get("name", Path(fav["path"]).name)
                child = QTreeWidgetItem([f"  {icon}  {name}"])
                self._set_vtype(child, VTYPE_FAV_CHILD, fav["path"])
                child.setToolTip(0, fav["path"])
                fav_header.addChild(child)

        # ── Virtual: Recent Folders header ──────────────────────
        if self._show_recs:
            recs = self._recents.list_all()
            rec_count = len(recs)
            rec_header = QTreeWidgetItem([tr("sidebar.recent_folders", count=rec_count)])
            self._set_vtype(rec_header, VTYPE_REC_HEADER)
            self._bold_item(rec_header, themes.get()["recent"])
            self._tree.addTopLevelItem(rec_header)

            for r in recs:
                path = r["path"]
                name = Path(path).name
                time_lbl = r.get("_time_label", "")
                child = QTreeWidgetItem([f"  📁  {name}  · {time_lbl}"])
                self._set_vtype(child, VTYPE_REC_CHILD, path)
                child.setToolTip(0, f"{path}\n{time_lbl}")
                rec_header.addChild(child)

        # ── Filesystem: root children as top-level ──────────────
        roots = [self._library_root] if self._library_root else self.ROOTS
        for root_path in roots:
            p = Path(root_path)
            if not p.exists():
                continue
            try:
                entries = sorted(os.scandir(p),
                                 key=lambda e: (not e.is_dir(), e.name.lower()))
            except OSError:
                continue
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                icon = "📁 " if entry.is_dir() else "   "
                item = QTreeWidgetItem([f"{icon}{entry.name}"])
                self._set_vtype(item, VTYPE_FS, entry.path)
                self._tree.addTopLevelItem(item)
                branch_depth = self._branch_depths.get(entry.name, self._depth)
                if entry.is_dir() and branch_depth > 1:
                    QTreeWidgetItem(item, ["..."])
                elif entry.is_dir():
                    item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)

        # Collapse virtual headers by default (or restore saved state).
        # Filesystem items stay collapsed (lazy-load on user expand).
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            vtype = self._get_vtype(item)
            if vtype == VTYPE_FAV_HEADER:
                if self._fav_expanded is None:
                    item.setExpanded(False)
                else:
                    item.setExpanded(self._fav_expanded)
            elif vtype == VTYPE_REC_HEADER:
                if self._rec_expanded is None:
                    item.setExpanded(False)
                else:
                    item.setExpanded(self._rec_expanded)

        total = self._tree.topLevelItemCount()
        if total == 0:
            self._status.setText(tr("sidebar.status_empty"))
        else:
            self._status.setText(tr("sidebar.status_root_folders", count=total))


    # ── Lazy-load filesystem children ───────────────────────────────

    def _on_expand(self, item):
        if self._get_vtype(item) != VTYPE_FS:
            return
        if item.childCount() == 1 and item.child(0).text(0) == "...":
            item.removeChild(item.child(0))
            self._load_children(item, 0)

    def _load_children(self, parent_item, _unused=0):
        level = _fs_level(parent_item)
        branch_depth = self._depth
        it = parent_item
        while it:
            if self._get_vtype(it) == VTYPE_FS and not it.parent():
                name = Path(it.data(0, Qt.ItemDataRole.UserRole) or "").name
                if name in self._branch_depths:
                    branch_depth = self._branch_depths[name]
                break
            it = it.parent()

        if level >= branch_depth:
            parent_item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)
            return
        path = parent_item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        try:
            entries = sorted(os.scandir(path),
                             key=lambda e: (not e.is_dir(), e.name.lower()))
        except OSError:
            return
        for entry in entries:
            if entry.name.startswith("."):
                continue
            icon = "📁 " if entry.is_dir() else "   "
            child = QTreeWidgetItem([f"{icon}{entry.name}"])
            self._set_vtype(child, VTYPE_FS, entry.path)
            parent_item.addChild(child)
            if entry.is_dir() and level + 1 < branch_depth:
                QTreeWidgetItem(child, ["..."])
            elif entry.is_dir():
                child.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)

    # ── Drag-drop onto favorites ───────────────────────────────────

    def _fav_header_item(self) -> QTreeWidgetItem | None:
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if self._get_vtype(item) == VTYPE_FAV_HEADER:
                return item
        return None

    def _is_drag_over_fav(self, event) -> bool:
        item = self._tree.itemAt(event.position().toPoint())
        if not item:
            return False
        vtype = self._get_vtype(item)
        return vtype in (VTYPE_FAV_HEADER, VTYPE_FAV_CHILD)

    def _fav_highlight(self, on: bool):
        item = self._fav_header_item()
        if not item:
            return
        if on and self._drag_highlight_item is not item:
            self._drag_highlight_item = item
            t = themes.get()
            item.setBackground(0, QBrush(QColor(t["accent"])))
        elif not on and self._drag_highlight_item is item:
            item.setBackground(0, QBrush(Qt.BrushStyle.NoBrush))
            self._drag_highlight_item = None

    def _on_tree_drag_enter(self, event) -> bool:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._fav_highlight(True)
            return True
        return False

    def _on_tree_drag_move(self, event) -> bool:
        if self._is_drag_over_fav(event):
            event.acceptProposedAction()
            self._fav_highlight(True)
            return True
        self._fav_highlight(False)
        return False

    def _on_tree_drag_leave(self, event) -> bool:
        self._fav_highlight(False)
        return False

    def _on_tree_drop(self, event) -> bool:
        self._fav_highlight(False)
        if not self._is_drag_over_fav(event):
            return False
        paths = []
        mime = event.mimeData()
        for url in mime.urls():
            local = url.toLocalFile()
            if local and os.path.isdir(local):
                paths.append(local)
        if not paths and mime.hasText():
            for line in mime.text().splitlines():
                line = line.strip()
                if line and os.path.isdir(line):
                    paths.append(line)
        added = False
        for p in paths:
            if self._favs.add(p):
                added = True
        if added:
            self._fav_expanded = True
            self._populate()
            event.acceptProposedAction()
            return True
        return False

    # ── Click / double-click routing ────────────────────────────────

    def _on_tree_click(self, item, col):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        self._select_item(item)
        bus().file_focused.emit(str(path))

    def _on_tree_double_click(self, item, col):
        vtype = self._get_vtype(item)
        path = item.data(0, Qt.ItemDataRole.UserRole)

        if vtype in (VTYPE_FAV_CHILD, VTYPE_REC_CHILD, VTYPE_FS) and path:
            self.directory_selected.emit(path)
            bus().directory_changed.emit(path)
        elif vtype == VTYPE_FAV_HEADER:
            item.setExpanded(not item.isExpanded())
            self._fav_expanded = item.isExpanded()
        elif vtype == VTYPE_REC_HEADER:
            item.setExpanded(not item.isExpanded())
            self._rec_expanded = item.isExpanded()

    def _select_item(self, item):
        self._tree.setCurrentItem(item)
        self._tree.scrollToItem(item)

    # ── Context menu ────────────────────────────────────────────────

    def _tree_menu(self, pos):
        item = self._tree.itemAt(pos)
        if not item:
            return
        vtype = self._get_vtype(item)
        path = item.data(0, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)

        if vtype == VTYPE_FAV_HEADER:
            menu.addAction(tr("sidebar.menu.add_current_fav"),
                           lambda: self._add_current_to_favorites())
        elif vtype == VTYPE_FAV_CHILD and path:
            menu.addAction(tr("sidebar.menu.rename"), lambda p=path: self._fav_rename(p))
            icons_menu = menu.addMenu(tr("sidebar.menu.change_icon"))
            for ic in ICONS:
                icons_menu.addAction(ic,
                    lambda checked, p=path, i=ic: (
                        self._favs.set_icon(p, i), self._populate()))
            menu.addSeparator()
            menu.addAction(tr("sidebar.menu.remove_fav"),
                           lambda p=path: (self._favs.remove(p), self._populate()))
        elif vtype == VTYPE_REC_HEADER:
            menu.addAction(tr("sidebar.menu.clear_recent"),
                           lambda: (self._recents.clear(), self._populate()))
        elif vtype == VTYPE_REC_CHILD and path:
            menu.addAction(tr("sidebar.menu.open"),
                           lambda p=path: self.directory_selected.emit(p))
            menu.addAction(tr("sidebar.menu.add_fav"),
                           lambda p=path: (self._favs.add(p), self._populate()))
            menu.addAction(tr("sidebar.menu.copy_path"),
                           lambda p=path: QApplication.clipboard().setText(p))
            menu.addSeparator()
            menu.addAction(tr("sidebar.menu.remove_recent"),
                           lambda p=path: (self._recents.remove(p), self._populate()))
        elif vtype == VTYPE_FS and path:
            is_dir = os.path.isdir(path)
            if is_dir:
                if self._favs.is_favorite(path):
                    menu.addAction(tr("sidebar.menu.remove_fav"),
                                   lambda p=path: (self._favs.remove(p), self._populate()))
                else:
                    menu.addAction(tr("sidebar.menu.add_fav"),
                                   lambda p=path: (self._favs.add(p), self._populate()))
                menu.addSeparator()
                menu.addAction(tr("sidebar.menu.expand_all"),
                               lambda it=item: self._tree.expandItem(it))
                menu.addAction(tr("sidebar.menu.collapse_all"),
                               lambda it=item: self._tree.collapseItem(it))
                menu.addSeparator()
            menu.addAction(tr("sidebar.menu.reveal_explorer"),
                           lambda p=path, d=is_dir: self._open_path(
                               str(Path(p).parent if not d else p)))
            menu.addAction(tr("sidebar.menu.copy_path"),
                           lambda p=path: QApplication.clipboard().setText(p))

        if menu.actions():
            menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _fav_rename(self, path):
        current = Path(path).name
        for fav in self._favs.list_all():
            if fav["path"] == path:
                current = fav.get("name", current)
                break
        name, ok = QInputDialog.getText(self, tr("sidebar.rename_dialog"), tr("sidebar.rename_label"), text=current)
        if ok and name.strip():
            self._favs.rename(path, name.strip())
            self._populate()

    def _add_current_to_favorites(self):
        item = self._tree.currentItem()
        if item:
            path = item.data(0, Qt.ItemDataRole.UserRole)
            vtype = self._get_vtype(item)
            if vtype == VTYPE_FS and path and self._favs.add(path):
                self._populate()

    # ── Search (debounced, 200ms) ───────────────────────────────────

    def _on_search_text(self, text):
        """Restart debounce timer on every keystroke."""
        self._search_pending = text.lower()
        if self._search_timer:
            self._search_timer.start()

    def _do_search(self):
        """Execute debounced search: preload children, filter, expand matches."""
        text = self._search_pending
        self._clear_search_highlights()
        if text:
            gen = self._controller.next_search_gen()
            roots = [self._library_root] if self._library_root else self.ROOTS
            self._search.setPlaceholderText(tr("sidebar.searching"))
            task = _PreloadTask(roots, max_depth=2)
            task.signals.done.connect(lambda results: self._on_preload_done(text, results, gen))
            QThreadPool.globalInstance().start(task)
        else:
            self._match_count = 0
            for i in range(self._tree.topLevelItemCount()):
                item = self._tree.topLevelItem(i)
                vtype = self._get_vtype(item)
                if vtype in (VTYPE_FAV_HEADER, VTYPE_REC_HEADER):
                    item.setHidden(False)
                    continue
                if vtype == VTYPE_FS:
                    self._filter_item(item, "")
            self._search.setPlaceholderText(tr("sidebar.filter_placeholder"))

    def _on_preload_done(self, text, results, gen):
        """Apply preload results and filter."""
        if not self._controller.is_current_search(gen):
            return
        for parent_path, entries in results:
            self._apply_preloaded_entries(parent_path, entries)
        self._match_count = 0
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            vtype = self._get_vtype(item)
            if vtype in (VTYPE_FAV_HEADER, VTYPE_REC_HEADER):
                item.setHidden(bool(text))
                continue
            if vtype == VTYPE_FS:
                self._filter_item(item, text)
        if text:
            self._search.setPlaceholderText(tr("sidebar.filter_matches", count=self._match_count))
        else:
            self._search.setPlaceholderText(tr("sidebar.filter_placeholder"))

    def _apply_preloaded_entries(self, parent_path, entries):
        """Find the tree item for parent_path and populate children from scan results."""
        parent_item = self._find_item_by_path(parent_path)
        if not parent_item:
            return
        if parent_item.childCount() == 1 and parent_item.child(0).text(0) == "...":
            parent_item.removeChild(parent_item.child(0))
        elif parent_item.childCount() > 0:
            return
        level = _fs_level(parent_item)
        branch_depth = self._depth
        it = parent_item
        while it:
            if self._get_vtype(it) == VTYPE_FS and not it.parent():
                name = Path(it.data(0, Qt.ItemDataRole.UserRole) or "").name
                if name in self._branch_depths:
                    branch_depth = self._branch_depths[name]
                break
            it = it.parent()
        for name, path, is_dir in entries:
            icon = "📁 " if is_dir else "   "
            child = QTreeWidgetItem([f"{icon}{name}"])
            self._set_vtype(child, VTYPE_FS, path)
            parent_item.addChild(child)
            if is_dir and level + 1 < branch_depth:
                QTreeWidgetItem(child, ["..."])
            elif is_dir:
                child.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)

    def _find_item_by_path(self, target_path):
        """Find a tree item by its stored path (BFS)."""
        from collections import deque
        queue = deque()
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            queue.append(root.child(i))
        while queue:
            item = queue.popleft()
            if self._get_vtype(item) == VTYPE_FS and item.data(0, Qt.ItemDataRole.UserRole) == target_path:
                return item
            for i in range(item.childCount()):
                queue.append(item.child(i))
        return None

    def _expand_all_children(self, item):
        if item.childCount() == 1 and item.child(0).text(0) == "...":
            item.removeChild(item.child(0))
            self._load_children(item, 0)
        for i in range(item.childCount()):
            child = item.child(i)
            if self._get_vtype(child) == VTYPE_FS:
                self._expand_all_children(child)

    def _filter_item(self, item, text):
        if not text:
            item.setHidden(False)
            for i in range(item.childCount()):
                self._filter_item(item.child(i), text)
            return False
        visible = text in item.text(0).lower()
        for i in range(item.childCount()):
            if self._filter_item(item.child(i), text):
                visible = True
        item.setHidden(not visible)
        if visible:
            self._match_count += 1
            # Highlight matching items
            if text in item.text(0).lower():
                self._highlight_item(item, direct=True)
            else:
                self._highlight_item(item, direct=False)
            p = item.parent()
            while p:
                p.setHidden(False)
                p = p.parent()
        return visible

    def _highlight_item(self, item, direct: bool):
        """Apply search highlight styling to an item with animation."""
        t = themes.get()
        font = item.font(0)
        if direct:
            # Direct match: accent color + bold + background flash
            item.setForeground(0, QBrush(QColor(t["accent"])))
            font.setBold(True)
            # Flash background briefly
            item.setBackground(0, QBrush(QColor(t["accent"] + "30")))
            # Fade out background after 500ms
            from PySide6.QtCore import QTimer
            QTimer.singleShot(500, lambda: item.setBackground(0, QBrush()))
        else:
            # Ancestor of match: muted accent
            item.setForeground(0, QBrush(QColor(t["muted"])))
            font.setBold(False)
        item.setFont(0, font)

    def _clear_search_highlights(self):
        """Reset all item styles after search is cleared."""
        root = self._tree.invisibleRootItem()
        self._reset_item_style(root)

    def _reset_item_style(self, item):
        """Recursively reset foreground and font for an item and its children."""
        item.setForeground(0, QBrush())
        font = item.font(0)
        font.setBold(False)
        item.setFont(0, font)
        for i in range(item.childCount()):
            self._reset_item_style(item.child(i))

    # ── Keyboard shortcuts ─────────────────────────────────────────

    def eventFilter(self, obj, event):
        if obj is self._tree:
            t = event.type()
            if t == event.Type.DragEnter:
                return self._on_tree_drag_enter(event)
            if t == event.Type.DragMove:
                return self._on_tree_drag_move(event)
            if t == event.Type.DragLeave:
                return self._on_tree_drag_leave(event)
            if t == event.Type.Drop:
                return self._on_tree_drop(event)
        if event.type() == event.Type.KeyPress:
            return self._handle_key(obj, event)
        return super().eventFilter(obj, event)

    def _handle_key(self, widget, event: QKeyEvent) -> bool:
        key = event.key()
        mods = event.modifiers()
        if widget is self._search:
            if key == Qt.Key.Key_Escape and not mods:
                if self._search.text():
                    self._search.clear()
                    self._do_search()
                else:
                    self._tree.setFocus()
                return True
            return False
        if widget is self._tree:
            if mods == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_F:
                self._search.setFocus()
                self._search.selectAll()
                return True
            if mods == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier) and key == Qt.Key.Key_F:
                self._add_current_to_favorites()
                return True
            if key == Qt.Key.Key_Delete:
                item = self._tree.currentItem()
                if item:
                    vtype = self._get_vtype(item)
                    path = item.data(0, Qt.ItemDataRole.UserRole)
                    if vtype == VTYPE_FAV_CHILD and path:
                        self._favs.remove(path)
                        self._populate()
                        return True
                    if vtype == VTYPE_REC_CHILD and path:
                        self._recents.remove(path)
                        self._populate()
                        return True
        return False

    # ── Navigation ──────────────────────────────────────────────────

    def _on_theme_changed(self, _name: str = ""):
        """Refresh sidebar styles when theme changes (in-place, no tree rebuild)."""
        t = themes.get()
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            vtype = self._get_vtype(item)
            if vtype == VTYPE_FAV_HEADER:
                self._bold_item(item, t["favorite"])
            elif vtype == VTYPE_REC_HEADER:
                self._bold_item(item, t["recent"])
        self._apply_status_style()
        self._apply_nav_btn_style()

    def _apply_status_style(self):
        t = themes.get()
        self._status_bar.setStyleSheet(
            f"background: transparent; "
            f"border-top: 1px solid {t['border']};")
        self._status.setStyleSheet(
            f"color: {t['muted']}; font-size: {scaled_pt(11)}px; background: transparent;")

    def _apply_nav_btn_style(self):
        t = themes.get()
        for btn in (self._expand_btn, self._collapse_btn):
            btn.setStyleSheet(
                f"color: {t['body']}; padding: 0; font-size: {scaled_pt(14)}px; font-weight: bold; "
                f"background: transparent; border-radius: {scaled_px(6)}px; "
                f"border: 1px solid {alpha(t['border'], 0.375)};")

    def navigate_to(self, path: str):
        self._library_root = path
        self._favs.set_library_root(path)
        self._recents.set_library_root(path)
        self._populate()
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if self._get_vtype(item) == VTYPE_FS:
                self._on_expand(item)
                break

    @staticmethod
    def _open_path(path: str):
        """Open path in system file manager or default app (cross-platform)."""
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def select_path(self, path: str):
        def _find(itr, target):
            for i in range(itr.childCount()):
                child = itr.child(i)
                if child.data(0, Qt.ItemDataRole.UserRole) == target:
                    self._tree.setCurrentItem(child)
                    self._tree.scrollToItem(child)
                    return True
                if _find(child, target):
                    return True
            return False
        _find(self._tree.invisibleRootItem(), path)

    def title_bar_buttons(self) -> list:
        from AssetsManager.core import themes
        t = themes.get()
        gear = QPushButton("⚙")
        gear.setToolTip(tr("sidebar_settings.title"))
        gear.setFixedSize(scaled_px(20), scaled_px(20))
        gear.setFlat(True)
        gear.setStyleSheet(
            f"color: {t['heading']}; font-size: {scaled_pt(13)}px; font-weight: bold; "
            f"padding: 0; background: transparent; border: none; border-radius: {scaled_px(3)}px;")
        gear.setCursor(Qt.CursorShape.PointingHandCursor)
        gear.clicked.connect(self._show_settings_menu)
        return [gear]

    def _show_settings_menu(self):
        from AssetsManager.dialogs.sidebar_settings_dialog import SidebarSettingsDialog
        dlg = SidebarSettingsDialog(
            parent=self,
            root_paths=[self._library_root] if self._library_root else self.ROOTS,
            show_favs=self._show_favs, show_recs=self._show_recs,
            show_filter=self._show_filter, global_depth=self._depth,
            branch_depths=self._branch_depths,
        )
        if dlg.exec() == dlg.DialogCode.Accepted:
            r = dlg.result()
            self._show_favs = r["show_favs"]
            self._show_recs = r["show_recs"]
            self._show_filter = r["show_filter"]
            self._search.setVisible(self._show_filter)
            self._depth = r["global_depth"]
            self._branch_depths = r["branch_depths"]
            bus().sidebar_depth_changed.emit(self._depth, dict(self._branch_depths))
            from AssetsManager.core.settings import AppSettings
            cfg = {"depth": self._depth, "branch_depths": self._branch_depths}
            AppSettings.instance().set("sidebar_depth_cfg", cfg)
            AppSettings.instance().save()
            self._populate()

    # ── Clone / State ───────────────────────────────────────────────

    def clone(self):
        from copy import deepcopy
        new = SidebarPanel()
        new._state = deepcopy(self._state)
        new._depth = self._depth
        new._branch_depths = dict(self._branch_depths)
        new._show_favs = self._show_favs
        new._show_recs = self._show_recs
        new._show_filter = self._show_filter
        new._fav_expanded = self._fav_expanded
        new._rec_expanded = self._rec_expanded
        if self._library_root:
            new._library_root = self._library_root
            new._favs.set_library_root(self._library_root)
            new._recents.set_library_root(self._library_root)
        return new

    def save_state(self) -> dict:
        return self._state

    def restore_state(self, state: dict):
        self._state = state
