"""Share System management shell and its endpoint, link, access, and settings pages."""
import logging
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QRunnable, QThreadPool
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QFrame,
    QFileDialog, QWidget, QApplication,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QCheckBox, QMessageBox, QStackedWidget, QDialogButtonBox,
)
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from AssetsManager.core import themes
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.core.settings import AppSettings
from AssetsManager.dialogs.tabbed_dialog import TabbedDialog
from AssetsManager.dialogs._share_api import ShareApiTask
from AssetsManager.widgets.toast import Toast
from AssetsManager import i18n
from AssetsManager.widgets.lan_sharing import HOT_SHARING_SETTINGS, RESTART_SHARING_SETTINGS

tr = i18n.tr
_log = logging.getLogger(__name__)


def _t():
    return themes.get()


def _endpoint_state(status: dict, tunnel_running: bool = False) -> str:
    """Map server facts to the small set of states rendered by the endpoint page."""
    state = status.get("state")
    if state in {"starting", "failed"}:
        return state
    if not status.get("running", False):
        return "off"
    return "public" if tunnel_running else "local"


def _endpoint_primary_action(state: str) -> str:
    """Return the action scope, leaving translated presentation to the widget."""
    return {
        "off": "start",
        "starting": "busy",
        "local": "stop_server",
        "public": "stop_tunnel",
        "failed": "retry",
    }.get(state, "start")


