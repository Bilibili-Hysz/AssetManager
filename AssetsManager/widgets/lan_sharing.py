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

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton, QWidget
from AssetsManager import i18n
from AssetsManager.core import icons
from AssetsManager.core.ui_scale import scaled_px

if TYPE_CHECKING:
    from AssetsManager.application.context import LibrarySession
    from AssetsManager.lan import LanServer
    from AssetsManager.lan.routes._helpers import LanScopedServices
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
    "lan_port", "lan_bind", "lan_auth_mode", "lan_password", "lan_access_key",
    "lan_rate_limit", "lan_blocked_ips", "lan_ip_whitelist", "lan_ssl_cert", "lan_ssl_key",
})
_CONFIRMABLE_SECURITY_REASONS = frozenset({
    "share_safety_ack_required",
    "bind_scope_expanded",
    "authentication_removed",
    "trusted_network_confirmation_required",
})
_SECURITY_REASON_KEYS = {
    "share_safety_ack_required": "sharing.security.reason_ack_required",
    "bind_scope_expanded": "sharing.security.reason_bind_scope_expanded",
    "authentication_removed": "sharing.security.reason_authentication_removed",
    "trusted_network_confirmation_required": "sharing.security.reason_trusted_required",
}


def _security_blocked_message(reason: str) -> str:
    reason_key = _SECURITY_REASON_KEYS.get(reason)
    reason_text = tr(reason_key) if reason_key else tr("sharing.security.reason_generic")
    return tr("sharing.security.blocked_message", reason=reason_text)


