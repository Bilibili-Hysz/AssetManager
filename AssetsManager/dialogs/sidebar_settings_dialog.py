"""Sidebar settings dialog — sections visibility + per-branch depth control.

Reusable: accepts current settings, returns modified values on accept.
Caller handles applying changes (rebuilding tree, hiding sections).
"""
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QCheckBox, QGroupBox, QLabel, QSpinBox, QScrollArea,
    QWidget, QDialogButtonBox,
)
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager import i18n
tr = i18n.tr

DEPTH_OPTIONS = [0, 1, 2, 3, 5, 99]
DEPTH_LABELS = {0: "0 (hidden)", 1: "1", 2: "2", 3: "3", 5: "5", 99: "All"}


class SidebarSettingsDialog(QDialog):
    def __init__(self, parent=None, root_paths=None, show_favs=True, show_recs=True,
                 show_filter=True, global_depth=2, branch_depths=None):
        super().__init__(parent)
        self.setWindowTitle(tr("sidebar_settings.title"))
        self.setMinimumWidth(scaled_px(420))
        self.setMinimumHeight(scaled_px(320))

        from AssetsManager.core import themes
        themes.apply_to(self)
        from AssetsManager.core.signal_bus import get as bus
        self._bus_theme_slot = lambda _: themes.apply_to(self)
        bus().theme_changed.connect(self._bus_theme_slot)

        self._root_paths = root_paths or []
        self._branch_depths = dict(branch_depths or {})

        layout = QVBoxLayout(self)

        # ── Sections ───────────────────────────────────────────────
        sections = QGroupBox(tr("sidebar_settings.sections"))
        sec_layout = QVBoxLayout(sections)
        self._chk_favs = QCheckBox(tr("sidebar_settings.favorites"))
        self._chk_favs.setChecked(show_favs)
        self._chk_recs = QCheckBox(tr("sidebar_settings.recent"))
        self._chk_recs.setChecked(show_recs)
        self._chk_filter = QCheckBox(tr("sidebar_settings.filter_bar"))
        self._chk_filter.setChecked(show_filter)
        for chk in (self._chk_favs, self._chk_recs, self._chk_filter):
            sec_layout.addWidget(chk)
        layout.addWidget(sections)

        # ── Global Depth ───────────────────────────────────────────
        global_grp = QGroupBox(tr("sidebar_settings.default_depth"))
        global_layout = QHBoxLayout(global_grp)
        global_layout.addWidget(QLabel(tr("sidebar_settings.max_levels")))
        self._global_depth = QSpinBox()
        self._global_depth.setRange(0, 5)
        self._global_depth.setValue(global_depth)
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
        from AssetsManager.core import themes
        t = themes.get()
        scroll.setStyleSheet(f"QScrollArea {{ background: {t['base']}; border: none; }}"
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
                sb.setValue(self._branch_depths.get(name, global_depth))
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

        reset_btn = QPushButton(tr("sidebar_settings.reset"))
        reset_btn.clicked.connect(self._reset_branches)
        branches_layout.addWidget(reset_btn)
        layout.addWidget(branches_grp)

        # ── Buttons ────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _reset_branches(self):
        default = self._global_depth.value()
        for sb in self._branch_spinboxes.values():
            sb.setValue(default)

    def closeEvent(self, event):
        """Disconnect bus signals on close."""
        from AssetsManager.core.signal_bus import get as bus
        try:
            bus().theme_changed.disconnect(self._bus_theme_slot)
        except (RuntimeError, TypeError):
            pass
        super().closeEvent(event)

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
