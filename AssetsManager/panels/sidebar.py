"""Sidebar panel — virtual favorites/recent headers integrated into tree.

Features:
- Favorites and Recent Folders as top-level virtual tree items
- Real filesystem roots below virtual sections
- Lazy-loading tree with expandable directories
- Search/filter bar (applies to filesystem items only)
- Right-click context menu on all item types
- Keyboard: Ctrl+F, Ctrl+Shift+F, Escape
"""
import logging
import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer, QSize
from PySide6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QLineEdit, QPushButton, QHBoxLayout,
    QMenu, QInputDialog, QApplication, QAbstractItemView,
    QLabel, QWidget, QSizePolicy,
)
from PySide6.QtGui import QKeyEvent, QBrush, QColor, QFont

from AssetsManager.panels.base import StandardPanel
from AssetsManager import i18n
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.core import themes, icons
from AssetsManager.core.workers import BoundedPool, CancellationToken
from AssetsManager.widgets.stylekit import StyleKit
from AssetsManager.dialogs.sidebar_favorites import SidebarFavorites
from AssetsManager.dialogs.sidebar_recent import SidebarRecentFolders
from AssetsManager.panels._sidebar_parts import (
    _fs_level,
    _PreloadTask,
    VTYPE_FS,
)

tr = i18n.tr

_log = logging.getLogger(__name__)


def _cancel_task(task):
    """Cooperatively cancel *task* if it supports cancellation.

    Defensive like ``_drain_worker_pool``: test doubles or legacy pseudo-tasks
    without a ``cancel`` method must not break shutdown.  Real tasks all derive
    from ``CancellableRunnable``; the shared pool's ``cancel_all`` remains the
    guaranteed fallback.
    """
    cancel = getattr(task, "cancel", None)
    if callable(cancel):
        cancel()

ICONS = ["star", "folder", "folder_open", "tag", "home", "file", "image",
         "video", "archive", "cube", "clock", "heart", "monitor", "save",
         "grid", "search"]

VTYPE_FAV_HEADER = "fav_header"
VTYPE_REC_HEADER = "rec_header"
VTYPE_FAV_CHILD = "fav_child"
VTYPE_REC_CHILD = "rec_child"
_ICON_ROLE = Qt.ItemDataRole.UserRole + 2

# User-collection virtual group (migration v38). Collection rows keep their
# integer id / kind string outside the path slot (UserRole) so click handlers
# can distinguish them from navigable filesystem paths.
VTYPE_COLLECTION_HEADER = "collection_header"
VTYPE_COLLECTION = "collection"
VTYPE_COLLECTION_MEMBER = "collection_member"
_COLLECTION_ID_ROLE = Qt.ItemDataRole.UserRole + 3
_COLLECTION_KIND_ROLE = Qt.ItemDataRole.UserRole + 4

# Max directories loaded per event-loop tick during "expand all", so a large
# tree reveals progressively instead of blocking the UI thread on the first
# click (each directory expands via a synchronous scandir).
_EXPAND_ALL_BATCH = 8

_FAVORITE_ICON_MAP = {
    "\u2b50": "star",
    "\U0001f4c1": "folder",
    "\U0001f4c2": "folder",
    "\U0001f516": "tag",
    "\U0001f4be": "save",
    "\U0001f5a5": "monitor",
    "\U0001f3a8": "image",
    "\U0001f4cc": "tag",
    "\U0001f3e0": "home",
    "\U0001f525": "star",
    "\U0001f4f7": "image",
    "\u2699": "settings",
    "\u2699\ufe0f": "settings",
    "\U0001f5d1": "trash",
    "\U0001f5d1\ufe0f": "trash",
    "\U0001f50d": "search",
    "\U0001f4c4": "file",
    "\U0001f4dd": "file",
    "\U0001f4a1": "star",
    "\U0001f3b5": "play",
    "\U0001f4f9": "video",
    "\U0001f5c2": "folder_open",
    "\U0001f5c2\ufe0f": "folder_open",
    "\U0001f4e5": "download",
    "\U0001f4e4": "upload",
    "\u2764": "heart",
    "\u2139": "info",
    "\u2139\ufe0f": "info",
}


