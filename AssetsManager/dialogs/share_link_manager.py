"""ShareLinkManager — Manage existing share links.

Dialog for listing, viewing, and deleting share links.
"""
import logging

from PySide6.QtCore import Qt, QTimer, QObject, Signal, QRunnable, QThreadPool
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QApplication, QAbstractItemView, QWidget,
)
from AssetsManager.dialogs.tabbed_dialog import TabbedDialog
from AssetsManager import i18n
from AssetsManager.core.ui_scale import scaled_px, scaled_pt

tr = i18n.tr
_log = logging.getLogger(__name__)


class _ApiResult(QObject):
    """Signals for async API call results."""
    finished = Signal(bool, object)  # (success, data_or_error)


class _HttpGetTask(QRunnable):
    """Background task for GET requests."""

    def __init__(self, url, headers):
        super().__init__()
        self._url = url
        self._headers = headers
        self.signals = _ApiResult()

    def run(self):
        try:
            import requests
            resp = requests.get(self._url, headers=self._headers, timeout=10)
            if resp.status_code == 200:
                self.signals.finished.emit(True, resp.json())
            else:
                self.signals.finished.emit(False, tr("sharemgr.error.load_failed"))
        except Exception as e:
            self.signals.finished.emit(False, str(e))


class _HttpDeleteTask(QRunnable):
    """Background task for DELETE requests."""

    def __init__(self, url, headers):
        super().__init__()
        self._url = url
        self._headers = headers
        self.signals = _ApiResult()

    def run(self):
        try:
            import requests
            resp = requests.delete(self._url, headers=self._headers, timeout=10)
            if resp.status_code == 200:
                self.signals.finished.emit(True, None)
            else:
                self.signals.finished.emit(False, tr("sharemgr.error.delete_failed_generic"))
        except Exception as e:
            self.signals.finished.emit(False, str(e))


