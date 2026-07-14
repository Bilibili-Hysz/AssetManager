"""Sidebar settings dialog — sections visibility + per-branch depth control.

Reusable: accepts current settings, returns modified values on accept.
Caller handles applying changes (rebuilding tree, hiding sections).
"""
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout,
    QCheckBox, QGroupBox, QLabel, QSpinBox, QScrollArea,
    QWidget, QDialogButtonBox,
)
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.dialogs.tabbed_dialog import TabbedDialog
from AssetsManager import i18n
tr = i18n.tr

DEPTH_OPTIONS = [0, 1, 2, 3, 5, 99]
DEPTH_LABELS = {0: tr("sidebar_settings.depth_hidden"), 1: "1", 2: "2", 3: "3", 5: "5", 99: tr("sidebar_settings.depth_all")}


class SidebarSettingsDialog(TabbedDialog):
    def __init__(self, parent=None, root_paths=None, show_favs=True, show_recs=True,
                 show_filter=True, global_depth=2, branch_depths=None):
        self._root_paths = root_paths or []
        self._branch_depths_cfg = dict(branch_depths or {})
        self._show_favs_init = show_favs
        self._show_recs_init = show_recs
        self._show_filter_init = show_filter
        self._global_depth_init = global_depth
        super().__init__(parent, title=tr("sidebar_settings.title"),
                         min_size=(scaled_px(420), scaled_px(320)))

    def _build_ui(self):
        self.setStyleSheet(self._dialog_qss())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(scaled_px(12), scaled_px(12), scaled_px(12), scaled_px(12))
        layout.setSpacing(scaled_px(10))

        # ── Sections ───────────────────────────────────────────────
        sections = QGroupBox(tr("sidebar_settings.sections"))
        sec_layout = QVBoxLayout(sections)
        self._chk_favs = QCheckBox(tr("sidebar_settings.favorites"))
        self._chk_favs.setChecked(self._show_favs_init)
        self._chk_favs.setToolTip(tr("sidebar_settings.favs_tooltip"))
        self._chk_recs = QCheckBox(tr("sidebar_settings.recent"))
        self._chk_recs.setChecked(self._show_recs_init)
        self._chk_recs.setToolTip(tr("sidebar_settings.recent_tooltip"))
        self._chk_filter = QCheckBox(tr("sidebar_settings.filter_bar"))
        self._chk_filter.setChecked(self._show_filter_init)
        self._chk_filter.setToolTip(tr("sidebar_settings.filter_bar_tooltip"))
        for chk in (self._chk_favs, self._chk_recs, self._chk_filter):
            sec_layout.addWidget(chk)
        layout.addWidget(sections)

        # ── Global Depth ───────────────────────────────────────────
        global_grp = QGroupBox(tr("sidebar_settings.default_depth"))
        global_layout = QHBoxLayout(global_grp)
        global_layout.addWidget(QLabel(tr("sidebar_settings.max_levels")))
        self._global_depth = QSpinBox()
        self._global_depth.setRange(0, 5)
        self._global_depth.setValue(self._global_depth_init)
        self._global_depth.setToolTip(tr("sidebar_settings.global_hint"))
        global_layout.addWidget(self._global_depth)
        global_layout.addStretch()
        layout.addWidget(global_grp)

        # ── Per-Branch Depth ───────────────────────────────────────
        branches_grp = QGroupBox(tr("sidebar_settings.branch_depths"))
        branches_layout = QVBoxLayout(branches_grp)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(scaled_px(200))
        scroll.setStyleSheet(f"QScrollArea {{ background: {self._t['base']}; border: none; }}"
                             f"QScrollArea > QWidget {{ background: transparent; }}")
        branch_widget = QWidget()
        branch_widget.setStyleSheet("background: transparent;")
        branch_layout = QVBoxLayout(branch_widget)
        branch_layout.setSpacing(scaled_px(3))

        self._branch_spinboxes: dict[str, QSpinBox] = {}
        seen_branches: set[str] = set()
        for root in self._root_paths:
            p = Path(root)
            if not p.is_dir():
                continue
            try:
                entries = sorted(
                    [e for e in os.scandir(p) if e.is_dir() and not e.name.startswith(".")],
                    key=lambda e: e.name.lower())
            except OSError:
                continue
            for entry in entries:
                name = entry.name
                if name in seen_branches:
                    continue
                seen_branches.add(name)
                row = QHBoxLayout()
                lbl = QLabel(f"📁 {name}")
                lbl.setMinimumWidth(scaled_px(180))
                row.addWidget(lbl)
                sb = QSpinBox()
                sb.setRange(0, 5)
                sb.setValue(self._branch_depths_cfg.get(name, self._global_depth_init))
                sb.setToolTip(tr("sidebar_settings.depth_hint"))
                row.addWidget(sb)
                row.addStretch()
                branch_layout.addLayout(row)
                self._branch_spinboxes[name] = sb

        if not self._branch_spinboxes:
            branch_layout.addWidget(QLabel(tr("sidebar_settings.no_folders")))
        branch_layout.addStretch()

        scroll.setWidget(branch_widget)
        branches_layout.addWidget(scroll)

        reset_btn = self.make_secondary_btn(tr("sidebar_settings.reset"), self._reset_branches)
        branches_layout.addWidget(reset_btn)
        layout.addWidget(branches_grp)

        # ── Buttons ────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        btns.button(QDialogButtonBox.StandardButton.Ok).setToolTip(tr("sidebar_settings.ok_tooltip"))
        btns.button(QDialogButtonBox.StandardButton.Cancel).setToolTip(tr("sidebar_settings.cancel_tooltip"))
        layout.addWidget(btns)

    def _reset_branches(self):
        default = self._global_depth.value()
        for sb in self._branch_spinboxes.values():
            sb.setValue(default)

    def result(self) -> dict:
        return {
            "show_favs": self._chk_favs.isChecked(),
            "show_recs": self._chk_recs.isChecked(),
            "show_filter": self._chk_filter.isChecked(),
            "global_depth": self._global_depth.value(),
            "branch_depths": {
                name: sb.value() for name, sb in self._branch_spinboxes.items()
                if sb.value() != self._global_depth.value()
            },
        }
