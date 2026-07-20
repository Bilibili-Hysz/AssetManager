"""LanSharingMixin — LAN sharing logic extracted from MainWindow.

Contains:
- Toggle sharing on/off
- Share status display
- Share dialog with QR code, tunnel support
- Sharing settings integration
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton, QWidget
from AssetsManager import i18n

if TYPE_CHECKING:
    from AssetsManager.application.context import LibrarySession
    from AssetsManager.lan import LanServer
    from AssetsManager.widgets.tray import SystemTrayManager

tr = i18n.tr

_log = logging.getLogger(__name__)

# These settings are passed through to LanServer.reload_settings without a
# server restart. Configuration presentation imports this declaration so its
# impact summary cannot drift from the lifecycle owner.
HOT_SHARING_SETTINGS = {
    "lan_share_name": "share_name",
    "lan_blur_tags": "blur_tags",
    "lan_theme_color": "theme_color",
    "lan_welcome_msg": "welcome_msg",
    "lan_footer_text": "footer_text",
    "lan_show_hidden": "show_hidden",
    "lan_max_depth": "max_depth",
    "lan_include_types": "include_types",
    "lan_exclude_patterns": "exclude_patterns",
}
HOT_SHARING_DEFAULTS = {
    "lan_share_name": "AssetManager", "lan_blur_tags": [], "lan_theme_color": "#5b7ff5",
    "lan_welcome_msg": "", "lan_footer_text": "", "lan_show_hidden": False,
    "lan_max_depth": 0, "lan_include_types": None, "lan_exclude_patterns": None,
}
RESTART_SHARING_SETTINGS = frozenset({
    "lan_port", "lan_bind", "lan_password", "lan_access_key",
    "lan_rate_limit", "lan_blocked_ips", "lan_ip_whitelist", "lan_ssl_cert", "lan_ssl_key",
})



class LanSharingMixin:
    """Mixin for LAN sharing functionality. Must be used with QMainWindow."""

    # Supplied by the QMainWindow host. Annotations preserve the mixin's MRO.
    _lan_server: LanServer | None
    _library_session: LibrarySession | None
    _tray_manager: SystemTrayManager | None
    _share_status_label: QLabel
    _share_toggle_btn: QPushButton

    def _dialog_parent(self) -> QWidget:
        return cast(QWidget, self)

    # ── Toggle sharing ──────────────────────────────────────────

    def _toggle_sharing(self):
        """Start or stop LAN sharing."""
        from AssetsManager import lan
        if self._lan_server and self._lan_server.is_running():
            self._lan_server.stop()
            self._update_share_status(False)
            if hasattr(self, '_tray_manager') and self._tray_manager:
                self._tray_manager.update_sharing_state(False)
            return

        # Start sharing
        from AssetsManager.core.settings import AppSettings
        settings = AppSettings.instance()
        port = settings.get("lan_port", 8080)
        bind = settings.get("lan_bind", "0.0.0.0")
        password = settings.get("lan_password")
        access_key = settings.get("lan_access_key")
        share_name = settings.get("lan_share_name", "AssetManager")

        session = getattr(self, "_library_session", None)
        if session is None or session.is_closed:
            QMessageBox.warning(self._dialog_parent(), tr("dialog.error"), tr("sharing.no_library"))
            return

        try:
            bootstrap = getattr(self, "_bootstrap", None)
            server = lan.LanServer(
                library_root=session.root_str,
                thumbnail_dir=session.thumb_dir_str,
                db_conn=session.connection_for(session.root),
                share_name=share_name,
                password=password,
                access_key=access_key,
                rate_limit=settings.get("lan_rate_limit", 1000),
                blocked_ips=settings.get("lan_blocked_ips", []),
                ip_whitelist=settings.get("lan_ip_whitelist", []),
                blur_tags=settings.get("lan_blur_tags", []),
                ssl_cert=settings.get("lan_ssl_cert"),
                ssl_key=settings.get("lan_ssl_key"),
                performance_recorder=getattr(bootstrap, "performance_recorder", None),
                session_token=getattr(session, "event_token", None),
            )
            self._lan_server = server
            server.start(port=port, bind=bind)
            self._update_share_status(True, port)
            if hasattr(self, '_tray_manager') and self._tray_manager:
                from AssetsManager.lan.server import get_local_ip
                self._tray_manager.update_sharing_state(True, f"http://{get_local_ip()}:{port}")
        except OSError:
            QMessageBox.warning(self._dialog_parent(), tr("dialog.error"), tr("sharing.port_in_use", port=port))

    # ── Status display ──────────────────────────────────────────

    def _update_share_status(self, running, port=8080):
        """Update share status indicators in status bar and toolbar."""
        from AssetsManager.core import themes
        t = themes.get()

        # Update status bar label
        if hasattr(self, '_share_status_label'):
            if running:
                from AssetsManager.lan.server import get_local_ip
                ip = get_local_ip()
                url = f"http://{ip}:{port}"
                self._share_status_label.setText(f"🟢 {url}")
                self._share_status_label.setStyleSheet(f"color: {t['accent']}; padding: 0 8px;")
                self._share_status_label.setToolTip(tr("sharing.click_to_copy"))
            else:
                self._share_status_label.setText(tr("sharing.off"))
                self._share_status_label.setStyleSheet(f"color: {t['muted']}; padding: 0 8px;")
                self._share_status_label.setToolTip(tr("sharing.click_to_share"))

        # Update toolbar button
        if hasattr(self, '_share_toggle_btn'):
            if running:
                self._share_toggle_btn.setText("🟢")
                self._share_toggle_btn.setToolTip(tr("sharing.stop_tooltip"))
            else:
                self._share_toggle_btn.setText("🌐")
                self._share_toggle_btn.setToolTip(tr("sharing.start_tooltip"))


    # ── Settings ────────────────────────────────────────────────

    def _open_sharing_settings(self):
        try:
            from AssetsManager.dialogs.sharing_settings_dialog import SharingSettingsDialog
            status = self._lan_server.status() if self._lan_server else {}
            dlg = SharingSettingsDialog(self._dialog_parent(), server_status=status, server=self._lan_server)
            dlg.settings_changed.connect(self._apply_sharing_settings)
            dlg.exec()
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("Failed to open sharing settings")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self._dialog_parent(), tr("dialog.error"), tr("sharing.error_open", error=str(e)))

    def _apply_sharing_settings(self):
        """Apply sharing settings. Called after dialog saves settings."""
        from AssetsManager.core.settings import AppSettings
        settings = AppSettings.instance()

        if self._lan_server and self._lan_server.is_running():
            # Update main window UI to reflect current server state
            self._update_share_status(True, self._lan_server._port)
            if hasattr(self, '_tray_manager') and self._tray_manager:
                self._tray_manager.update_sharing_state(True)

            # Check if we can hot-reload or need to restart
            hot_settings = {
                server_key: settings.get(setting_key, HOT_SHARING_DEFAULTS[setting_key])
                for setting_key, server_key in HOT_SHARING_SETTINGS.items()
            }
            self._lan_server.reload_settings(hot_settings)

            # Check if restart-required settings changed
            restart_required = False
            server_config = getattr(self._lan_server, "_impl", self._lan_server)
            if settings.get("lan_port", 8080) != self._lan_server._port:
                restart_required = True
            if settings.get("lan_bind", "0.0.0.0") != self._lan_server._bind:
                restart_required = True
            restart_settings = {
                "lan_password": getattr(server_config, "_password_value", None),
                "lan_access_key": getattr(server_config, "_access_key_value", None),
                "lan_rate_limit": getattr(server_config, "_rate_limit_value", 1000),
                "lan_blocked_ips": getattr(server_config, "_blocked_ips", []),
                "lan_ip_whitelist": getattr(server_config, "_ip_whitelist", []),
                "lan_ssl_cert": getattr(server_config, "_ssl_cert", None),
                "lan_ssl_key": getattr(server_config, "_ssl_key", None),
            }
            for key, current_value in restart_settings.items():
                if settings.get(key, current_value) != current_value:
                    restart_required = True
                    break

            if restart_required:
                self._lan_server.stop()
                self._update_share_status(False)
                self._toggle_sharing()
        else:
            self._toggle_sharing()

    # ── Share Link Management ───────────────────────────────────

    def _open_share_link_dialog(self, path: str = "", paths: list[str] | None = None):
        """Open dialog to create a share link for a path."""
        if not self._lan_server or not self._lan_server.is_running():
            from PySide6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self._dialog_parent(), tr("sharing.not_running"),
                tr("sharing.start_to_share"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._toggle_sharing()
            else:
                return

        try:
            from AssetsManager.dialogs.share_link_dialog import ShareLinkDialog
            selected_paths = list(paths) if paths is not None else ([path] if path else [])
            dlg = ShareLinkDialog(self._dialog_parent(), paths=selected_paths, server=self._lan_server)
            dlg.exec()
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("Failed to open share link dialog")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self._dialog_parent(), tr("dialog.error"), str(e))

    def _open_share_link_manager(self):
        """Open dialog to manage share links."""
        if not self._lan_server or not self._lan_server.is_running():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self._dialog_parent(), tr("sharing.not_running"), tr("sharing.start_to_manage"))
            return

        try:
            from AssetsManager.dialogs.sharing_settings_dialog import SharingSettingsDialog
            dlg = SharingSettingsDialog(
                self._dialog_parent(),
                server_status=self._lan_server.status(),
                server=self._lan_server,
                initial_page="links",
            )
            dlg.exec()
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("Failed to open share link manager")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self._dialog_parent(), tr("dialog.error"), str(e))

    def _quick_share(self, path: str):
        """Route legacy quick-share callers through the canonical creator."""
        self._open_share_link_dialog(path=path)

    def _show_quick_share_card(self, paths: list[str], _global_pos):
        """Compatibility entry point for FileList while its caller migrates."""
        self._open_share_link_dialog(paths=paths)
