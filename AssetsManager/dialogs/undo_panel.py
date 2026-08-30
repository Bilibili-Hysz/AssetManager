"""Undo history panel — the in-library find-again entry point (H1-b E-C2).

Honest-minimum scope: the undo stack is session memory (LIFO), so this panel
shows exactly what can really be undone/redone right now — the current
session's history via :meth:`UndoService.history_snapshot` — plus the backup
retention promise for delete-type entries (90 days under the library data
directory). It deliberately does NOT pretend to be an arbitrary-recycle-bin:

- no cross-session history (the stack is not persisted),
- no selective restore of arbitrary entries (LIFO semantics only support
  consecutive undo/redo from the top),
- no direct backup-file restore (bypassing the undo execution path would
  skip projection snapshots and has real data risk).

After a successful undo the panel refreshes its own list and publishes one
``FileSystemChanged`` so the open projections re-render; the file operations
inside the undo publish their own per-kind events on top.
"""
from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from AssetsManager import i18n
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.dialogs.tabbed_dialog import TabbedDialog
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import FileSystemChanged

tr = i18n.tr
_log = logging.getLogger(__name__)

# Columns of the history table (kept in one place so the fill logic and the
# header labels cannot drift apart).
_COL_TYPE, _COL_TARGET, _COL_TIME, _COL_STATE, _COL_RETENTION = range(5)


class UndoPanelDialog(TabbedDialog):
    """Session-scoped undo/redo history with a one-step undo button.

    Binds one LibraryRuntime (duck-typed) and reads the history through its
    ``undo_service``; undo/redo execute through the runtime's
    ``file_operation_service`` — the exact same path as Ctrl+Z/Ctrl+Y.
    """

    def __init__(self, runtime, parent=None):
        self._runtime = runtime
        services = runtime.services
        self._undo_service = services.undo_service
        self._file_operations = services.file_operation_service
        super().__init__(
            parent, title=tr("undo_panel.title"), min_size=(640, 420))
        self.setObjectName("UndoPanelDialog")

    # ── UI ───────────────────────────────────────────────────────

    def _build_ui(self):
        self.setStyleSheet(self._dialog_qss())
        root = QVBoxLayout(self)
        root.setContentsMargins(
            scaled_px(12), scaled_px(12), scaled_px(12), scaled_px(12))
        root.setSpacing(scaled_px(8))

        # Fixed explanation line: session-scoped history + backup retention.
        self._note_label = self.make_muted(tr("undo_panel.note"))
        self._note_label.setWordWrap(True)
        root.addWidget(self._note_label)

        self._table = QTableWidget(0, 5, self)
        self._table.setHorizontalHeaderLabels([
            tr("undo_panel.col_type"),
            tr("undo_panel.col_target"),
            tr("undo_panel.col_time"),
            tr("undo_panel.col_state"),
            tr("undo_panel.col_retention"),
        ])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setWordWrap(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(_COL_TARGET, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(
            _COL_TYPE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            _COL_TIME, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            _COL_STATE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            _COL_RETENTION, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._table, 1)

        # Inline status line: empty state / undo-undoable outcome. Non-critical
        # errors stay inline per the dialog error convention.
        self._status_label = QLabel("", self)
        self._status_label.setWordWrap(True)
        root.addWidget(self._status_label)

        buttons = QHBoxLayout()
        self._undo_btn = self.make_primary_btn(
            tr("undo_panel.undo_latest"), self._on_undo_latest)
        self._redo_btn = self.make_secondary_btn(
            tr("undo_panel.redo"), self._on_redo)
        self._refresh_btn = self.make_secondary_btn(
            tr("undo_panel.refresh"), self._refresh)
        buttons.addWidget(self._undo_btn)
        buttons.addWidget(self._redo_btn)
        buttons.addStretch()
        buttons.addWidget(self._refresh_btn)
        root.addLayout(buttons)

        self._refresh()

    # ── Data ─────────────────────────────────────────────────────

    def _refresh(self):
        """Re-read the history snapshot and rebuild the rows (newest first)."""
        try:
            items = self._undo_service.history_snapshot()
        except Exception:
            # A closed session must not crash the panel; show the empty state.
            _log.exception("Undo history snapshot failed")
            items = []
        undo_available = any(item.origin == "undo" for item in items)
        redo_available = any(item.origin == "redo" for item in items)
        self._undo_btn.setEnabled(undo_available)
        self._redo_btn.setEnabled(redo_available)

        self._table.setRowCount(len(items))
        for row, item in enumerate(items):
            self._table.setItem(
                row, _COL_TYPE, self._read_only(tr(_type_label_key(item))))
            if item.is_batch:
                target = tr("undo_panel.batch_items").format(n=item.child_count)
            else:
                target = item.target
            self._table.setItem(row, _COL_TARGET, self._read_only(target))
            self._table.setItem(
                row, _COL_TIME, self._read_only(_format_time(item.recorded_at)))
            state = (
                tr("undo_panel.state_redo") if item.origin == "redo"
                else tr("undo_panel.state_undo")
            )
            if item.degraded:
                state += f" · {tr('undo_panel.state_degraded')}"
            if item.failed:
                state += f" · {tr('undo_panel.state_failed')}"
            self._table.setItem(row, _COL_STATE, self._read_only(state))
            retention = (
                tr("undo_panel.retention_delete") if item.has_backup
                else tr("undo_panel.retention_none")
            )
            self._table.setItem(
                row, _COL_RETENTION, self._read_only(retention))

        if not items:
            self._status_label.setText(tr("undo_panel.empty"))
        elif not undo_available:
            self._status_label.setText(tr("undo_panel.empty_undo"))
        else:
            self._status_label.setText("")

    @staticmethod
    def _read_only(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable)
        return item

    # ── Actions ──────────────────────────────────────────────────

    def _on_undo_latest(self):
        self._execute(lambda: self._undo_service.perform_undo(
            self._file_operations, self._runtime.session.root_str))

    def _on_redo(self):
        self._execute(lambda: self._undo_service.perform_redo(
            self._file_operations, self._runtime.session.root_str))

    def _execute(self, operation):
        """Run one undo/redo step synchronously and refresh afterwards.

        The execution path is exactly ``perform_undo``/``perform_redo`` — no
        direct backup-file poking. On success the panel refreshes and one
        session-scoped ``FileSystemChanged`` re-renders the open projections.
        """
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            succeeded = bool(operation())
        except Exception:
            _log.exception("Undo panel operation failed")
            succeeded = False
        finally:
            QApplication.restoreOverrideCursor()
        self._refresh()
        if succeeded:
            self._publish_refresh()
            self._status_label.setText("")
        else:
            self._status_label.setText(tr("undo_panel.operation_failed"))

    def _publish_refresh(self):
        session = self._runtime.session
        try:
            get_event_bus().publish(FileSystemChanged(
                library_root=session.root_str,
                session_token=session.event_token,
                kind="undo",
            ))
        except Exception:
            _log.exception("Undo panel refresh event failed")


def _type_label_key(item) -> str:
    """Return the i18n key for the entry's translated type label."""
    if item.is_batch:
        return "undo_panel.type_batch"
    if item.entry_type == "rename":
        return "undo_panel.type_rename"
    if item.entry_type == "delete":
        return "undo_panel.type_delete"
    return "undo_panel.type_other"


def _format_time(recorded_at: float) -> str:
    if not recorded_at:
        return "—"
    try:
        # Local-time display, same convention as the other desktop panels.
        return datetime.fromtimestamp(recorded_at).strftime(  # noqa: DTZ006
            "%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return "—"