def confirm_security_preflight(
    parent: QWidget | None,
    *,
    settings,
    preflight,
    snapshot,
    bind: str | None,
    auth_status,
) -> bool:
    """Ask for an explicit user decision and atomically persist it.

    This is deliberately the only UI-facing confirmation helper.  It never
    starts a server; callers must re-run the pure preflight snapshot after a
    successful commit and only then enter the lifecycle path.
    """
    from AssetsManager.application.security_preflight import effective_auth, is_lan_bind

    reason = getattr(snapshot, "failure_reason", None)
    if reason not in _CONFIRMABLE_SECURITY_REASONS:
        return False

    auth = effective_auth(auth_status)
    if is_lan_bind(bind) and not auth["enabled"]:
        title_key = "sharing.security.confirm_trusted_title"
        message_key = "sharing.security.confirm_trusted_message"
        confirm_decision = preflight.confirm_trusted_lan
    elif is_lan_bind(bind):
        title_key = "sharing.security.confirm_authenticated_title"
        message_key = "sharing.security.confirm_authenticated_message"
        confirm_decision = preflight.confirm_authenticated_lan
    else:
        title_key = "sharing.security.confirm_local_title"
        message_key = "sharing.security.confirm_local_message"
        confirm_decision = preflight.confirm_authenticated_lan

    # Do not mutate confirmation state until the user explicitly accepts.
    decision = QMessageBox.question(
        parent,
        tr(title_key),
        tr(message_key),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if decision != QMessageBox.StandardButton.Yes:
        preflight.cancel()
        return False

    confirm_decision()
    committer = getattr(settings, "commit_share_safety_confirmation", None)
    persisted = False
    if callable(committer):
        try:
            persisted = bool(
                committer(
                    preflight.ack_version,
                    preflight.trusted_network_confirmed,
                )
            )
        except Exception:
            _log.exception("Unable to persist LAN security confirmation")
            persisted = False

    if not persisted:
        preflight.cancel()
        QMessageBox.warning(
            parent,
            tr("sharing.security.persist_failed_title"),
            tr("sharing.security.persist_failed_message"),
        )
        return False
    return True


class LanSharingMixin:
    """Mixin for LAN sharing functionality. Must be used with QMainWindow."""

    # Supplied by the QMainWindow host. Annotations preserve the mixin's MRO.
    _lan_server: LanServer | None
    # Compatibility-only bundle injected by pre-runtime hosts. The mixin must
    # never assemble LAN/application services from legacy connection inputs.
    _lan_services: LanScopedServices | None
    _library_session: LibrarySession | None
    _tray_manager: SystemTrayManager | None
    _share_status_label: QLabel
    _share_toggle_btn: QPushButton

    def _dialog_parent(self) -> QWidget:
        return cast(QWidget, self)

    def _active_share_url(self, port: int) -> str:
        server = getattr(self, "_lan_server", None)
        if server is not None:
            status = server.status()
            if isinstance(status, dict):
                url = status.get("url")
                if isinstance(url, str) and url:
                    return url
        from AssetsManager.lan.server import get_local_ip

        return f"http://{get_local_ip()}:{port}"

    @staticmethod
    def _runtime_auth_status(runtime, *, password, access_key, auth_mode):
        if access_key:
            return True, "key"
        if password:
            return True, "password"
        if auth_mode not in {"user", "users"}:
            return False, "none"
        services = getattr(runtime, "sharing_services", None)
        auth_service = getattr(services, "auth_service", None)
        has_active_users = getattr(auth_service, "has_active_users", None)
        if not callable(has_active_users):
            return False, "none"
        try:
            return (True, "user") if has_active_users(raise_on_error=True) else (False, "none")
        except Exception:
            _log.exception("Unable to inspect active LAN users before startup")
            return False, "none"

    # ── Toggle sharing ──────────────────────────────────────────

    def _toggle_sharing(self):
        """Start or stop LAN sharing."""
        from AssetsManager import lan
        if self._lan_server and self._lan_server.is_running():
            self._lan_server.stop()
            # Drop the stopped server handle and the now-stale security
            # snapshot so a later start builds fresh state.
            self._lan_server = None
            self._share_security_snapshot = None
            self._update_share_status(False)
            if hasattr(self, '_tray_manager') and self._tray_manager:
                self._tray_manager.update_sharing_state(False)
            return

        # Start sharing
        from AssetsManager.core.settings import AppSettings
        from AssetsManager.application.security_preflight import (
            security_preflight_from_settings,
        )
        settings = AppSettings.instance()
        port = settings.get("lan_port", 8080)
        bind = settings.get("lan_bind", "0.0.0.0")
        password = settings.get("lan_password")
        access_key = settings.get("lan_access_key")
        auth_mode = settings.get("lan_auth_mode", "none")
        share_name = settings.get("lan_share_name", "AssetManager")
        session = getattr(self, "_library_session", None)
        if session is None or session.is_closed:
            QMessageBox.warning(self._dialog_parent(), tr("dialog.error"), tr("sharing.no_library"))
            return

        bootstrap = getattr(self, "_bootstrap", None)
        runtime_for = getattr(bootstrap, "runtime_for", None)
        if not callable(runtime_for):
            _log.error("Cannot start LAN sharing without the canonical application bootstrap")
            QMessageBox.warning(self._dialog_parent(), tr("dialog.error"), tr("sharing.no_library"))
            return
        runtime = runtime_for(session)

        preflight = security_preflight_from_settings(settings)
        configured_auth = self._runtime_auth_status(
            runtime,
            password=password,
            access_key=access_key,
            auth_mode=auth_mode,
        )
        security_snapshot = preflight.snapshot(
            sharing=True,
            bind=bind,
            auth_status=configured_auth,
        )
        self._share_security_snapshot = security_snapshot
        if security_snapshot.share_state != "local_active":
            reason = security_snapshot.failure_reason or "share_safety_ack_required"
            parent = self._dialog_parent()
            if not isinstance(parent, QWidget):
                parent = None
            if reason in _CONFIRMABLE_SECURITY_REASONS:
                confirmed = confirm_security_preflight(
                    parent,
                    settings=settings,
                    preflight=preflight,
                    snapshot=security_snapshot,
                    bind=bind,
                    auth_status=configured_auth,
                )
                if not confirmed:
                    self._share_security_snapshot = preflight.snapshot(
                        sharing=True,
                        bind=bind,
                        auth_status=configured_auth,
                    )
                    return
                security_snapshot = preflight.snapshot(
                    sharing=True,
                    bind=bind,
                    auth_status=configured_auth,
                )
                self._share_security_snapshot = security_snapshot
            if security_snapshot.share_state != "local_active":
                QMessageBox.warning(
                    parent,
                    tr("dialog.error"),
                    _security_blocked_message(reason),
                )
                return

        try:
            options = dict(
                share_name=share_name,
                password=password,
                access_key=access_key,
                auth_mode=auth_mode,
                rate_limit=settings.get("lan_rate_limit", 1000),
                blocked_ips=settings.get("lan_blocked_ips", []),
                ip_whitelist=settings.get("lan_ip_whitelist", []),
                blur_tags=settings.get("lan_blur_tags", []),
                ssl_cert=settings.get("lan_ssl_cert"),
                ssl_key=settings.get("lan_ssl_key"),
            )
            server = lan.LanServer(
                runtime=runtime,
                preflight=preflight,
                **options,
            )
            start_result = server.start(port=port, bind=bind)
            if isinstance(start_result, dict) and start_result.get("share_state") != "local_active":
                self._share_security_snapshot = start_result
                server_running = bool(
                    start_result.get("running") or start_result.get("rollback_failed")
                )
                if not server_running:
                    is_running = getattr(server, "is_running", None)
                    if callable(is_running):
                        try:
                            server_running = bool(is_running())
                        except Exception:
                            _log.exception("Unable to inspect LAN server after failed startup")
                reason = start_result.get("failure_reason") or "share_safety_ack_required"
                parent = self._dialog_parent()
                if not isinstance(parent, QWidget):
                    parent = None
                if server_running:
                    # The server is actually up despite the reported failure
                    # (e.g. a rollback that failed after a post-start security
                    # problem). Surface the reason as an additional hint, but
                    # keep the status bar and tray consistent with the
                    # running server instead of showing "off".
                    self._lan_server = server
                    QMessageBox.warning(
                        parent,
                        tr("dialog.error"),
                        _security_blocked_message(reason),
                    )
                    self._update_share_status(True, port)
                    if hasattr(self, '_tray_manager') and self._tray_manager:
                        self._tray_manager.update_sharing_state(
                            True, self._active_share_url(port)
                        )
                    return
                QMessageBox.warning(
                    parent,
                    tr("dialog.error"),
                    _security_blocked_message(reason),
                )
                return
            self._lan_server = server
            self._update_share_status(True, port)
            if hasattr(self, '_tray_manager') and self._tray_manager:
                self._tray_manager.update_sharing_state(
                    True, self._active_share_url(port)
                )
        except (OSError, ValueError, TypeError):
            _log.exception("LAN server failed to start on port %s", port)
            QMessageBox.warning(self._dialog_parent(), tr("dialog.error"), tr("sharing.port_in_use", port=port))

    # ── Status display ──────────────────────────────────────────

    def _update_share_status(self, running, port=8080):
        """Update share status indicators in status bar and toolbar."""
        from AssetsManager.core import themes
        t = themes.get()

        # Update status bar label
        if hasattr(self, '_share_status_label'):
            if running:
                url = self._active_share_url(port)
                self._share_status_label.setText(
                    f"{tr('sharing.status_active')} · {url}"
                )
                self._share_status_label.setStyleSheet(
                    f"color: {t['accent']}; padding: 0 8px;"
                )
                self._share_status_label.setToolTip(tr("sharing.click_to_copy"))
            else:
                self._share_status_label.setText(tr("sharing.off"))
                self._share_status_label.setStyleSheet(
                    f"color: {t['muted']}; padding: 0 8px;"
                )
                self._share_status_label.setToolTip(tr("sharing.click_to_share"))

        # Update toolbar button
        if hasattr(self, '_share_toggle_btn'):
            if running:
                self._share_toggle_btn.setIcon(
                    icons.icon("close", color="icon_primary", size=scaled_px(16)))
                self._share_toggle_btn.setToolTip(tr("sharing.stop_tooltip"))
            else:
                self._share_toggle_btn.setIcon(
                    icons.icon("share", color="icon_primary", size=scaled_px(16)))
                self._share_toggle_btn.setToolTip(tr("sharing.start_tooltip"))
            self._share_toggle_btn.setIconSize(QSize(scaled_px(16), scaled_px(16)))
            self._share_toggle_btn.setText("")
            self._share_toggle_btn.setAccessibleName(self._share_toggle_btn.toolTip())


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
                "lan_auth_mode": getattr(
                    server_config, "_auth_mode", settings.get("lan_auth_mode", "none")
                ),
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
                # The restart deliberately re-enters the full startup
                # lifecycle (_toggle_sharing), which re-runs the security
                # preflight and may ask the user to confirm again. This is
                # intentional: restart-required settings (bind scope, auth
                # mode, password, ...) change the security posture, so the
                # previous confirmation snapshot must NOT be reused —
                # re-verification against the new settings is required.
                self._lan_server.stop()
                self._update_share_status(False)
                self._toggle_sharing()
        else:
            self._toggle_sharing()

    # ── Share Link Management ───────────────────────────────────

    def _open_share_link_dialog(self, path: str = "", paths: list[str] | None = None):
        """Open dialog to create a share link for a path."""
        try:
            from AssetsManager.core.settings import AppSettings
            from AssetsManager.dialogs.share_link_dialog import ShareLinkDialog

            session = getattr(self, "_library_session", None)
            if session is None or session.is_closed:
                QMessageBox.warning(self._dialog_parent(), tr("dialog.error"), tr("sharing.no_library"))
                return
            bootstrap = getattr(self, "_bootstrap", None)
            runtime_for = getattr(bootstrap, "runtime_for", None)
            if not callable(runtime_for):
                QMessageBox.warning(
                    self._dialog_parent(), tr("dialog.error"), tr("sharing.no_library")
                )
                return
            runtime = runtime_for(session)
            sharing_services = getattr(runtime, "sharing_services", None)
            share_service = getattr(sharing_services, "share_service", None)
            if share_service is None:
                QMessageBox.warning(self._dialog_parent(), tr("dialog.error"), tr("sharelink.error.server_unavailable"))
                return

            settings = AppSettings.instance()
            server = getattr(self, "_lan_server", None)
            running = bool(server and server.is_running())
            server_config = getattr(server, "_impl", server) if running else None
            port = getattr(server, "_port", None) if running else None
            if port is None:
                port = settings.get("lan_port", 8080)

            if running:
                requires_key = bool(
                    getattr(server_config, "access_key_hash", None)
                )
            else:
                requires_key = bool(settings.get("lan_access_key"))

            selected_paths = list(paths) if paths is not None else ([path] if path else [])
            base_url = self._active_share_url(port)
            dlg = ShareLinkDialog(
                self._dialog_parent(),
                paths=selected_paths,
                server=server,
                share_service=share_service,
                base_url=base_url,
                requires_key=requires_key,
            )
            dlg.exec()
        except Exception as e:
            _log.exception("Failed to open share link dialog")
            QMessageBox.warning(self._dialog_parent(), tr("dialog.error"), str(e))
