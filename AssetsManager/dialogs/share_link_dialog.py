"""ShareLinkDialog — Create share links for files/folders.

Independent dialog for creating share links with password, expiry, and download limits.
"""
import logging

from PySide6.QtCore import Qt, QObject, Signal, QRunnable, QThreadPool
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLineEdit,
    QApplication, QMessageBox,
)
from AssetsManager.dialogs.tabbed_dialog import TabbedDialog
from AssetsManager import i18n
from AssetsManager.core.ui_scale import scaled_px

tr = i18n.tr
_log = logging.getLogger(__name__)


class _ApiResult(QObject):
    """Signals for async API call results."""
    finished = Signal(bool, object)  # (success, data_or_error)


class _CreateShareTask(QRunnable):
    """Background task for creating a share link."""

    def __init__(self, url, data, headers):
        super().__init__()
        self._url = url
        self._data = data
        self._headers = headers
        self.signals = _ApiResult()

    def run(self):
        try:
            import requests
            resp = requests.post(self._url, json=self._data, headers=self._headers, timeout=10)
            if resp.status_code == 200:
                self.signals.finished.emit(True, resp.json())
            else:
                error = resp.json().get("error", tr("sharelink.error.unknown"))
                self.signals.finished.emit(False, error)
        except ImportError:
            self.signals.finished.emit(False, tr("sharelink.error.requests_missing"))
        except Exception as e:
            self.signals.finished.emit(False, str(e))


