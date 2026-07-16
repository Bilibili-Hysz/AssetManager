"""Tag tree panel — tag browser with file listing.

Performance: lazy-loads from TagStore (JSON). Tree is virtual (items created
on demand). Filtering is O(n) on tag count (typically <1000). Tag store is
sharded per library — no cross-library tag mixing.
"""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QLineEdit, QPushButton, QHBoxLayout,
    QMenu, QInputDialog, QMessageBox,
)
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.panels.base import PanelContent
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.controllers.tag_tree_controller import TagTreeController
from AssetsManager import i18n
tr = i18n.tr


class TagTreePanel(PanelContent):
    directory_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._library_root = ""
        self._current_path = ""
        self._store = None
        self._controller: TagTreeController | None = None
        self._active_tag_filter: str | None = None
        self._scoped_services = None

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(12)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._ctx_menu)
        self._tree.itemClicked.connect(self._on_click)
        self.content_layout.addWidget(self._tree)

        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("tagtree.filter_placeholder"))
        self._search.textChanged.connect(self._on_search)
        self._search.setClearButtonEnabled(True)
        bar = QHBoxLayout()
        bar.addWidget(self._search)
        add_btn = QPushButton(tr("tagtree.new_tag"))
        add_btn.clicked.connect(self._add_tag)
        add_btn.setMaximumWidth(scaled_px(50))
        bar.addWidget(add_btn)
        self.content_layout.addLayout(bar)

        # Subscribe to domain events through a Qt bridge for UI-safe delivery.
        from AssetsManager.domain.events import TagsChanged, LibraryOpened
        self._connect_domain_event(LibraryOpened, self._on_library_changed)
        self._connect_domain_event(TagsChanged, self._on_domain_tags_changed)
        self._connect_bus(bus().directory_changed, self._on_directory_changed)
        self._connect_bus(bus().theme_changed, lambda _: self._populate())
        self._connect_bus(bus().language_changed, lambda _: self._populate())
        self._connect_bus(bus().ui_scale_changed, lambda _: self._populate())
        self._populate()

    def _resolve_tag_store(self, root: str):
        if self._scoped_services is not None:
            return self._scoped_services.session.tag_store, self._scoped_services.tag_service
        raise RuntimeError("TagTreePanel scoped services not injected for root: " + root)

    def _populate(self):
        if not self._controller:
            return
        self._tree.clear()
        tags_with_files = self._controller.get_tag_with_files()
        if not tags_with_files:
            item = QTreeWidgetItem([tr("tagtree.no_tags")])
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._tree.addTopLevelItem(item)
            return

        if self._active_tag_filter:
            show_all = QTreeWidgetItem([tr("tagtree.show_all")])
            show_all.setData(0, Qt.ItemDataRole.UserRole, "__clear_filter__")
            show_all.setForeground(0, Qt.GlobalColor.gray)
            self._tree.addTopLevelItem(show_all)

        for entry in tags_with_files:
            tag = entry["tag"]
            count = entry["count"]
            files = entry["files"]
            item = QTreeWidgetItem([f"🏷 {tag}  ({count})"])
            item.setData(0, Qt.ItemDataRole.UserRole, tag)
            self._tree.addTopLevelItem(item)
            for f in files:
                name = Path(f).name
                child = QTreeWidgetItem([f"  {name}"])
                child.setData(0, Qt.ItemDataRole.UserRole, f)
                child.setToolTip(0, f)
                item.addChild(child)

    def _on_click(self, item, col):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        if data == "__clear_filter__":
            self._active_tag_filter = None
            self._populate()
            bus().refresh_requested.emit()
            return
        if item.parent() is None:
            self._active_tag_filter = data
            bus().directory_changed.emit(self._library_root)
            self._populate()
        else:
            self.directory_selected.emit(data)
            bus().directory_changed.emit(data)

    def _ctx_menu(self, pos):
        item = self._tree.itemAt(pos)
        if not item:
            menu = QMenu(self)
            menu.addAction(tr("tagtree.menu.new"), self._add_tag)
            menu.exec(self._tree.viewport().mapToGlobal(pos))
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data == "__clear_filter__":
            return
        menu = QMenu(self)
        if item.parent() is None:
            menu.addAction(tr("tagtree.menu.rename"),
                           lambda t=data: self._rename_tag(t))
            menu.addAction(tr("tagtree.menu.delete"),
                           lambda t=data: self._delete_tag(t))
        else:
            tag = item.parent().data(0, Qt.ItemDataRole.UserRole)
            if tag:
                menu.addAction(tr("tagtree.menu.remove"),
                               lambda f=data: self._remove_tag(f, tag))
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _add_tag(self):
        tag, ok = QInputDialog.getText(self, tr("tagtree.dialog.new_tag"), tr("tagtree.dialog.tag_label"))
        if ok and tag.strip() and self._controller:
            self._controller.add_tag(tag.strip())
            self._populate()

    def _rename_tag(self, old_tag):
        new_tag, ok = QInputDialog.getText(self, tr("tagtree.dialog.rename"), tr("tagtree.dialog.rename_label"), text=old_tag)
        if ok and new_tag.strip() and new_tag.strip().lower() != old_tag.lower() and self._controller:
            self._controller.rename_tag(old_tag, new_tag.strip())
            self._populate()

    def _delete_tag(self, tag):
        files = self._controller.get_files_for_tag(tag) if self._controller else []
        reply = QMessageBox.question(
            self, tr("tagtree.dialog.delete"),
            tr("tagtree.dialog.delete_msg", tag=tag, count=len(files)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        if self._controller:
            self._controller.delete_tag(tag)
            self._populate()

    def _remove_tag(self, filepath, tag):
        if self._controller:
            self._controller.remove_tag_from_file(filepath, tag)
            self._populate()

    def _on_search(self, text):
        search = text.lower()
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item is None or not item.data(0, Qt.ItemDataRole.UserRole):
                continue
            match = not search or search in item.text(0).lower()
            item.setHidden(not match)

    def _on_domain_tags_changed(self, event):
        """Handle TagsChanged from EventBus (application layer)."""
        self._populate()

    def _on_library_changed(self, event):
        root = str(Path(event.library_root).resolve())
        if root == self._library_root:
            return
        old_root = self._library_root
        self._library_root = root
        self._current_path = root
        scoped = self._scoped_services
        if scoped is not None and scoped.session.root_str == root:
            self._store = scoped.session.tag_store
            self._controller = TagTreeController(root, tag_svc=scoped.tag_service)
        else:
            self._store = None
            self._controller = None
        if self._active_tag_filter and old_root != root:
            self._active_tag_filter = None
        self._populate()

    def set_scoped_services(self, services):
        """Bind library-scoped services resolved by MainWindow."""
        old_root = self._library_root
        self._scoped_services = services
        self._library_root = services.session.root_str
        self._current_path = services.session.root_str
        self._store = services.session.tag_store
        self._controller = TagTreeController(self._library_root, tag_svc=services.tag_service)
        if self._active_tag_filter and old_root != self._library_root:
            self._active_tag_filter = None
        self._populate()

    def _on_directory_changed(self, path):
        self._current_path = str(Path(path).resolve())

    def _ensure_store(self):
        if self._store is None and self._library_root:
            self._store, tag_service = self._resolve_tag_store(self._library_root)
            self._controller = TagTreeController(self._library_root, tag_svc=tag_service)
        self._populate()

    def set_library_root(self, path: str):
        from AssetsManager.domain.events import LibraryOpened
        self._on_library_changed(LibraryOpened(library_root=path))

    def get_tag_filter(self) -> str | None:
        return self._active_tag_filter

    def clone(self):
        new = TagTreePanel()
        new.set_library_root(self._library_root)
        return new
