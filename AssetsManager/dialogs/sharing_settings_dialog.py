"""Share System dialog — unified sharing control with tabbed interface.

Inherits from TabbedDialog for consistent styling and reusable components.

Tab 1: Share — Status, share link, QR code, Cloudflare tunnel
Tab 2: Settings — General, Access Control, Sharing Scope, Security, Branding, Monitoring
"""
import logging
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTextEdit, QFrame,
    QFileDialog, QWidget, QApplication,
)
from PySide6.QtGui import QPixmap, QImage, QColor, QPainter, QDesktopServices
from PySide6.QtCore import QUrl
from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.core.settings import AppSettings
from AssetsManager.dialogs.tabbed_dialog import TabbedDialog
from AssetsManager import i18n

tr = i18n.tr
_log = logging.getLogger(__name__)


def _t():
    return themes.get()


class SharingSettingsDialog(TabbedDialog):
    """Unified Share System dialog with tabbed interface.

    Inherits from TabbedDialog for consistent styling and reusable components.
    """

    settings_changed = Signal()

    def __init__(self, parent=None, server_status: dict | None = None, server=None):
        self._settings = AppSettings.instance()
        self._server_status = server_status or {}
        self._server = server

        super().__init__(parent, title=tr("sharing.dialog_title"), min_size=(560, 650))

        self._update_status()
        self._load_settings()

        # Setup real-time status polling
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(2000)  # Poll every 2 seconds
        self._status_timer.timeout.connect(self._poll_server_status)
        if self._server and self._server.is_running():
            self._status_timer.start()

    def _setup_tabs(self):
        """Setup Share and Settings tabs."""
        # Tab 1: Share
        share_tab = QWidget()
        self._setup_share_tab(share_tab)
        self._add_tab(share_tab, tr("sharing.tab_share"))

        # Tab 2: Settings (scrollable)
        settings_tab = QWidget()
        self._setup_settings_tab(settings_tab)
        self._add_tab(settings_tab, tr("sharing.tab_settings"), scrollable=True)

    # ══════════════════════════════════════════════════════════
    # Tab 1: Share
    # ══════════════════════════════════════════════════════════

    def _setup_share_tab(self, parent):
        """Setup the Share tab with status, link, QR code, and tunnel."""
        t = _t()
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(scaled_px(16), scaled_px(16), scaled_px(16), scaled_px(16))
        layout.setSpacing(scaled_px(12))

        # ── Status Card ──────────────────────────────────────
        self._status_frame = QFrame()
        self._status_frame.setStyleSheet(self.status_style(False))
        status_layout = QVBoxLayout(self._status_frame)
        status_layout.setContentsMargins(scaled_px(16), scaled_px(14), scaled_px(16), scaled_px(14))
        status_layout.setSpacing(scaled_px(8))

        status_row = QHBoxLayout()
        self._status_icon = QLabel("🔴")
        self._status_icon.setFixedWidth(scaled_px(24))
        status_row.addWidget(self._status_icon)
        self._status_label = QLabel(tr("sharing.status_off"))
        self._status_label.setStyleSheet(f"font-weight: bold; font-size: {scaled_pt(14)}px; color: {t['heading']};")
        status_row.addWidget(self._status_label)
        status_row.addStretch()
        self._toggle_btn = self.make_primary_btn(tr("sharing.btn_start_sharing"), self._on_toggle_server)
        self._toggle_btn.setFixedWidth(scaled_px(120))
        status_row.addWidget(self._toggle_btn)
        status_layout.addLayout(status_row)

        self._url_row = QHBoxLayout()
        self._url_label = QLabel("")
        self._url_label.setStyleSheet(f"font-size: {scaled_pt(13)}px; color: {t['accent']};")
        self._url_row.addWidget(self._url_label)
        self._url_row.addStretch()
        self._copy_btn = self.make_secondary_btn(tr("sharing.btn_copy_link"), self._copy_link)
        self._copy_btn.setFixedWidth(scaled_px(90))
        self._copy_btn.setVisible(False)
        self._url_row.addWidget(self._copy_btn)
        status_layout.addLayout(self._url_row)

        self._stats_label = self.make_muted("")
        status_layout.addWidget(self._stats_label)

        layout.addWidget(self._status_frame)

        # ── Share Link & QR Code ─────────────────────────────
        self._share_section = self.make_groupbox(tr("sharing.group_share_link"))
        share_layout = QVBoxLayout(self._share_section)
        share_layout.setSpacing(scaled_px(10))
        share_layout.setContentsMargins(scaled_px(16), scaled_px(18), scaled_px(16), scaled_px(12))

        self._share_url_label = QLabel("")
        self._share_url_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._share_url_label.setStyleSheet(
            f"font-size: {scaled_pt(13)}px; color: {t['accent']}; "
            f"padding: 10px; background: {t['panel']}; "
            f"border: 1px solid {t['border']}; border-radius: {scaled_px(6)}px;")
        self._share_url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._share_url_label.setVisible(False)
        share_layout.addWidget(self._share_url_label)

        share_btn_row = QHBoxLayout()
        self._share_copy_btn = self.make_primary_btn(tr("sharing.btn_copy_link"), self._copy_share_link)
        self._share_copy_btn.setVisible(False)
        share_btn_row.addWidget(self._share_copy_btn)
        self._share_open_btn = self.make_secondary_btn(tr("sharing.btn_open_in_browser"), self._open_share_link)
        self._share_open_btn.setVisible(False)
        share_btn_row.addWidget(self._share_open_btn)
        share_btn_row.addStretch()
        share_layout.addLayout(share_btn_row)

        # QR Code
        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setFixedSize(scaled_px(200), scaled_px(200))
        self._qr_label.setStyleSheet(f"background: {_t()['input_bg']}; border-radius: {scaled_px(10)}px; padding: 8px;")
        self._qr_label.setVisible(False)
        share_layout.addWidget(self._qr_label, 0, Qt.AlignmentFlag.AlignCenter)

        self._qr_copy_btn = self.make_secondary_btn(tr("sharing.btn_copy_qr"), self._copy_qr)
        self._qr_copy_btn.setVisible(False)
        share_layout.addWidget(self._qr_copy_btn, 0, Qt.AlignmentFlag.AlignCenter)

        self._qr_pixmap = None
        layout.addWidget(self._share_section)

        # ── Cloudflare Tunnel ────────────────────────────────
        from AssetsManager.lan.tunnel import is_available as is_tunnel_available
        if is_tunnel_available():
            self._tunnel_section = self.make_groupbox(tr("sharing.group_cloudflare_tunnel"))
            tunnel_layout = QVBoxLayout(self._tunnel_section)
            tunnel_layout.setSpacing(scaled_px(8))
            tunnel_layout.setContentsMargins(scaled_px(16), scaled_px(18), scaled_px(16), scaled_px(12))

            self._tunnel_status = self.make_muted(tr("sharing.tunnel_not_connected"))
            tunnel_layout.addWidget(self._tunnel_status)

            self._tunnel_url_label = QLabel("")
            self._tunnel_url_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._tunnel_url_label.setStyleSheet(
                f"font-size: {scaled_pt(13)}px; color: {t['accent']}; "
                f"padding: 8px; background: {t['panel']}; "
                f"border: 1px solid {t['border']}; border-radius: {scaled_px(6)}px;")
            self._tunnel_url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._tunnel_url_label.setVisible(False)
            tunnel_layout.addWidget(self._tunnel_url_label)

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
            tunnel_layout.addLayout(tunnel_btn_row)

            layout.addWidget(self._tunnel_section)
        else:
            self._tunnel_section = None

        layout.addStretch()

    # ══════════════════════════════════════════════════════════
    # Tab 2: Settings
    # ══════════════════════════════════════════════════════════

    def _setup_settings_tab(self, parent):
        """Setup the Settings tab with all configuration options."""
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(scaled_px(12), scaled_px(12), scaled_px(12), scaled_px(12))
        layout.setSpacing(scaled_px(10))

        # ── General ──────────────────────────────────────────
        general = self.make_groupbox(tr("sharing.group_general"))
        gl = QVBoxLayout(general)
        gl.setSpacing(scaled_px(6))
        gl.setContentsMargins(scaled_px(12), scaled_px(16), scaled_px(12), scaled_px(8))

        name_row = self.make_labeled_row(tr("sharing.label_share_name"), self.make_input("AssetManager"))
        self._name_edit = name_row.itemAt(1).widget()
        gl.addLayout(name_row)

        port_bind_row = QHBoxLayout()
        port_bind_row.addWidget(self.make_label(tr("sharing.label_port")))
        self._port_spin = self.make_spinbox(1024, 65535, 8080)
        port_bind_row.addWidget(self._port_spin)
        port_bind_row.addSpacing(scaled_px(16))
        port_bind_row.addWidget(self.make_label(tr("sharing.label_bind")))
        self._bind_combo = self.make_combobox([tr("sharing.bind_all"), tr("sharing.bind_local_only")])
        port_bind_row.addWidget(self._bind_combo)
        gl.addLayout(port_bind_row)

        self._auto_start = self.make_checkbox(tr("sharing.auto_start_sharing"))
        gl.addWidget(self._auto_start)

        layout.addWidget(general)

        # ── Access Control (collapsible) ─────────────────────
        access_section, al = self.make_collapsible(tr("sharing.group_access_control"))

        auth_row = QHBoxLayout()
        auth_row.addWidget(self.make_label(tr("sharing.label_auth_mode")))
        self._auth_combo = self.make_combobox([tr("sharing.auth_none"), tr("sharing.auth_password")])
        self._auth_combo.currentTextChanged.connect(self._on_auth_changed)
        auth_row.addWidget(self._auth_combo)
        auth_row.addStretch()
        al.addLayout(auth_row)

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
        al.addWidget(self._pw_widget)

        limits_row = QHBoxLayout()
        limits_row.addWidget(self.make_label(tr("sharing.label_max_connections")))
        self._max_conn = self.make_spinbox(1, 500, 50)
        limits_row.addWidget(self._max_conn)
        limits_row.addSpacing(scaled_px(12))
        limits_row.addWidget(self.make_label(tr("sharing.label_timeout")))
        self._timeout = self.make_spinbox(60, 86400, 3600)
        self._timeout.setSingleStep(300)
        limits_row.addWidget(self._timeout)
        al.addLayout(limits_row)

        rate_row = QHBoxLayout()
        rate_row.addWidget(self.make_label(tr("sharing.label_rate_limit")))
        self._rate_limit = self.make_spinbox(10, 10000, 100)
        rate_row.addWidget(self._rate_limit)
        rate_row.addWidget(self.make_muted(tr("sharing.helper_req_per_min_ip")))
        rate_row.addStretch()
        al.addLayout(rate_row)

        al.addWidget(self.make_label(tr("sharing.label_ip_whitelist")))
        self._ip_whitelist = QTextEdit()
        self._ip_whitelist.setMaximumHeight(scaled_px(60))
        self._ip_whitelist.setPlaceholderText("192.168.1.0/24")
        al.addWidget(self._ip_whitelist)

        layout.addWidget(access_section)

        # ── Sharing Scope (collapsible) ──────────────────────
        scope_section, sl = self.make_collapsible(tr("sharing.group_sharing_scope"))

        sl.addWidget(self.make_label(tr("sharing.label_include_types")))
        types_row = QHBoxLayout()
        self._type_checks = {}
        for cat in [tr("sharing.type_images"), tr("sharing.type_3d_models"), tr("sharing.type_videos"), tr("sharing.type_documents"), tr("sharing.type_archives")]:
            chk = self.make_checkbox(cat, checked=True)
            types_row.addWidget(chk)
            self._type_checks[cat.lower().replace(" ", "_")] = chk
        sl.addLayout(types_row)

        opts_row = QHBoxLayout()
        self._show_hidden = self.make_checkbox(tr("sharing.show_hidden_files"))
        opts_row.addWidget(self._show_hidden)
        opts_row.addSpacing(scaled_px(16))
        opts_row.addWidget(self.make_label(tr("sharing.label_max_depth")))
        self._max_depth = self.make_spinbox(0, 50, 0)
        self._max_depth.setSpecialValueText(tr("sharing.unlimited"))
        opts_row.addWidget(self._max_depth)
        opts_row.addStretch()
        sl.addLayout(opts_row)

        sl.addWidget(self.make_label(tr("sharing.label_exclude_patterns")))
        self._exclude_patterns = QTextEdit()
        self._exclude_patterns.setMaximumHeight(scaled_px(80))
        self._exclude_patterns.setPlaceholderText(".git\nnode_modules\n__pycache__\n.thumbnails")
        sl.addWidget(self._exclude_patterns)

        layout.addWidget(scope_section)

        # ── Preview Review (collapsible) ─────────────────────
        preview_section, prl = self.make_collapsible(tr("sharing.group_preview_review"))

        prl.addWidget(self.make_label(tr("sharing.label_blur_tags")))
        self._blur_tags = QTextEdit()
        self._blur_tags.setMaximumHeight(scaled_px(80))
        self._blur_tags.setPlaceholderText("nsfw\nnsfl\nsensitive\nspoiler")
        prl.addWidget(self._blur_tags)
        prl.addWidget(self.make_muted(tr("sharing.helper_blur_tags")))

        layout.addWidget(preview_section)

        # ── Security (collapsible) ───────────────────────────
        security_section, sl2 = self.make_collapsible(tr("sharing.group_security"))

        sl2.addWidget(self.make_label(tr("sharing.label_https")))
        ssl_row, self._ssl_cert = self.make_browse_row(tr("sharing.label_cert"), "/path/to/cert.pem",
            lambda: self._browse_file(self._ssl_cert))
        sl2.addLayout(ssl_row)
        key_row, self._ssl_key = self.make_browse_row(tr("sharing.label_key"), "/path/to/key.pem",
            lambda: self._browse_file(self._ssl_key))
        sl2.addLayout(key_row)

        sl2.addWidget(self.make_label(tr("sharing.label_blocked_ips")))
        self._blocked_ips = QTextEdit()
        self._blocked_ips.setMaximumHeight(scaled_px(60))
        self._blocked_ips.setPlaceholderText("192.168.1.100\n10.0.0.50")
        sl2.addWidget(self._blocked_ips)

        layout.addWidget(security_section)

        # ── Branding (collapsible) ───────────────────────────
        branding_section, bl = self.make_collapsible(tr("sharing.group_branding"))

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
        self._footer_edit = self.make_input("Built with AssetManager")
        footer_row.addWidget(self._footer_edit)
        bl.addLayout(footer_row)

        layout.addWidget(branding_section)

        # ── Monitoring (collapsible) ─────────────────────────
        monitor_section, ml = self.make_collapsible(tr("sharing.group_monitoring"))

        self._enable_log = self.make_checkbox(tr("sharing.enable_access_log"))
        ml.addWidget(self._enable_log)

        log_path_row, self._log_path = self.make_browse_row(tr("sharing.label_log_path"), "RuntimeData/Shared/lan_access.log",
            self._browse_log_path)
        ml.addLayout(log_path_row)

        rotation_row = QHBoxLayout()
        rotation_row.addWidget(self.make_label(tr("sharing.label_log_rotation")))
        self._log_rotation = self.make_spinbox(1, 100, 10)
        rotation_row.addWidget(self._log_rotation)
        rotation_row.addWidget(self.make_muted(tr("sharing.helper_mb_per_file")))
        rotation_row.addStretch()
        ml.addLayout(rotation_row)

        layout.addWidget(monitor_section)

        layout.addStretch()

    # ══════════════════════════════════════════════════════════
    # Status & Actions
    # ══════════════════════════════════════════════════════════

    def _update_status(self):
        """Update the share status display based on server state."""
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
            self._stats_label.setText(
                f"{self._server_status.get('connections', 0)} {tr('sharing.stats_clients')} · "
                f"{self._server_status.get('requests', 0)} {tr('sharing.stats_requests')} · "
                f"{self._format_bytes(self._server_status.get('bytes_transferred', 0))}"
            )
            self._stats_label.setStyleSheet(f"font-size: {scaled_pt(11)}px; color: {t['muted']};")
            self._status_frame.setStyleSheet(self.status_style(True))

            # Show share link and QR code
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
            self._stats_label.setText("")
            self._status_frame.setStyleSheet(self.status_style(False))

            # Hide share link and QR code
            self._share_url_label.setVisible(False)
            self._share_copy_btn.setVisible(False)
            self._share_open_btn.setVisible(False)
            self._qr_label.setVisible(False)
            self._qr_copy_btn.setVisible(False)

    def _poll_server_status(self):
        """Poll server for real-time status updates (async, non-blocking)."""
        if not self._server or not self._server.is_running():
            self._status_timer.stop()
            return

        port = self._server._port
        url = f"http://localhost:{port}/api/stats"
        headers = {}
        if hasattr(self._server, 'token_secret'):
            from AssetsManager.lan.utils import get_auth_headers
            headers.update(get_auth_headers(self._server.token_secret))

        from PySide6.QtCore import QRunnable, QThreadPool, QObject, Signal

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

    def _on_poll_result(self, success, data):
        """Handle async poll result."""
        if not success or data is None:
            return
        connections = data.get("connections", 0)
        requests_count = data.get("requests", 0)
        bytes_transferred = data.get("bytes_transferred", 0)
        self._stats_label.setText(
            f"{connections} {tr('sharing.stats_clients')} · "
            f"{requests_count} {tr('sharing.stats_requests')} · "
            f"{self._format_bytes(bytes_transferred)}"
        )

    def _format_bytes(self, size: int) -> str:
        """Format bytes to human readable string."""
        if size == 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while size >= 1024 and i < len(units) - 1:
            size /= 1024
            i += 1
        return f"{size:.1f} {units[i]}"

    def _on_toggle_server(self):
        """Toggle server on/off."""
        # Save settings first
        self._save_settings()

        # Update server_status after toggle
        if self._server:
            self._server_status = self._server.status()

        # Update UI
        self._update_status()

        # Start/stop polling based on server state
        if self._server and self._server.is_running():
            self._status_timer.start()
        else:
            self._status_timer.stop()

    def _copy_link(self):
        """Copy server URL to clipboard."""
        url = self._server_status.get("url", "")
        if url:
            QApplication.clipboard().setText(url)
            self._copy_btn.setText(tr("sharing.copied"))
            QTimer.singleShot(1500, lambda: self._copy_btn.setText(tr("sharing.btn_copy_link")))

    def _copy_share_link(self):
        """Copy share URL to clipboard."""
        url = self._share_url_label.text()
        if url:
            QApplication.clipboard().setText(url)
            self._share_copy_btn.setText(tr("sharing.copied"))
            QTimer.singleShot(1500, lambda: self._share_copy_btn.setText(tr("sharing.btn_copy_link")))

    def _open_share_link(self):
        """Open share URL in browser."""
        url = self._share_url_label.text()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _copy_qr(self):
        """Copy QR code to clipboard."""
        if self._qr_pixmap and not self._qr_pixmap.isNull():
            QApplication.clipboard().setPixmap(self._qr_pixmap)
            self._qr_copy_btn.setText(tr("sharing.copied"))
            QTimer.singleShot(1500, lambda: self._qr_copy_btn.setText(tr("sharing.btn_copy_qr")))

    def _copy_tunnel_url(self):
        """Copy tunnel URL to clipboard."""
        url = self._tunnel_url_label.text()
        if url:
            QApplication.clipboard().setText(url)
            self._tunnel_copy_btn.setText(tr("sharing.copied"))
            QTimer.singleShot(1500, lambda: self._tunnel_copy_btn.setText(tr("sharing.btn_copy")))

    def _open_tunnel_url(self):
        """Open tunnel URL in browser."""
        url = self._tunnel_url_label.text()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _toggle_tunnel(self):
        """Toggle Cloudflare tunnel."""
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
        else:
            # Disable button and show loading state
            self._tunnel_btn.setEnabled(False)
            self._tunnel_btn.setText(tr("sharing.btn_connecting"))
            self._tunnel_status.setText(tr("sharing.tunnel_starting"))
            self._tunnel_status.setStyleSheet(f"font-size: {scaled_pt(12)}px; color: {t['muted']};")

            # Use QThread to avoid blocking main thread
            from PySide6.QtCore import QThread, Signal as QSignal

            class TunnelWorker(QThread):
                finished = QSignal(str)  # public_url or empty string

                def __init__(self, server):
                    super().__init__()
                    self._server = server

                def run(self):
                    url = self._server.start_tunnel(timeout=30)
                    self.finished.emit(url or "")

            self._tunnel_worker = TunnelWorker(self._server)
            self._tunnel_worker.finished.connect(self._on_tunnel_result)
            self._tunnel_worker.start()

    def _on_tunnel_result(self, public_url: str):
        """Handle tunnel startup result."""
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
            self._generate_qr(public_url)
        else:
            self._tunnel_status.setText(tr("sharing.tunnel_failed"))
            self._tunnel_status.setStyleSheet(f"font-size: {scaled_pt(12)}px; color: {t['danger']};")
            self._tunnel_btn.setText(tr("sharing.btn_start_tunnel"))
            self._tunnel_btn.setStyleSheet(self.primary_btn_style())
            self._tunnel_btn.setEnabled(True)

    def _generate_qr(self, url: str):
        """Generate and display QR code for the given URL."""
        try:
            import segno
            from io import BytesIO
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
        except Exception:
            self._qr_label.setText(tr("sharing.qr_generation_failed"))
            self._qr_label.setVisible(True)

    # ── Auth ──────────────────────────────────────────────────

    def _on_auth_changed(self, text):
        """Show/hide password field based on auth mode selection."""
        self._pw_widget.setVisible(text == tr("sharing.auth_password"))

    # ── Browse ────────────────────────────────────────────────

    def _browse_log_path(self):
        """Browse for log file path."""
        path, _ = QFileDialog.getSaveFileName(
            self, tr("sharing.dialog_select_log_file"), self._log_path.text(), tr("sharing.dialog_log_files_filter"))
        if path:
            self._log_path.setText(path)

    def _browse_file(self, target_edit):
        """Browse for a file path."""
        path, _ = QFileDialog.getOpenFileName(
            self, tr("sharing.dialog_select_file"), target_edit.text(), tr("sharing.dialog_all_files_filter"))
        if path:
            target_edit.setText(path)

    # ── Settings persistence ──────────────────────────────────

    def _load_settings(self):
        """Load settings from AppSettings into UI."""
        s = self._settings
        self._name_edit.setText(s.get("lan_share_name", "AssetManager"))
        self._port_spin.setValue(s.get("lan_port", 8080))
        bind = s.get("lan_bind", "0.0.0.0")
        self._bind_combo.setCurrentIndex(0 if bind == "0.0.0.0" else 1)
        self._auto_start.setChecked(s.get("lan_auto_start", False))

        auth = s.get("lan_auth_mode", "none")
        self._auth_combo.setCurrentText(tr("sharing.auth_password") if auth == "password" else tr("sharing.auth_none"))
        # Don't load hashed password into UI field - leave empty
        # Password will only be updated if user enters a new one
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

    def _on_apply(self):
        """Save settings to AppSettings."""
        self._save_settings()

    def _save_settings(self):
        """Save all settings to AppSettings."""
        s = self._settings
        s.set("lan_share_name", self._name_edit.text() or "AssetManager")
        s.set("lan_port", self._port_spin.value())
        s.set("lan_bind", "0.0.0.0" if self._bind_combo.currentIndex() == 0 else "127.0.0.1")
        s.set("lan_auto_start", self._auto_start.isChecked())

        s.set("lan_auth_mode", "password" if self._auth_combo.currentText() == tr("sharing.auth_password") else "none")
        pw = self._pw_edit.text() if self._auth_combo.currentText() == tr("sharing.auth_password") else None
        if pw:
            from AssetsManager.lan.auth import hash_password
            s.set("lan_password", hash_password(pw))
        elif self._auth_combo.currentText() == tr("sharing.auth_password") and self._has_existing_password:
            # Keep existing password if field is empty but password was set before
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

        s.save()
        self.settings_changed.emit()

    def closeEvent(self, event):
        """Stop timer when dialog is closed."""
        self._status_timer.stop()
        super().closeEvent(event)
