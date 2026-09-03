"""Access page construction for the sharing settings dialog."""
from typing import Any

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.widgets.stylekit import StyleKit
from AssetsManager import i18n

tr = i18n.tr


class AccessPageMixin:
    """Access page: guest policy, invitations, and connected-users tables."""

    # Widgets built by _setup_users_tab.
    _admin_user_label: QLabel
    _guest_download: QCheckBox
    _guest_preview: QCheckBox
    _guest_list: QCheckBox
    _guest_policy_status: QLabel
    _generate_code_btn: QPushButton
    _codes_table: QTableWidget
    _copy_code_btn: QPushButton
    _revoke_code_btn: QPushButton
    _codes_status: QLabel
    _online_table: QTableWidget
    _online_status: QLabel

    # Runtime data owned by the main dialog.
    _settings: Any
    _invite_codes: list
    _online_users: list

    # Supplied by the main dialog, TabbedDialog, or SharedUiMixin.
    make_label: Any
    make_groupbox: Any
    make_muted: Any
    make_checkbox: Any
    make_primary_btn: Any
    make_secondary_btn: Any
    _apply_table_theme: Any
    _on_invite_selection_changed: Any
    _generate_invite_code: Any
    _copy_selected_invite: Any
    _revoke_selected_invite: Any
    _save_guest_permissions: Any

    def _setup_users_tab(self, parent):
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(scaled_px(16), scaled_px(16), scaled_px(16), scaled_px(16))
        layout.setSpacing(scaled_px(12))

        # Keep identity available without giving it a competing section.
        user_row = QHBoxLayout()
        user_row.addWidget(self.make_label(tr("sharing.access.signed_in_as")))
        self._admin_user_label = QLabel(self._settings.get("lan_share_name", "Admin"))
        self._admin_user_label.setStyleSheet(sk.label_css("heading", bold=True))
        user_row.addWidget(self._admin_user_label)
        role_label = QLabel(tr("sharing.users.role_admin"))
        role_label.setStyleSheet(sk.label_css("accent", bold=True))
        user_row.addWidget(role_label)
        self._access_role_label = role_label
        self._apply_access_theme()
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

    def _apply_access_theme(self):
        """Re-derive access-page label styles from current tokens (B2⑧)."""
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        for label in (
            getattr(self, "_admin_user_label", None),
            getattr(self, "_access_role_label", None),
        ):
            if label is None:
                continue
            try:
                label.setStyleSheet(sk.label_css(
                    "accent" if label is self._access_role_label else "heading",
                    bold=True))
            except RuntimeError:
                pass
