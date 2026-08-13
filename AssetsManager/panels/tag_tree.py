"""Tag tree panel — tag browser with file listing.

Performance: lazy-loads from TagStore (JSON). Tree is virtual (items created
on demand). Filtering is O(n) on tag count (typically <1000). Tag store is
sharded per library — no cross-library tag mixing.
"""
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer, QSize
from PySide6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QLineEdit, QPushButton, QHBoxLayout,
    QMenu, QInputDialog, QMessageBox,
)
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.core.color_utils import alpha
from AssetsManager.core import themes, icons
from AssetsManager.panels.base import PanelContent
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.controllers.tag_tree_controller import TagTreeController
from AssetsManager.application.runtime_events import ProjectionDomain
from AssetsManager.panels._event_bridge import RuntimeEventSubscription
from AssetsManager.domain.events import TagCatalogChanged
from AssetsManager import i18n
tr = i18n.tr
_ICON_ROLE = Qt.ItemDataRole.UserRole + 1


class TagTreePanel(PanelContent):
    directory_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._library_root = ""
        self._controller: TagTreeController | None = None
        self._active_tag_filter: str | None = None
        self._scoped_services = None
        self._tags_port = None
        self._runtime = None
        self._runtime_subscription = None
        self._binding_generation = 0


        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(scaled_px(16))
        self._tree.setUniformRowHeights(True)
        self._tree.setAlternatingRowColors(False)
        self._tree.setIconSize(QSize(scaled_px(18), scaled_px(18)))
        self._tree.setAllColumnsShowFocus(False)
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
        add_btn.setIcon(icons.icon("tag", color="icon_secondary", size=scaled_px(16)))
        add_btn.setIconSize(QSize(scaled_px(16), scaled_px(16)))
        add_btn.setAccessibleName(tr("tagtree.new_tag"))
        add_btn.clicked.connect(self._add_tag)
        add_btn.setMaximumWidth(scaled_px(72))
        bar.addWidget(add_btn)
        self._add_btn = add_btn
        self._apply_tree_style()
        self.content_layout.addLayout(bar)

        self._connect_bus(bus().theme_changed, self._on_visual_theme_changed)
        self._connect_bus(bus().language_changed, self._on_language_changed)
        self._connect_bus(bus().ui_scale_changed, self._on_visual_theme_changed)
        self._populate()

    def _apply_tree_style(self):
        """Apply the compact tree presentation shared by the desktop panels."""
        t = themes.get()
        self._tree.setIconSize(QSize(scaled_px(18), scaled_px(18)))
        self._tree.setStyleSheet(
            f"QTreeWidget {{"
            f"  background: transparent; color: {t['body']}; border: none; outline: none; "
            f"  font-size: {scaled_pt(11)}px; "
            f"}}"
            f"QTreeWidget::item {{"
            f"  padding: {scaled_px(4)}px {scaled_px(6)}px; "
            f"  border: none; border-radius: {scaled_px(5)}px; "
            f"}}"
            f"QTreeWidget::item:hover {{"
            f"  background: {alpha(t['accent'], 0.12)}; "
            f"}}"
            f"QTreeWidget::item:selected {{"
            f"  background: {alpha(t['accent'], 0.28)}; color: {t['heading']}; "
            f"}}"
            f"QTreeWidget::item:disabled {{ color: {t['muted']}; }}")
        self._add_btn.setIcon(icons.icon("tag", color="icon_secondary", size=scaled_px(16)))
        self._add_btn.setIconSize(QSize(scaled_px(16), scaled_px(16)))

    @staticmethod
    def _set_item_icon(item: QTreeWidgetItem, icon_name: str, color: str | None = None):
        normalized = icons.normalize(icon_name, fallback="file")
        item.setData(0, _ICON_ROLE, normalized)
        item.setIcon(0, icons.icon(
            normalized,
            color=color or "icon_secondary",
            size=scaled_px(18),
        ))

    def _refresh_item_icons(self):
        root = self._tree.invisibleRootItem()
        stack = [root]
        while stack:
            parent = stack.pop()
            for i in range(parent.childCount()):
                item = parent.child(i)
                if item is None:
                    continue
                icon_name = item.data(0, _ICON_ROLE)
                if icon_name:
                    item.setIcon(0, icons.icon(
                        str(icon_name), color="icon_secondary", size=scaled_px(18)
                    ))
                stack.append(item)

    def _on_visual_theme_changed(self, _value=None):
        """Retint the existing tree; theme/scale changes must not refetch tags."""
        self._apply_tree_style()
        self._refresh_item_icons()

    def _on_language_changed(self, _value=None):
        self._search.setPlaceholderText(tr("tagtree.filter_placeholder"))
        self._add_btn.setText(tr("tagtree.new_tag"))
        self._add_btn.setAccessibleName(tr("tagtree.new_tag"))
        self._populate()

    def _begin_tree_update_batch(self):
        self._tree.setUpdatesEnabled(False)
        if getattr(self, "_tree_update_restore_pending", False):
            return
        self._tree_update_restore_pending = True
        QTimer.singleShot(0, self._finish_tree_update_batch)

    def _finish_tree_update_batch(self):
        self._tree_update_restore_pending = False
        self._tree.setUpdatesEnabled(True)
        self._tree.viewport().update()
        self._tree.update()

    def _populate(self):
        if not self._controller:
            return
        self._begin_tree_update_batch()
        self._tree.clear()
        tags_with_files = self._controller.get_tag_with_files()
        if not tags_with_files:
            item = QTreeWidgetItem([tr("tagtree.no_tags")])
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._set_item_icon(item, "tag", "icon_muted")
            self._tree.addTopLevelItem(item)
            return

        if self._active_tag_filter:
            show_all = QTreeWidgetItem([tr("tagtree.show_all")])
            show_all.setData(0, Qt.ItemDataRole.UserRole, "__clear_filter__")
            self._set_item_icon(show_all, "arrow_left")
            show_all.setForeground(0, Qt.GlobalColor.gray)
            self._tree.addTopLevelItem(show_all)

        for entry in tags_with_files:
            tag = entry["tag"]
            count = entry["count"]
            files = entry["files"]
            item = QTreeWidgetItem([f"{tag}  ({count})"])
            item.setData(0, Qt.ItemDataRole.UserRole, tag)
            icon_name = icons.normalize(str(entry.get("icon") or ""), fallback="tag")
            self._set_item_icon(item, icon_name)
            self._tree.addTopLevelItem(item)
            for f in files:
                name = Path(f).name
                child = QTreeWidgetItem([name])
                child.setData(0, Qt.ItemDataRole.UserRole, f)
                self._set_item_icon(child, "file")
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
        self._begin_tree_update_batch()
        search = text.lower()
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item is None or not item.data(0, Qt.ItemDataRole.UserRole):
                continue
            match = not search or search in item.text(0).lower()
            item.setHidden(not match)

    def _on_domain_tags_changed(self, event: TagCatalogChanged):
        """Handle a legacy session-scoped tag catalog update."""
        scoped = self._scoped_services
        if scoped is None or event.session_token != scoped.session.event_token:
            return
        self._populate()

    def _close_runtime_subscription(self) -> None:
        subscription = self._runtime_subscription
        self._runtime_subscription = None
        if subscription is not None:
            subscription.close()

    def _on_runtime_invalidation(self, generation, runtime, invalidation) -> None:
        if generation != self._binding_generation or runtime is not self._runtime:
            return
        if invalidation.epoch != runtime.epoch:
            return
        scoped = self._scoped_services
        if scoped is None or runtime.session.event_token != scoped.session.event_token:
            return
        if ProjectionDomain.TAGS not in invalidation.domains:
            return
        self._populate()

    def set_runtime(self, runtime) -> None:
        """Bind the immutable service snapshot and runtime projection router."""
        self.set_scoped_services(runtime.services_snapshot, runtime=runtime)

    def set_scoped_services(self, services, *, runtime=None):
        """Bind library-scoped services and an optional runtime projection router."""
        self._close_runtime_subscription()
        self._binding_generation += 1
        binding_generation = self._binding_generation
        old_root = self._library_root
        self._runtime = runtime
        self._scoped_services = services
        self._library_root = services.session.root_str
        self._tags_port = services.tag_service
        self._controller = TagTreeController(self._library_root, tag_svc=self._tags_port)
        if self._active_tag_filter and old_root != self._library_root:
            self._active_tag_filter = None
        if runtime is not None:
            self._runtime_subscription = RuntimeEventSubscription(
                runtime,
                lambda invalidation: self._on_runtime_invalidation(
                    binding_generation, runtime, invalidation,
                ),
                self,
            )
        self._populate()

    def prepare_library_switch(self) -> None:
        """Drop service-bound state before the old session closes."""
        self._binding_generation += 1
        self._close_runtime_subscription()
        self._runtime = None
        self._controller = None
        self._scoped_services = None
        self._tags_port = None
        self._active_tag_filter = None
        self._tree.clear()

    def shutdown(self) -> None:
        self.prepare_library_switch()
        super().shutdown()

    def set_library_root(self, path: str):
        """Set a legacy standalone root, reusing a matching scoped service."""
        root = str(Path(path).resolve())
        if root == self._library_root:
            return
        self._library_root = root
        scoped = self._scoped_services
        if (
            scoped is not None
            and not scoped.session.is_closed
            and scoped.session.root_str == root
        ):
            self._controller = TagTreeController(root, tag_svc=self._tags_port)
        else:
            self._controller = None
        self._active_tag_filter = None
        self._populate()

    def get_tag_filter(self) -> str | None:
        return self._active_tag_filter

    def clone(self):
        new = TagTreePanel()
        new.set_library_root(self._library_root)
        return new
