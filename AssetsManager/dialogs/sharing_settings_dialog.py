"""Share System management shell and its endpoint, link, access, and settings pages."""
import logging
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QRunnable, QThreadPool
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton,
    QFrame, QFileDialog, QWidget, QApplication,
    QMessageBox, QStackedWidget, QDialogButtonBox,
)
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from AssetsManager.core import themes
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.constants import DEFAULT_LAN_THEME_COLOR
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.core.settings import AppSettings
from AssetsManager.application.desktop_ports import (
    FallbackShareSettingsPort,
    LanControlPort,
    ShareSettingsPort,
)
from AssetsManager.domain.auth import hash_password
from AssetsManager.dialogs.tabbed_dialog import TabbedDialog
from AssetsManager.dialogs.sharing_settings import (
    SharedUiMixin,
    EndpointPageMixin,
    LinksPageMixin,
    AccessPageMixin,
    ConfigurationPageMixin,
)
from AssetsManager.dialogs._share_api import ShareApiTask
from AssetsManager.dialogs._sharing_helpers import (
    _msg,
    _t,
    _endpoint_state,
    _endpoint_primary_action,
)
from AssetsManager.widgets.stylekit import StyleKit
from AssetsManager.widgets.toast import Toast
from AssetsManager import i18n
from AssetsManager.widgets.sharing_contracts import (
    HOT_SHARING_SETTINGS,
    RESTART_SHARING_SETTINGS,
    confirm_security_preflight,
)

tr = i18n.tr
_log = logging.getLogger(__name__)

# ── Dialog-local configuration classification ─────────────────
# Keys rendered by this dialog that have no server-side consumer yet.
# The change summary reports them as "planned" instead of implying they are
# saved for the next start; wiring them up server-side is out of scope here.
_PLANNED_ONLY_SETTINGS = frozenset({
    "lan_max_connections",
    "lan_session_timeout",
    "lan_enable_log",
    "lan_log_path",
    "lan_log_rotation_mb",
})

# Feature switches read per-request by LAN routes (quota.py, commerce_policy.py,
# shop_authorization.py), so they take effect as soon as settings are persisted.
# They are not listed in sharing_contracts.HOT_SHARING_SETTINGS (server
# reload_settings), so the dialog adds them to its live bucket itself.
_DIALOG_LIVE_SETTINGS = frozenset({
    "lan_commerce_enabled",
    "lan_seller_enabled",
    "lan_shop_authorized_roots",
    "lan_quota_enabled",
    "lan_quota_period",
    "lan_quota_limit",
    "lan_quota_min_interval_seconds",
})