class ShareLinkDialog(TabbedDialog):
    """Dialog for creating share links."""

    def __init__(self, parent=None, path: str = "", server=None):
        self._path = path
        self._server = server
        self._share_url = None
        super().__init__(parent, title=tr("sharelink.title"), min_size=(400, 450))

    def _build_ui(self):
        """Build the share link creation dialog."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(scaled_px(16), scaled_px(16), scaled_px(16), scaled_px(16))
        layout.setSpacing(scaled_px(12))

        # Path display
        path_group = self.make_groupbox(tr("sharelink.group.path"))
        path_layout = QVBoxLayout(path_group)
        path_label = self.make_label(self._path)
        path_label.setWordWrap(True)
        path_layout.addWidget(path_label)
        layout.addWidget(path_group)

        # Options
        options_group = self.make_groupbox(tr("sharelink.group.options"))
        options_layout = QVBoxLayout(options_group)
        options_layout.setSpacing(scaled_px(8))

        # Password
        pw_row = self.make_labeled_row(tr("sharelink.label.password"), self.make_input(tr("sharelink.placeholder.password")))
        self._password_input = pw_row.itemAt(1).widget()
        self._password_input.setEchoMode(QLineEdit.EchoMode.Password)
        options_layout.addLayout(pw_row)

        # Expiry
        expiry_row = QHBoxLayout()
        expiry_row.addWidget(self.make_label(tr("sharelink.label.expires_after")))
        self._expiry_combo = self.make_combobox([
            tr("sharelink.expiry.never"), tr("sharelink.expiry.1hour"), tr("sharelink.expiry.6hours"),
            tr("sharelink.expiry.24hours"), tr("sharelink.expiry.7days"), tr("sharelink.expiry.30days")
        ])
        self._expiry_combo.setCurrentIndex(3)  # Default: 24 hours
        expiry_row.addWidget(self._expiry_combo)
        expiry_row.addStretch()
        options_layout.addLayout(expiry_row)

        # Max downloads
        dl_row = QHBoxLayout()
        dl_row.addWidget(self.make_label(tr("sharelink.label.max_downloads")))
        self._max_downloads_spin = self.make_spinbox(0, 10000, 0)
        self._max_downloads_spin.setSpecialValueText(tr("sharelink.spin.unlimited"))
        dl_row.addWidget(self._max_downloads_spin)
        dl_row.addStretch()
        options_layout.addLayout(dl_row)

        # Allow preview
        self._allow_preview_check = self.make_checkbox(tr("sharelink.checkbox.allow_preview"), checked=True)
        options_layout.addWidget(self._allow_preview_check)

        layout.addWidget(options_group)

        # Result section (hidden initially)
        self._result_group = self.make_groupbox(tr("sharelink.group.result"))
        result_layout = QVBoxLayout(self._result_group)

        self._url_label = self.make_label("")
        self._url_label.setWordWrap(True)
        self._url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._url_label.setStyleSheet(
            f"padding: {scaled_px(8)}px; background: {self._t['panel']}; "
            f"border: 1px solid {self._t['border']}; border-radius: {scaled_px(4)}px;"
        )
        result_layout.addWidget(self._url_label)

        # Key hint
        self._key_hint = self.make_muted("")
        self._key_hint.setVisible(False)
        result_layout.addWidget(self._key_hint)

        # Copy button
        btn_row = QHBoxLayout()
        self._copy_btn = self.make_primary_btn(tr("sharelink.btn.copy_link"), self._copy_link)
        self._copy_btn.setEnabled(False)
        btn_row.addWidget(self._copy_btn)

        self._open_btn = self.make_secondary_btn(tr("sharelink.btn.open_browser"), self._open_link)
        self._open_btn.setEnabled(False)
        btn_row.addWidget(self._open_btn)
        btn_row.addStretch()
        result_layout.addLayout(btn_row)

        self._result_group.setVisible(False)
        layout.addWidget(self._result_group)

        # Action buttons
        action_row = QHBoxLayout()
        self._create_btn = self.make_primary_btn(tr("sharelink.btn.create_link"), self._create_link)
        action_row.addWidget(self._create_btn)

        self._close_btn = self.make_secondary_btn(tr("sharelink.btn.close"), self.accept)
        action_row.addWidget(self._close_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

        layout.addStretch()

    def _create_link(self):
        """Create the share link via API (async, non-blocking)."""
        if not self._server:
            QMessageBox.warning(self, tr("sharelink.msg.error_title"), tr("sharelink.error.server_unavailable"))
            return

        password = self._password_input.text().strip() or None
        expiry_map = {0: None, 1: 1, 2: 6, 3: 24, 4: 168, 5: 720}
        expires_hours = expiry_map.get(self._expiry_combo.currentIndex())
        max_downloads = self._max_downloads_spin.value() or None
        allow_preview = self._allow_preview_check.isChecked()

        port = self._server._port
        url = f"http://localhost:{port}/api/shares"
        data = {
            "paths": [self._path],
            "password": password,
            "expires_hours": expires_hours,
            "max_downloads": max_downloads,
            "allow_preview": allow_preview,
        }

        headers = {"Content-Type": "application/json"}
        if hasattr(self._server, 'token_secret'):
            from AssetsManager.lan.utils import get_auth_headers
            headers.update(get_auth_headers(self._server.token_secret))

        self._create_btn.setEnabled(False)
        self._create_btn.setText(tr("sharelink.btn.creating"))

        task = _CreateShareTask(url, data, headers)
        task.signals.finished.connect(self._on_create_result)
        QThreadPool.globalInstance().start(task)

    def _on_create_result(self, success, data):
        """Handle async share link creation result."""
        self._create_btn.setText(tr("sharelink.btn.create_link"))
        if success:
            self._share_url = data.get("url")
            requires_key = data.get("requires_key", False)
            self._url_label.setText(self._share_url)
            self._result_group.setVisible(True)
            self._create_btn.setEnabled(False)
            if requires_key:
                self._key_hint.setText(tr("sharelink.hint.requires_key"))
                self._key_hint.setVisible(True)
            else:
                self._key_hint.setVisible(False)
            self._copy_btn.setEnabled(True)
            self._open_btn.setEnabled(True)
            self._create_btn.setEnabled(True)
        else:
            self._create_btn.setEnabled(True)
            QMessageBox.warning(self, tr("sharelink.msg.error_title"), tr("sharelink.error.create_failed").format(data=data))

    def _copy_link(self):
        """Copy share link to clipboard."""
        if self._share_url:
            QApplication.clipboard().setText(self._share_url)
            self._copy_btn.setText(tr("sharelink.btn.copied"))
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1500, lambda: self._copy_btn.setText(tr("sharelink.btn.copy_link")))

    def _open_link(self):
        """Open share link in browser."""
        if self._share_url:
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(self._share_url))

    def get_share_url(self) -> str | None:
        """Return the created share URL."""
        return self._share_url