class SharingSettingsDialog(TabbedDialog):
    """Dedicated Share System shell while retaining existing page behavior."""

    settings_changed = Signal()
    _data_changed = Signal()

    def __init__(
        self, parent=None, server_status: dict | None = None, server=None, initial_page: int | str = 0,
    ):
        self._settings = AppSettings.instance()
        self._host = parent
        self._server_status = server_status or {}
        self._server = server
        self._shares = []
        self._invite_codes = []
        self._online_users = []
        self._activity_items = []
        if initial_page == "links":
            self._initial_page = 1
        elif initial_page == "access":
            self._initial_page = 2
        elif isinstance(initial_page, int):
            self._initial_page = initial_page
        else:
            self._initial_page = 0

        # Start at the desktop target while allowing the specified narrow-window fallback.
        super().__init__(parent, title=tr("sharing.dialog_title"), min_size=(700, 620))
        self.resize(scaled_px(980), scaled_px(720))

        self._data_changed.connect(self._refresh_all_tabs)

        self._update_status()
        self._loading_settings = True
        try:
            self._load_settings()
        finally:
            self._loading_settings = False
        self._update_configuration_summary()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(2000)
        self._status_timer.timeout.connect(self._poll_server_status)
        if self._server and self._server.is_running():
            self._status_timer.start()
            self._load_share_links()
            self._load_activity()
            self._load_online_users()
            self._load_invite_codes()

    def _build_ui(self):
        """Build a desktop navigation shell with a compact top-nav fallback."""
        self.setStyleSheet(self._dialog_qss())
        root = QVBoxLayout(self)
        root.setContentsMargins(scaled_px(16), scaled_px(16), scaled_px(16), scaled_px(12))
        root.setSpacing(scaled_px(12))

        header = QHBoxLayout()
        title = self.make_heading(tr("sharing.dialog_title"))
        title.setStyleSheet(f"font-size: {scaled_pt(18)}px; font-weight: bold; color: {_t()['heading']};")
        header.addWidget(title)
        header.addStretch()
        root.addLayout(header)

        self._top_nav = QWidget()
        top_nav_layout = QHBoxLayout(self._top_nav)
        top_nav_layout.setContentsMargins(0, 0, 0, 0)
        top_nav_layout.setSpacing(scaled_px(6))
        self._nav_rail = QFrame()
        self._nav_rail.setFixedWidth(scaled_px(216))
        rail_layout = QVBoxLayout(self._nav_rail)
        rail_layout.setContentsMargins(scaled_px(8), scaled_px(8), scaled_px(8), scaled_px(8))
        rail_layout.setSpacing(scaled_px(4))

        self._page_stack = QStackedWidget()
        self._nav_buttons = []
        self._top_nav_buttons = []
        pages = (
            (tr("sharing.nav.endpoint"), self._setup_overview_tab),
            (tr("sharing.nav.links"), self._setup_share_links_tab),
            (tr("sharing.nav.access"), self._setup_users_tab),
            (tr("sharing.nav.configuration"), self._setup_settings_tab),
        )
        for index, (label, setup) in enumerate(pages):
            page = QWidget()
            setup(page)
            self._page_stack.addWidget(page)
            self._nav_buttons.append(self._make_nav_button(label, index, rail_layout))
            self._top_nav_buttons.append(self._make_nav_button(label, index, top_nav_layout))
        rail_layout.addStretch()
        root.addWidget(self._top_nav)

        body = QHBoxLayout()
        body.setSpacing(scaled_px(16))
        body.addWidget(self._nav_rail)
        body.addWidget(self._page_stack, 1)
        root.addLayout(body, 1)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        apply_btn = btn_box.addButton(tr("dialog.apply"), QDialogButtonBox.ButtonRole.ApplyRole)
        self._dialog_apply_btn = apply_btn
        apply_btn.clicked.connect(lambda: self._apply_configuration_changes(force=True))
        btn_box.accepted.connect(self._accept_configuration_changes)
        btn_box.rejected.connect(self.reject)
        root.addWidget(btn_box)
        self._select_page(self._initial_page)
        self._update_navigation_mode()

    def _make_nav_button(self, label, index, layout):
        button = QPushButton(label)
        button.setCheckable(True)
        button.setAccessibleName(label)
        button.setToolTip(label)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumHeight(scaled_px(36))
        button.clicked.connect(lambda _checked=False, page=index: self._select_page(page))
        layout.addWidget(button)
        return button

    def _select_page(self, index):
        self._page_stack.setCurrentIndex(index)
        for button in self._nav_buttons + self._top_nav_buttons:
            button.setChecked(button in (self._nav_buttons[index], self._top_nav_buttons[index]))
        self._apply_shell_theme()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_nav_rail"):
            self._update_navigation_mode()

    def _update_navigation_mode(self):
        compact = self.width() < scaled_px(800)
        self._nav_rail.setVisible(not compact)
        self._top_nav.setVisible(compact)

    def _apply_shell_theme(self):
        t = _t()
        nav_style = (
            f"QFrame {{ background: {t['base']}; border: 1px solid {t['border']}; border-radius: {scaled_px(6)}px; }}"
            f"QPushButton {{ text-align: left; background: transparent; color: {t['body']}; border: none; "
            f"border-radius: {scaled_px(4)}px; padding: {scaled_px(8)}px {scaled_px(10)}px; }}"
            f"QPushButton:hover {{ background: {t['hover_overlay']}; }}"
            f"QPushButton:checked {{ background: {t['accent']}; color: {t['on_accent']}; font-weight: bold; }}"
        )
        self._nav_rail.setStyleSheet(nav_style)
        self._top_nav.setStyleSheet(nav_style)

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
        self._apply_shell_theme()
        self._status_label.setStyleSheet(f"font-weight: bold; font-size: {scaled_pt(20)}px; color: {t['heading']};")
        self._url_label.setStyleSheet(f"font-size: {scaled_pt(15)}px; color: {t['accent']};")
        if hasattr(self, '_tunnel_url_label'):
            self._tunnel_url_label.setStyleSheet(
                f"font-size: {scaled_pt(13)}px; color: {t['accent']}; "
                f"padding: 8px; background: {t['panel']}; "
                f"border: 1px solid {t['border']}; border-radius: {scaled_px(6)}px;")
        self._apply_table_theme()
        if hasattr(self, "_configuration_nav"):
            self._apply_configuration_theme()

    def _apply_table_theme(self):
        t = _t()
        table_style = (
            f"QTableWidget {{ background: {t['panel']}; color: {t['body']}; "
            f"alternate-background-color: {alpha(t['header'], 0.18)}; "
            f"selection-background-color: {alpha(t['accent'], 0.24)}; "
            f"selection-color: {t['heading']}; "
            f"border: 1px solid {t['border']}; border-radius: {scaled_px(6)}px; outline: none; }}"
            f"QTableWidget::item {{ padding: {scaled_px(5)}px {scaled_px(8)}px; border: none; "
            f"border-bottom: 1px solid {alpha(t['border'], 0.16)}; }}"
            f"QTableWidget::item:hover {{ background: {alpha(t['accent'], 0.10)}; }}"
            f"QTableWidget::item:selected {{ background: {alpha(t['accent'], 0.24)}; color: {t['heading']}; }}"
            f"QHeaderView::section {{ background: {t['header']}; color: {t['heading']}; "
            f"padding: {scaled_px(6)}px {scaled_px(8)}px; border: none; "
            f"border-right: 1px solid {alpha(t['border'], 0.24)}; "
            f"font-weight: bold; }}"
        )
        for table in (
            getattr(self, "_links_table", None),
            getattr(self, "_codes_table", None),
            getattr(self, "_online_table", None),
        ):
            if table is None:
                continue
            table.setAlternatingRowColors(True)
            table.setShowGrid(False)
            table.verticalHeader().setDefaultSectionSize(scaled_px(30))
            table.horizontalHeader().setMinimumHeight(scaled_px(30))
            table.setStyleSheet(table_style)

    # ══════════════════════════════════════════════════════════
    # Endpoint
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

        self._status_frame = QFrame()
        endpoint_layout = QVBoxLayout(self._status_frame)
        endpoint_layout.setContentsMargins(scaled_px(16), scaled_px(16), scaled_px(16), scaled_px(16))
        endpoint_layout.setSpacing(scaled_px(10))
        status_row = QHBoxLayout()
        self._status_icon = QLabel()
        self._status_icon.setFixedSize(scaled_px(12), scaled_px(12))
        self._status_icon.setAccessibleName(tr("sharing.endpoint.status_indicator"))
        status_row.addWidget(self._status_icon)
        self._status_label = QLabel(tr("sharing.status_off"))
        self._status_label.setStyleSheet(f"font-size: {scaled_pt(20)}px; font-weight: bold; color: {t['heading']};")
        status_row.addWidget(self._status_label)
        self._exposure_label = QLabel()
        self._exposure_label.setVisible(False)
        status_row.addWidget(self._exposure_label)
        status_row.addStretch()
        self._toggle_btn = self.make_primary_btn(tr("sharing.btn_start_sharing"), self._on_primary_endpoint_action)
        self._set_action_icon(self._toggle_btn, "share")
        status_row.addWidget(self._toggle_btn)
        endpoint_layout.addLayout(status_row)

        self._url_label = QLabel()
        self._url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._url_label.setWordWrap(False)
        self._url_label.setStyleSheet(f"font-size: {scaled_pt(15)}px; color: {t['accent']};")
        endpoint_layout.addWidget(self._url_label)
        action_row = QHBoxLayout()
        self._copy_btn = self.make_secondary_btn(tr("sharing.btn_copy_link"), self._copy_link)
        self._set_action_icon(self._copy_btn, "copy")
        self._open_btn = self.make_secondary_btn(tr("sharing.btn_open"), self._open_endpoint)
        self._set_action_icon(self._open_btn, "arrow_right")
        self._qr_btn = self.make_secondary_btn(tr("sharing.qr.show"), self._show_endpoint_qr)
        self._set_action_icon(self._qr_btn, "qr_code")
        action_row.addWidget(self._copy_btn)
        action_row.addWidget(self._open_btn)
        action_row.addWidget(self._qr_btn)
        action_row.addStretch()
        endpoint_layout.addLayout(action_row)
        metadata_row = QHBoxLayout()
        metadata_row.setSpacing(scaled_px(24))
        self._ip_info, self._ip_info_value = self._make_info_pair(tr("sharing.overview.ip_address"), "—")
        self._port_info, self._port_info_value = self._make_info_pair(tr("sharing.overview.port"), "—")
        self._online_info, self._online_info_value = self._make_info_pair(tr("sharing.endpoint.connections"), "0")
        self._traffic_info, self._traffic_info_value = self._make_info_pair(tr("sharing.overview.traffic"), "0 B")
        for info in (self._ip_info, self._port_info, self._online_info, self._traffic_info):
            metadata_row.addLayout(info)
        metadata_row.addStretch()
        endpoint_layout.addLayout(metadata_row)
        layout.addWidget(self._status_frame)

        # Tunnel remains an independent exposure control; it never stops local sharing.
        from AssetsManager.lan.tunnel import is_available as is_tunnel_available
        if is_tunnel_available():
            tunnel_card, tunnel_cl = self._make_card(tr("sharing.card_tunnel"))
            self._tunnel_status = self.make_muted(tr("sharing.tunnel_not_connected"))
            tunnel_cl.addWidget(self._tunnel_status)
            self._tunnel_url_label = QLabel("")
            self._tunnel_url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._tunnel_url_label.setVisible(False)
            tunnel_cl.addWidget(self._tunnel_url_label)
            tunnel_btn_row = QHBoxLayout()
            self._tunnel_btn = self.make_primary_btn(tr("sharing.btn_start_tunnel"), self._toggle_tunnel)
            self._set_action_icon(self._tunnel_btn, "share")
            self._tunnel_copy_btn = self.make_secondary_btn(tr("sharing.btn_copy"), self._copy_tunnel_url)
            self._set_action_icon(self._tunnel_copy_btn, "copy")
            self._tunnel_copy_btn.setVisible(False)
            self._tunnel_open_btn = self.make_secondary_btn(tr("sharing.btn_open"), self._open_tunnel_url)
            self._set_action_icon(self._tunnel_open_btn, "arrow_right")
            self._tunnel_open_btn.setVisible(False)
            tunnel_btn_row.addWidget(self._tunnel_btn)
            tunnel_btn_row.addWidget(self._tunnel_copy_btn)
            tunnel_btn_row.addWidget(self._tunnel_open_btn)
            tunnel_btn_row.addStretch()
            tunnel_cl.addLayout(tunnel_btn_row)
            layout.addWidget(tunnel_card)
        else:
            self._tunnel_section = None

        activity_card, activity_cl = self._make_card(tr("sharing.card_recent_activity"))
        self._activity_list = QLabel(tr("sharing.overview.no_activity"))
        self._activity_list.setWordWrap(True)
        self._activity_list.setStyleSheet(f"color: {t['muted']}; font-size: {scaled_pt(11)}px;")
        activity_cl.addWidget(self._activity_list)
        layout.addWidget(activity_card)
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

    # ══════════════════════════════════════════════════════════
    # Tab 3: Access
    # ══════════════════════════════════════════════════════════

    def _setup_users_tab(self, parent):
        t = _t()
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(scaled_px(16), scaled_px(16), scaled_px(16), scaled_px(16))
        layout.setSpacing(scaled_px(12))

        # Keep identity available without giving it a competing section.
        user_row = QHBoxLayout()
        user_row.addWidget(self.make_label(tr("sharing.access.signed_in_as")))
        self._admin_user_label = QLabel(self._settings.get("lan_share_name", "Admin"))
        self._admin_user_label.setStyleSheet(f"font-weight: bold; color: {t['heading']};")
        user_row.addWidget(self._admin_user_label)
        role_label = QLabel(tr("sharing.users.role_admin"))
        role_label.setStyleSheet(f"color: {t['accent']}; font-weight: bold;")
        user_row.addWidget(role_label)
        user_row.addStretch()
        layout.addLayout(user_row)

        # ── Guest Access Policy ───────────────────────────────
        guest_group = self.make_groupbox(tr("sharing.access.guest_policy"))
        guest_layout = QVBoxLayout(guest_group)
        guest_layout.setSpacing(scaled_px(6))
        guest_layout.setContentsMargins(scaled_px(12), scaled_px(16), scaled_px(12), scaled_px(8))
        guest_layout.addWidget(self.make_muted(tr("sharing.access.guest_policy_immediate")))

        self._guest_download = self.make_checkbox(tr("sharing.users.guest_can_download"), checked=True)
        guest_layout.addWidget(self._guest_download)
        self._guest_preview = self.make_checkbox(tr("sharing.users.guest_can_preview"), checked=True)
        guest_layout.addWidget(self._guest_preview)
        self._guest_list = self.make_checkbox(tr("sharing.users.guest_can_list"), checked=True)
        guest_layout.addWidget(self._guest_list)
        for checkbox in (self._guest_download, self._guest_preview, self._guest_list):
            checkbox.toggled.connect(self._save_guest_permissions)
        self._guest_policy_status = self.make_muted("")
        guest_layout.addWidget(self._guest_policy_status)
        layout.addWidget(guest_group)

        # ── Invitations ───────────────────────────────────────
        invite_group = self.make_groupbox(tr("sharing.access.invitations"))
        invite_layout = QVBoxLayout(invite_group)
        invite_layout.setSpacing(scaled_px(8))
        invite_layout.setContentsMargins(scaled_px(12), scaled_px(16), scaled_px(12), scaled_px(8))

        invite_btn_row = QHBoxLayout()
        self._generate_code_btn = self.make_primary_btn(tr("sharing.access.generate_invitation"), self._generate_invite_code)
        self._generate_code_btn.setAccessibleName(tr("sharing.access.generate_invitation"))
        invite_btn_row.addWidget(self._generate_code_btn)
        invite_btn_row.addStretch()
        invite_layout.addLayout(invite_btn_row)

        self._codes_table = QTableWidget()
        self._codes_table.setColumnCount(3)
        self._codes_table.setHorizontalHeaderLabels([
            tr("sharing.users.code"),
            tr("sharing.users.code_status"),
            tr("sharing.users.code_created"),
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

        self._apply_table_theme()
        invite_layout.addWidget(self._codes_table)

        invite_footer = QHBoxLayout()
        self._copy_code_btn = self.make_secondary_btn(tr("sharing.users.btn_copy_code"), self._copy_selected_invite)
        self._copy_code_btn.setEnabled(False)
        self._revoke_code_btn = self.make_secondary_btn(tr("sharing.users.btn_revoke"), self._revoke_selected_invite)
        self._revoke_code_btn.setEnabled(False)
        invite_footer.addWidget(self._copy_code_btn)
        invite_footer.addWidget(self._revoke_code_btn)
        invite_footer.addStretch()
        self._codes_status = self.make_muted(tr("sharing.users.no_codes"))
        invite_footer.addWidget(self._codes_status)
        invite_layout.addLayout(invite_footer)
        layout.addWidget(invite_group)
        self._codes_table.itemSelectionChanged.connect(self._on_invite_selection_changed)

        # ── Connected Users ───────────────────────────────────
        online_group = self.make_groupbox(tr("sharing.access.connected_users"))
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
        layout.addStretch()

    # ══════════════════════════════════════════════════════════
    # Tab 4: Settings
    # ══════════════════════════════════════════════════════════

    def _setup_settings_tab(self, parent):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(scaled_px(12), scaled_px(12), scaled_px(12), scaled_px(12))
        layout.setSpacing(scaled_px(10))

        body = QHBoxLayout()
        body.setSpacing(scaled_px(12))
        self._configuration_nav = QFrame()
        self._configuration_nav.setFixedWidth(scaled_px(170))
        nav_layout = QVBoxLayout(self._configuration_nav)
        nav_layout.setContentsMargins(scaled_px(6), scaled_px(6), scaled_px(6), scaled_px(6))
        nav_layout.setSpacing(scaled_px(4))
        self._configuration_stack = QStackedWidget()
        self._configuration_nav_buttons = []

        def section(key):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(scaled_px(12), scaled_px(8), scaled_px(12), scaled_px(8))
            page_layout.setSpacing(scaled_px(10))
            heading = self.make_heading(tr(f"sharing.configuration.{key}"))
            heading.setStyleSheet(f"font-size: {scaled_pt(15)}px; color: {_t()['heading']};")
            page_layout.addWidget(heading)
            description = self.make_muted(tr(f"sharing.configuration.{key}_desc"))
            description.setWordWrap(True)
            page_layout.addWidget(description)
            page_layout.addSpacing(scaled_px(4))
            self._configuration_stack.addWidget(page)
            index = self._configuration_stack.count() - 1
            button = self._make_configuration_nav_button(tr(f"sharing.configuration.{key}"), index, nav_layout)
            self._configuration_nav_buttons.append(button)
            return page_layout

        # Network
        nl = section("network")

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

        nl.addStretch()

        # Protection
        sl = section("protection")

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

        sl.addStretch()

        # Presentation
        bl = section("presentation")

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

        bl.addStretch()

        # Library scope
        al = section("library_scope")

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

        al.addStretch()

        # Diagnostics
        dl = section("diagnostics")
        self._enable_log = self.make_checkbox(tr("sharing.enable_access_log"))
        dl.addWidget(self._enable_log)
        log_path_row, self._log_path = self.make_browse_row(tr("sharing.label_log_path"), tr("sharing.placeholder_log_path"), self._browse_log_path)
        dl.addLayout(log_path_row)
        rotation_row = QHBoxLayout()
        rotation_row.addWidget(self.make_label(tr("sharing.label_log_rotation")))
        self._log_rotation = self.make_spinbox(1, 100, 10)
        rotation_row.addWidget(self._log_rotation)
        rotation_row.addWidget(self.make_muted(tr("sharing.helper_mb_per_file")))
        rotation_row.addStretch()
        dl.addLayout(rotation_row)
        dl.addStretch()

        # Internet access is omitted when the tunnel dependency is unavailable.
        from AssetsManager.lan.tunnel import is_available as is_tunnel_available
        if is_tunnel_available():
            tl = section("internet_access")

            self._settings_tunnel_status = self.make_muted(tr("sharing.tunnel_not_connected"))
            tl.addWidget(self._settings_tunnel_status)

            self._settings_tunnel_url = QLabel("")
            self._settings_tunnel_url.setStyleSheet(
                f"font-size: {scaled_pt(13)}px; color: {themes.get()['accent']};")
            self._settings_tunnel_url.setVisible(False)
            tl.addWidget(self._settings_tunnel_url)

            tl.addStretch()

        nav_layout.addStretch()
        body.addWidget(self._configuration_nav)
        body.addWidget(self._configuration_stack, 1)
        layout.addLayout(body, 1)

        self._configuration_summary = QFrame()
        summary_layout = QHBoxLayout(self._configuration_summary)
        summary_layout.setContentsMargins(scaled_px(10), scaled_px(8), scaled_px(10), scaled_px(8))
        self._configuration_summary_label = QLabel()
        self._configuration_summary_label.setWordWrap(True)
        summary_layout.addWidget(self._configuration_summary_label, 1)
        self._configuration_discard_btn = self.make_secondary_btn(tr("sharing.configuration.discard"), self._discard_configuration_changes)
        summary_layout.addWidget(self._configuration_discard_btn)
        self._configuration_apply_btn = self.make_primary_btn(tr("sharing.configuration.apply"), self._apply_configuration_changes)
        summary_layout.addWidget(self._configuration_apply_btn)
        layout.addWidget(self._configuration_summary)
        self._select_configuration_section(0)
        self._connect_configuration_tracking()
        self._apply_configuration_theme()

    def _make_configuration_nav_button(self, label, index, layout):
        button = QPushButton(label)
        button.setCheckable(True)
        button.setAccessibleName(label)
        button.setToolTip(label)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMinimumHeight(scaled_px(34))
        button.clicked.connect(lambda _checked=False, section_index=index: self._select_configuration_section(section_index))
        layout.addWidget(button)
        return button

    def _select_configuration_section(self, index):
        self._configuration_stack.setCurrentIndex(index)
        for button_index, button in enumerate(self._configuration_nav_buttons):
            button.setChecked(button_index == index)

    def _apply_configuration_theme(self):
        t = _t()
        nav_style = (
            f"QFrame {{ background: {t['base']}; border: 1px solid {t['border']}; border-radius: {scaled_px(6)}px; }}"
            f"QPushButton {{ text-align: left; background: transparent; color: {t['body']}; border: none; "
            f"border-radius: {scaled_px(4)}px; padding: {scaled_px(7)}px {scaled_px(8)}px; }}"
            f"QPushButton:hover {{ background: {t['hover_overlay']}; }}"
            f"QPushButton:checked {{ background: {t['accent']}; color: {t['on_accent']}; font-weight: bold; }}"
        )
        self._configuration_nav.setStyleSheet(nav_style)
        self._configuration_summary.setStyleSheet(
            f"QFrame {{ background: {t['panel']}; border: 1px solid {t['border']}; border-radius: {scaled_px(6)}px; }}"
        )

    def _connect_configuration_tracking(self):
        tracked_widgets = (
            self._name_edit, self._port_spin, self._bind_combo, self._auto_start, self._auth_combo,
            self._pw_edit, self._max_conn, self._timeout, self._rate_limit, self._blocked_ips,
            self._ip_whitelist, self._ssl_cert, self._ssl_key, self._color_edit, self._welcome_edit,
            self._footer_edit, self._show_hidden, self._max_depth, self._exclude_patterns,
            self._blur_tags, self._enable_log, self._log_path, self._log_rotation,
        ) + tuple(self._type_checks.values())
        for widget in tracked_widgets:
            signal = getattr(widget, "textChanged", None) or getattr(widget, "valueChanged", None) or getattr(widget, "toggled", None) or getattr(widget, "currentIndexChanged", None)
            if signal is not None:
                signal.connect(self._update_configuration_summary)

    @staticmethod
    def _lines(widget):
        return [line.strip() for line in widget.toPlainText().splitlines() if line.strip()]

    def _configuration_values(self):
        return {
            "lan_share_name": self._name_edit.text() or "AssetManager",
            "lan_port": self._port_spin.value(),
            "lan_bind": "0.0.0.0" if self._bind_combo.currentIndex() == 0 else "127.0.0.1",
            "lan_auto_start": self._auto_start.isChecked(),
            "lan_auth_mode": self._auth_mode(),
            # Existing password remains unchanged unless the user explicitly enters one.
            "lan_password": self._pw_edit.text() if self._pw_edit.text() else None,
            "lan_max_connections": self._max_conn.value(),
            "lan_session_timeout": self._timeout.value(),
            "lan_rate_limit": self._rate_limit.value(),
            "lan_blocked_ips": self._lines(self._blocked_ips),
            "lan_ip_whitelist": self._lines(self._ip_whitelist),
            "lan_ssl_cert": self._ssl_cert.text() or None,
            "lan_ssl_key": self._ssl_key.text() or None,
            "lan_theme_color": self._color_edit.text() or "#5b7ff5",
            "lan_welcome_msg": self._welcome_edit.toPlainText(),
            "lan_footer_text": self._footer_edit.text(),
            "lan_include_types": [key for key, check in self._type_checks.items() if check.isChecked()],
            "lan_show_hidden": self._show_hidden.isChecked(),
            "lan_max_depth": self._max_depth.value(),
            "lan_exclude_patterns": self._lines(self._exclude_patterns),
            "lan_blur_tags": self._lines(self._blur_tags),
            "lan_enable_log": self._enable_log.isChecked(),
            "lan_log_path": self._log_path.text(),
            "lan_log_rotation_mb": self._log_rotation.value(),
        }

    def _configuration_changes(self):
        values = self._configuration_values()
        changes = {key for key, value in values.items() if self._configuration_snapshot.get(key) != value}
        if "lan_password" in changes and not values["lan_password"]:
            changes.remove("lan_password")
        return changes

    def _update_configuration_summary(self, *_args):
        if getattr(self, "_loading_settings", False) or not hasattr(self, "_configuration_snapshot"):
            return
        changes = self._configuration_changes()
        live_count = len(changes & HOT_SHARING_SETTINGS.keys())
        restart_count = len(changes & RESTART_SHARING_SETTINGS)
        saved_count = len(changes - HOT_SHARING_SETTINGS.keys() - RESTART_SHARING_SETTINGS)
        if not changes:
            text = tr("sharing.configuration.no_unsaved_changes")
        else:
            text = tr("sharing.configuration.change_summary").format(
                live=live_count, restart=restart_count, saved=saved_count)
        self._configuration_summary_label.setText(text)
        self._configuration_discard_btn.setEnabled(bool(changes))
        self._configuration_apply_btn.setEnabled(bool(changes))

    def _discard_configuration_changes(self):
        self._loading_settings = True
        try:
            self._load_settings()
        finally:
            self._loading_settings = False
        self._sync_configuration_snapshot()
        self._update_configuration_summary()

    def _sync_configuration_snapshot(self):
        if hasattr(self, "_name_edit"):
            self._configuration_snapshot = self._configuration_values()

    def _apply_configuration_changes(self, force=False):
        if not force and not self._configuration_changes():
            return
        self._save_settings()
        self._sync_configuration_snapshot()
        self.settings_changed.emit()
        self._update_configuration_summary()

    def _accept_configuration_changes(self):
        self._apply_configuration_changes(force=True)
        self.accept()

    # ══════════════════════════════════════════════════════════
    # Overview: Status & Actions
    # ══════════════════════════════════════════════════════════

    def _set_action_icon(self, button: QPushButton, icon_name: str) -> None:
        """Register a semantic icon so TabbedDialog refreshes it with the theme."""
        button.setProperty("semanticIcon", icon_name)
        button.setProperty("semanticIconColor", "heading")
        self._refresh_semantic_button_icons()

    def _update_status(self):
        t = _t()
        tunnel_running = bool(self._server and hasattr(self._server, "is_tunnel_running") and self._server.is_tunnel_running())
        state = _endpoint_state(self._server_status, tunnel_running)
        action = _endpoint_primary_action(state)
        details = {
            "off": (tr("sharing.status_off"), t["muted"], tr("sharing.btn_start_sharing")),
            "starting": (tr("sharing.btn_connecting"), t["accent"], tr("sharing.btn_connecting")),
            "local": (tr("sharing.status_active"), t["success"], tr("sharing.btn_stop_sharing")),
            "public": (tr("sharing.status_active"), t["success"], tr("sharing.btn_stop_tunnel")),
            "failed": (tr("sharing.endpoint.failed"), t["danger"], tr("sharing.endpoint.try_again")),
        }
        label, color, action_label = details[state]
        action_icon = {
            "off": "share",
            "starting": "refresh",
            "local": "close",
            "public": "close",
            "failed": "refresh",
        }[state]
        self._status_icon.setStyleSheet(
            f"background: {color}; border-radius: {scaled_px(6)}px; border: none;")
        self._status_label.setText(label)
        self._toggle_btn.setText(action_label)
        self._set_action_icon(self._toggle_btn, action_icon)
        self._toggle_btn.setEnabled(action != "busy")
        self._toggle_btn.setStyleSheet(self.toggle_btn_style(action in {"stop_server", "stop_tunnel"}))
        self._status_frame.setStyleSheet(self.status_style(state in {"local", "public"}))
        local_url = self._server_status.get("url", "")
        public_url = self._tunnel_url_label.text() if state == "public" and hasattr(self, "_tunnel_url_label") else ""
        url = public_url or local_url
        self._url_label.setText(url)
        self._url_label.setVisible(bool(url))
        self._copy_btn.setVisible(bool(url))
        self._open_btn.setVisible(bool(url))
        self._qr_btn.setVisible(bool(url))
        self._ip_info_value.setText(self._server_status.get("ip", "—") if local_url else "—")
        self._port_info_value.setText(str(self._server_status.get("port", "—")) if local_url else "—")
        self._online_info_value.setText(str(self._server_status.get("connections", 0)))
        self._traffic_info_value.setText(self._format_bytes(self._server_status.get("bytes_transferred", 0)))
        self._exposure_label.setVisible(state == "public")
        if state == "public":
            self._exposure_label.setText(tr("sharing.endpoint.internet_access"))
            self._exposure_label.setStyleSheet(
                f"color: {t['heading']}; background: {t['warning']}; border-radius: {scaled_px(3)}px; "
                f"padding: {scaled_px(3)}px {scaled_px(6)}px;")

    def _on_primary_endpoint_action(self):
        """Keep local server and public-tunnel scopes distinct on the Endpoint page."""
        tunnel_running = bool(self._server and hasattr(self._server, "is_tunnel_running") and self._server.is_tunnel_running())
        state = _endpoint_state(self._server_status, tunnel_running)
        if _endpoint_primary_action(state) == "stop_tunnel":
            self._toggle_tunnel()
        else:
            self._on_toggle_server()

    def _show_endpoint_qr(self):
        url = self._url_label.text()
        if not url:
            return
        from AssetsManager.dialogs.share_qr_dialog import ShareQrDialog
        ShareQrDialog(self, url).exec()

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
        self._sync_configuration_snapshot()
        self._update_configuration_summary()

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
        if self._server and self._server.is_running():
            self.settings_changed.emit()

    def _copy_link(self):
        url = self._server_status.get("url", "")
        if url:
            QApplication.clipboard().setText(url)
            Toast.instance(self, tr("sharing.toast.copied"), level="success")
            self._copy_btn.setText(tr("sharing.copied"))
            QTimer.singleShot(1500, lambda: self._copy_btn.setText(tr("sharing.btn_copy_link")))

    def _open_endpoint(self):
        url = self._server_status.get("url", "")
        if url:
            QDesktopServices.openUrl(QUrl(url))

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

    def _open_create_link_dialog(self):
        """Open the canonical creator from the Links page."""
        if not self._server or not self._server.is_running():
            self._links_status.setText(tr("sharemgr.error.server_unavailable"))
            return
        from AssetsManager.dialogs.share_link_dialog import ShareLinkDialog

        dialog = ShareLinkDialog(self, paths=[], server=self._server)
        if dialog.exec():
            self._load_share_links()

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
        if success:
            self._invite_codes = data.get("invites", data) if isinstance(data, dict) else (data or [])
            self._populate_codes_table()
        else:
            self._codes_status.setText(tr("sharing.access.invites_load_failed"))

    def _populate_codes_table(self):
        if not isinstance(self._invite_codes, list):
            self._invite_codes = []
        self._codes_table.setRowCount(len(self._invite_codes))
        for i, code_data in enumerate(self._invite_codes):
            code = code_data if isinstance(code_data, str) else code_data.get("code", str(code_data))
            self._codes_table.setItem(i, 0, QTableWidgetItem(str(code)))

            status = code_data.get("status", "active") if isinstance(code_data, dict) else "active"
            self._codes_table.setItem(i, 1, QTableWidgetItem(status))

            created = code_data.get("created", "—") if isinstance(code_data, dict) else "—"
            self._codes_table.setItem(i, 2, QTableWidgetItem(str(created)))

        self._codes_status.setText(
            tr("sharing.access.invitation_count").format(count=len(self._invite_codes))
            if self._invite_codes else tr("sharing.users.no_codes"))
        self._on_invite_selection_changed()

    def _on_invite_selection_changed(self):
        has_selection = bool(self._codes_table.selectionModel().selectedRows())
        self._copy_code_btn.setEnabled(has_selection)
        self._revoke_code_btn.setEnabled(has_selection)

    def _selected_invite_row(self):
        rows = self._codes_table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def _copy_selected_invite(self):
        row = self._selected_invite_row()
        if row is None or row >= len(self._invite_codes):
            return
        code_data = self._invite_codes[row]
        code = code_data if isinstance(code_data, str) else code_data.get("code", "")
        if code:
            QApplication.clipboard().setText(str(code))
            self._codes_status.setText(tr("sharing.access.invitation_copied"))

    def _revoke_selected_invite(self):
        row = self._selected_invite_row()
        if row is not None:
            self._revoke_invite_code(row)

    def _generate_invite_code(self):
        base = self._get_api_base()
        if not base:
            self._codes_status.setText(tr("sharing.access.invites_unavailable"))
            return
        headers = self._get_auth_headers()
        self._generate_code_btn.setEnabled(False)
        self._codes_status.setText(tr("sharing.access.invitation_generating"))
        task = ShareApiTask("POST", f"{base}/api/invites/create", headers, success_statuses=(200, 201))
        task.signals.finished.connect(lambda ok, data: self._on_generate_code_result(ok, data))
        QThreadPool.globalInstance().start(task)
        self._gen_task = task

    def _on_generate_code_result(self, success, data):
        self._generate_code_btn.setEnabled(True)
        if success:
            self._codes_status.setText(tr("sharing.access.invitation_generated"))
            self._load_invite_codes()
            self._data_changed.emit()
        else:
            self._codes_status.setText(tr("sharing.access.invitation_generate_failed"))

    def _revoke_invite_code(self, row):
        if row < 0 or row >= len(self._invite_codes):
            return
        code_data = self._invite_codes[row]
        code = code_data if isinstance(code_data, str) else code_data.get("code", "")
        if not code:
            return
        base = self._get_api_base()
        if not base:
            self._codes_status.setText(tr("sharing.access.invites_unavailable"))
            return
        headers = self._get_auth_headers()
        self._copy_code_btn.setEnabled(False)
        self._revoke_code_btn.setEnabled(False)
        self._codes_status.setText(tr("sharing.access.invitation_revoking"))
        task = ShareApiTask("DELETE", f"{base}/api/invites/{code}/revoke", headers)
        task.signals.finished.connect(lambda ok, _: self._on_revoke_result(ok, row))
        QThreadPool.globalInstance().start(task)
        self._revoke_task = task

    def _on_revoke_result(self, success, row):
        if success:
            if 0 <= row < len(self._invite_codes):
                self._invite_codes.pop(row)
            self._populate_codes_table()
            self._codes_status.setText(tr("sharing.access.invitation_revoked"))
            self._data_changed.emit()
        else:
            self._on_invite_selection_changed()
            self._codes_status.setText(tr("sharing.access.invitation_revoke_failed"))

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
        if success:
            self._online_users = data.get("users", data) if isinstance(data, dict) else (data or [])
            self._populate_online_table()
        else:
            self._online_status.setText(tr("sharing.access.connected_users_load_failed"))

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
            tr("sharing.access.connected_user_count").format(count=len(self._online_users))
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
                        lines.append(f"{time_str}: {msg}" if time_str else str(msg))
                    else:
                        lines.append(str(item))
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
            self._set_action_icon(self._tunnel_btn, "share")
            self._tunnel_btn.setStyleSheet(self.primary_btn_style())
            self._tunnel_status.setText(tr("sharing.tunnel_not_connected"))
            self._tunnel_status.setStyleSheet(f"font-size: {scaled_pt(12)}px; color: {t['muted']};")
            self._tunnel_url_label.setVisible(False)
            self._tunnel_copy_btn.setVisible(False)
            self._tunnel_open_btn.setVisible(False)
            self._update_status()
            self._data_changed.emit()
        else:
            self._tunnel_btn.setEnabled(False)
            self._tunnel_btn.setText(tr("sharing.btn_connecting"))
            self._set_action_icon(self._tunnel_btn, "refresh")
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
            self._set_action_icon(self._tunnel_btn, "close")
            self._tunnel_btn.setStyleSheet(self.toggle_btn_style(True))
            self._tunnel_btn.setEnabled(True)
            self._tunnel_copy_btn.setVisible(True)
            self._tunnel_open_btn.setVisible(True)
            self._update_status()
            self._data_changed.emit()
        else:
            self._tunnel_status.setText(tr("sharing.tunnel_failed"))
            self._tunnel_status.setStyleSheet(f"font-size: {scaled_pt(12)}px; color: {t['danger']};")
            self._tunnel_btn.setText(tr("sharing.btn_start_tunnel"))
            self._set_action_icon(self._tunnel_btn, "share")
            self._tunnel_btn.setStyleSheet(self.primary_btn_style())
            self._tunnel_btn.setEnabled(True)
            self._update_status()
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
        self._configuration_snapshot = self._configuration_values()
        self._update_configuration_summary()

    def _on_apply(self):
        self._apply_configuration_changes()

    def _save_guest_permissions(self):
        """Persist guest policy immediately; routes read these settings per request."""
        if getattr(self, "_loading_settings", False):
            return
        s = self._settings
        s.set("lan_guest_download", self._guest_download.isChecked())
        s.set("lan_guest_preview", self._guest_preview.isChecked())
        s.set("lan_guest_list", self._guest_list.isChecked())
        s.save()
        self._guest_policy_status.setText(tr("sharing.access.guest_policy_saved"))

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