class ShareLinkManager(TabbedDialog):
    """Dialog for managing share links."""

    def __init__(self, parent=None, server=None):
        self._server = server
        self._shares = []
        super().__init__(parent, title=tr("sharemgr.title"), min_size=(600, 400))

    def _build_ui(self):
        """Build the share link manager dialog."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(scaled_px(16), scaled_px(16), scaled_px(16), scaled_px(16))
        layout.setSpacing(scaled_px(12))

        # Apply theme
        self.setStyleSheet(self._dialog_qss())

        # Header
        header_row = QHBoxLayout()
        header_label = self.make_heading(tr("sharemgr.heading.active_links"))
        header_row.addWidget(header_label)
        header_row.addStretch()

        self._refresh_btn = self.make_secondary_btn(tr("sharemgr.btn.refresh"), self._load_shares)
        header_row.addWidget(self._refresh_btn)
        layout.addLayout(header_row)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels([tr("sharemgr.col.path"), tr("sharemgr.col.created"), tr("sharemgr.col.expires"), tr("sharemgr.col.downloads"), tr("sharemgr.col.actions")])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)

        # Set column widths
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(4, scaled_px(200))

        # Apply table theme
        t = self._t
        self._table.setStyleSheet(
            f"QTableWidget {{ background: {t['panel']}; color: {t['body']}; "
            f"border: 1px solid {t['border']}; border-radius: {scaled_px(4)}px; }}"
            f"QTableWidget::item {{ padding: {scaled_px(4)}px; }}"
            f"QTableWidget::item:selected {{ background: {t['accent']}; }}"
            f"QHeaderView::section {{ background: {t['header']}; color: {t['heading']}; "
            f"padding: {scaled_px(4)}px; border: none; border-right: 1px solid {t['border']}; }}"
        )
        layout.addWidget(self._table)

        # Status
        self._status_label = self.make_muted(tr("sharemgr.status.loading"))
        layout.addWidget(self._status_label)

        # Bottom buttons
        btn_row = QHBoxLayout()
        self._delete_selected_btn = self.make_secondary_btn(tr("sharemgr.btn.delete_selected"), self._delete_selected)
        self._delete_selected_btn.setEnabled(False)
        btn_row.addWidget(self._delete_selected_btn)

        self._copy_link_btn = self.make_secondary_btn(tr("sharemgr.btn.copy_link"), self._copy_link)
        self._copy_link_btn.setEnabled(False)
        btn_row.addWidget(self._copy_link_btn)

        btn_row.addStretch()

        self._close_btn = self.make_secondary_btn(tr("sharemgr.btn.close"), self.accept)
        btn_row.addWidget(self._close_btn)
        layout.addLayout(btn_row)

        # Connect selection change
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        # Load shares
        self._load_shares()

    def _load_shares(self):
        """Load share links from server (async, non-blocking)."""
        if not self._server:
            self._status_label.setText(tr("sharemgr.error.server_unavailable"))
            return

        self._status_label.setText(tr("sharemgr.status.loading"))
        port = self._server._port
        url = f"http://localhost:{port}/api/shares"
        headers = {}
        if hasattr(self._server, 'token_secret'):
            from AssetsManager.lan.utils import get_auth_headers
            headers.update(get_auth_headers(self._server.token_secret))

        self._load_task = _HttpGetTask(url, headers)
        self._load_task.signals.finished.connect(self._on_load_result)
        QThreadPool.globalInstance().start(self._load_task)

    def _on_load_result(self, success, data):
        """Handle async load result."""
        if success:
            self._shares = data.get("shares", [])
            self._populate_table()
            if self._shares:
                self._status_label.setText(tr("sharemgr.status.active_count").format(count=len(self._shares)))
            else:
                self._status_label.setText(tr("sharemgr.status.empty"))
        else:
            self._status_label.setText(tr("sharemgr.status.error").format(data=str(data)))

    def _populate_table(self):
        """Populate table with share links."""
        self._table.setRowCount(len(self._shares))

        for i, share in enumerate(self._shares):
            # Path
            paths = share.get("paths", [])
            path_text = ", ".join(paths) if paths else tr("sharemgr.fallback.unknown")
            path_item = QTableWidgetItem(path_text)
            path_item.setData(Qt.ItemDataRole.UserRole, share.get("id"))
            self._table.setItem(i, 0, path_item)

            # Created
            created = share.get("created_fmt", tr("sharemgr.fallback.unknown"))
            self._table.setItem(i, 1, QTableWidgetItem(created))

            # Expires
            expires = share.get("expires_fmt", tr("sharemgr.fallback.never"))
            self._table.setItem(i, 2, QTableWidgetItem(expires))

            # Downloads
            downloads = share.get("download_count", 0)
            max_downloads = share.get("max_downloads")
            if max_downloads:
                dl_text = f"{downloads}/{max_downloads}"
            else:
                dl_text = f"{downloads}/∞"
            self._table.setItem(i, 3, QTableWidgetItem(dl_text))

            # Actions
            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(scaled_px(4), scaled_px(2), scaled_px(4), scaled_px(2))
            actions_layout.setSpacing(scaled_px(4))

            copy_btn = QPushButton(tr("sharemgr.btn.copy"))
            copy_btn.setFixedSize(scaled_px(60), scaled_px(24))
            copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            copy_btn.setStyleSheet(
                f"QPushButton {{ background: {self._t['accent']}; color: {self._t.get('on_accent', 'white')}; "
                f"border: none; border-radius: {scaled_px(3)}px; font-size: {scaled_pt(11)}px; }}"
                f"QPushButton:hover {{ background: {self._t['accent']}dd; }}"
            )
            copy_btn.clicked.connect(lambda checked, idx=i: self._copy_share_link(idx))
            actions_layout.addWidget(copy_btn)

            delete_btn = QPushButton(tr("sharemgr.btn.delete"))
            delete_btn.setFixedSize(scaled_px(60), scaled_px(24))
            delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            delete_btn.setStyleSheet(
                f"QPushButton {{ background: {self._t['danger']}; color: {self._t.get('on_accent', 'white')}; "
                f"border: none; border-radius: {scaled_px(3)}px; font-size: {scaled_pt(11)}px; }}"
                f"QPushButton:hover {{ background: {self._t['danger']}dd; }}"
            )
            delete_btn.clicked.connect(lambda checked, idx=i: self._delete_share(idx))
            actions_layout.addWidget(delete_btn)

            actions_layout.addStretch()
            self._table.setCellWidget(i, 4, actions_widget)

    def _on_selection_changed(self):
        """Handle selection change in table."""
        has_selection = len(self._table.selectedItems()) > 0
        self._delete_selected_btn.setEnabled(has_selection)
        self._copy_link_btn.setEnabled(has_selection)

    def _copy_link(self):
        """Copy selected share link to clipboard."""
        selected = self._table.selectedItems()
        if not selected:
            return

        row = selected[0].row()
        self._copy_share_link(row)

    def _copy_share_link(self, row: int):
        """Copy share link for a specific row."""
        if row < 0 or row >= len(self._shares):
            return
        server = self._server
        if server is None:
            self._status_label.setText(tr("sharemgr.error.server_unavailable"))
            return

        share = self._shares[row]
        share_id = share.get("id")
        if not share_id:
            return

        # Build URL
        port = server._port
        from AssetsManager.lan.server import get_local_ip
        ip = get_local_ip()
        url = f"http://{ip}:{port}/s/{share_id}"

        QApplication.clipboard().setText(url)
        self._status_label.setText(tr("sharemgr.status.link_copied"))

        # Reset status after 2 seconds
        QTimer.singleShot(2000, lambda: self._status_label.setText(
            tr("sharemgr.status.active_count").format(count=len(self._shares))
        ))

    def _delete_selected(self):
        """Delete selected share link."""
        selected = self._table.selectedItems()
        if not selected:
            return

        row = selected[0].row()
        self._delete_share(row)

    def _delete_share(self, row: int):
        """Delete share link for a specific row (async, non-blocking)."""
        if row < 0 or row >= len(self._shares):
            return
        server = self._server
        if server is None:
            self._status_label.setText(tr("sharemgr.error.server_unavailable"))
            return

        share = self._shares[row]
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

        port = server._port
        url = f"http://localhost:{port}/api/shares/{share_id}"
        headers = {}
        if hasattr(server, 'token_secret'):
            from AssetsManager.lan.utils import get_auth_headers
            headers.update(get_auth_headers(server.token_secret))

        captured_row = row
        self._delete_task = _HttpDeleteTask(url, headers)
        self._delete_task.signals.finished.connect(lambda ok, msg: self._on_delete_result(ok, msg, captured_row, share_id))
        QThreadPool.globalInstance().start(self._delete_task)

    def _on_delete_result(self, success, _data, row: int, share_id: str):
        """Handle async delete result."""
        if success:
            if 0 <= row < len(self._shares):
                self._shares.pop(row)
                self._populate_table()
            self._status_label.setText(tr("sharemgr.status.deleted"))
        else:
            QMessageBox.warning(self, tr("sharemgr.msg.error_title"), tr("sharemgr.error.delete_failed").format(data=str(_data)))
