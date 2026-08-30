"""Activity panel — surface the per-library activity_log on the desktop.

The ``activity_log`` table already receives desktop rows (file/tag/import
operations through ``ActivityRecorder``) and LAN rows (the web admin feed's
richer ``ActivityLog``); this dialog is the missing read side on the desktop:
the most recent 200 rows, newest first, with a day-range filter. Reads go
through the session connection under the shared write lock (same discipline
as the LAN ``recent()`` reader) and never escalate a read failure — an empty
table or a read error renders as an inline hint, never an exception.
"""
from __future__ import annotations

import logging
from datetime import datetime
from time import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from AssetsManager.core.database import db_write_lock
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.dialogs.tabbed_dialog import TabbedDialog
from AssetsManager import i18n

tr = i18n.tr
_log = logging.getLogger(__name__)

#: Row cap: the panel is a "what happened recently" view, not an audit dump.
MAX_ROWS = 200

#: Filter keys for the day-range combo (index-aligned with the items added
#: in _build_ui): today / 7 days / 30 days / all, default 7 days.
_FILTER_TODAY, _FILTER_7D, _FILTER_30D, _FILTER_ALL = range(4)

_COL_TIME, _COL_ACTION, _COL_USER, _COL_DETAILS = range(4)


def _cutoff_timestamp(filter_index: int, *, now: float | None = None) -> float | None:
    """Return the ``timestamp >`` cutoff for a filter, or ``None`` for "all".

    "Today" means since local midnight; the day filters use whole-day
    windows. Exposed module-level so tests can pin ``now``.
    """
    current = time() if now is None else now
    if filter_index == _FILTER_ALL:
        return None
    if filter_index == _FILTER_TODAY:
        # "Today" is deliberately the user's local midnight (wall-clock day),
        # matching the local-time display format of the rows.
        today = datetime.fromtimestamp(current)  # noqa: DTZ006
        midnight = today.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight.timestamp()
    days = {_FILTER_7D: 7, _FILTER_30D: 30}.get(filter_index, 7)
    return current - days * 24 * 60 * 60


class ActivityPanelDialog(TabbedDialog):
    """Read-only viewer for the library's ``activity_log`` (H1-b E-C3).

    Binds one open ``LibrarySession`` and reads through
    ``session.connection_for`` — the same session connection every desktop
    service uses — so no second connection is opened and the shared write
    lock keeps the SELECT from racing in-flight writers.
    """

    def __init__(self, session, parent=None):
        self._session = session
        super().__init__(
            parent, title=tr("activity_panel.title"), min_size=(680, 420))
        self.setObjectName("ActivityPanelDialog")

    # ── UI ───────────────────────────────────────────────────────

    def _build_ui(self):
        self.setStyleSheet(self._dialog_qss())
        root = QVBoxLayout(self)
        root.setContentsMargins(
            scaled_px(12), scaled_px(12), scaled_px(12), scaled_px(12))
        root.setSpacing(scaled_px(8))

        controls = QHBoxLayout()
        self._filter_combo = QComboBox(self)
        self._filter_combo.addItems([
            tr("activity_panel.filter_today"),
            tr("activity_panel.filter_7d"),
            tr("activity_panel.filter_30d"),
            tr("activity_panel.filter_all"),
        ])
        self._filter_combo.setCurrentIndex(_FILTER_7D)
        self._filter_combo.currentIndexChanged.connect(self._refresh)
        controls.addWidget(QLabel(tr("activity_panel.filter_label"), self))
        controls.addWidget(self._filter_combo)
        controls.addStretch()
        self._refresh_btn = self.make_secondary_btn(
            tr("activity_panel.refresh"), self._refresh)
        controls.addWidget(self._refresh_btn)
        root.addLayout(controls)

        self._table = QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels([
            tr("activity_panel.col_time"),
            tr("activity_panel.col_action"),
            tr("activity_panel.col_user"),
            tr("activity_panel.col_details"),
        ])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setWordWrap(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(_COL_DETAILS, QHeaderView.ResizeMode.Stretch)
        for column in (_COL_TIME, _COL_ACTION, _COL_USER):
            header.setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._table, 1)

        # Inline status line: empty state / read-error hint (non-critical
        # errors stay inline per the dialog error convention).
        self._status_label = QLabel("", self)
        self._status_label.setWordWrap(True)
        root.addWidget(self._status_label)

        self._refresh()

    # ── Data ─────────────────────────────────────────────────────

    def _fetch_rows(self) -> list[tuple] | None:
        """Read the newest rows; ``None`` signals a read error.

        Read-only SELECT under the connection's write lock (the LAN
        ``recent()`` discipline): the library shares one
        ``check_same_thread=False`` connection across surfaces, so an
        unguarded read could race an in-flight write transaction. Connection
        acquisition failures degrade to the same ``None`` as query failures —
        a viewer never escalates.
        """
        try:
            conn = self._session.connection_for(self._session.root)
            cutoff = _cutoff_timestamp(self._filter_combo.currentIndex())
            sql = (
                "SELECT timestamp, action, username, details FROM activity_log "
            )
            if cutoff is not None:
                sql += "WHERE timestamp > ? "
            sql += "ORDER BY timestamp DESC, id DESC LIMIT ?"
            parameters: tuple = (
                (cutoff, MAX_ROWS) if cutoff is not None else (MAX_ROWS,))
            with db_write_lock(conn):
                return conn.execute(sql, parameters).fetchall()
        except Exception:
            # A read failure must never surface as an exception from a
            # viewer; the caller renders the inline error hint instead.
            _log.exception("Activity log read failed")
            return None

    def _refresh(self):
        rows = self._fetch_rows()
        if rows is None:
            self._table.setRowCount(0)
            self._status_label.setText(tr("activity_panel.read_error"))
            return
        self._table.setRowCount(len(rows))
        for row_index, (timestamp, action, username, details) in enumerate(rows):
            self._table.setItem(
                row_index, _COL_TIME,
                self._read_only(_format_time(timestamp)))
            self._table.setItem(
                row_index, _COL_ACTION, self._read_only(str(action or "")))
            self._table.setItem(
                row_index, _COL_USER, self._read_only(str(username or "")))
            self._table.setItem(
                row_index, _COL_DETAILS, self._read_only(str(details or "")))
        self._status_label.setText(
            tr("activity_panel.empty") if not rows else "")

    @staticmethod
    def _read_only(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        return item


def _format_time(timestamp: float) -> str:
    try:
        # Local-time display, same convention as the other desktop panels.
        return datetime.fromtimestamp(float(timestamp)).strftime(  # noqa: DTZ006
            "%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, TypeError, ValueError):
        return "—"