class SharingSettingsDialog(
    TabbedDialog,
    SharedUiMixin,
    EndpointPageMixin,
    LinksPageMixin,
    AccessPageMixin,
    ConfigurationPageMixin,
):
    """Dedicated Share System shell while retaining existing page behavior."""

    settings_changed = Signal()
    _data_changed = Signal()

    def __init__(
        self, parent=None, server_status: dict | None = None,
        server: LanControlPort | None = None, initial_page: int | str = 0,
        desktop_port: ShareSettingsPort | None = None,
    ):
        self._settings = AppSettings.instance()
        self._host = parent
        self._server_status = server_status or {}
        self._server = server
        self._sharing_port = (
            desktop_port if desktop_port is not None else FallbackShareSettingsPort()
        )
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
        self._closed = False
        if self._server and self._server.is_running():
            self._status_timer.start()
            self._load_share_links()
            self._load_activity()
            self._load_online_users()
            self._load_invite_codes()

    def _build_ui(self):
        """Build a desktop navigation shell with a compact top-nav fallback."""
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        self.setStyleSheet(self._dialog_qss())
        root = QVBoxLayout(self)
        root.setContentsMargins(scaled_px(16), scaled_px(16), scaled_px(16), scaled_px(12))
        root.setSpacing(scaled_px(12))

        header = QHBoxLayout()
        title = self.make_heading(tr("sharing.dialog_title"))
        title.setStyleSheet(sk.label_css("heading", size=18, bold=True))
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
        radius = scaled_px(int(themes.prop("border_radius", "sm")))
        pad_y = scaled_px(int(themes.prop("spacing", "sm")))
        pad_x = scaled_px(int(themes.prop("spacing", "md")))
        hover_bg = alpha(t["hover_overlay"], themes.prop("opacity", "hover"))
        focus_color = t.get("border_focus", t["accent"])
        pressed_bg = alpha(t["accent"], 0.18)
        nav_style = (
            f"QFrame {{ background: {t['base']}; border: 1px solid {t['border_subtle']}; "
            f"border-radius: {radius}px; }}"
            f"QPushButton {{ text-align: left; background: transparent; color: {t['body']}; border: none; "
            f"border-radius: {radius}px; padding: {pad_y}px {pad_x}px; }}"
            f"QPushButton:hover {{ background: {hover_bg}; }}"
            f"QPushButton:pressed {{ background: {pressed_bg}; }}"
            f"QPushButton:focus {{ background: {hover_bg}; border: 1px solid {focus_color}; }}"
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
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        self._apply_shell_theme()
        self._status_label.setStyleSheet(sk.label_css("heading", size=20, bold=True))
        self._url_label.setStyleSheet(sk.label_css("accent", size=15))
        if hasattr(self, '_tunnel_url_label'):
            self._tunnel_url_label.setStyleSheet(
                f"font-size: {sk.pt(int(sk.prop('font_size', 'md')))}px; color: {sk.token('accent')}; "
                f"padding: {sk.px(int(sk.prop('spacing', 'sm')))}px; background: {sk.token('panel')}; "
                f"border: 1px solid {sk.token('border_subtle')}; "
                f"border-radius: {sk.px(int(sk.prop('border_radius', 'sm')))}px;")
        self._apply_table_theme()
        if hasattr(self, "_configuration_nav"):
            self._apply_configuration_theme()

    # ══════════════════════════════════════════════════════════
    # Configuration state & persistence
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _lines(widget):
        return [line.strip() for line in widget.toPlainText().splitlines() if line.strip()]

    @staticmethod
    def _bounded_int(value, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(parsed, maximum))

    def _configuration_values(self):
        return {
            "lan_share_name": self._name_edit.text() or "AssetManager",
            "lan_port": self._port_spin.value(),
            "lan_bind": "0.0.0.0" if self._bind_combo.currentIndex() == 0 else "127.0.0.1",
            "lan_auto_start": self._auto_start.isChecked(),
            "lan_commerce_enabled": self._commerce_enabled.isChecked(),
            "lan_seller_enabled": (
                self._commerce_enabled.isChecked() and self._seller_enabled.isChecked()
            ),
            "lan_shop_authorized_roots": self._lines(self._shop_authorized_roots),
            "lan_quota_enabled": self._quota_enabled.isChecked(),
            "lan_quota_period": self._quota_period.currentData() or "daily",
            "lan_quota_limit": self._quota_limit.value(),
            "lan_quota_min_interval_seconds": self._quota_min_interval.value(),
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
            "lan_theme_color": self._color_edit.text() or DEFAULT_LAN_THEME_COLOR,
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
        live_keys = set(HOT_SHARING_SETTINGS) | _DIALOG_LIVE_SETTINGS
        live_count = len(changes & live_keys)
        restart_count = len(changes & RESTART_SHARING_SETTINGS)
        planned_count = len(changes & _PLANNED_ONLY_SETTINGS)
        saved_count = len(
            changes - live_keys - RESTART_SHARING_SETTINGS - _PLANNED_ONLY_SETTINGS
        )
        if not changes:
            text = tr("sharing.configuration.no_unsaved_changes")
        else:
            text = tr("sharing.configuration.change_summary").format(
                live=live_count, restart=restart_count, saved=saved_count)
            if planned_count:
                text = "{} · {}".format(
                    text,
                    _msg(
                        "sharing.configuration.planned_note",
                        "{count} planned — not yet active",
                    ).format(count=planned_count),
                )
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
        if self._save_settings() is False:
            _log.error("Sharing settings were not persisted; keeping the dialog dirty")
            Toast.instance(self, tr("sharing.toast.error"), level="error")
            return False
        self._sync_configuration_snapshot()
        self.settings_changed.emit()
        self._update_configuration_summary()
        return True

    def _accept_configuration_changes(self):
        if self._apply_configuration_changes(force=True) is False:
            return
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
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        tunnel_running = bool(self._server and hasattr(self._server, "is_tunnel_running") and self._server.is_tunnel_running())
        state = _endpoint_state(self._server_status, tunnel_running)
        action = _endpoint_primary_action(state)
        details = {
            "off": (tr("sharing.status_off"), sk.token("muted"), tr("sharing.btn_start_sharing")),
            "starting": (tr("sharing.btn_connecting"), sk.token("accent"), tr("sharing.btn_connecting")),
            "local": (tr("sharing.status_active"), sk.state_color("success"), tr("sharing.btn_stop_sharing")),
            "public": (tr("sharing.status_active"), sk.state_color("success"), tr("sharing.btn_stop_tunnel")),
            "failed": (tr("sharing.endpoint.failed"), sk.state_color("error"), tr("sharing.endpoint.try_again")),
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
            f"background: {color}; border-radius: {sk.px(int(sk.prop('border_radius', 'sm')))}px; border: none;")
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
        self._online_info_value.setText(str(self._server_status.get("connections") or 0))
        self._traffic_info_value.setText(self._format_bytes(self._server_status.get("bytes_transferred")))
        self._exposure_label.setVisible(state == "public")
        if state == "public":
            self._exposure_label.setText(tr("sharing.endpoint.internet_access"))
            self._exposure_label.setStyleSheet(
                f"color: {sk.token('heading')}; background: {sk.token('warning')}; "
                f"border-radius: {sk.px(int(sk.prop('border_radius', 'sm')))}px; "
                f"padding: {sk.px(int(sk.prop('spacing', 'xs')))}px {sk.px(int(sk.prop('spacing', 'sm')))}px;")

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
        # The server binds 0.0.0.0 (IPv4); 'localhost' resolves to ::1 first
        # on Windows, and requests does not fall back to 127.0.0.1, so the
        # IPv6 loopback connection is refused (WinError 10061).
        url = f"http://127.0.0.1:{port}/api/stats"
        headers = {}
        if hasattr(self._server, 'token_secret'):
            headers.update(self._sharing_port.auth_headers(self._server.token_secret))

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
        if self._closed or not success or data is None:
            return
        connections = data.get("connections") or 0
        bytes_transferred = data.get("bytes_transferred") or 0
        self._online_info_value.setText(str(connections))
        self._traffic_info_value.setText(self._format_bytes(bytes_transferred))

        # Periodically refresh all tabs
        self._poll_counter = getattr(self, '_poll_counter', 0) + 1
        if self._poll_counter % 3 == 0:  # Every 6 seconds (3 * 2s interval)
            self._refresh_all_tabs()

    def _format_bytes(self, size: int | float | None) -> str:
        if not size:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB"]
        value = float(size)
        i = 0
        while value >= 1024 and i < len(units) - 1:
            value /= 1024
            i += 1
        return f"{value:.1f} {units[i]}"

    def _on_toggle_server(self):
        starting = self._server is None or not self._server.is_running()
        # The dirty check only applies once the configuration page exists; a
        # partially constructed dialog has no unapplied changes to confirm.
        has_config_state = (
            hasattr(self, "_configuration_snapshot") and hasattr(self, "_name_edit")
        )
        if starting and has_config_state and self._configuration_changes():
            reply = QMessageBox.question(
                self,
                _msg("sharing.configuration.unapplied_title", "Unapplied settings"),
                _msg(
                    "sharing.configuration.unapplied_start_message",
                    "The server will start with the current form values; "
                    "unapplied changes will be saved automatically. Continue?",
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._toggle_btn.setEnabled(False)
        self._toggle_btn.setText(tr("sharing.btn_connecting"))
        if self._save_settings() is False:
            _log.error("Sharing settings were not persisted; refusing to change server state")
            self._update_status()
            Toast.instance(self, tr("sharing.toast.error"), level="error")
            return
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
                    from AssetsManager.application.security_preflight import (
                        security_preflight_from_settings,
                    )

                    preflight = security_preflight_from_settings(self._settings)
                    bind = self._settings.get("lan_bind", "0.0.0.0")
                    auth_status = (False, "none")
                    auth_reader = getattr(self._server, "auth_status", None)
                    if callable(auth_reader):
                        try:
                            auth_status = auth_reader()
                        except Exception:
                            _log.exception("Unable to inspect LAN auth before standalone start")
                    security_snapshot = preflight.snapshot(
                        sharing=True,
                        bind=bind,
                        auth_status=auth_status,
                    )
                    if security_snapshot.share_state != "local_active":
                        if not confirm_security_preflight(
                            self,
                            settings=self._settings,
                            preflight=preflight,
                            snapshot=security_snapshot,
                            bind=bind,
                            auth_status=auth_status,
                        ):
                            self._server_status = self._server.status()
                            self._update_status()
                            self._toggle_btn.setEnabled(True)
                            return
                        security_snapshot = preflight.snapshot(
                            sharing=True,
                            bind=bind,
                            auth_status=auth_status,
                        )
                        if security_snapshot.share_state != "local_active":
                            self._server_status = self._server.status()
                            self._update_status()
                            self._toggle_btn.setEnabled(True)
                            return
                    start_result = self._server.start(
                        port=self._settings.get("lan_port", 8080),
                        bind=bind,
                        preflight=preflight,
                    )
                    self._server_status = self._server.status()
                    self._update_status()
                    self._toggle_btn.setEnabled(True)
                    if (
                        isinstance(start_result, dict)
                        and start_result.get("share_state") != "local_active"
                    ) or not self._server.is_running():
                        Toast.instance(self, tr("sharing.toast.error"), level="error")
                        self._status_timer.stop()
                        return
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
            headers.update(self._sharing_port.auth_headers(self._server.token_secret))
        return headers

    def _get_api_base(self):
        if not self._server or not self._server.is_running():
            return None
        port = self._server._port
        # 127.0.0.1, not localhost: the LAN server binds IPv4 only and
        # requests pins the first resolved address (::1 on Windows).
        return f"http://127.0.0.1:{port}"

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
        if success and isinstance(data, dict):
            self._shares = data.get("shares", [])
            self._populate_links_table()
            if self._shares:
                self._links_status.setText(tr("sharemgr.status.active_count").format(count=len(self._shares)))
            else:
                self._links_status.setText(tr("sharing.links.no_links"))
        else:
            self._links_status.setText(tr("sharemgr.status.error").format(data=""))

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
        ip = self._sharing_port.local_ip()
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
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        if self._server.is_tunnel_running():
            self._server.stop_tunnel()
            self._tunnel_btn.setText(tr("sharing.btn_start_tunnel"))
            self._set_action_icon(self._tunnel_btn, "share")
            self._tunnel_btn.setStyleSheet(self.primary_btn_style())
            self._tunnel_status.setText(tr("sharing.tunnel_not_connected"))
            self._tunnel_status.setStyleSheet(sk.muted_css(12))
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
            self._tunnel_status.setStyleSheet(sk.muted_css(12))

            from PySide6.QtCore import QThread, Signal as QSignal

            class TunnelWorker(QThread):
                finished = QSignal(str)
                status = QSignal(str)

                def __init__(self, server, settings_port):
                    super().__init__()
                    self._server = server
                    self._settings_port = settings_port
                    self._cancelled = False

                def cancel(self):
                    self._cancelled = True
                    self.requestInterruption()

                def run(self):
                    # Ensure cloudflared is available (download if needed)
                    if self._cancelled:
                        return
                    if not self._settings_port.tunnel_is_available():
                        self.status.emit(tr("sharing.tunnel_downloading"))
                        if not self._settings_port.ensure_tunnel_available():
                            self.finished.emit("")
                            return
                    if self._cancelled:
                        self.finished.emit("")
                        return
                    url = self._server.start_tunnel(timeout=30)
                    if self._cancelled:
                        # The dialog is gone; undo a tunnel that slipped through
                        # between the cancel request and start_tunnel returning.
                        if url:
                            try:
                                self._server.stop_tunnel()
                            except Exception:
                                _log.exception("Failed to roll back tunnel started during dismissal")
                            url = ""
                    self.finished.emit(url or "")

            self._tunnel_worker = TunnelWorker(self._server, self._sharing_port)
            self._tunnel_worker.status.connect(lambda msg: self._tunnel_status.setText(msg))
            self._tunnel_worker.finished.connect(self._on_tunnel_result)
            self._tunnel_worker.start()

    def _cancel_tunnel_worker(self):
        """Abort a pending tunnel start when the dialog is dismissed.

        The worker thread may be parked inside start_tunnel(timeout=30), so
        besides requesting interruption we kill any cloudflared subprocess to
        guarantee the tunnel cannot be established after the dialog is gone.
        """
        worker = getattr(self, "_tunnel_worker", None)
        if worker is None:
            return
        worker.cancel()
        if worker.isRunning():
            server = self._server
            if server is not None:
                try:
                    server.stop_tunnel()
                except Exception:
                    _log.exception("Failed to abort pending tunnel start")
            if not worker.wait(2000):
                # Thread is still parked in the tunnel wait; keep the reference
                # attached so the QThread is not destroyed while still running.
                self._tunnel_worker = worker
                return
        self._tunnel_worker = None

    def _on_tunnel_result(self, public_url: str):
        if self._closed:
            return
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        if public_url:
            self._tunnel_status.setText(tr("sharing.tunnel_connected"))
            self._tunnel_status.setStyleSheet(
                f"color: {sk.state_color('success')}; font-size: {sk.pt(int(sk.prop('font_size', 'sm')))}px;")
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
            message = self._tunnel_failure_message()
            self._tunnel_status.setText(message)
            self._tunnel_status.setStyleSheet(
                f"color: {sk.state_color('error')}; font-size: {sk.pt(int(sk.prop('font_size', 'sm')))}px;")
            self._tunnel_btn.setText(tr("sharing.btn_start_tunnel"))
            self._set_action_icon(self._tunnel_btn, "share")
            self._tunnel_btn.setStyleSheet(self.primary_btn_style())
            self._tunnel_btn.setEnabled(True)
            self._update_status()
            Toast.instance(self, message, level="error")

    def _tunnel_failure_message(self) -> str:
        """Map the server's tunnel block reason to a user-facing message."""
        server = self._server
        block_reason = ""
        if server is not None:
            block_reason = getattr(server, "tunnel_start_block_reason", None) or ""
        if block_reason == "authentication_required":
            return _msg(
                "sharing.tunnel.auth_required",
                "Public tunnel requires password authentication. "
                "Enable Password in the Protection settings first.",
            )
        return tr("sharing.tunnel_failed")

    # ── Auth ──────────────────────────────────────────────────

    def _on_auth_changed(self, _index):
        self._pw_widget.setVisible(self._auth_mode() == "password")

    def _clear_auth_error(self, *_args):
        if hasattr(self, "_auth_error_label"):
            self._auth_error_label.setVisible(False)

    def _show_password_required_error(self):
        message = _msg(
            "sharing.configuration.password_required",
            "Password protection requires a password. Enter one to enable it.",
        )
        self._auth_error_label.setText(message)
        self._auth_error_label.setVisible(True)
        Toast.instance(self, message, level="error")

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
        self._commerce_enabled.setChecked(s.get("lan_commerce_enabled", False))
        self._seller_enabled.setChecked(s.get("lan_seller_enabled", False))
        raw_authorized_roots = s.get("lan_shop_authorized_roots", [])
        if isinstance(raw_authorized_roots, str):
            authorized_roots = [
                value.strip()
                for value in raw_authorized_roots.replace(";", "\n").splitlines()
                if value.strip()
            ]
        elif isinstance(raw_authorized_roots, (list, tuple)):
            authorized_roots = [str(value).strip() for value in raw_authorized_roots if str(value).strip()]
        else:
            authorized_roots = []
        self._shop_authorized_roots.setPlainText("\n".join(authorized_roots))
        self._quota_enabled.setChecked(bool(s.get("lan_quota_enabled", False)))
        quota_period = str(s.get("lan_quota_period", "daily")).lower()
        self._quota_period.setCurrentIndex(1 if quota_period == "weekly" else 0)
        self._quota_limit.setValue(
            self._bounded_int(s.get("lan_quota_limit", 20), 20, 1, 1_000_000)
        )
        self._quota_min_interval.setValue(
            self._bounded_int(s.get("lan_quota_min_interval_seconds", 5), 5, 0, 86_400)
        )
        self._refresh_quota_controls()
        self._refresh_commerce_controls()

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

        self._color_edit.setText(s.get("lan_theme_color", DEFAULT_LAN_THEME_COLOR))
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
        commerce_enabled = self._commerce_enabled.isChecked()
        s.set("lan_commerce_enabled", commerce_enabled)
        s.set("lan_seller_enabled", commerce_enabled and self._seller_enabled.isChecked())
        s.set("lan_shop_authorized_roots", self._lines(self._shop_authorized_roots))
        s.set("lan_quota_enabled", self._quota_enabled.isChecked())
        s.set("lan_quota_period", self._quota_period.currentData() or "daily")
        s.set("lan_quota_limit", self._quota_limit.value())
        s.set("lan_quota_min_interval_seconds", self._quota_min_interval.value())

        auth_mode = self._auth_mode()
        pw = self._pw_edit.text() if auth_mode == "password" else None
        if auth_mode == "password" and not pw and not self._has_existing_password:
            # Refuse to persist an ambiguous "password mode without a password":
            # the server would otherwise fall back to no auth or lock everyone
            # out with no explanation.
            self._show_password_required_error()
            return False
        s.set("lan_auth_mode", auth_mode)
        if pw:
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

        s.set("lan_theme_color", self._color_edit.text() or DEFAULT_LAN_THEME_COLOR)
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

        return s.save()

    def closeEvent(self, event):
        self._on_dialog_closed()
        super().closeEvent(event)

    def _on_dialog_closed(self):
        """Dismissal cleanup: stop polling and cancel in-flight background work.

        Runs for OK/Cancel (via TabbedDialog.done()) and window-close alike;
        safe to call multiple times.
        """
        if getattr(self, "_closed", False):
            return
        self._closed = True
        self._status_timer.stop()
        self._cancel_tunnel_worker()