class SidebarPanel(StandardPanel):
    directory_selected = Signal(str)

    ROOTS = [str(Path.home()), str(Path.home() / "Documents"),
             str(Path.home() / "Downloads"), str(Path.home() / "Pictures")]
    panel_state_key = "sidebar_depth_cfg"

    def __init__(self, parent=None, *, _shared_sources: dict | None = None, _populate: bool = True):
        super().__init__(parent)
        # ``clone`` passes shared favorites/recent stores so the second panel
        # reuses the already-loaded data sources instead of re-reading JSON.
        shared = _shared_sources or {}
        self._favs = shared.get("favs") or SidebarFavorites()
        self._recents = shared.get("recents") or SidebarRecentFolders()
        library_root = shared.get("library_root")
        self._library_root: str | None = (
            library_root if isinstance(library_root, str) and library_root else None
        )
        self._scoped_services = shared.get("services")
        # Lazy-loaded user collections (manual reference sets; smart rows
        # display-only). Invalidated on CollectionChanged domain events.
        self._collections_loaded_ids: set[int] = set()
        self._search_pending = ""
        self._search_timer = None
        self._match_count = 0
        self._preload_task: _PreloadTask | None = None
        self._preload_pool = BoundedPool(2)
        self._preload_token = CancellationToken()
        from AssetsManager.controllers.sidebar_controller import SidebarController
        self._controller = SidebarController()

        # ── Search bar + toolbar ─────────────────────────────────

        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("sidebar.filter_placeholder"))
        self._search.textChanged.connect(self._on_search_text)
        self._search.setClearButtonEnabled(True)
        self._search.installEventFilter(self)
        self.setFocusProxy(self._search)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._do_search)

        # ── Tree (stretch=1) ────────────────────────────────────

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(scaled_px(18))
        self._tree.setAnimated(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setAlternatingRowColors(False)
        self._tree.setIconSize(QSize(scaled_px(18), scaled_px(18)))
        self._tree.setAllColumnsShowFocus(False)
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
        self._tree_generation = 0

        bar = QHBoxLayout()
        bar.setContentsMargins(scaled_px(6), scaled_px(4), scaled_px(6), scaled_px(4))
        bar.setSpacing(scaled_px(2))
        self._search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._search.setMinimumWidth(0)
        bar.addWidget(self._search, 1)
        self._expand_btn = QPushButton()
        self._expand_btn.setIcon(icons.icon("arrow_down", color="icon_secondary", size=scaled_px(16)))
        self._expand_btn.setToolTip(tr("sidebar.expand_all"))
        self._expand_btn.setAccessibleName(tr("sidebar.expand_all"))
        self._expand_btn.setIconSize(QSize(scaled_px(16), scaled_px(16)))
        self._expand_btn.clicked.connect(self._expand_all)
        self._collapse_btn = QPushButton()
        self._collapse_btn.setIcon(icons.icon("arrow_up", color="icon_secondary", size=scaled_px(16)))
        self._collapse_btn.setToolTip(tr("sidebar.collapse_all"))
        self._collapse_btn.setAccessibleName(tr("sidebar.collapse_all"))
        self._collapse_btn.setIconSize(QSize(scaled_px(16), scaled_px(16)))
        self._collapse_btn.clicked.connect(self._tree.collapseAll)
        hit = scaled_px(themes.metrics("hit_area"))
        for btn in (self._expand_btn, self._collapse_btn):
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.setFixedSize(hit, hit)
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            bar.addWidget(btn, 0)
        self._toolbar_layout = bar
        self._apply_nav_btn_style()
        self._apply_tree_style()
        # StandardPanel slot contract: search/expand bar → toolbar, tree → body.
        toolbar = QWidget()
        toolbar.setLayout(bar)
        self.set_toolbar(toolbar)
        self.set_body(self._tree, 1)

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
        self.set_footer(self._status_bar)

        self._depth = 2
        self._branch_depths: dict[str, int] = {}
        self._show_favs = True
        self._show_recs = True
        self._show_filter = True
        self._restore_depth_cfg()
        self._search.setVisible(self._show_filter)
        self._fav_expanded: bool | None = None
        self._rec_expanded: bool | None = None
        self._state = {"depth": 2, "expanded": set()}
        self._expand_frontier: list[QTreeWidgetItem] = []
        if _populate:
            self._populate()
        self._connect_bus(bus().refresh_requested, self._populate)
        # Collection catalog changes publish domain events from worker
        # threads; the queued Qt bridge keeps the repopulate on the GUI
        # thread (same pattern as the info panel's Asset*Changed hooks).
        from AssetsManager.domain.events import CollectionChanged

        self._connect_domain_event(
            CollectionChanged, self._on_domain_collections_changed
        )
        self._connect_bus(bus().theme_changed, self._on_theme_changed)
        self._connect_bus(bus().language_changed, self._on_language_changed)
        self._connect_bus(bus().ui_scale_changed, self._on_theme_changed)

    def _restore_depth_cfg(self):
        try:
            state = self.panel_state().read()
            if state is not None:
                self.restore_state(state, populate=False)
        except Exception as exc:
            _log.warning("Failed to restore sidebar depth config: %s", exc)

    def set_scoped_services(self, services, *, runtime=None) -> None:
        """Bind the library bundle resolved by MainWindow.

        ``runtime`` is part of the uniform ``ScopedServicesConsumer``
        signature; the sidebar binds no runtime projection router, so the
        kwarg is accepted and ignored.
        """
        self.prepare_library_switch()
        library_root = services.session.root_str
        if not isinstance(library_root, str):
            return
        self._scoped_services = services
        self._library_root = library_root
        self._favs.set_library_root(library_root, services.session.data_dir)
        self._recents.set_library_root(library_root, services.session.data_dir)
        self._populate()

    def prepare_library_switch(self) -> None:
        """Invalidate pending searches before replacing the library bundle."""
        self._tree_generation += 1
        self._controller.next_search_gen()
        # Single-flight: supersede the in-flight preload before draining.
        _cancel_task(self._preload_task)
        self._preload_task = None
        self._preload_token.cancel()
        self._preload_token = CancellationToken()
        self._preload_pool.cancel_all()
        self._preload_pool.drain(3_000)
        if self._search_timer is not None:
            self._search_timer.stop()
        self._expand_frontier = []
        self._tree_update_restore_pending = False
        self._clear_pending_timers()

    def shutdown(self) -> None:
        self.prepare_library_switch()
        super().shutdown()

    @staticmethod
    def _set_vtype(item: QTreeWidgetItem, vtype: str, path: str = ""):
        item.setData(0, Qt.ItemDataRole.UserRole, path)
        item.setData(0, Qt.ItemDataRole.UserRole + 1, vtype)

    @staticmethod
    def _favorite_icon_name(value: str | None) -> str:
        """Map legacy emoji preferences to stable semantic SVG names."""
        legacy = str(value or "star")
        return _FAVORITE_ICON_MAP.get(legacy, icons.normalize(legacy, fallback="star"))

    @staticmethod
    def _set_item_icon(item: QTreeWidgetItem, icon_name: str, color: str | None = None):
        """Store an icon semantic name so theme refreshes stay in-place."""
        normalized = icons.normalize(icon_name, fallback="file")
        item.setData(0, _ICON_ROLE, normalized)
        tint = color or "icon_secondary"
        item.setIcon(0, icons.icon(normalized, color=tint, size=scaled_px(18)))

    def _refresh_item_icons(self, item: QTreeWidgetItem | None = None):
        """Retint existing tree icons without rebuilding or losing expansion."""
        root = item or self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            child = root.child(i)
            if child is None:
                continue
            icon_name = child.data(0, _ICON_ROLE)
            if icon_name:
                vtype = self._get_vtype(child)
                if vtype == VTYPE_FAV_HEADER:
                    tint = "favorite"
                elif vtype == VTYPE_REC_HEADER:
                    tint = "recent"
                elif vtype == VTYPE_COLLECTION_HEADER:
                    tint = "accent"
                else:
                    tint = "icon_secondary"
                child.setIcon(0, icons.icon(str(icon_name), color=tint, size=scaled_px(18)))
            self._refresh_item_icons(child)

    @staticmethod
    def _get_vtype(item: QTreeWidgetItem | None) -> str:
        if item is None:
            return ""
        return item.data(0, Qt.ItemDataRole.UserRole + 1) or VTYPE_FS

    @staticmethod
    def _bold_item(item: QTreeWidgetItem, color: str = ""):
        font = item.font(0)
        font.setBold(True)
        font.setWeight(QFont.Weight.Bold)
        item.setFont(0, font)
        if color:
            item.setForeground(0, QBrush(QColor(color)))

    def _begin_tree_update_batch(self):
        """Suppress intermediate tree paints during bulk item changes."""
        self._tree.setUpdatesEnabled(False)
        if getattr(self, "_tree_update_restore_pending", False):
            return
        self._tree_update_restore_pending = True
        self._schedule_once(0, self._finish_tree_update_batch)

    def _finish_tree_update_batch(self):
        self._tree_update_restore_pending = False
        if not self._tree:
            return
        self._tree.setUpdatesEnabled(True)
        self._tree.viewport().update()
        self._tree.update()

    def _populate(self):
        self._begin_tree_update_batch()
        self._tree_generation += 1
        self._tree.clear()

        # ── Virtual: Favorites header ──────────────────────────
        if self._show_favs:
            favs = self._favs.list_all()
            fav_count = len(favs)
            fav_header = QTreeWidgetItem([tr("sidebar.favorites", count=fav_count)])
            self._set_vtype(fav_header, VTYPE_FAV_HEADER)
            self._set_item_icon(fav_header, "star", "favorite")
            self._bold_item(fav_header, themes.get()["favorite"])
            self._tree.addTopLevelItem(fav_header)

            for fav in favs:
                name = fav.get("name", Path(fav["path"]).name)
                child = QTreeWidgetItem([name])
                self._set_vtype(child, VTYPE_FAV_CHILD, fav["path"])
                self._set_item_icon(child, self._favorite_icon_name(fav.get("icon")))
                child.setToolTip(0, fav["path"])
                fav_header.addChild(child)

        # ── Virtual: Recent Folders header ──────────────────────
        if self._show_recs:
            recs = self._recents.list_all()
            rec_count = len(recs)
            rec_header = QTreeWidgetItem([tr("sidebar.recent_folders", count=rec_count)])
            self._set_vtype(rec_header, VTYPE_REC_HEADER)
            self._set_item_icon(rec_header, "clock", "recent")
            self._bold_item(rec_header, themes.get()["recent"])
            self._tree.addTopLevelItem(rec_header)

            for r in recs:
                path = r["path"]
                name = Path(path).name
                time_lbl = r.get("_time_label", "")
                child = QTreeWidgetItem([f"{name}  · {time_lbl}"])
                self._set_vtype(child, VTYPE_REC_CHILD, path)
                self._set_item_icon(child, "folder")
                child.setToolTip(0, f"{path}\n{time_lbl}")
                rec_header.addChild(child)

        # ── Virtual: User collections header ────────────────────
        collections = self._load_collections()
        if collections is not None:
            collection_header = QTreeWidgetItem(
                [tr("sidebar.collections", count=len(collections))]
            )
            self._set_vtype(collection_header, VTYPE_COLLECTION_HEADER)
            self._set_item_icon(collection_header, "grid", "accent")
            self._bold_item(collection_header, themes.get().get("accent", themes.get()["recent"]))
            self._tree.addTopLevelItem(collection_header)

            for collection in collections:
                if collection["kind"] == "smart":
                    # Smart collections are query views; the desktop shows
                    # them display-only and skips evaluation entirely.
                    label = tr(
                        "sidebar.smart_collection_label",
                        name=collection["name"],
                    )
                else:
                    label = tr(
                        "sidebar.collection_label",
                        name=collection["name"],
                        count=collection["member_count"],
                    )
                child = QTreeWidgetItem([label])
                self._set_vtype(child, VTYPE_COLLECTION)
                child.setData(0, _COLLECTION_ID_ROLE, int(collection["id"]))
                child.setData(0, _COLLECTION_KIND_ROLE, str(collection["kind"]))
                self._set_item_icon(child, "grid")
                child.setToolTip(0, collection["name"])
                collection_header.addChild(child)
                # Manual collections start collapsed with their members
                # loaded on first click (members reference absolute paths
                # that are only navigable, never moved).
                if collection["kind"] == "manual":
                    QTreeWidgetItem(child, ["..."])

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
                item = QTreeWidgetItem([entry.name])
                self._set_vtype(item, VTYPE_FS, entry.path)
                self._set_item_icon(item, "folder" if entry.is_dir() else "file")
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
            if item is None:
                continue
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
        has_content = False
        for i in range(total):
            item = self._tree.topLevelItem(i)
            if item is not None and (
                self._get_vtype(item) == VTYPE_FS or item.childCount() > 0
            ):
                has_content = True
                break
        if not has_content:
            self._status.setText(tr("sidebar.status_empty"))
            # StandardPanel state overlay replaces the body (tree) in place;
            # the title/hint i18n keys match the previous hand-drawn state.
            self.show_state(
                "directory",
                title=tr("sidebar.status_empty"),
                subtitle=tr("sidebar.empty_hint"),
            )
        else:
            self.clear_state()
            self._status.setText(tr("sidebar.status_root_folders", count=total))


    # ── Lazy-load filesystem children ───────────────────────────────

    def _on_expand(self, item):
        if self._get_vtype(item) != VTYPE_FS:
            return
        placeholder = item.child(0) if item.childCount() == 1 else None
        if placeholder is not None and placeholder.text(0) == "...":
            item.removeChild(placeholder)
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
        self._begin_tree_update_batch()
        for entry in entries:
            if entry.name.startswith("."):
                continue
            child = QTreeWidgetItem([entry.name])
            self._set_vtype(child, VTYPE_FS, entry.path)
            self._set_item_icon(child, "folder" if entry.is_dir() else "file")
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
        if on:
            item = self._fav_header_item()
            if not item or self._drag_highlight_item is item:
                return
            self._drag_highlight_item = item
            t = themes.get()
            try:
                item.setBackground(0, QBrush(QColor(t["accent"])))
            except RuntimeError:
                # Tree was rebuilt between drag events; item is gone.
                self._drag_highlight_item = None
            return
        item = self._drag_highlight_item
        if item is None:
            return
        self._drag_highlight_item = None
        try:
            item.setBackground(0, QBrush(Qt.BrushStyle.NoBrush))
        except RuntimeError:
            # Item was removed by a tree rebuild while the drag was active.
            pass

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
        vtype = self._get_vtype(item)
        if vtype == VTYPE_COLLECTION:
            self._toggle_collection_members(item)
            return
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        self._select_item(item)
        bus().file_focused.emit(str(path))

    def _on_tree_double_click(self, item, col):
        vtype = self._get_vtype(item)
        path = item.data(0, Qt.ItemDataRole.UserRole)

        if vtype in (VTYPE_FAV_CHILD, VTYPE_REC_CHILD, VTYPE_FS) and path:
            # Keep the recent-folders list fresh; file_list.navigate_to emits
            # bus().directory_changed afterwards (window wires
            # directory_selected -> navigate_to).
            self._recents.record_visit(path)
            self.directory_selected.emit(path)
        elif vtype == VTYPE_COLLECTION_MEMBER and path:
            # Collection members navigate like filesystem paths but are
            # never recorded as recent-folder visits: the collection is a
            # reference set, not a visited folder.
            self.directory_selected.emit(path)
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
        elif vtype == VTYPE_COLLECTION_HEADER:
            menu.addAction(tr("sidebar.menu.new_collection"),
                           self._collection_new)
        elif vtype == VTYPE_COLLECTION:
            menu.addAction(tr("sidebar.menu.rename"),
                           lambda: self._collection_rename(item))
            menu.addAction(tr("sidebar.menu.delete_collection"),
                           lambda: self._collection_delete(item))
        elif vtype == VTYPE_FAV_CHILD and path:
            menu.addAction(tr("sidebar.menu.rename"), lambda p=path: self._fav_rename(p))
            icons_menu = menu.addMenu(tr("sidebar.menu.change_icon"))
            for ic in ICONS:
                action = icons_menu.addAction(ic.replace("_", " ").title(),
                    lambda checked=False, p=path, i=ic: (
                        self._favs.set_icon(p, i), self._populate()))
                action.setIcon(icons.icon(
                    self._favorite_icon_name(ic),
                    color="icon_secondary",
                    size=scaled_px(16),
                ))
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

    # ── User collections (manual reference sets + smart display rows) ──

    def _collection_service(self):
        """Return the bound CollectionService, or None when unscoped."""
        service = getattr(self._scoped_services, "collection_service", None)
        if service is None or not self._library_root:
            return None
        return service

    def _load_collections(self) -> list[dict] | None:
        """Return the collection rows, or None when collections are unbound.

        Failures degrade to "no collections" instead of breaking the whole
        tree population; the sidebar is a navigation aid, not the source of
        truth.
        """
        service = self._collection_service()
        if service is None:
            return None
        try:
            return list(service.list_collections(self._library_root))
        except Exception as exc:
            _log.warning("Sidebar collection listing failed: %s", exc)
            return []

    def _toggle_collection_members(self, item) -> None:
        """First click lazily loads manual members; later clicks toggle."""
        if self._get_vtype(item) != VTYPE_COLLECTION:
            return
        collection_id = item.data(0, _COLLECTION_ID_ROLE)
        kind = item.data(0, _COLLECTION_KIND_ROLE)
        if kind != "manual" or collection_id is None:
            # Smart rows stay display-only on desktop (no evaluation).
            item.setExpanded(not item.isExpanded())
            return
        if collection_id not in self._collections_loaded_ids:
            self._collections_loaded_ids.add(collection_id)
            item.takeChildren()
            for member in self._collection_member_paths(int(collection_id)):
                child = QTreeWidgetItem([Path(member).name])
                self._set_vtype(child, VTYPE_COLLECTION_MEMBER, member)
                self._set_item_icon(child, "file")
                child.setToolTip(0, member)
                item.addChild(child)
        item.setExpanded(not item.isExpanded())

    def _collection_member_paths(self, collection_id: int) -> list[str]:
        """Return existing member paths for one manual collection.

        Members whose files no longer exist are skipped here (the read
        tolerates them with an ``exists`` flag); nothing is ever pruned
        from the reference set as a side effect of listing.
        """
        service = self._collection_service()
        if service is None:
            return []
        try:
            members = service.get_members(self._library_root, collection_id)
        except Exception as exc:
            _log.warning("Sidebar collection members failed: %s", exc)
            return []
        return [
            member["file_path"] for member in members
            if member.get("exists", True)
        ]

    def _collection_new(self):
        if self._collection_service() is None:
            return
        name, ok = QInputDialog.getText(
            self, tr("sidebar.dialog.new_collection"),
            tr("sidebar.dialog.collection_name_label"),
        )
        if not (ok and name.strip()):
            return
        try:
            self._collection_service().create(self._library_root, name.strip())
        except Exception as exc:
            _log.warning("Sidebar collection create failed: %s", exc)
        # CollectionChanged repopulates the tree.

    def _collection_rename(self, item):
        service = self._collection_service()
        if service is None:
            return
        collection_id = item.data(0, _COLLECTION_ID_ROLE)
        if collection_id is None:
            return
        current = item.toolTip(0) or item.text(0)
        name, ok = QInputDialog.getText(
            self, tr("sidebar.dialog.rename_collection"),
            tr("sidebar.dialog.collection_name_label"), text=current,
        )
        if not (ok and name.strip()):
            return
        try:
            service.rename(self._library_root, int(collection_id), name.strip())
        except Exception as exc:
            _log.warning("Sidebar collection rename failed: %s", exc)

    def _collection_delete(self, item):
        service = self._collection_service()
        if service is None:
            return
        collection_id = item.data(0, _COLLECTION_ID_ROLE)
        if collection_id is None:
            return
        try:
            service.delete(self._library_root, int(collection_id))
        except Exception as exc:
            _log.warning("Sidebar collection delete failed: %s", exc)

    def _on_domain_collections_changed(self, event) -> None:
        """Repopulate when the session's collection catalog changes."""
        scoped = self._scoped_services
        if scoped is None or event.session_token != scoped.session.event_token:
            return
        self._collections_loaded_ids.clear()
        self._populate()

    # ── Search (debounced, 200ms) ───────────────────────────────────

    def _on_search_text(self, text):
        """Restart debounce timer on every keystroke."""
        self._search_pending = text.lower()
        if self._search_timer:
            self._search_timer.start()

    def _do_search(self):
        """Execute debounced search: preload children, filter, expand matches."""
        self._begin_tree_update_batch()
        text = self._search_pending
        self._clear_search_highlights()
        # Bump the search generation even when clearing so in-flight preload
        # results from a previous query are invalidated.
        gen = self._controller.next_search_gen()
        # Single-flight: cancel the in-flight walk before starting the new one.
        _cancel_task(self._preload_task)
        self._preload_token.cancel()
        self._preload_token = CancellationToken()
        self._preload_task = None
        if text:
            roots = [self._library_root] if self._library_root else self.ROOTS
            self._search.setPlaceholderText(tr("sidebar.searching"))
            self._search.setToolTip(tr("sidebar.search_scope_hint"))
            # Search should honor the user's depth configuration instead of a
            # fixed depth-2 scan, bounded to keep the preload cheap.
            configured_depth = max(
                [self._depth, *self._branch_depths.values()], default=2)
            max_depth = max(2, min(configured_depth, 5))
            task = _PreloadTask(
                roots, text, gen, self._library_root,
                max_depth=max_depth, cancel_token=self._preload_token,
            )
            # Bound QObject slot: queued to the UI thread when the worker emits.
            task.signals.done.connect(self._on_preload_done)
            self._preload_task = task
            self._preload_pool.start(task)
        else:
            self._match_count = 0
            self._search.setToolTip("")
            for i in range(self._tree.topLevelItemCount()):
                item = self._tree.topLevelItem(i)
                if item is None:
                    continue
                vtype = self._get_vtype(item)
                if vtype in (VTYPE_FAV_HEADER, VTYPE_REC_HEADER):
                    item.setHidden(False)
                    continue
                if vtype == VTYPE_FS:
                    self._filter_item(item, "")
            self._search.setPlaceholderText(tr("sidebar.filter_placeholder"))

    def _on_preload_done(self, text, results, gen, root=None):
        """Apply preload results and filter."""
        self._begin_tree_update_batch()
        if root != self._library_root or not self._controller.is_current_search(gen):
            return
        # Build the path→item index once for the whole batch; the previous
        # per-result BFS made the fill O(results × tree size).
        index = self._build_path_index()
        for parent_path, entries in results:
            self._apply_preloaded_entries(parent_path, entries, index)
        self._match_count = 0
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item is None:
                continue
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

    def _apply_preloaded_entries(self, parent_path, entries, index=None):
        """Find the tree item for parent_path and populate children from scan results."""
        if index is not None:
            parent_item = index.get(parent_path)
        else:
            parent_item = self._find_item_by_path(parent_path)
        if not parent_item:
            return
        self._begin_tree_update_batch()
        placeholder = parent_item.child(0) if parent_item.childCount() == 1 else None
        if placeholder is not None and placeholder.text(0) == "...":
            parent_item.removeChild(placeholder)
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
            child = QTreeWidgetItem([name])
            self._set_vtype(child, VTYPE_FS, path)
            self._set_item_icon(child, "folder" if is_dir else "file")
            parent_item.addChild(child)
            if is_dir and level + 1 < branch_depth:
                QTreeWidgetItem(child, ["..."])
            elif is_dir:
                child.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)

    def _build_path_index(self) -> dict[str, QTreeWidgetItem]:
        """Build one path→item map for a search batch (single BFS, O(N))."""
        from collections import deque
        index: dict[str, QTreeWidgetItem] = {}
        queue = deque()
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            child = root.child(i)
            if child is not None:
                queue.append(child)
        while queue:
            item = queue.popleft()
            if self._get_vtype(item) == VTYPE_FS:
                path = item.data(0, Qt.ItemDataRole.UserRole)
                if path:
                    index[path] = item
            for i in range(item.childCount()):
                child = item.child(i)
                if child is not None:
                    queue.append(child)
        return index

    def _find_item_by_path(self, target_path):
        """Find a tree item by its stored path (BFS)."""
        from collections import deque
        queue = deque()
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            child = root.child(i)
            if child is not None:
                queue.append(child)
        while queue:
            item = queue.popleft()
            if self._get_vtype(item) == VTYPE_FS and item.data(0, Qt.ItemDataRole.UserRole) == target_path:
                return item
            for i in range(item.childCount()):
                child = item.child(i)
                if child is not None:
                    queue.append(child)
        return None

    def _expand_all(self):
        """Progressive expand-all: reveal filesystem items in small batches.

        Replaces ``QTreeWidget.expandAll`` (which expanded every level
        synchronously via the itemExpanded→_load_children chain and froze the UI
        on the first click for large trees). Each tick expands at most
        ``_EXPAND_ALL_BATCH`` directories, yielding to the event loop so the
        tree paints progress instead of blocking.
        """
        frontier: list[QTreeWidgetItem] = []
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item is None:
                continue
            vtype = self._get_vtype(item)
            if vtype == VTYPE_FS:
                frontier.append(item)
            elif vtype in (VTYPE_FAV_HEADER, VTYPE_REC_HEADER):
                # Virtual headers are already populated — expand in place and
                # persist the state so a later refresh keeps them expanded.
                item.setExpanded(True)
                if vtype == VTYPE_FAV_HEADER:
                    self._fav_expanded = True
                else:
                    self._rec_expanded = True
        self._expand_frontier = frontier
        self._process_expand_frontier()

    def _process_expand_frontier(self):
        next_frontier: list[QTreeWidgetItem] = []
        budget = _EXPAND_ALL_BATCH
        while self._expand_frontier and budget > 0:
            item = self._expand_frontier.pop(0)
            if item is None:
                continue
            self._tree.expandItem(item)  # triggers _on_expand → lazy load
            for i in range(item.childCount()):
                child = item.child(i)
                if child is None or self._get_vtype(child) != VTYPE_FS:
                    continue
                if child.childCount() == 1 and child.child(0).text(0) == "...":
                    next_frontier.append(child)
            budget -= 1
        if self._expand_frontier:
            # Still more directories in the current level — continue next tick.
            self._schedule_once(0, self._process_expand_frontier)
        elif next_frontier:
            self._expand_frontier = next_frontier
            self._schedule_once(0, self._process_expand_frontier)

    def _filter_item(self, item, text):
        if not text:
            item.setHidden(False)
            for i in range(item.childCount()):
                child = item.child(i)
                if child is not None:
                    self._filter_item(child, text)
            return False
        visible = text in item.text(0).lower()
        for i in range(item.childCount()):
            child = item.child(i)
            if child is not None and self._filter_item(child, text):
                visible = True
        item.setHidden(not visible)
        if visible:
            # Count only direct name hits; ancestor branches kept visible for
            # context must not inflate the "N matches" feedback.
            if text in item.text(0).lower():
                self._match_count += 1
                # Highlight matching items
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
            if not StyleKit.reduce_motion():
                # Flash background briefly (respect the global reduced-motion
                # preference; the text/weight change remains as feedback).
                flash = QColor(t["accent"])
                flash.setAlphaF(0.19)
                item.setBackground(0, QBrush(flash))
                generation = self._tree_generation
                self._schedule_once(500, lambda: self._clear_highlight_background(item, generation))
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

    def _clear_highlight_background(self, item, generation: int):
        if generation != self._tree_generation:
            return
        try:
            item.setBackground(0, QBrush())
            for i in range(item.childCount()):
                child = item.child(i)
                if child is not None:
                    self._reset_item_style(child)
        except RuntimeError:
            # The tree was rebuilt before the fade-out timer fired; the C++
            # item is gone. Nothing left to reset.
            pass

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

    def _on_language_changed(self, _code: str = ""):
        self._search.setPlaceholderText(tr("sidebar.filter_placeholder"))
        self._expand_btn.setToolTip(tr("sidebar.expand_all"))
        self._expand_btn.setAccessibleName(tr("sidebar.expand_all"))
        self._collapse_btn.setToolTip(tr("sidebar.collapse_all"))
        self._collapse_btn.setAccessibleName(tr("sidebar.collapse_all"))
        self._populate()

    def _apply_section_headers_style(self):
        """Format Favorites, Recent Folders, and Collections headers with crisp hierarchy."""
        t = themes.get()
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item is None:
                continue
            vtype = self._get_vtype(item)
            if vtype == VTYPE_FAV_HEADER:
                self._bold_item(item, t["favorite"])
            elif vtype == VTYPE_REC_HEADER:
                self._bold_item(item, t["recent"])
            elif vtype == VTYPE_COLLECTION_HEADER:
                self._bold_item(item, t.get("accent", t["recent"]))

    def _apply_tree_style(self):
        """Apply compact, theme-aware tree styling without rebuilding items."""
        self._tree.setIconSize(QSize(scaled_px(18), scaled_px(18)))
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        self._tree.setStyleSheet(sk.tree_css())
        self._apply_section_headers_style()

    def _on_theme_changed(self, _name: str = ""):
        """Refresh sidebar styles when theme changes (in-place, no tree rebuild)."""
        self._apply_section_headers_style()
        self._apply_tree_style()
        self._refresh_item_icons()
        self._apply_status_style()
        self._refresh_empty_state()
        self._apply_nav_btn_style()
        if hasattr(self, "_toolbar_layout"):
            self._toolbar_layout.setContentsMargins(
                scaled_px(6), scaled_px(4), scaled_px(6), scaled_px(4)
            )
            self._toolbar_layout.setSpacing(scaled_px(2))

    def _apply_status_style(self):
        font_size = scaled_pt(int(themes.prop("font_size", "sm")))
        self._status_bar.setStyleSheet(
            f"background: transparent; "
            f"border-top: {scaled_px(1)}px solid {themes.color('border_subtle')};")
        self._status.setStyleSheet(
            f"color: {themes.color('muted')}; font-size: {font_size}px; background: transparent;")

    def _refresh_empty_state(self):
        """Re-render the shared empty-state overlay after theme/language changes.

        The overlay is owned by ``StandardPanel`` (EmptyStateWidget) and
        rebuilds itself on theme/lang/scale events; this only refreshes the
        sidebar-specific title/hint strings while the state is showing.
        """
        if self._state_overlay is None or self._state_overlay.isHidden():
            return
        self.show_state(
            "directory",
            title=tr("sidebar.status_empty"),
            subtitle=tr("sidebar.empty_hint"),
        )

    def _apply_nav_btn_style(self):
        t = themes.get()
        hover = alpha(
            t["hover_overlay"], themes.prop("opacity", "hover"))
        selected = alpha(t["selected_overlay"], 0.28)
        radius = scaled_px(int(themes.prop("border_radius", "sm")))
        font_size = scaled_pt(int(themes.prop("font_size", "lg")))
        hit = scaled_px(themes.metrics("hit_area"))
        for btn, icon_name in (
            (self._expand_btn, "arrow_down"),
            (self._collapse_btn, "arrow_up"),
        ):
            btn.setFixedSize(hit, hit)
            btn.setIcon(icons.icon(icon_name, color="icon_secondary", size=scaled_px(16)))
            btn.setIconSize(QSize(scaled_px(16), scaled_px(16)))
            btn.setStyleSheet(
                f"QPushButton {{ color: {themes.color('body')}; padding: 0; "
                f"font-size: {font_size}px; font-weight: bold; "
                f"background: transparent; border-radius: {radius}px; "
                f"border: {scaled_px(1)}px solid {themes.color('border_subtle')}; }}"
                f"QPushButton:hover {{ background: {hover}; }}"
                f"QPushButton:pressed {{ background: {selected}; }}")

    def navigate_to(self, path: str):
        self._library_root = path
        self._favs.set_library_root(path)
        self._recents.set_library_root(path)
        self._populate()
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item is not None and self._get_vtype(item) == VTYPE_FS:
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
        gear = QPushButton()
        gear.setIcon(icons.icon("settings", color="icon_primary", size=scaled_px(16)))
        gear.setIconSize(QSize(scaled_px(16), scaled_px(16)))
        gear.setToolTip(tr("sidebar_settings.title"))
        gear.setAccessibleName(tr("sidebar_settings.title"))
        gear.setFixedSize(scaled_px(20), scaled_px(20))
        gear.setFlat(True)
        gear.setProperty("semanticIcon", "settings")
        themes.set_button_variant(gear, "ghost")
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
            self.persist_panel_state()
            self._populate()

    # ── Clone / State ───────────────────────────────────────────────

    def clone(self):
        # Share the loaded favorites/recent stores and scoped services, and
        # defer the first tree population until the copied preferences are in
        # place — the clone never re-reads store JSON nor scans the default
        # ROOTS before adopting the source panel's library root.
        new = SidebarPanel(
            _shared_sources={
                "favs": self._favs,
                "recents": self._recents,
                "services": self._scoped_services,
                "library_root": self._library_root,
            },
            _populate=False,
        )
        new.restore_state(self.save_state())
        return new

    def save_state(self) -> dict:
        """Snapshot the sidebar layout preferences for dock save/restore."""
        return {
            "depth": self._depth,
            "branch_depths": dict(self._branch_depths),
            "show_favs": self._show_favs,
            "show_recs": self._show_recs,
            "show_filter": self._show_filter,
            "fav_expanded": self._fav_expanded,
            "rec_expanded": self._rec_expanded,
        }

    def restore_state(self, state: dict, *, populate: bool = True):
        """Apply a saved layout snapshot and rebuild the tree to match."""
        if not isinstance(state, dict):
            return
        self._state = state
        depth = state.get("depth")
        if isinstance(depth, int) and not isinstance(depth, bool):
            self._depth = max(1, min(5, depth))
        branches = state.get("branch_depths")
        if isinstance(branches, dict):
            self._branch_depths = {
                str(name): int(value)
                for name, value in branches.items()
                if (
                    isinstance(name, str)
                    and isinstance(value, int)
                    and not isinstance(value, bool)
                    and 1 <= value <= 5
                )
            }
        for key in ("show_favs", "show_recs", "show_filter"):
            value = state.get(key)
            if isinstance(value, bool):
                setattr(self, f"_{key}", value)
        for key in ("fav_expanded", "rec_expanded"):
            value = state.get(key)
            if isinstance(value, bool) or value is None:
                setattr(self, f"_{key}", value)
        self._search.setVisible(self._show_filter)
        if populate:
            self._populate()
        bus().sidebar_depth_changed.emit(self._depth, dict(self._branch_depths))
