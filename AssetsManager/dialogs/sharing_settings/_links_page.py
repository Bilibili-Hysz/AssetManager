"""Share-links page construction for the sharing settings dialog."""
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QCheckBox, QComboBox, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from AssetsManager.core import themes
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.widgets.stylekit import StyleKit
from AssetsManager import i18n

tr = i18n.tr


class LinksPageMixin:
    """Share-links page: search/filter bar, links table, and bottom bar."""

    # Widgets built by _setup_share_links_tab.
    _links_search: QLineEdit
    _links_filter: QComboBox
    _refresh_links_btn: QPushButton
    _create_link_btn: QPushButton
    _links_table: QTableWidget
    _select_all_chk: QCheckBox
    _batch_delete_btn: QPushButton
    _links_status: QLabel

    # Supplied by the main dialog, TabbedDialog, or SharedUiMixin.
    make_combobox: Any
    make_secondary_btn: Any
    make_primary_btn: Any
    make_muted: Any
    _filter_links: Any
    _open_create_link_dialog: Any
    _load_share_links: Any
    _batch_delete_links: Any
    _on_select_all: Any
    _on_links_selection_changed: Any
    _apply_table_theme: Any
    _get_filtered_shares: Any
    _copy_table_share_link: Any
    _delete_share_link: Any

    def _setup_share_links_tab(self, parent):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(scaled_px(16), scaled_px(16), scaled_px(16), scaled_px(16))
        layout.setSpacing(scaled_px(10))

        # ── Search & Filter Bar ───────────────────────────────
        filter_row = QHBoxLayout()
        self._links_search = QLineEdit()
        self._links_search.setPlaceholderText(tr("sharing.links.search_placeholder"))
        self._links_search.setClearButtonEnabled(True)
        self._links_search.textChanged.connect(self._filter_links)
        filter_row.addWidget(self._links_search, 1)

        self._links_filter = self.make_combobox([
            tr("sharing.links.filter_all"),
            tr("sharing.links.filter_active"),
            tr("sharing.links.filter_expired"),
        ])
        self._links_filter.currentIndexChanged.connect(self._filter_links)
        filter_row.addWidget(self._links_filter)

        self._refresh_links_btn = self.make_secondary_btn(tr("sharemgr.btn.refresh"), self._load_share_links)
        filter_row.addWidget(self._refresh_links_btn)
        self._create_link_btn = self.make_primary_btn(tr("sharelink.btn.create_link"), self._open_create_link_dialog)
        filter_row.addWidget(self._create_link_btn)
        layout.addLayout(filter_row)

        # ── Table ─────────────────────────────────────────────
        self._links_table = QTableWidget()
        self._links_table.setColumnCount(6)
        self._links_table.setHorizontalHeaderLabels([
            tr("sharing.links.col_name"),
            tr("sharing.links.col_path"),
            tr("sharing.links.col_permissions"),
            tr("sharing.links.col_expiry"),
            tr("sharing.links.col_downloads"),
            tr("sharing.links.col_actions"),
        ])
        self._links_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._links_table.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self._links_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._links_table.verticalHeader().setVisible(False)

        header = self._links_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self._links_table.setColumnWidth(5, scaled_px(240))

        self._apply_table_theme()
        layout.addWidget(self._links_table)

        # ── Bottom Bar ────────────────────────────────────────
        bottom_row = QHBoxLayout()
        self._select_all_chk = QCheckBox(tr("sharing.links.select_all"))
        self._select_all_chk.toggled.connect(self._on_select_all)
        bottom_row.addWidget(self._select_all_chk)

        self._batch_delete_btn = self.make_secondary_btn(tr("sharing.links.batch_delete"), self._batch_delete_links)
        self._batch_delete_btn.setEnabled(False)
        bottom_row.addWidget(self._batch_delete_btn)
        bottom_row.addStretch()

        self._links_status = self.make_muted(tr("sharing.links.loading"))
        bottom_row.addWidget(self._links_status)
        layout.addLayout(bottom_row)

        self._links_table.itemSelectionChanged.connect(self._on_links_selection_changed)

    def _populate_links_table(self):
        filtered = self._get_filtered_shares()
        self._links_table.setRowCount(len(filtered))
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)

        for i, share in enumerate(filtered):
            name = share.get("name", share.get("paths", ["—"])[0] if share.get("paths") else "—")
            self._links_table.setItem(i, 0, QTableWidgetItem(str(name)))

            paths = share.get("paths", [])
            path_text = ", ".join(paths) if paths else "—"
            path_item = QTableWidgetItem(path_text)
            path_item.setData(Qt.ItemDataRole.UserRole, share.get("id"))
            self._links_table.setItem(i, 1, path_item)

            has_password = share.get("has_password", False)
            perm_text = tr("sharing.auth_password") if has_password else tr("sharing.auth_none")
            self._links_table.setItem(i, 2, QTableWidgetItem(perm_text))

            expires = share.get("expires_fmt", tr("sharemgr.fallback.never"))
            self._links_table.setItem(i, 3, QTableWidgetItem(expires))

            downloads = share.get("download_count", 0)
            max_dl = share.get("max_downloads")
            dl_text = f"{downloads}/{max_dl}" if max_dl else f"{downloads}/∞"
            self._links_table.setItem(i, 4, QTableWidgetItem(dl_text))

            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(scaled_px(4), scaled_px(2), scaled_px(4), scaled_px(2))
            actions_layout.setSpacing(scaled_px(4))

            copy_btn = QPushButton(tr("sharing.links.btn_copy_link"))
            copy_btn.setFixedHeight(scaled_px(24))
            copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            copy_btn.setStyleSheet(
                f"QPushButton {{ background: {sk.token('accent')}; color: {sk.token('on_accent')}; "
                f"border: none; border-radius: {sk.px(int(sk.prop('border_radius', 'sm')))}px; "
                f"font-size: {sk.pt(sk.font_size('xs'))}px; "
                f"padding: {sk.px(int(sk.prop('spacing', 'xs')))}px {sk.px(int(sk.prop('spacing', 'sm')))}px; }}"
                f"QPushButton:hover {{ background: {alpha(sk.token('accent'), 0.87)}; }}"
                f"QPushButton:pressed {{ background: {alpha(sk.token('accent'), 0.18)}; }}"
                f"QPushButton:focus {{ border: {scaled_px(1)}px solid {sk.token('border_focus', sk.token('accent'))}; }}")
            copy_btn.clicked.connect(lambda checked, idx=i: self._copy_table_share_link(idx))
            actions_layout.addWidget(copy_btn)

            delete_btn = QPushButton(tr("sharing.links.btn_delete"))
            delete_btn.setFixedHeight(scaled_px(24))
            delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            delete_btn.setStyleSheet(
                f"QPushButton {{ background: {sk.token('danger')}; color: {sk.token('on_accent')}; "
                f"border: none; border-radius: {sk.px(int(sk.prop('border_radius', 'sm')))}px; "
                f"font-size: {sk.pt(sk.font_size('xs'))}px; "
                f"padding: {sk.px(int(sk.prop('spacing', 'xs')))}px {sk.px(int(sk.prop('spacing', 'sm')))}px; }}"
                f"QPushButton:hover {{ background: {alpha(sk.token('danger'), 0.87)}; }}"
                f"QPushButton:pressed {{ background: {alpha(sk.token('danger'), 0.18)}; }}"
                f"QPushButton:focus {{ border: {scaled_px(1)}px solid {sk.token('border_focus', sk.token('danger'))}; }}")
            delete_btn.clicked.connect(lambda checked, idx=i: self._delete_share_link(idx))
            actions_layout.addWidget(delete_btn)

            actions_layout.addStretch()
            self._links_table.setCellWidget(i, 5, actions_widget)
