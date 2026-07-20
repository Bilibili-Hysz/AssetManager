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
    from AssetsManager.dialogs.quick_share_card import QuickShareCard
    from AssetsManager.lan import LanServer
    from AssetsManager.widgets.tray import SystemTrayManager

tr = i18n.tr

_log = logging.getLogger(__name__)



class LanSharingMixin:
    """Mixin for LAN sharing functionality. Must be used with QMainWindow."""

    # Supplied by the QMainWindow host. Annotations preserve the mixin's MRO.
    _lan_server: LanServer | None
    _library_session: LibrarySession | None
    _tray_manager: SystemTrayManager | None
    _share_status_label: QLabel
    _share_toggle_btn: QPushButton
    _quick_share_card: QuickShareCard | None

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
                "share_name": settings.get("lan_share_name", "AssetManager"),
                "blur_tags": settings.get("lan_blur_tags", []),
                "theme_color": settings.get("lan_theme_color", "#5b7ff5"),
                "welcome_msg": settings.get("lan_welcome_msg", ""),
                "footer_text": settings.get("lan_footer_text", ""),
                "show_hidden": settings.get("lan_show_hidden", False),
                "max_depth": settings.get("lan_max_depth", 0),
                "include_types": settings.get("lan_include_types", None),
                "exclude_patterns": settings.get("lan_exclude_patterns", None),
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

    @staticmethod
    def _quick_share_api_url(server) -> str:
        port = server._port
        base_url = server.status().get("url", f"http://localhost:{port}")
        return f"{base_url}/api/shares"

    def _open_share_link_dialog(self, path: str = ""):
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
            dlg = ShareLinkDialog(self._dialog_parent(), path=path, server=self._lan_server)
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
            from AssetsManager.dialogs.share_link_manager import ShareLinkManager
            dlg = ShareLinkManager(self._dialog_parent(), server=self._lan_server)
            dlg.exec()
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("Failed to open share link manager")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self._dialog_parent(), tr("dialog.error"), str(e))

    def _quick_share(self, path: str):
        """Quick share a file/folder with default settings (async, non-blocking)."""
        if not self._lan_server or not self._lan_server.is_running():
            self._toggle_sharing()
            if not self._lan_server or not self._lan_server.is_running():
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self._dialog_parent(), tr("sharing.error"), tr("sharing.failed_to_start"))
                return

        url = self._quick_share_api_url(self._lan_server)
        data = {"paths": [path], "expires_hours": 24, "allow_preview": True}

        headers = {"Content-Type": "application/json"}
        if hasattr(self._lan_server, 'token_secret'):
            from AssetsManager.lan.utils import get_auth_headers
            headers.update(get_auth_headers(self._lan_server.token_secret))

        from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool

        class _Result(QObject):
            finished = Signal(bool, object)

        class _Task(QRunnable):
            def __init__(self):
                super().__init__()
                self.setAutoDelete(False)
                self.signals = _Result()
            def run(self):
                try:
                    import requests
                    resp = requests.post(url, json=data, headers=headers, timeout=10)
                    if resp.status_code == 200:
                        self.signals.finished.emit(True, resp.json())
                    else:
                        err = resp.json().get("error", "Unknown error")
                        self.signals.finished.emit(False, err)
                except ImportError:
                    self.signals.finished.emit(False, "requests not installed")
                except Exception as e:
                    self.signals.finished.emit(False, str(e))

        task = _Task()
        task.signals.finished.connect(self._on_quick_share_result)
        QThreadPool.globalInstance().start(task)

    def _on_quick_share_result(self, success, data):
        from PySide6.QtWidgets import QApplication, QMessageBox
        if success:
            share_url = data.get("url")
            if share_url:
                QApplication.clipboard().setText(share_url)
                msg = QMessageBox(self._dialog_parent())
                msg.setWindowTitle(tr("sharing.quick_share"))
                msg.setText(tr("sharing.link_copied"))
                msg.setInformativeText(share_url)
                msg.setStandardButtons(QMessageBox.StandardButton.Ok)
                msg.exec()
            else:
                QMessageBox.warning(self._dialog_parent(), tr("sharing.error"), tr("sharing.no_url"))
        else:
            QMessageBox.warning(self._dialog_parent(), tr("sharing.error"), f"{tr('sharing.failed_to_start')}: {data}")

    # ── Quick Share Card ─────────────────────────────────────

    def _show_quick_share_card(self, paths: list[str], global_pos):
        """Show a QuickShareCard popup at the given position for the selected paths."""
        from AssetsManager.dialogs.quick_share_card import QuickShareCard
        self._quick_share_card = QuickShareCard(self._dialog_parent())
        self._quick_share_card.share_requested.connect(self._on_quick_share_card_request)
        self._quick_share_card.show_for_paths(paths, global_pos)

    def _on_quick_share_card_request(self, data: dict):
        """Handle share_requested signal from QuickShareCard."""
        if not self._lan_server or not self._lan_server.is_running():
            self._toggle_sharing()
            if not self._lan_server or not self._lan_server.is_running():
                if hasattr(self, '_quick_share_card') and self._quick_share_card:
                    self._quick_share_card.close()
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self._dialog_parent(), tr("sharing.error"), tr("sharing.failed_to_start"))
                return

        paths = data.get("paths", [])
        password = data.get("password")
        expiry_hours = data.get("expiry_hours")

        url = self._quick_share_api_url(self._lan_server)
        api_data = {
            "paths": paths,
            "expires_hours": expiry_hours or 24,
            "allow_preview": True,
        }
        if password:
            api_data["password"] = password

        headers = {"Content-Type": "application/json"}
        if hasattr(self._lan_server, 'token_secret'):
            from AssetsManager.lan.utils import get_auth_headers
            headers.update(get_auth_headers(self._lan_server.token_secret))

        from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool

        class _CardResult(QObject):
            finished = Signal(bool, object)

        class _CardTask(QRunnable):
            def __init__(self):
                super().__init__()
                self.setAutoDelete(False)
                self.signals = _CardResult()

            def run(self):
                try:
                    import requests
                    resp = requests.post(url, json=api_data, headers=headers, timeout=10)
                    if resp.status_code == 200:
                        self.signals.finished.emit(True, resp.json())
                    else:
                        err = resp.json().get("error", "Unknown error")
                        self.signals.finished.emit(False, err)
                except ImportError:
                    self.signals.finished.emit(False, "requests not installed")
                except Exception as e:
                    self.signals.finished.emit(False, str(e))

        task = _CardTask()
        task.signals.finished.connect(self._on_quick_share_card_result)
        QThreadPool.globalInstance().start(task)

    def _on_quick_share_card_result(self, success, data):
        """Handle async result for QuickShareCard share creation."""
        if not hasattr(self, '_quick_share_card') or not self._quick_share_card:
            return
        if success:
            share_url = data.get("url")
            if share_url:
                self._quick_share_card.show_result(share_url)
            else:
                self._quick_share_card.close()
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self._dialog_parent(), tr("sharing.error"), tr("sharing.no_url"))
        else:
            self._quick_share_card.close()
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self._dialog_parent(), tr("sharing.error"), f"{tr('sharing.failed_to_start')}: {data}")
