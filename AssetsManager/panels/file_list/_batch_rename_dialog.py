"""Preview dialog for applying a validated FileList batch rename plan."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QTableWidget, QTableWidgetItem, QVBoxLayout

from AssetsManager import i18n
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.dialogs.modal_dialog import StandardModalDialog
from AssetsManager.panels.file_list._batch_rename import BatchRenamePlan, plan_batch_rename

tr = i18n.tr


class BatchRenameDialog(StandardModalDialog):
    # D1: cap on sibling entries collected per parent directory. A full
    # iterdir()+resolve() pass over every sibling is what makes duplicate
    # detection reliable, but scanning huge directories synchronously on the
    # GUI thread freezes the dialog; 5000 entries per parent is far beyond
    # any realistic rename-collision surface.
    _OCCUPIED_CAP = 5000

    def __init__(self, paths: list[str], parent=None):
        self._paths = [Path(path) for path in paths]
        # D1: lazy — collecting thousands of paths (iterdir + resolve in
        # plan_batch_rename) is deferred to the first _update_plan() call
        # instead of blocking dialog construction.
        self._occupied_paths: list[Path] | None = None
        self.plan: BatchRenamePlan | None = None
        super().__init__(
            parent,
            title=tr("filelist.dialog.batch_rename"),
            min_size=(scaled_px(620), scaled_px(400)),
            ok_text=tr("filelist.batch_rename.apply"),
        )
        # The template-hosted primary OK button IS the apply action; keep the
        # historical ``_apply`` alias so plan-refresh logic and tests can
        # enable/disable it as before.
        self._apply = self._ok_btn
        self._pattern.textChanged.connect(self._update_plan)
        self._update_plan()

    def setup_content(self, layout: QVBoxLayout) -> None:
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
        layout.addWidget(self._table, 1)

    def _collect_occupied_paths(self) -> list[Path]:
        occupied: list[Path] = []
        for parent in {path.parent for path in self._paths}:
            count = 0
            try:
                for child in parent.iterdir():
                    occupied.append(child)
                    count += 1
                    if count >= self._OCCUPIED_CAP:
                        break
            except OSError:
                continue
        return occupied

    def _update_plan(self) -> None:
        if self._occupied_paths is None:
            self._occupied_paths = self._collect_occupied_paths()
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
