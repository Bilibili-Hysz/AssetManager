"""LanSharingMixin — LAN sharing logic extracted from MainWindow.

Contains:
- Toggle sharing on/off
- Share status display
- Share dialog with QR code, tunnel support
- Sharing settings integration
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton, QWidget
from AssetsManager import i18n
from AssetsManager.core import icons
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.widgets.sharing_contracts import (
    HOT_SHARING_DEFAULTS,
    HOT_SHARING_SETTINGS,
    RESTART_SHARING_SETTINGS as RESTART_SHARING_SETTINGS,
    _CONFIRMABLE_SECURITY_REASONS,
    _security_blocked_message,
    confirm_security_preflight,
)

if TYPE_CHECKING:
    from AssetsManager.application.context import LibrarySession
    from AssetsManager.application.desktop_ports import LanControlPort, ShareSettingsPort
    from AssetsManager.widgets.tray import SystemTrayManager

tr = i18n.tr

_log = logging.getLogger(__name__)


class LanSharingMixin:
    """Mixin for LAN sharing functionality. Must be used with QMainWindow."""

    # Supplied by the QMainWindow host. Annotations preserve the mixin's MRO.
    _lan_server: LanControlPort | None
    # Compatibility-only bundle injected by pre-runtime hosts. The mixin must
    # never assemble LAN/application services from legacy connection inputs.
    _lan_services: Any | None
    _library_session: LibrarySession | None
    _tray_manager: SystemTrayManager | None
    _sharing_port: ShareSettingsPort | None
    _lan_server_factory: Callable[..., Any] | None
    _share_status_label: QLabel
    _share_toggle_btn: QPushButton
    # True while an async server stop is in flight (toggle path only).
    _share_stop_in_progress: bool

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
        sharing_port = getattr(self, "_sharing_port", None)
        local_ip = getattr(sharing_port, "local_ip", None)
        if callable(local_ip):
            return f"http://{local_ip()}:{port}"
        return f"http://127.0.0.1:{port}"

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
        if getattr(self, "_share_stop_in_progress", False):
            # A stop is already running in the background; the toggle button
            # is disabled, so this guard only covers non-button triggers.
            return
        if self._lan_server and self._lan_server.is_running():
            self._begin_share_stop()
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
                rate_limit=settings.get("lan_rate_limit", 100),
                blocked_ips=settings.get("lan_blocked_ips", []),
                ip_whitelist=settings.get("lan_ip_whitelist", []),
                blur_tags=settings.get("lan_blur_tags", []),
                ssl_cert=settings.get("lan_ssl_cert"),
                ssl_key=settings.get("lan_ssl_key"),
            )
            server_factory = getattr(self, "_lan_server_factory", None)
            if not callable(server_factory):
                _log.error("No LAN server factory is injected into the sharing host")
                QMessageBox.warning(
                    self._dialog_parent(),
                    tr("dialog.error"),
                    tr("sharing.error_open", error="LAN server factory is not available"),
                )
                return
            server = cast(Callable[..., Any], server_factory)(
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

    def _begin_share_stop(self):
        """Stop the LAN server on a worker thread; write back state on done.

        ``server.stop()`` waits for the serving threads (up to seconds), so
        it must not run on the GUI thread.  The server handle stays on
        ``_lan_server`` until the stop completes: the library-switch
        coordinator inspects that handle and must still see a running
        server it can stop/wait for.  Only the toggle's UI affordances
        (button, status label) reflect the pending stop; correctness-order
        callers keep their synchronous semantics.
        """
        from AssetsManager.panels.file_list._background import run_task

        # The toggle path only reaches here while a server is running, so the
        # handle is present; keep the (captured) reference — _work must stop
        # exactly this server even if _lan_server is replaced afterwards.
        server = cast("LanControlPort", self._lan_server)
        self._share_stop_in_progress = True
        toggle_btn = getattr(self, "_share_toggle_btn", None)
        if toggle_btn is not None:
            toggle_btn.setEnabled(False)
        status_label = getattr(self, "_share_status_label", None)
        if status_label is not None:
            status_label.setText(tr("sharing.stopping"))

        def _work():
            server.stop()

        def _on_done(_result, exc):
            self._share_stop_in_progress = False
            toggle_btn = getattr(self, "_share_toggle_btn", None)
            if toggle_btn is not None:
                toggle_btn.setEnabled(True)
            try:
                if exc is not None:
                    # Keep the handle so a later toggle can retry the stop;
                    # report the still-running state instead of "off".
                    _log.error("LAN server stop failed: %s", exc)
                    self._update_share_status(True, getattr(server, "_port", 8080))
                    return
                if self._lan_server is server:
                    # Drop the stopped server handle and the now-stale
                    # security snapshot so a later start builds fresh state.
                    self._lan_server = None
                    self._share_security_snapshot = None
                    self._update_share_status(False)
                    if hasattr(self, '_tray_manager') and self._tray_manager:
                        self._tray_manager.update_sharing_state(False)
            except RuntimeError:
                # The host window was destroyed while the stop ran.
                _log.debug("LAN stop completion skipped: host gone")

        run_task(_work, on_done=_on_done)

    # ── Status display ──────────────────────────────────────────

    def _update_share_status(self, running, port=8080):
        """Update share status indicators in status bar and toolbar."""
        from AssetsManager.core import themes

        # Update status bar label
        if hasattr(self, '_share_status_label'):
            if running:
                url = self._active_share_url(port)
                self._share_status_label.setText(
                    f"{tr('sharing.status_active')} · {url}"
                )
                self._share_status_label.setStyleSheet(
                    f"color: {themes.color('accent')}; padding: 0 {scaled_px(8)}px;"
                )
                self._share_status_label.setToolTip(tr("sharing.click_to_copy"))
            else:
                self._share_status_label.setText(tr("sharing.off"))
                self._share_status_label.setStyleSheet(
                    f"color: {themes.color('muted')}; padding: 0 {scaled_px(8)}px;"
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
            dlg = SharingSettingsDialog(
                self._dialog_parent(),
                server_status=status,
                server=self._lan_server,
                desktop_port=getattr(self, "_sharing_port", None),
            )
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
                "lan_rate_limit": getattr(server_config, "_rate_limit_value", 100),
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
                # The stop must finish before the fresh start, so it stays
                # synchronous — surface the wait via cursor + status hint.
                from PySide6.QtWidgets import QApplication
                status_label = getattr(self, "_share_status_label", None)
                if status_label is not None:
                    status_label.setText(tr("sharing.stopping"))
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                try:
                    self._lan_server.stop()
                finally:
                    QApplication.restoreOverrideCursor()
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
