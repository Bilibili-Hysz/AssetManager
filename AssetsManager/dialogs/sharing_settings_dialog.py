"""Share System dialog — unified sharing control with tabbed interface.

Inherits from TabbedDialog for consistent styling and reusable components.

Tab 1: Overview — Server status, quick share, recent activity, tunnel
Tab 2: Share Links — Table of share links with search/filter/actions
Tab 3: Users — Admin info, invite codes, online users, guest defaults
Tab 4: Settings — Network, Security, Branding, Advanced
"""
import logging
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QRunnable, QThreadPool
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QFrame, QGridLayout,
    QFileDialog, QWidget, QApplication,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QCheckBox, QMessageBox,
)
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.core.settings import AppSettings
from AssetsManager.dialogs.tabbed_dialog import TabbedDialog
from AssetsManager.dialogs._share_api import ShareApiTask
from AssetsManager.widgets.toast import Toast
from AssetsManager.widgets.collapsible_panel import CollapsiblePanel
from AssetsManager import i18n

tr = i18n.tr
_log = logging.getLogger(__name__)


def _t():
    return themes.get()


class SharingSettingsDialog(TabbedDialog):
    """Unified Share System dialog with 4-tab interface.

    Inherits from TabbedDialog for consistent styling and reusable components.
    """

    settings_changed = Signal()
    _data_changed = Signal()

    def __init__(self, parent=None, server_status: dict | None = None, server=None):
        self._settings = AppSettings.instance()
        self._host = parent
        self._server_status = server_status or {}
        self._server = server
        self._shares = []
        self._invite_codes = []
        self._online_users = []
        self._activity_items = []

        super().__init__(parent, title=tr("sharing.dialog_title"), min_size=(700, 700))

        self._data_changed.connect(self._refresh_all_tabs)

        self._update_status()
        self._load_settings()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(2000)
        self._status_timer.timeout.connect(self._poll_server_status)
        if self._server and self._server.is_running():
            self._status_timer.start()
            self._load_share_links()
            self._load_activity()
            self._load_online_users()
            self._load_invite_codes()

    def _setup_tabs(self):
        """Setup 4 tabs: Overview, Share Links, Users, Settings."""
        # Tab 1: Overview
        overview_tab = QWidget()
        self._setup_overview_tab(overview_tab)
        self._add_tab(overview_tab, tr("sharing.tab_overview"), scrollable=True)

        # Tab 2: Share Links
        links_tab = QWidget()
        self._setup_share_links_tab(links_tab)
        self._add_tab(links_tab, tr("sharing.tab_share_links"), scrollable=True)

        # Tab 3: Users
        users_tab = QWidget()
        self._setup_users_tab(users_tab)
        self._add_tab(users_tab, tr("sharing.tab_users"), scrollable=True)

        # Tab 4: Settings
        settings_tab = QWidget()
        self._setup_settings_tab(settings_tab)
        self._add_tab(settings_tab, tr("sharing.tab_settings"), scrollable=True)

    def _refresh_all_tabs(self):
        """Refresh all tabs with current server data."""
        if not self._server or not self._server.is_running():
            self._clear_runtime_data()
            return
        self._load_share_links()
        self._load_activity()
        self._load_online_users()
        self._load_invite_codes()

    def _clear_runtime_data(self):
        """Clear server-backed panes when sharing is stopped or unavailable."""
        self._shares = []
        self._invite_codes = []
        self._online_users = []
        self._activity_items = []
        if hasattr(self, "_links_table"):
            self._links_table.setRowCount(0)
        if hasattr(self, "_codes_table"):
            self._codes_table.setRowCount(0)
        if hasattr(self, "_online_table"):
            self._online_table.setRowCount(0)
        if hasattr(self, "_links_status"):
            self._links_status.setText(tr("sharemgr.error.server_unavailable"))
        if hasattr(self, "_codes_status"):
            self._codes_status.setText(tr("sharing.users.no_codes"))
        if hasattr(self, "_online_status"):
            self._online_status.setText(tr("sharing.users.no_online"))
        if hasattr(self, "_activity_list"):
            self._activity_list.setText(tr("sharing.overview.no_activity"))

    def _on_theme_changed(self, _name):
        super()._on_theme_changed(_name)
        t = _t()
        self._status_label.setStyleSheet(f"font-weight: bold; font-size: {scaled_pt(14)}px; color: {t['heading']};")
        self._url_label.setStyleSheet(f"font-size: {scaled_pt(13)}px; color: {t['accent']};")
        if hasattr(self, '_share_url_label') and self._share_url_label:
            self._share_url_label.setStyleSheet(
                f"font-size: {scaled_pt(13)}px; color: {t['accent']}; "
                f"padding: 10px; background: {t['panel']}; "
                f"border: 1px solid {t['border']}; border-radius: {scaled_px(6)}px;")
        if hasattr(self, '_qr_label'):
            self._qr_label.setStyleSheet(f"background: {t['input_bg']}; border-radius: {scaled_px(10)}px; padding: 8px;")
        if hasattr(self, '_tunnel_url_label'):
            self._tunnel_url_label.setStyleSheet(
                f"font-size: {scaled_pt(13)}px; color: {t['accent']}; "
                f"padding: 8px; background: {t['panel']}; "
                f"border: 1px solid {t['border']}; border-radius: {scaled_px(6)}px;")
        self._apply_table_theme()

    def _apply_table_theme(self):
        t = _t()
        table_style = (
            f"QTableWidget {{ background: {t['panel']}; color: {t['body']}; "
            f"border: 1px solid {t['border']}; border-radius: {scaled_px(4)}px; }}"
            f"QTableWidget::item {{ padding: {scaled_px(4)}px; }}"
            f"QTableWidget::item:selected {{ background: {t['accent']}; }}"
            f"QHeaderView::section {{ background: {t['header']}; color: {t['heading']}; "
            f"padding: {scaled_px(4)}px; border: none; border-right: 1px solid {t['border']}; }}"
        )
        if hasattr(self, '_links_table'):
            self._links_table.setStyleSheet(table_style)
        if hasattr(self, '_codes_table'):
            self._codes_table.setStyleSheet(table_style)
        if hasattr(self, '_online_table'):
            self._online_table.setStyleSheet(table_style)

    # ══════════════════════════════════════════════════════════
    # Tab 1: Overview
    # ══════════════════════════════════════════════════════════

    def _make_card(self, title: str, icon: str = "") -> tuple[QFrame, QVBoxLayout]:
        """Create a styled dashboard card with title and return (frame, content_layout)."""
        t = _t()
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {t['panel']}; border: 1px solid {t['border']}; "
            f"border-radius: {scaled_px(10)}px; }}")

        outer = QVBoxLayout(frame)
        outer.setContentsMargins(scaled_px(16), scaled_px(14), scaled_px(16), scaled_px(14))
        outer.setSpacing(scaled_px(10))

        header = QLabel(f"{icon}  {title}" if icon else title)
        header.setStyleSheet(
            f"font-weight: bold; font-size: {scaled_pt(13)}px; color: {t['heading']}; "
            f"background: transparent; border: none;")
        outer.addWidget(header)

        content = QVBoxLayout()
        content.setSpacing(scaled_px(8))
        outer.addLayout(content)

        return frame, content

    def _setup_overview_tab(self, parent):
        t = _t()
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(scaled_px(16), scaled_px(16), scaled_px(16), scaled_px(16))
        layout.setSpacing(scaled_px(12))

        grid = QGridLayout()
        grid.setSpacing(scaled_px(12))

        # ── Card 1: Server Status (row 0, col 0) ─────────────
        status_card, status_cl = self._make_card(tr("sharing.card_server_status"), "🖥️")
        self._status_frame = status_card

        status_row = QHBoxLayout()
        self._status_icon = QLabel("🔴")
        self._status_icon.setFixedWidth(scaled_px(24))
        status_row.addWidget(self._status_icon)
        self._status_label = QLabel(tr("sharing.status_off"))
        self._status_label.setStyleSheet(
            f"font-weight: bold; font-size: {scaled_pt(14)}px; color: {t['heading']};")
        status_row.addWidget(self._status_label)
        status_row.addStretch()
        self._toggle_btn = self.make_primary_btn(tr("sharing.btn_start_sharing"), self._on_toggle_server)
        self._toggle_btn.setFixedWidth(scaled_px(120))
        status_row.addWidget(self._toggle_btn)
        status_cl.addLayout(status_row)

        self._url_row = QHBoxLayout()
        self._url_label = QLabel("")
        self._url_label.setStyleSheet(f"font-size: {scaled_pt(13)}px; color: {t['accent']};")
        self._url_row.addWidget(self._url_label)
        self._url_row.addStretch()
        self._copy_btn = self.make_secondary_btn(tr("sharing.btn_copy_link"), self._copy_link)
        self._copy_btn.setFixedWidth(scaled_px(90))
        self._copy_btn.setVisible(False)
        self._url_row.addWidget(self._copy_btn)
        status_cl.addLayout(self._url_row)

        info_grid = QHBoxLayout()
        info_grid.setSpacing(scaled_px(20))
        self._ip_info, self._ip_info_value = self._make_info_pair(tr("sharing.overview.ip_address"), "—")
        self._port_info, self._port_info_value = self._make_info_pair(tr("sharing.overview.port"), "—")
        info_grid.addLayout(self._ip_info)
        info_grid.addLayout(self._port_info)
        info_grid.addStretch()
        status_cl.addLayout(info_grid)

        grid.addWidget(status_card, 0, 0)

        # ── Card 2: Online Users (row 0, col 1) ──────────────
        online_card, online_cl = self._make_card(tr("sharing.card_online_users"), "👥")

        self._online_info, self._online_info_value = self._make_info_pair(tr("sharing.overview.online_users"), "0")
        self._traffic_info, self._traffic_info_value = self._make_info_pair(tr("sharing.overview.traffic"), "0 B")
        stats_row = QHBoxLayout()
        stats_row.setSpacing(scaled_px(20))
        stats_row.addLayout(self._online_info)
        stats_row.addLayout(self._traffic_info)
        stats_row.addStretch()
        online_cl.addLayout(stats_row)

        grid.addWidget(online_card, 0, 1)

        # ── Card 3: Traffic Stats (row 1, col 0) ─────────────
        traffic_card, traffic_cl = self._make_card(tr("sharing.card_traffic_stats"), "📊")

        self._share_section_content = QVBoxLayout()
        self._share_section_content.setSpacing(scaled_px(8))

        self._share_url_label = QLabel("")
        self._share_url_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._share_url_label.setStyleSheet(
            f"font-size: {scaled_pt(13)}px; color: {t['accent']}; "
            f"padding: 10px; background: {t['panel']}; "
            f"border: 1px solid {t['border']}; border-radius: {scaled_px(6)}px;")
        self._share_url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._share_url_label.setVisible(False)
        self._share_section_content.addWidget(self._share_url_label)

        share_btn_row = QHBoxLayout()
        self._share_copy_btn = self.make_primary_btn(tr("sharing.btn_copy_link"), self._copy_overview_link)
        self._share_copy_btn.setVisible(False)
        share_btn_row.addWidget(self._share_copy_btn)
        self._share_open_btn = self.make_secondary_btn(tr("sharing.btn_open_in_browser"), self._open_share_link)
        self._share_open_btn.setVisible(False)
        share_btn_row.addWidget(self._share_open_btn)
        share_btn_row.addStretch()
        self._share_section_content.addLayout(share_btn_row)

        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setFixedSize(scaled_px(200), scaled_px(200))
        self._qr_label.setStyleSheet(
            f"background: {t['input_bg']}; border-radius: {scaled_px(10)}px; padding: 8px;")
        self._qr_label.setVisible(False)
        self._share_section_content.addWidget(self._qr_label, 0, Qt.AlignmentFlag.AlignCenter)

        self._qr_copy_btn = self.make_secondary_btn(tr("sharing.btn_copy_qr"), self._copy_qr)
        self._qr_copy_btn.setVisible(False)
        self._share_section_content.addWidget(self._qr_copy_btn, 0, Qt.AlignmentFlag.AlignCenter)
        self._qr_pixmap = None

        traffic_cl.addLayout(self._share_section_content)
        grid.addWidget(traffic_card, 1, 0)

        # ── Card 4: Quick Share (row 1, col 1) ───────────────
        quick_card, quick_cl = self._make_card(tr("sharing.card_quick_share"), "⚡")

        self._quick_share_btn = self.make_primary_btn(tr("sharing.overview.quick_share"), self._on_quick_share)
        self._quick_share_btn.setFixedHeight(scaled_px(44))
        self._quick_share_btn.setStyleSheet(
            f"QPushButton {{ background: {t['accent']}; color: {t['on_accent']}; border: none; "
            f"border-radius: {scaled_px(8)}px; padding: 10px 24px; "
            f"font-size: {scaled_pt(14)}px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {t['accent']}dd; }}")
        quick_cl.addWidget(self._quick_share_btn)
        quick_hint = self.make_muted(tr("sharing.overview.quick_share_hint"))
        quick_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        quick_cl.addWidget(quick_hint)

        grid.addWidget(quick_card, 1, 1)

        # ── Card 5: Recent Activity (row 2, full width) ──────
        activity_card, activity_cl = self._make_card(tr("sharing.card_recent_activity"), "📋")

        self._activity_list = QLabel(tr("sharing.overview.no_activity"))
        self._activity_list.setWordWrap(True)
        self._activity_list.setStyleSheet(f"color: {t['muted']}; font-size: {scaled_pt(11)}px;")
        activity_cl.addWidget(self._activity_list)

        grid.addWidget(activity_card, 2, 0, 1, 2)

        # ── Card 6: Cloudflare Tunnel (row 3, full width) ────
        from AssetsManager.lan.tunnel import is_available as is_tunnel_available
        if is_tunnel_available():
            tunnel_card, tunnel_cl = self._make_card(tr("sharing.card_tunnel"), "🌐")

            self._tunnel_status = self.make_muted(tr("sharing.tunnel_not_connected"))
            tunnel_cl.addWidget(self._tunnel_status)

            self._tunnel_url_label = QLabel("")
            self._tunnel_url_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._tunnel_url_label.setStyleSheet(
                f"font-size: {scaled_pt(13)}px; color: {t['accent']}; "
                f"padding: 8px; background: {t['panel']}; "
                f"border: 1px solid {t['border']}; border-radius: {scaled_px(6)}px;")
            self._tunnel_url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._tunnel_url_label.setVisible(False)
            tunnel_cl.addWidget(self._tunnel_url_label)

            tunnel_btn_row = QHBoxLayout()
            self._tunnel_btn = self.make_primary_btn(tr("sharing.btn_start_tunnel"), self._toggle_tunnel)
            self._tunnel_copy_btn = self.make_secondary_btn(tr("sharing.btn_copy"), self._copy_tunnel_url)
            self._tunnel_copy_btn.setVisible(False)
            self._tunnel_open_btn = self.make_secondary_btn(tr("sharing.btn_open"), self._open_tunnel_url)
            self._tunnel_open_btn.setVisible(False)
            tunnel_btn_row.addWidget(self._tunnel_btn)
            tunnel_btn_row.addWidget(self._tunnel_copy_btn)
            tunnel_btn_row.addWidget(self._tunnel_open_btn)
            tunnel_btn_row.addStretch()
            tunnel_cl.addLayout(tunnel_btn_row)

            grid.addWidget(tunnel_card, 3, 0, 1, 2)
        else:
            self._tunnel_section = None

        layout.addLayout(grid)
        layout.addStretch()

    def _make_info_pair(self, label_text, value_text):
        t = _t()
        layout = QVBoxLayout()
        layout.setSpacing(scaled_px(2))
        lbl = QLabel(label_text)
        lbl.setStyleSheet(f"color: {t['muted']}; font-size: {scaled_pt(10)}px;")
        val = QLabel(value_text)
        val.setStyleSheet(f"color: {t['heading']}; font-weight: bold; font-size: {scaled_pt(12)}px;")
        layout.addWidget(lbl)
        layout.addWidget(val)
        return layout, val

    # ══════════════════════════════════════════════════════════
    # Tab 2: Share Links
    # ══════════════════════════════════════════════════════════

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

    # ══════════════════════════════════════════════════════════
    # Tab 3: Users
    # ══════════════════════════════════════════════════════════

    def _setup_users_tab(self, parent):
        t = _t()
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(scaled_px(16), scaled_px(16), scaled_px(16), scaled_px(16))
        layout.setSpacing(scaled_px(12))

        # ── Admin Info ────────────────────────────────────────
        admin_group = self.make_groupbox(tr("sharing.users.admin_info"))
        admin_layout = QVBoxLayout(admin_group)
        admin_layout.setSpacing(scaled_px(6))
        admin_layout.setContentsMargins(scaled_px(12), scaled_px(16), scaled_px(12), scaled_px(8))

        user_row = QHBoxLayout()
        user_row.addWidget(self.make_label(tr("sharing.users.current_user")))
        self._admin_user_label = QLabel(self._settings.get("lan_share_name", "Admin"))
        self._admin_user_label.setStyleSheet(f"font-weight: bold; color: {t['heading']};")
        user_row.addWidget(self._admin_user_label)
        user_row.addSpacing(scaled_px(20))
        user_row.addWidget(self.make_label(tr("sharing.users.role")))
        role_label = QLabel(tr("sharing.users.role_admin"))
        role_label.setStyleSheet(f"color: {t['accent']}; font-weight: bold;")
        user_row.addWidget(role_label)
        user_row.addStretch()
        admin_layout.addLayout(user_row)
        layout.addWidget(admin_group)

        # ── Invite Codes ──────────────────────────────────────
        invite_group = self.make_groupbox(tr("sharing.users.invite_codes"))
        invite_layout = QVBoxLayout(invite_group)
        invite_layout.setSpacing(scaled_px(8))
        invite_layout.setContentsMargins(scaled_px(12), scaled_px(16), scaled_px(12), scaled_px(8))

        invite_btn_row = QHBoxLayout()
        self._generate_code_btn = self.make_primary_btn(tr("sharing.users.generate_code"), self._generate_invite_code)
        invite_btn_row.addWidget(self._generate_code_btn)
        invite_btn_row.addStretch()
        invite_layout.addLayout(invite_btn_row)

        self._codes_table = QTableWidget()
        self._codes_table.setColumnCount(4)
        self._codes_table.setHorizontalHeaderLabels([
            tr("sharing.users.code"),
            tr("sharing.users.code_status"),
            tr("sharing.users.code_created"),
            tr("sharing.users.code_actions"),
        ])
        self._codes_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._codes_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._codes_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._codes_table.verticalHeader().setVisible(False)
        self._codes_table.setMaximumHeight(scaled_px(180))

        c_header = self._codes_table.horizontalHeader()
        c_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        c_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        c_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        c_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._codes_table.setColumnWidth(3, scaled_px(120))

        self._apply_table_theme()
        invite_layout.addWidget(self._codes_table)

        self._codes_status = self.make_muted(tr("sharing.users.no_codes"))
        invite_layout.addWidget(self._codes_status)
        layout.addWidget(invite_group)

        # ── Online Users ──────────────────────────────────────
        online_group = self.make_groupbox(tr("sharing.users.online_users"))
        online_layout = QVBoxLayout(online_group)
        online_layout.setSpacing(scaled_px(6))
        online_layout.setContentsMargins(scaled_px(12), scaled_px(16), scaled_px(12), scaled_px(8))

        self._online_table = QTableWidget()
        self._online_table.setColumnCount(3)
        self._online_table.setHorizontalHeaderLabels([
            tr("sharing.users.current_user"),
            tr("sharing.overview.ip_address"),
            tr("sharing.overview.port"),
        ])
        self._online_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._online_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._online_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._online_table.verticalHeader().setVisible(False)
        self._online_table.setMaximumHeight(scaled_px(160))

        o_header = self._online_table.horizontalHeader()
        o_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        o_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        o_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        self._apply_table_theme()
        online_layout.addWidget(self._online_table)

        self._online_status = self.make_muted(tr("sharing.users.no_online"))
        online_layout.addWidget(self._online_status)
        layout.addWidget(online_group)

        # ── Guest Permission Defaults ─────────────────────────
        guest_group = self.make_groupbox(tr("sharing.users.guest_defaults"))
        guest_layout = QVBoxLayout(guest_group)
        guest_layout.setSpacing(scaled_px(6))
        guest_layout.setContentsMargins(scaled_px(12), scaled_px(16), scaled_px(12), scaled_px(8))

        self._guest_download = self.make_checkbox(tr("sharing.users.guest_can_download"), checked=True)
        guest_layout.addWidget(self._guest_download)
        self._guest_preview = self.make_checkbox(tr("sharing.users.guest_can_preview"), checked=True)
        guest_layout.addWidget(self._guest_preview)
        self._guest_list = self.make_checkbox(tr("sharing.users.guest_can_list"), checked=True)
        guest_layout.addWidget(self._guest_list)

        layout.addWidget(guest_group)
        layout.addStretch()

    # ══════════════════════════════════════════════════════════
    # Tab 4: Settings
    # ══════════════════════════════════════════════════════════

    def _setup_settings_tab(self, parent):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(scaled_px(12), scaled_px(12), scaled_px(12), scaled_px(12))
        layout.setSpacing(scaled_px(10))

        # ── Network (expanded) ────────────────────────────────
        network_panel = CollapsiblePanel(
            tr("sharing.settings.network"),
            tr("sharing.settings.network_desc"),
            expanded=True, parent=parent)
        nl = network_panel.content_layout()

        self._name_edit = self.make_input("AssetManager")
        name_row = self.make_labeled_row(tr("sharing.label_share_name"), self._name_edit)
        nl.addLayout(name_row)

        port_bind_row = QHBoxLayout()
        port_bind_row.addWidget(self.make_label(tr("sharing.label_port")))
        self._port_spin = self.make_spinbox(1024, 65535, 8080)
        port_bind_row.addWidget(self._port_spin)
        port_bind_row.addSpacing(scaled_px(16))
        port_bind_row.addWidget(self.make_label(tr("sharing.label_bind")))
        self._bind_combo = self.make_combobox([tr("sharing.bind_all"), tr("sharing.bind_local_only")])
        port_bind_row.addWidget(self._bind_combo)
        nl.addLayout(port_bind_row)

        self._auto_start = self.make_checkbox(tr("sharing.auto_start_sharing"))
        nl.addWidget(self._auto_start)

        nl.addWidget(self.make_label(tr("sharing.label_https")))
        ssl_row, self._ssl_cert = self.make_browse_row(tr("sharing.label_cert"), tr("sharing.placeholder_cert"),
            lambda: self._browse_file(self._ssl_cert))
        nl.addLayout(ssl_row)
        key_row, self._ssl_key = self.make_browse_row(tr("sharing.label_key"), tr("sharing.placeholder_key"),
            lambda: self._browse_file(self._ssl_key))
        nl.addLayout(key_row)

        layout.addWidget(network_panel)

        # ── Security (expanded) ───────────────────────────────
        security_panel = CollapsiblePanel(
            tr("sharing.settings.security"),
            tr("sharing.settings.security_desc"),
            expanded=True, parent=parent)
        sl = security_panel.content_layout()

        auth_row = QHBoxLayout()
        auth_row.addWidget(self.make_label(tr("sharing.label_auth_mode")))
        self._auth_combo = self.make_combobox([tr("sharing.auth_none"), tr("sharing.auth_password")])
        self._auth_combo.setItemData(0, "none")
        self._auth_combo.setItemData(1, "password")
        self._auth_combo.currentIndexChanged.connect(self._on_auth_changed)
        auth_row.addWidget(self._auth_combo)
        auth_row.addStretch()
        sl.addLayout(auth_row)

        self._pw_widget = QWidget()
        pw_layout = QHBoxLayout(self._pw_widget)
        pw_layout.setContentsMargins(0, 0, 0, 0)
        pw_layout.addWidget(self.make_label(tr("sharing.label_password")))
        self._pw_edit = QLineEdit()
        self._pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._pw_edit.setPlaceholderText(tr("sharing.placeholder_enter_password"))
        pw_layout.addWidget(self._pw_edit)
        self._pw_show = self.make_checkbox(tr("sharing.show_password"))
        self._pw_show.toggled.connect(lambda v: self._pw_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if v else QLineEdit.EchoMode.Password))
        pw_layout.addWidget(self._pw_show)
        self._pw_widget.setVisible(False)
        sl.addWidget(self._pw_widget)

        limits_row = QHBoxLayout()
        limits_row.addWidget(self.make_label(tr("sharing.label_max_connections")))
        self._max_conn = self.make_spinbox(1, 500, 50)
        limits_row.addWidget(self._max_conn)
        limits_row.addSpacing(scaled_px(12))
        limits_row.addWidget(self.make_label(tr("sharing.label_timeout")))
        self._timeout = self.make_spinbox(60, 86400, 3600)
        self._timeout.setSingleStep(300)
        limits_row.addWidget(self._timeout)
        sl.addLayout(limits_row)

        rate_row = QHBoxLayout()
        rate_row.addWidget(self.make_label(tr("sharing.label_rate_limit")))
        self._rate_limit = self.make_spinbox(10, 10000, 100)
        rate_row.addWidget(self._rate_limit)
        rate_row.addWidget(self.make_muted(tr("sharing.helper_req_per_min_ip")))
        rate_row.addStretch()
        sl.addLayout(rate_row)

        sl.addWidget(self.make_label(tr("sharing.label_blocked_ips")))
        self._blocked_ips = QTextEdit()
        self._blocked_ips.setMaximumHeight(scaled_px(60))
        self._blocked_ips.setPlaceholderText(tr("sharing.placeholder_blocked_ips"))
        sl.addWidget(self._blocked_ips)

        sl.addWidget(self.make_label(tr("sharing.label_ip_whitelist")))
        self._ip_whitelist = QTextEdit()
        self._ip_whitelist.setMaximumHeight(scaled_px(60))
        self._ip_whitelist.setPlaceholderText(tr("sharing.placeholder_ip_whitelist"))
        sl.addWidget(self._ip_whitelist)

        layout.addWidget(security_panel)

        # ── Branding (collapsed) ──────────────────────────────
        branding_panel = CollapsiblePanel(
            tr("sharing.settings.branding"),
            tr("sharing.settings.branding_desc"),
            expanded=False, parent=parent)
        bl = branding_panel.content_layout()

        color_row = QHBoxLayout()
        color_row.addWidget(self.make_label(tr("sharing.label_theme_color")))
        self._color_edit = self.make_input("#5b7ff5")
        color_row.addWidget(self._color_edit)
        reset_btn = self.make_secondary_btn(tr("sharing.btn_reset"), lambda: self._color_edit.setText("#5b7ff5"))
        reset_btn.setFixedWidth(scaled_px(60))
        color_row.addWidget(reset_btn)
        bl.addLayout(color_row)

        bl.addWidget(self.make_label(tr("sharing.label_welcome_message")))
        self._welcome_edit = QTextEdit()
        self._welcome_edit.setMaximumHeight(scaled_px(50))
        self._welcome_edit.setPlaceholderText(tr("sharing.placeholder_welcome_msg"))
        bl.addWidget(self._welcome_edit)

        footer_row = QHBoxLayout()
        footer_row.addWidget(self.make_label(tr("sharing.label_footer")))
        self._footer_edit = self.make_input(tr("sharing.default_footer"))
        footer_row.addWidget(self._footer_edit)
        bl.addLayout(footer_row)

        layout.addWidget(branding_panel)

        # ── Advanced (collapsed) ──────────────────────────────
        advanced_panel = CollapsiblePanel(
            tr("sharing.settings.advanced"),
            tr("sharing.settings.advanced_desc"),
            expanded=False, parent=parent)
        al = advanced_panel.content_layout()

        al.addWidget(self.make_label(tr("sharing.label_include_types")))
        types_row = QHBoxLayout()
        self._type_checks = {}
        for key, label in (
            ("images", tr("sharing.type_images")),
            ("models", tr("sharing.type_3d_models")),
            ("videos", tr("sharing.type_videos")),
            ("documents", tr("sharing.type_documents")),
            ("archives", tr("sharing.type_archives")),
        ):
            chk = self.make_checkbox(label, checked=True)
            types_row.addWidget(chk)
            self._type_checks[key] = chk
        al.addLayout(types_row)

        opts_row = QHBoxLayout()
        self._show_hidden = self.make_checkbox(tr("sharing.show_hidden_files"))
        opts_row.addWidget(self._show_hidden)
        opts_row.addSpacing(scaled_px(16))
        opts_row.addWidget(self.make_label(tr("sharing.label_max_depth")))
        self._max_depth = self.make_spinbox(0, 50, 0)
        self._max_depth.setSpecialValueText(tr("sharing.unlimited"))
        opts_row.addWidget(self._max_depth)
        opts_row.addStretch()
        al.addLayout(opts_row)

        al.addWidget(self.make_label(tr("sharing.label_exclude_patterns")))
        self._exclude_patterns = QTextEdit()
        self._exclude_patterns.setMaximumHeight(scaled_px(80))
        self._exclude_patterns.setPlaceholderText(tr("sharing.placeholder_exclude_patterns"))
        al.addWidget(self._exclude_patterns)

        al.addWidget(self.make_label(tr("sharing.label_blur_tags")))
        self._blur_tags = QTextEdit()
        self._blur_tags.setMaximumHeight(scaled_px(80))
        self._blur_tags.setPlaceholderText(tr("sharing.placeholder_blur_tags"))
        al.addWidget(self._blur_tags)
        al.addWidget(self.make_muted(tr("sharing.helper_blur_tags")))

        self._enable_log = self.make_checkbox(tr("sharing.enable_access_log"))
        al.addWidget(self._enable_log)

        log_path_row, self._log_path = self.make_browse_row(tr("sharing.label_log_path"), tr("sharing.placeholder_log_path"),
            self._browse_log_path)
        al.addLayout(log_path_row)

        rotation_row = QHBoxLayout()
        rotation_row.addWidget(self.make_label(tr("sharing.label_log_rotation")))
        self._log_rotation = self.make_spinbox(1, 100, 10)
        rotation_row.addWidget(self._log_rotation)
        rotation_row.addWidget(self.make_muted(tr("sharing.helper_mb_per_file")))
        rotation_row.addStretch()
        al.addLayout(rotation_row)

        layout.addWidget(advanced_panel)

        # ── Tunnel (collapsed) ────────────────────────────────
        from AssetsManager.lan.tunnel import is_available as is_tunnel_available
        if is_tunnel_available():
            tunnel_panel = CollapsiblePanel(
                tr("sharing.settings.tunnel"),
                tr("sharing.settings.tunnel_desc"),
                expanded=False, parent=parent)
            tl = tunnel_panel.content_layout()

            self._settings_tunnel_status = self.make_muted(tr("sharing.tunnel_not_connected"))
            tl.addWidget(self._settings_tunnel_status)

            self._settings_tunnel_url = QLabel("")
            self._settings_tunnel_url.setStyleSheet(
                f"font-size: {scaled_pt(13)}px; color: {themes.get()['accent']};")
            self._settings_tunnel_url.setVisible(False)
            tl.addWidget(self._settings_tunnel_url)

            layout.addWidget(tunnel_panel)

        layout.addStretch()

    # ══════════════════════════════════════════════════════════
    # Overview: Status & Actions
    # ══════════════════════════════════════════════════════════

    def _update_status(self):
        t = _t()
        running = self._server_status.get("running", False)

        if running:
            self._status_icon.setText("🟢")
            self._status_label.setText(tr("sharing.status_active"))
            self._status_label.setStyleSheet(f"font-weight: bold; font-size: {scaled_pt(14)}px; color: {t['heading']};")
            url = self._server_status.get("url", "")
            self._url_label.setText(url)
            self._url_label.setVisible(True)
            self._copy_btn.setVisible(True)
            self._toggle_btn.setText(tr("sharing.btn_stop_sharing"))
            self._toggle_btn.setStyleSheet(self.toggle_btn_style(True))
            self._status_frame.setStyleSheet(self.status_style(True))

            self._ip_info_value.setText(self._server_status.get("ip", "—"))
            self._port_info_value.setText(str(self._server_status.get("port", "—")))
            self._online_info_value.setText(str(self._server_status.get("connections", 0)))
            self._traffic_info_value.setText(self._format_bytes(self._server_status.get("bytes_transferred", 0)))

            if hasattr(self, '_share_url_label'):
                access_key = self._settings.get("lan_access_key", "")
                share_url = f"{url}?key={access_key}" if access_key else url
                self._share_url_label.setText(share_url)
                self._share_url_label.setVisible(True)
                self._share_copy_btn.setVisible(True)
                self._share_open_btn.setVisible(True)
                self._generate_qr(share_url)
        else:
            self._status_icon.setText("🔴")
            self._status_label.setText(tr("sharing.status_off"))
            self._status_label.setStyleSheet(f"font-weight: bold; font-size: {scaled_pt(14)}px; color: {t['heading']};")
            self._url_label.setVisible(False)
            self._copy_btn.setVisible(False)
            self._toggle_btn.setText(tr("sharing.btn_start_sharing"))
            self._toggle_btn.setStyleSheet(self.toggle_btn_style(False))
            self._status_frame.setStyleSheet(self.status_style(False))

            self._ip_info_value.setText("—")
            self._port_info_value.setText("—")
            self._online_info_value.setText("0")
            self._traffic_info_value.setText("0 B")
            if hasattr(self, '_share_url_label'):
                self._share_url_label.setVisible(False)
                self._share_copy_btn.setVisible(False)
                self._share_open_btn.setVisible(False)
            if hasattr(self, '_qr_label'):
                self._qr_label.setVisible(False)
                self._qr_copy_btn.setVisible(False)

    def _generate_qr(self, url: str):
        """Generate and display QR code for the given URL."""
        try:
            import segno
            from io import BytesIO
            from PySide6.QtGui import QImage, QPixmap, QPainter, QColor
            qr = segno.make_qr(url, error="H")
            buf = BytesIO()
            qr.save(buf, kind="png", scale=16, border=2)
            buf.seek(0)
            raw_img = QImage()
            raw_img.loadFromData(buf.read())
            if raw_img.isNull():
                return
            size = raw_img.width() + 40
            canvas = QPixmap(size, size)
            canvas.fill(QColor("white"))
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("white"))
            painter.drawRoundedRect(0, 0, size, size, 16, 16)
            x = (size - raw_img.width()) // 2
            y = (size - raw_img.height()) // 2
            painter.drawImage(x, y, raw_img)
            painter.end()
            self._qr_pixmap = canvas
            self._qr_label.setPixmap(canvas.scaled(
                190, 190, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
            self._qr_label.setVisible(True)
            self._qr_copy_btn.setVisible(True)
        except ImportError:
            self._qr_label.setText(tr("sharing.install_segno_hint"))
            self._qr_label.setVisible(True)
        except Exception:
            self._qr_label.setText(tr("sharing.qr_generation_failed"))
            self._qr_label.setVisible(True)

    def _copy_overview_link(self):
        """Copy share URL to clipboard."""
        url = self._share_url_label.text()
        if url:
            QApplication.clipboard().setText(url)
            self._share_copy_btn.setText(tr("sharing.copied"))
            QTimer.singleShot(1500, lambda: self._share_copy_btn.setText(tr("sharing.btn_copy_link")))

    def _open_share_link(self):
        """Open share URL in browser."""
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        url = self._share_url_label.text()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _copy_qr(self):
        """Copy QR code to clipboard."""
        if self._qr_pixmap and not self._qr_pixmap.isNull():
            QApplication.clipboard().setPixmap(self._qr_pixmap)
            self._qr_copy_btn.setText(tr("sharing.copied"))
            QTimer.singleShot(1500, lambda: self._qr_copy_btn.setText(tr("sharing.btn_copy_qr")))

    def _poll_server_status(self):
        if not self._server or not self._server.is_running():
            self._status_timer.stop()
            return

        port = self._server._port
        url = f"http://localhost:{port}/api/stats"
        headers = {}
        if hasattr(self._server, 'token_secret'):
            from AssetsManager.lan.utils import get_auth_headers
            headers.update(get_auth_headers(self._server.token_secret))

        class _PollSignals(QObject):
            finished = Signal(bool, object)

        class _PollTask(QRunnable):
            def __init__(self):
                super().__init__()
                self.signals = _PollSignals()

            def run(self):
                try:
                    import requests
                    resp = requests.get(url, headers=headers, timeout=2)
                    if resp.status_code == 200:
                        self.signals.finished.emit(True, resp.json())
                    else:
                        self.signals.finished.emit(False, None)
                except Exception:
                    self.signals.finished.emit(False, None)

        task = _PollTask()
        task.signals.finished.connect(self._on_poll_result)
        QThreadPool.globalInstance().start(task)
        self._poll_task = task

    def _on_poll_result(self, success, data):
        if not success or data is None:
            return
        connections = data.get("connections", 0)
        bytes_transferred = data.get("bytes_transferred", 0)
        self._online_info_value.setText(str(connections))
        self._traffic_info_value.setText(self._format_bytes(bytes_transferred))

        # Periodically refresh all tabs
        self._poll_counter = getattr(self, '_poll_counter', 0) + 1
        if self._poll_counter % 3 == 0:  # Every 6 seconds (3 * 2s interval)
            self._refresh_all_tabs()

    def _format_bytes(self, size: int | float) -> str:
        if size == 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB"]
        value = float(size)
        i = 0
        while value >= 1024 and i < len(units) - 1:
            value /= 1024
            i += 1
        return f"{value:.1f} {units[i]}"

    def _on_toggle_server(self):
        self._toggle_btn.setEnabled(False)
        self._toggle_btn.setText(tr("sharing.btn_connecting"))
        self._save_settings()

        host = getattr(self, "_host", None)
        if host is not None and hasattr(host, "_toggle_sharing"):
            was_running = bool(self._server and self._server.is_running())
            host._toggle_sharing()
            self._server = getattr(host, "_lan_server", None)
            self._server_status = self._server.status() if self._server else {}
            self._update_status()
            if self._server and self._server.is_running():
                self._status_timer.start()
                self._refresh_all_tabs()
                if not was_running:
                    Toast.instance(self, tr("sharing.toast.server_started"), level="success")
            else:
                self._status_timer.stop()
                self._clear_runtime_data()
                if was_running:
                    Toast.instance(self, tr("sharing.toast.server_stopped"), level="info")
            self._toggle_btn.setEnabled(True)
        else:
            if self._server:
                status = self._server.status()
                if status.get('running'):
                    self._server.stop()
                    Toast.instance(self, tr("sharing.toast.server_stopped"), level="info")
                    self._server_status = self._server.status()
                    self._update_status()
                    self._status_timer.stop()
                    self._toggle_btn.setEnabled(True)
                else:
                    self._server.start()
                    self._server_status = self._server.status()
                    self._update_status()
                    self._toggle_btn.setEnabled(True)
                    Toast.instance(self, tr("sharing.toast.server_started"), level="success")
                    self._status_timer.start()
                    self._refresh_all_tabs()
            else:
                self._toggle_btn.setEnabled(True)
        self.settings_changed.emit()

    def _copy_link(self):
        url = self._server_status.get("url", "")
        if url:
            QApplication.clipboard().setText(url)
            Toast.instance(self, tr("sharing.toast.copied"), level="success")
            self._copy_btn.setText(tr("sharing.copied"))
            QTimer.singleShot(1500, lambda: self._copy_btn.setText(tr("sharing.btn_copy_link")))

    def _on_quick_share(self):
        from AssetsManager.dialogs.quick_share_card import QuickShareCard
        if not hasattr(self, '_quick_card'):
            self._quick_card = QuickShareCard(self)
            self._quick_card.share_requested.connect(self._create_quick_share)
        pos = self._quick_share_btn.mapToGlobal(self._quick_share_btn.rect().bottomLeft())
        self._quick_card.show_for_paths([], pos)

    def _create_quick_share(self, data: dict):
        base = self._get_api_base()
        if not base:
            Toast.instance(self, tr("sharing.toast.error"), level="error")
            return
        headers = self._get_auth_headers()
        headers["Content-Type"] = "application/json"
        task = ShareApiTask("POST", f"{base}/api/shares", headers, data, success_statuses=(200, 201))
        task.signals.finished.connect(self._on_quick_share_result)
        QThreadPool.globalInstance().start(task)
        self._quick_share_task = task

    def _on_quick_share_result(self, success, data):
        if success:
            Toast.instance(self, tr("sharing.toast.share_created"), level="success")
            self._data_changed.emit()
        else:
            Toast.instance(self, tr("sharing.toast.error"), level="error")

    # ══════════════════════════════════════════════════════════
    # Share Links Tab: Data & Actions
    # ══════════════════════════════════════════════════════════

    def _get_auth_headers(self):
        headers = {}
        if self._server and hasattr(self._server, 'token_secret'):
            from AssetsManager.lan.utils import get_auth_headers
            headers.update(get_auth_headers(self._server.token_secret))
        return headers

    def _get_api_base(self):
        if not self._server or not self._server.is_running():
            return None
        port = self._server._port
        return f"http://localhost:{port}"

    def _load_share_links(self):
        base = self._get_api_base()
        if not base:
            self._links_status.setText(tr("sharemgr.error.server_unavailable"))
            return
        self._links_status.setText(tr("sharing.links.loading"))
        headers = self._get_auth_headers()
        task = ShareApiTask("GET", f"{base}/api/shares", headers)
        task.signals.finished.connect(self._on_shares_loaded)
        QThreadPool.globalInstance().start(task)
        self._links_load_task = task

    def _on_shares_loaded(self, success, data):
        if success and data:
            self._shares = data.get("shares", [])
            self._populate_links_table()
            if self._shares:
                self._links_status.setText(tr("sharemgr.status.active_count").format(count=len(self._shares)))
            else:
                self._links_status.setText(tr("sharing.links.no_links"))
        else:
            self._links_status.setText(tr("sharemgr.status.error").format(data=""))

    def _populate_links_table(self):
        filtered = self._get_filtered_shares()
        self._links_table.setRowCount(len(filtered))
        t = _t()

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
                f"QPushButton {{ background: {t['accent']}; color: {t['on_accent']}; "
                f"border: none; border-radius: {scaled_px(3)}px; font-size: {scaled_pt(10)}px; padding: 2px 8px; }}"
                f"QPushButton:hover {{ background: {t['accent']}dd; }}")
            copy_btn.clicked.connect(lambda checked, idx=i: self._copy_table_share_link(idx))
            actions_layout.addWidget(copy_btn)

            delete_btn = QPushButton(tr("sharing.links.btn_delete"))
            delete_btn.setFixedHeight(scaled_px(24))
            delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            delete_btn.setStyleSheet(
                f"QPushButton {{ background: {t['danger']}; color: {t['on_accent']}; "
                f"border: none; border-radius: {scaled_px(3)}px; font-size: {scaled_pt(10)}px; padding: 2px 8px; }}"
                f"QPushButton:hover {{ background: {t['danger']}dd; }}")
            delete_btn.clicked.connect(lambda checked, idx=i: self._delete_share_link(idx))
            actions_layout.addWidget(delete_btn)

            actions_layout.addStretch()
            self._links_table.setCellWidget(i, 5, actions_widget)

    def _get_filtered_shares(self):
        text = self._links_search.text().lower().strip() if hasattr(self, '_links_search') else ""
        filter_idx = self._links_filter.currentIndex() if hasattr(self, '_links_filter') else 0
        result = []
        for share in self._shares:
            if text:
                name = str(share.get("name", "")).lower()
                paths = " ".join(share.get("paths", [])).lower()
                if text not in name and text not in paths:
                    continue
            if filter_idx == 1:
                if share.get("expired", False):
                    continue
            elif filter_idx == 2:
                if not share.get("expired", False):
                    continue
            result.append(share)
        return result

    def _filter_links(self):
        self._populate_links_table()

    def _on_links_selection_changed(self):
        selected = bool(self._links_table.selectedItems())
        self._batch_delete_btn.setEnabled(selected)

    def _on_select_all(self, checked):
        if checked:
            self._links_table.selectAll()
        else:
            self._links_table.clearSelection()

    def _copy_table_share_link(self, row):
        filtered = self._get_filtered_shares()
        if row < 0 or row >= len(filtered):
            return
        server = self._server
        if server is None or not server.is_running():
            self._links_status.setText(tr("sharemgr.error.server_unavailable"))
            return
        share = filtered[row]
        share_id = share.get("id")
        if not share_id:
            return
        port = server._port
        from AssetsManager.lan.server import get_local_ip
        ip = get_local_ip()
        url = f"http://{ip}:{port}/s/{share_id}"
        QApplication.clipboard().setText(url)
        Toast.instance(self, tr("sharing.toast.copied"), level="success")
        self._links_status.setText(tr("sharemgr.status.link_copied"))
        QTimer.singleShot(2000, lambda: self._links_status.setText(
            tr("sharemgr.status.active_count").format(count=len(self._shares)) if self._shares else tr("sharing.links.no_links")))

    def _delete_share_link(self, row):
        filtered = self._get_filtered_shares()
        if row < 0 or row >= len(filtered):
            return
        share = filtered[row]
        share_id = share.get("id")
        if not share_id:
            return
        reply = QMessageBox.question(
            self, tr("sharemgr.msg.delete_title"),
            tr("sharemgr.msg.confirm_delete").format(path=share.get('paths', [tr("sharemgr.fallback.unknown")])[0]),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        base = self._get_api_base()
        headers = self._get_auth_headers()
        task = ShareApiTask("DELETE", f"{base}/api/shares/{share_id}", headers)
        task.signals.finished.connect(lambda ok, _: self._on_single_delete(ok, share_id))
        QThreadPool.globalInstance().start(task)
        self._delete_task = task

    def _on_single_delete(self, success, share_id):
        if success:
            self._shares = [s for s in self._shares if s.get("id") != share_id]
            self._populate_links_table()
            self._links_status.setText(tr("sharemgr.status.deleted"))
            Toast.instance(self, tr("sharing.toast.share_deleted"), level="info")
            self._data_changed.emit()
        else:
            Toast.instance(self, tr("sharing.toast.error"), level="error")
            QMessageBox.warning(self, tr("sharemgr.msg.error_title"), tr("sharemgr.error.delete_failed_generic"))

    def _batch_delete_links(self):
        selected_rows = sorted(set(idx.row() for idx in self._links_table.selectedIndexes()), reverse=True)
        if not selected_rows:
            return
        filtered = self._get_filtered_shares()
        count = len(selected_rows)
        reply = QMessageBox.question(
            self, tr("sharemgr.msg.delete_title"),
            tr("sharing.links.delete_confirm").format(count=count),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        ids_to_delete = []
        for row in selected_rows:
            if 0 <= row < len(filtered):
                ids_to_delete.append(filtered[row].get("id"))
        base = self._get_api_base()
        headers = self._get_auth_headers()
        self._batch_remaining = len(ids_to_delete)
        self._batch_deleted = 0
        self._batch_tasks = []
        for share_id in ids_to_delete:
            if not share_id:
                self._batch_remaining -= 1
                continue
            task = ShareApiTask("DELETE", f"{base}/api/shares/{share_id}", headers)
            task.signals.finished.connect(lambda ok, _, sid=share_id: self._on_batch_item_deleted(ok, sid))
            QThreadPool.globalInstance().start(task)
            self._batch_tasks.append(task)

    def _on_batch_item_deleted(self, success, share_id):
        self._batch_remaining -= 1
        if success:
            self._batch_deleted += 1
            self._shares = [s for s in self._shares if s.get("id") != share_id]
        if self._batch_remaining <= 0:
            self._populate_links_table()
            self._links_status.setText(tr("sharing.links.deleted").format(count=self._batch_deleted))
            self._select_all_chk.setChecked(False)
            self._data_changed.emit()

    # ══════════════════════════════════════════════════════════
    # Users Tab: Data & Actions
    # ══════════════════════════════════════════════════════════

    def _load_invite_codes(self):
        base = self._get_api_base()
        if not base:
            return
        headers = self._get_auth_headers()
        task = ShareApiTask("GET", f"{base}/api/invites", headers)
        task.signals.finished.connect(self._on_invites_loaded)
        QThreadPool.globalInstance().start(task)
        self._invites_task = task

    def _on_invites_loaded(self, success, data):
        if success and data:
            self._invite_codes = data.get("invites", data) if isinstance(data, dict) else data
            self._populate_codes_table()
        else:
            self._codes_status.setText(tr("sharing.users.no_codes"))

    def _populate_codes_table(self):
        if not isinstance(self._invite_codes, list):
            self._invite_codes = []
        self._codes_table.setRowCount(len(self._invite_codes))
        t = _t()

        for i, code_data in enumerate(self._invite_codes):
            code = code_data if isinstance(code_data, str) else code_data.get("code", str(code_data))
            self._codes_table.setItem(i, 0, QTableWidgetItem(str(code)))

            status = code_data.get("status", "active") if isinstance(code_data, dict) else "active"
            self._codes_table.setItem(i, 1, QTableWidgetItem(status))

            created = code_data.get("created", "—") if isinstance(code_data, dict) else "—"
            self._codes_table.setItem(i, 2, QTableWidgetItem(str(created)))

            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(scaled_px(4), scaled_px(2), scaled_px(4), scaled_px(2))
            actions_layout.setSpacing(scaled_px(4))

            copy_btn = QPushButton(tr("sharing.users.btn_copy_code"))
            copy_btn.setFixedHeight(scaled_px(22))
            copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            copy_btn.setStyleSheet(
                f"QPushButton {{ background: {t['accent']}; color: {t['on_accent']}; "
                f"border: none; border-radius: {scaled_px(3)}px; font-size: {scaled_pt(10)}px; padding: 2px 6px; }}"
                f"QPushButton:hover {{ background: {t['accent']}dd; }}")
            copy_btn.clicked.connect(lambda checked, c=code: QApplication.clipboard().setText(c))
            actions_layout.addWidget(copy_btn)

            revoke_btn = QPushButton(tr("sharing.users.btn_revoke"))
            revoke_btn.setFixedHeight(scaled_px(22))
            revoke_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            revoke_btn.setStyleSheet(
                f"QPushButton {{ background: {t['danger']}; color: {t['on_accent']}; "
                f"border: none; border-radius: {scaled_px(3)}px; font-size: {scaled_pt(10)}px; padding: 2px 6px; }}"
                f"QPushButton:hover {{ background: {t['danger']}dd; }}")
            revoke_btn.clicked.connect(lambda checked, idx=i: self._revoke_invite_code(idx))
            actions_layout.addWidget(revoke_btn)

            actions_layout.addStretch()
            self._codes_table.setCellWidget(i, 3, actions_widget)

        self._codes_status.setText(
            f"{len(self._invite_codes)} " + tr("sharing.users.invite_codes").lower()
            if self._invite_codes else tr("sharing.users.no_codes"))

    def _generate_invite_code(self):
        base = self._get_api_base()
        if not base:
            return
        headers = self._get_auth_headers()
        task = ShareApiTask("POST", f"{base}/api/invites/create", headers, success_statuses=(200, 201))
        task.signals.finished.connect(lambda ok, data: self._on_generate_code_result(ok, data))
        QThreadPool.globalInstance().start(task)
        self._gen_task = task

    def _on_generate_code_result(self, success, data):
        if success:
            self._load_invite_codes()
            self._data_changed.emit()

    def _revoke_invite_code(self, row):
        if row < 0 or row >= len(self._invite_codes):
            return
        code_data = self._invite_codes[row]
        code = code_data if isinstance(code_data, str) else code_data.get("code", "")
        if not code:
            return
        base = self._get_api_base()
        if not base:
            return
        headers = self._get_auth_headers()
        task = ShareApiTask("DELETE", f"{base}/api/invites/{code}/revoke", headers)
        task.signals.finished.connect(lambda ok, _: self._on_revoke_result(ok, row))
        QThreadPool.globalInstance().start(task)
        self._revoke_task = task

    def _on_revoke_result(self, success, row):
        if success:
            if 0 <= row < len(self._invite_codes):
                self._invite_codes.pop(row)
            self._populate_codes_table()
            self._data_changed.emit()

    def _load_online_users(self):
        base = self._get_api_base()
        if not base:
            return
        headers = self._get_auth_headers()
        task = ShareApiTask("GET", f"{base}/api/online-users", headers)
        task.signals.finished.connect(self._on_online_users_loaded)
        QThreadPool.globalInstance().start(task)
        self._online_task = task

    def _on_online_users_loaded(self, success, data):
        if success and data:
            self._online_users = data.get("users", data) if isinstance(data, dict) else data
            self._populate_online_table()
        else:
            self._online_status.setText(tr("sharing.users.no_online"))

    def _populate_online_table(self):
        if not isinstance(self._online_users, list):
            self._online_users = []
        self._online_table.setRowCount(len(self._online_users))

        for i, user in enumerate(self._online_users):
            if isinstance(user, dict):
                self._online_table.setItem(i, 0, QTableWidgetItem(user.get("name", "—")))
                self._online_table.setItem(i, 1, QTableWidgetItem(user.get("ip", "—")))
                self._online_table.setItem(i, 2, QTableWidgetItem(str(user.get("port", "—"))))
            else:
                self._online_table.setItem(i, 0, QTableWidgetItem(str(user)))
                self._online_table.setItem(i, 1, QTableWidgetItem("—"))
                self._online_table.setItem(i, 2, QTableWidgetItem("—"))

        self._online_status.setText(
            f"{len(self._online_users)} {tr('sharing.users.online_users').lower()}"
            if self._online_users else tr("sharing.users.no_online"))

    # ══════════════════════════════════════════════════════════
    # Activity
    # ══════════════════════════════════════════════════════════

    def _load_activity(self):
        base = self._get_api_base()
        if not base:
            return
        headers = self._get_auth_headers()
        task = ShareApiTask("GET", f"{base}/api/activity", headers)
        task.signals.finished.connect(self._on_activity_loaded)
        QThreadPool.globalInstance().start(task)
        self._activity_task = task

    def _on_activity_loaded(self, success, data):
        if success and data:
            activities = data.get("activities", data) if isinstance(data, dict) else data
            if isinstance(activities, list) and activities:
                lines = []
                for item in activities[:10]:
                    if isinstance(item, dict):
                        msg = item.get("message", item.get("action", str(item)))
                        time_str = item.get("time", item.get("timestamp", ""))
                        lines.append(f"• {msg}" + (f"  ({time_str})" if time_str else ""))
                    else:
                        lines.append(f"• {item}")
                self._activity_list.setText("\n".join(lines))
            else:
                self._activity_list.setText(tr("sharing.overview.no_activity"))
        else:
            self._activity_list.setText(tr("sharing.overview.no_activity"))

    # ══════════════════════════════════════════════════════════
    # Tunnel
    # ══════════════════════════════════════════════════════════

    def _copy_tunnel_url(self):
        url = self._tunnel_url_label.text()
        if url:
            QApplication.clipboard().setText(url)
            self._tunnel_copy_btn.setText(tr("sharing.copied"))
            QTimer.singleShot(1500, lambda: self._tunnel_copy_btn.setText(tr("sharing.btn_copy")))

    def _open_tunnel_url(self):
        url = self._tunnel_url_label.text()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _toggle_tunnel(self):
        if not self._server:
            return
        t = _t()
        if self._server.is_tunnel_running():
            self._server.stop_tunnel()
            self._tunnel_btn.setText(tr("sharing.btn_start_tunnel"))
            self._tunnel_btn.setStyleSheet(self.primary_btn_style())
            self._tunnel_status.setText(tr("sharing.tunnel_not_connected"))
            self._tunnel_status.setStyleSheet(f"font-size: {scaled_pt(12)}px; color: {t['muted']};")
            self._tunnel_url_label.setVisible(False)
            self._tunnel_copy_btn.setVisible(False)
            self._tunnel_open_btn.setVisible(False)
            # Revert QR code to local URL
            local_url = self._server_status.get("url", "")
            if local_url:
                access_key = self._settings.get("lan_access_key", "")
                share_url = f"{local_url}?key={access_key}" if access_key else local_url
                self._share_url_label.setText(share_url)
                self._generate_qr(share_url)
            self._data_changed.emit()
        else:
            self._tunnel_btn.setEnabled(False)
            self._tunnel_btn.setText(tr("sharing.btn_connecting"))
            self._tunnel_status.setText(tr("sharing.tunnel_starting"))
            self._tunnel_status.setStyleSheet(f"font-size: {scaled_pt(12)}px; color: {t['muted']};")

            from PySide6.QtCore import QThread, Signal as QSignal

            class TunnelWorker(QThread):
                finished = QSignal(str)
                status = QSignal(str)

                def __init__(self, server):
                    super().__init__()
                    self._server = server

                def run(self):
                    # Ensure cloudflared is available (download if needed)
                    from AssetsManager.lan.tunnel import ensure_available, is_available
                    if not is_available():
                        self.status.emit(tr("sharing.tunnel_downloading"))
                        if not ensure_available():
                            self.finished.emit("")
                            return
                    url = self._server.start_tunnel(timeout=30)
                    self.finished.emit(url or "")

            self._tunnel_worker = TunnelWorker(self._server)
            self._tunnel_worker.status.connect(lambda msg: self._tunnel_status.setText(msg))
            self._tunnel_worker.finished.connect(self._on_tunnel_result)
            self._tunnel_worker.start()

    def _on_tunnel_result(self, public_url: str):
        t = _t()
        if public_url:
            self._tunnel_status.setText(tr("sharing.tunnel_connected"))
            self._tunnel_status.setStyleSheet(f"font-size: {scaled_pt(12)}px; color: {t['success']};")
            self._tunnel_url_label.setText(public_url)
            self._tunnel_url_label.setVisible(True)
            self._tunnel_btn.setText(tr("sharing.btn_stop_tunnel"))
            self._tunnel_btn.setStyleSheet(self.toggle_btn_style(True))
            self._tunnel_btn.setEnabled(True)
            self._tunnel_copy_btn.setVisible(True)
            self._tunnel_open_btn.setVisible(True)
            # Update QR code to show tunnel URL
            self._generate_qr(public_url)
            self._share_url_label.setText(public_url)
            self._data_changed.emit()
        else:
            self._tunnel_status.setText(tr("sharing.tunnel_failed"))
            self._tunnel_status.setStyleSheet(f"font-size: {scaled_pt(12)}px; color: {t['danger']};")
            self._tunnel_btn.setText(tr("sharing.btn_start_tunnel"))
            self._tunnel_btn.setStyleSheet(self.primary_btn_style())
            self._tunnel_btn.setEnabled(True)
            Toast.instance(self, tr("sharing.toast.error"), level="error")

    # ── Auth ──────────────────────────────────────────────────

    def _on_auth_changed(self, _index):
        self._pw_widget.setVisible(self._auth_mode() == "password")

    def _auth_mode(self):
        return self._auth_combo.currentData()

    # ── Browse ────────────────────────────────────────────────

    def _browse_log_path(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("sharing.dialog_select_log_file"), self._log_path.text(), tr("sharing.dialog_log_files_filter"))
        if path:
            self._log_path.setText(path)

    def _browse_file(self, target_edit):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("sharing.dialog_select_file"), target_edit.text(), tr("sharing.dialog_all_files_filter"))
        if path:
            target_edit.setText(path)

    # ── Settings persistence ──────────────────────────────────

    def _load_settings(self):
        s = self._settings
        self._name_edit.setText(s.get("lan_share_name", "AssetManager"))
        self._port_spin.setValue(s.get("lan_port", 8080))
        bind = s.get("lan_bind", "0.0.0.0")
        self._bind_combo.setCurrentIndex(0 if bind == "0.0.0.0" else 1)
        self._auto_start.setChecked(s.get("lan_auto_start", False))

        auth = s.get("lan_auth_mode", "none")
        self._auth_combo.setCurrentIndex(1 if auth == "password" else 0)
        self._pw_edit.setText("")
        self._has_existing_password = s.get("lan_password") is not None
        if self._has_existing_password:
            self._pw_edit.setPlaceholderText(tr("sharing.placeholder_new_password"))
        self._max_conn.setValue(s.get("lan_max_connections", 50))
        self._timeout.setValue(s.get("lan_session_timeout", 3600))
        self._rate_limit.setValue(s.get("lan_rate_limit", 100))
        self._ip_whitelist.setPlainText("\n".join(s.get("lan_ip_whitelist", [])))

        types = s.get("lan_include_types", list(self._type_checks.keys()))
        for key, chk in self._type_checks.items():
            chk.setChecked(key in types)
        self._show_hidden.setChecked(s.get("lan_show_hidden", False))
        self._max_depth.setValue(s.get("lan_max_depth", 0))
        self._exclude_patterns.setPlainText(
            "\n".join(s.get("lan_exclude_patterns", [".git", "node_modules", "__pycache__", ".thumbnails"]))
        )

        self._color_edit.setText(s.get("lan_theme_color", "#5b7ff5"))
        self._welcome_edit.setPlainText(s.get("lan_welcome_msg", ""))
        self._footer_edit.setText(s.get("lan_footer_text", ""))

        self._enable_log.setChecked(s.get("lan_enable_log", False))
        self._log_path.setText(s.get("lan_log_path", ""))
        self._log_rotation.setValue(s.get("lan_log_rotation_mb", 10))

        self._blur_tags.setPlainText("\n".join(s.get("lan_blur_tags", [])))

        self._ssl_cert.setText(s.get("lan_ssl_cert", ""))
        self._ssl_key.setText(s.get("lan_ssl_key", ""))
        self._blocked_ips.setPlainText("\n".join(s.get("lan_blocked_ips", [])))

        self._guest_download.setChecked(s.get("lan_guest_download", False))
        self._guest_preview.setChecked(s.get("lan_guest_preview", True))
        self._guest_list.setChecked(s.get("lan_guest_list", True))

    def _on_apply(self):
        self._save_settings()

    def _save_settings(self):
        s = self._settings
        s.set("lan_share_name", self._name_edit.text() or "AssetManager")
        s.set("lan_port", self._port_spin.value())
        s.set("lan_bind", "0.0.0.0" if self._bind_combo.currentIndex() == 0 else "127.0.0.1")
        s.set("lan_auto_start", self._auto_start.isChecked())

        auth_mode = self._auth_mode()
        s.set("lan_auth_mode", auth_mode)
        pw = self._pw_edit.text() if auth_mode == "password" else None
        if pw:
            from AssetsManager.lan.auth import hash_password
            s.set("lan_password", hash_password(pw))
        elif auth_mode == "password" and self._has_existing_password:
            pass
        else:
            s.set("lan_password", None)
        s.set("lan_max_connections", self._max_conn.value())
        s.set("lan_session_timeout", self._timeout.value())
        s.set("lan_rate_limit", self._rate_limit.value())
        whitelist = [line.strip() for line in self._ip_whitelist.toPlainText().splitlines() if line.strip()]
        s.set("lan_ip_whitelist", whitelist)

        types = [k for k, chk in self._type_checks.items() if chk.isChecked()]
        s.set("lan_include_types", types)
        s.set("lan_show_hidden", self._show_hidden.isChecked())
        s.set("lan_max_depth", self._max_depth.value())
        exclude = [line.strip() for line in self._exclude_patterns.toPlainText().splitlines() if line.strip()]
        s.set("lan_exclude_patterns", exclude)

        s.set("lan_theme_color", self._color_edit.text() or "#5b7ff5")
        s.set("lan_welcome_msg", self._welcome_edit.toPlainText())
        s.set("lan_footer_text", self._footer_edit.text())

        s.set("lan_enable_log", self._enable_log.isChecked())
        s.set("lan_log_path", self._log_path.text())
        s.set("lan_log_rotation_mb", self._log_rotation.value())

        blur = [line.strip() for line in self._blur_tags.toPlainText().splitlines() if line.strip()]
        s.set("lan_blur_tags", blur)

        s.set("lan_ssl_cert", self._ssl_cert.text() or None)
        s.set("lan_ssl_key", self._ssl_key.text() or None)
        blocked = [line.strip() for line in self._blocked_ips.toPlainText().splitlines() if line.strip()]
        s.set("lan_blocked_ips", blocked)

        s.set("lan_guest_download", self._guest_download.isChecked())
        s.set("lan_guest_preview", self._guest_preview.isChecked())
        s.set("lan_guest_list", self._guest_list.isChecked())

        s.save()

    def closeEvent(self, event):
        self._status_timer.stop()
        super().closeEvent(event)
