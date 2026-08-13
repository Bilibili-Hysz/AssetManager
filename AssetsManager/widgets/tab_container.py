"""Tab container — QTabWidget wrapping multiple file list panels.

Performance: each tab holds its own FileListPanel (with its own worker thread).
Switching tabs is O(1). Tabs are created lazily. Signal forwarding is
constant-time per event.

Supports external tab bar: when an external QTabBar is provided, the internal
tab bar is hidden, allowing the tab bar to be mounted in the title bar area.
"""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QTabWidget, QPushButton, QMenu,
)
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.panels.file_list import FileListPanel
from AssetsManager.panels.base import PanelContent
from AssetsManager import i18n
tr = i18n.tr


class TabContainer(PanelContent):
    directory_selected = Signal(str)
    file_focused = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.content_layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._tabs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tabs.customContextMenuRequested.connect(self._tab_menu)
        self._tabs.tabBar().setDocumentMode(True)
        self._tabs.tabBar().setExpanding(False)

        self.content_layout.addWidget(self._tabs)
        self._tabs.setCornerWidget(self._new_tab_button(), Qt.Corner.TopRightCorner)

        self._tabs_to_filelists: dict[int, FileListPanel] = {}
        self._extension_bar = None
        self._add_tab()

    def title_bar_extension(self):
        """Return a QTabBar for the dock title bar. Used by dock_factory.

        The bar is created once and reused: dock_factory rebuilds title bars
        on theme/language changes, and swapping a fresh QTabBar every time
        would discard bar state and cause flicker.
        """
        if self._extension_bar is not None:
            return self._extension_bar
        from PySide6.QtWidgets import QTabBar
        bar = QTabBar()
        bar.setDocumentMode(True)
        bar.setExpanding(False)
        bar.setTabsClosable(True)
        bar.setMovable(True)
        bar.tabCloseRequested.connect(self._close_tab)
        self._tabs.tabBar().hide()
        self._tabs.setTabBar(bar)
        self._extension_bar = bar
        return bar

    def _new_tab_button(self):
        btn = QPushButton("+")
        btn.setMaximumWidth(scaled_px(26))
        btn.setMaximumHeight(scaled_px(24))
        btn.setFlat(True)
        btn.clicked.connect(lambda: self._add_tab())
        return btn

    def _add_tab(self, path: str | None = None):
        panel = FileListPanel()
        idx = self._tabs.addTab(panel, tr("tab.new"))
        self._tabs_to_filelists[idx] = panel
        self._tabs.setCurrentIndex(idx)

        panel.folder_entered.connect(lambda p, panel=panel: self._update_panel_tab_title(panel, p))
        panel.file_double_clicked.connect(self.file_double_clicked.emit)
        panel.file_selected.connect(lambda info: self.file_focused.emit(str(info)))
        panel.folder_entered.connect(self.directory_selected.emit)

        if path:
            panel.navigate_to(path, set_root=True)
        self._update_panel_tab_title(panel, panel.current_path)

    def _rebuild_tab_map(self):
        self._tabs_to_filelists = {
            i: panel
            for i in range(self._tabs.count())
            if isinstance((panel := self._tabs.widget(i)), FileListPanel)
        }

    def _close_tab(self, idx):
        if self._tabs.count() <= 1:
            return
        panel = self._tabs_to_filelists.pop(idx, None)
        if panel:
            panel.shutdown()
            panel.deleteLater()
        self._tabs.removeTab(idx)
        self._rebuild_tab_map()

    def _update_panel_tab_title(self, panel: FileListPanel, path: str):
        idx = self._tabs.indexOf(panel)
        if idx >= 0:
            self._update_tab_title(idx, path)

    def _update_tab_title(self, idx: int, path: str):
        name = Path(path).name or path
        if len(name) > 20:
            name = name[:17] + "..."
        self._tabs.setTabText(idx, name)
        self._tabs.setTabToolTip(idx, path)

    def _on_tab_changed(self, idx):
        if idx < 0:
            return
        panel = self._tabs_to_filelists.get(idx)
        if panel:
            self.directory_selected.emit(panel.current_path)

    def _tab_menu(self, pos):
        tab_idx = self._tabs.tabBar().tabAt(pos)
        menu = QMenu(self)
        menu.addAction(tr("tab.new"),
                       lambda: self._add_tab())
        if tab_idx >= 0:
            menu.addAction(tr("tab.close"),
                           lambda: self._close_tab(tab_idx))
            menu.addAction(tr("tab.close_others"),
                           lambda: self._close_others(tab_idx))
            menu.addAction(tr("tab.close_all"),
                           lambda: self._close_all(tab_idx))
        menu.exec(self._tabs.mapToGlobal(pos))

    def _close_others(self, keep_idx):
        for i in range(self._tabs.count() - 1, -1, -1):
            if i != keep_idx:
                self._close_tab(i)

    def _close_all(self, except_idx=None):
        for i in range(self._tabs.count() - 1, -1, -1):
            if i != except_idx:
                self._close_tab(i)
        if self._tabs.count() == 0:
            self._add_tab()

    def current_file_list(self) -> FileListPanel | None:
        idx = self._tabs.currentIndex()
        return self._tabs_to_filelists.get(idx)

    def navigate_to(self, path: str, *, set_root=False):
        fl = self.current_file_list()
        if fl:
            fl.navigate_to(path, set_root=set_root)

    def clone(self):
        new = TabContainer()
        fl = self.current_file_list()
        if fl:
            new._add_tab(fl.current_path)
        return new

    def save_state(self) -> dict:
        paths = []
        for i in range(self._tabs.count()):
            panel = self._tabs_to_filelists.get(i)
            if panel:
                paths.append(panel.current_path)
        return {"tabs": paths, "active": self._tabs.currentIndex()}

    def restore_state(self, state: dict):
        paths = state.get("tabs", [])
        active = state.get("active", 0)
        if not paths:
            return
        # Close all tabs except the last one, always from the end
        # to avoid index shifting issues.
        while self._tabs.count() > 1:
            panel = self._tabs.widget(self._tabs.count() - 1)
            if isinstance(panel, FileListPanel):
                panel.shutdown()
                panel.deleteLater()
            self._tabs.removeTab(self._tabs.count() - 1)
        # Rebuild index mapping
        self._tabs_to_filelists = {}
        if self._tabs.count() > 0:
            w = self._tabs.widget(0)
            if isinstance(w, FileListPanel):
                self._tabs_to_filelists[0] = w
        fl = self.current_file_list()
        if fl and paths:
            fl.navigate_to(paths[0], set_root=True)
        for p in paths[1:]:
            self._add_tab(p)
        if active < self._tabs.count():
            self._tabs.setCurrentIndex(active)

    def shutdown(self) -> None:
        """Stop all child file-list panels (dock_factory close contract).

        dock_factory._close_dock calls ``shutdown()`` on every dock panel;
        the per-tab file-list panels must be stopped so their worker
        threads and timers do not outlive the dock.
        """
        for fl in list(self._tabs_to_filelists.values()):
            fl.shutdown()

    def closeEvent(self, event):
        self.shutdown()
        if event:
            super().closeEvent(event)
