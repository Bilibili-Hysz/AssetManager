"""Preview dialog for applying a validated FileList batch rename plan."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QTableWidget, QTableWidgetItem, QVBoxLayout

from AssetsManager import i18n
from AssetsManager.panels.file_list._batch_rename import BatchRenamePlan, plan_batch_rename

tr = i18n.tr


class BatchRenameDialog(QDialog):
    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self._paths = [Path(path) for path in paths]
        self._occupied_paths = self._collect_occupied_paths()
        self.plan: BatchRenamePlan | None = None
        self.setWindowTitle(tr("filelist.dialog.batch_rename"))
        self.resize(620, 400)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("filelist.dialog.batch_pattern")))
        self._pattern = QLineEdit("{name}_{n}")
        row.addWidget(self._pattern)
        layout.addLayout(row)
        layout.addWidget(QLabel(tr("filelist.batch_rename.help")))
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels([
            tr("filelist.batch_rename.current_name"),
            tr("filelist.batch_rename.new_name"),
            tr("filelist.batch_rename.status"),
        ])
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)
        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self._apply = self._buttons.addButton(tr("filelist.batch_rename.apply"), QDialogButtonBox.ButtonRole.AcceptRole)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)
        self._pattern.textChanged.connect(self._update_plan)
        self._update_plan()

    def _collect_occupied_paths(self) -> list[Path]:
        occupied: list[Path] = []
        for parent in {path.parent for path in self._paths}:
            try:
                occupied.extend(parent.iterdir())
            except OSError:
                continue
        return occupied

    def _update_plan(self) -> None:
        self.plan = plan_batch_rename(
            self._paths,
            self._pattern.text(),
            occupied_paths=self._occupied_paths,
            windows_rules=os.name == "nt",
        )
        self._table.setRowCount(len(self.plan.entries))
        for row, entry in enumerate(self.plan.entries):
            status = tr("filelist.batch_rename.status.valid")
            if not entry.changed:
                status = tr("filelist.batch_rename.status.no_change")
            elif entry.errors:
                status = tr(f"filelist.batch_rename.error.{entry.errors[0]}")
            for column, text in enumerate((entry.source.name, entry.target.name, status)):
                self._table.setItem(row, column, QTableWidgetItem(text))
        self._apply.setEnabled(self.plan.is_valid)

    def accept(self) -> None:
        if self.plan is not None and self.plan.is_valid:
            super().accept()
