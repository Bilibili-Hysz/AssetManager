"""Configuration page construction for the sharing settings dialog."""
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QFrame, QWidget, QStackedWidget, QComboBox, QSpinBox, QCheckBox,
)

from AssetsManager.core import themes
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.constants import DEFAULT_LAN_THEME_COLOR
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.widgets.stylekit import StyleKit
from AssetsManager import i18n
from AssetsManager.dialogs._sharing_helpers import _t
from AssetsManager.application.desktop_ports import ShareSettingsPort

tr = i18n.tr


class ConfigurationPageMixin:
    """Configuration page: section navigation and the settings form itself."""

    # Widgets built by _setup_settings_tab.
    _configuration_nav: QFrame
    _configuration_stack: QStackedWidget
    _configuration_nav_buttons: list
    _name_edit: QLineEdit
    _port_spin: QSpinBox
    _bind_combo: QComboBox
    _auto_start: QCheckBox
    _ssl_cert: QLineEdit
    _ssl_key: QLineEdit
    _auth_combo: QComboBox
    _pw_widget: QWidget
    _pw_edit: QLineEdit
    _pw_show: QCheckBox
    _auth_error_label: QLabel
    _max_conn: QSpinBox
    _timeout: QSpinBox
    _rate_limit: QSpinBox
    _blocked_ips: QTextEdit
    _ip_whitelist: QTextEdit
    _color_edit: QLineEdit
    _welcome_edit: QTextEdit
    _footer_edit: QLineEdit
    _type_checks: dict
    _show_hidden: QCheckBox
    _max_depth: QSpinBox
    _exclude_patterns: QTextEdit
    _blur_tags: QTextEdit
    _enable_log: QCheckBox
    _log_path: QLineEdit
    _log_rotation: QSpinBox
    _quota_enabled: QCheckBox
    _quota_period: QComboBox
    _quota_limit: QSpinBox
    _quota_min_interval: QSpinBox
    _settings_tunnel_status: QLabel
    _settings_tunnel_url: QLabel
    _configuration_summary: QFrame
    _configuration_summary_label: QLabel
    _configuration_discard_btn: QPushButton
    _configuration_apply_btn: QPushButton

    # Supplied by the main dialog or TabbedDialog.
    _sharing_port: ShareSettingsPort
    make_heading: Any
    make_muted: Any
    make_input: Any
    make_labeled_row: Any
    make_label: Any
    make_spinbox: Any
    make_combobox: Any
    make_checkbox: Any
    make_browse_row: Any
    make_secondary_btn: Any
    make_primary_btn: Any
    _browse_file: Any
    _browse_log_path: Any
    _on_auth_changed: Any
    _clear_auth_error: Any
    _discard_configuration_changes: Any
    _apply_configuration_changes: Any
    _update_configuration_summary: Any

    def _setup_settings_tab(self, parent):
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
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
            heading.setStyleSheet(sk.label_css("heading", size=15))
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

        self._auth_error_label = self.make_muted("")
        self._auth_error_label.setWordWrap(True)
        self._auth_error_label.setVisible(False)
        sl.addWidget(self._auth_error_label)
        self._pw_edit.textChanged.connect(self._clear_auth_error)

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
        self._color_edit = self.make_input(DEFAULT_LAN_THEME_COLOR)
        color_row.addWidget(self._color_edit)
        reset_btn = self.make_secondary_btn(tr("sharing.btn_reset"), lambda: self._color_edit.setText(DEFAULT_LAN_THEME_COLOR))
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

        # Free download quota switches
        cl = section("quota")
        self._quota_enabled = self.make_checkbox(tr("sharing.quota.enabled"))
        cl.addWidget(self._quota_enabled)
        quota_desc = self.make_muted(tr("sharing.quota.enabled_desc"))
        quota_desc.setWordWrap(True)
        cl.addWidget(quota_desc)

        quota_period_row = QHBoxLayout()
        quota_period_row.addWidget(self.make_label(tr("sharing.quota.period")))
        self._quota_period = self.make_combobox([
            tr("sharing.quota.daily"),
            tr("sharing.quota.weekly"),
        ])
        self._quota_period.setItemData(0, "daily")
        self._quota_period.setItemData(1, "weekly")
        quota_period_row.addWidget(self._quota_period)
        quota_period_row.addSpacing(scaled_px(12))
        quota_period_row.addWidget(self.make_label(tr("sharing.quota.limit")))
        self._quota_limit = self.make_spinbox(1, 1_000_000, 20)
        quota_period_row.addWidget(self._quota_limit)
        quota_period_row.addStretch()
        cl.addLayout(quota_period_row)

        quota_interval_row = QHBoxLayout()
        quota_interval_row.addWidget(self.make_label(tr("sharing.quota.min_interval")))
        self._quota_min_interval = self.make_spinbox(0, 86_400, 5)
        quota_interval_row.addWidget(self._quota_min_interval)
        quota_interval_row.addWidget(self.make_muted(tr("sharing.quota.min_interval_desc")))
        quota_interval_row.addStretch()
        cl.addLayout(quota_interval_row)
        self._quota_enabled.toggled.connect(self._on_quota_toggled)
        self._refresh_quota_controls()
        cl.addStretch()

        # Internet access is omitted when the tunnel dependency is unavailable.
        if self._sharing_port.tunnel_is_available():
            tl = section("internet_access")

            self._settings_tunnel_status = self.make_muted(tr("sharing.tunnel_not_connected"))
            tl.addWidget(self._settings_tunnel_status)

            self._settings_tunnel_url = QLabel("")
            self._settings_tunnel_url.setStyleSheet(sk.label_css("accent", size=13))
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
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        radius = scaled_px(int(themes.prop("border_radius", "sm")))
        pad_y = scaled_px(int(themes.prop("spacing", "sm")))
        pad_x = scaled_px(int(themes.prop("spacing", "sm")))
        hover_bg = alpha(t["hover_overlay"], themes.prop("opacity", "hover"))
        focus_color = t.get("border_focus", t["accent"])
        pressed_bg = alpha(t["accent"], 0.18)
        nav_style = (
            f"QFrame {{ background: {t['base']}; border: {scaled_px(1)}px solid {t['border_subtle']}; "
            f"border-radius: {radius}px; }}"
            f"QPushButton {{ text-align: left; background: transparent; color: {t['body']}; border: none; "
            f"border-radius: {radius}px; padding: {pad_y}px {pad_x}px; }}"
            f"QPushButton:hover {{ background: {hover_bg}; }}"
            f"QPushButton:pressed {{ background: {pressed_bg}; }}"
            f"QPushButton:focus {{ background: {hover_bg}; border: {scaled_px(1)}px solid {focus_color}; }}"
            f"QPushButton:checked {{ background: {t['accent']}; color: {t['on_accent']}; font-weight: bold; }}"
        )
        self._configuration_nav.setStyleSheet(nav_style)
        self._configuration_summary.setStyleSheet(
            f"QFrame {{ background: {sk.token('panel')}; border: {scaled_px(1)}px solid {sk.token('border_subtle')}; "
            f"border-radius: {radius}px; }}"
        )

    def _connect_configuration_tracking(self):
        tracked_widgets = (
            self._name_edit, self._port_spin, self._bind_combo, self._auto_start, self._auth_combo,
            self._pw_edit, self._max_conn, self._timeout, self._rate_limit, self._blocked_ips,
            self._ip_whitelist, self._ssl_cert, self._ssl_key, self._color_edit, self._welcome_edit,
            self._footer_edit, self._show_hidden, self._max_depth, self._exclude_patterns,
            self._blur_tags, self._enable_log, self._log_path, self._log_rotation,
            self._quota_enabled, self._quota_period, self._quota_limit, self._quota_min_interval,
        ) + tuple(self._type_checks.values())
        for widget in tracked_widgets:
            signal = getattr(widget, "textChanged", None) or getattr(widget, "valueChanged", None) or getattr(widget, "toggled", None) or getattr(widget, "currentIndexChanged", None)
            if signal is not None:
                signal.connect(self._update_configuration_summary)

    def _on_quota_toggled(self, _enabled):
        self._refresh_quota_controls()
        self._update_configuration_summary()

    def _refresh_quota_controls(self):
        enabled = self._quota_enabled.isChecked()
        self._quota_period.setEnabled(enabled)
        self._quota_limit.setEnabled(enabled)
        self._quota_min_interval.setEnabled(enabled)
