"""QuickShareCard — popup card for one-click share link generation.

Shows file count/size, password and expiry options, and generate/copy buttons.
Designed for right-click → Quick Share workflow.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QSpinBox, QApplication,
)
from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager import i18n

tr = i18n.tr


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


class QuickShareCard(QWidget):
    share_requested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self._paths: list[str] = []
        self._url: str | None = None
        self._build_ui()

    def _build_ui(self):
        t = themes.get()
        self.setFixedWidth(scaled_px(300))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(scaled_px(12), scaled_px(10), scaled_px(12), scaled_px(10))
        lay.setSpacing(scaled_px(8))

        self._info_label = QLabel()
        self._info_label.setStyleSheet(f"font-size: {scaled_pt(11)}px; color: {t.get('text', '#eee')};")
        lay.addWidget(self._info_label)

        self._password_check = QCheckBox(tr("sharing.quick.password"))
        self._password_check.setStyleSheet(f"color: {t.get('text', '#eee')};")
        lay.addWidget(self._password_check)

        self._password_input = QLineEdit()
        self._password_input.setPlaceholderText(tr("sharing.quick.password_placeholder"))
        self._password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_input.setStyleSheet(
            f"QLineEdit {{ background: {t.get('panel', '#2a2a2a')}; color: {t.get('text', '#eee')}; "
            f"border: 1px solid {t.get('border', '#444')}; border-radius: {scaled_px(4)}px; "
            f"padding: {scaled_px(4)}px {scaled_px(6)}px; font-size: {scaled_pt(10)}px; }}"
        )
        self._password_input.setVisible(False)
        lay.addWidget(self._password_input)
        self._password_check.toggled.connect(self._password_input.setVisible)

        self._expiry_check = QCheckBox(tr("sharing.quick.expiry"))
        self._expiry_check.setStyleSheet(f"color: {t.get('text', '#eee')};")
        lay.addWidget(self._expiry_check)

        self._expiry_row = QWidget()
        expiry_lay = QHBoxLayout(self._expiry_row)
        expiry_lay.setContentsMargins(0, 0, 0, 0)
        expiry_lay.setSpacing(scaled_px(6))
        self._expiry_spin = QSpinBox()
        self._expiry_spin.setRange(1, 720)
        self._expiry_spin.setValue(24)
        self._expiry_spin.setStyleSheet(
            f"QSpinBox {{ background: {t.get('panel', '#2a2a2a')}; color: {t.get('text', '#eee')}; "
            f"border: 1px solid {t.get('border', '#444')}; border-radius: {scaled_px(4)}px; "
            f"padding: {scaled_px(3)}px; font-size: {scaled_pt(10)}px; }}"
        )
        expiry_lay.addWidget(self._expiry_spin)
        expiry_label = QLabel(tr("sharing.quick.hours"))
        expiry_label.setStyleSheet(f"color: {t.get('muted', '#999')}; font-size: {scaled_pt(10)}px;")
        expiry_lay.addWidget(expiry_label)
        expiry_lay.addStretch()
        self._expiry_row.setVisible(False)
        lay.addWidget(self._expiry_row)
        self._expiry_check.toggled.connect(self._expiry_row.setVisible)

        self._generate_btn = QPushButton(tr("sharing.quick.generate"))
        self._generate_btn.setStyleSheet(
            f"QPushButton {{ background: {t.get('accent', '#5b7ff5')}; color: #fff; "
            f"border: none; border-radius: {scaled_px(6)}px; "
            f"padding: {scaled_px(6)}px {scaled_px(12)}px; font-size: {scaled_pt(11)}px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {t.get('accent_hover', '#7b9ff5')}; }}"
        )
        self._generate_btn.clicked.connect(self._on_generate)
        lay.addWidget(self._generate_btn)

        self._url_label = QLabel()
        self._url_label.setWordWrap(True)
        self._url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._url_label.setStyleSheet(
            f"QLabel {{ background: {t.get('panel', '#2a2a2a')}; color: {t.get('accent', '#5b7ff5')}; "
            f"border: 1px solid {t.get('border', '#444')}; border-radius: {scaled_px(4)}px; "
            f"padding: {scaled_px(6)}px; font-size: {scaled_pt(10)}px; }}"
        )
        self._url_label.setVisible(False)
        lay.addWidget(self._url_label)

        self._copy_btn = QPushButton(tr("sharing.quick.copy"))
        self._copy_btn.setStyleSheet(
            f"QPushButton {{ background: {t.get('panel', '#2a2a2a')}; color: {t.get('text', '#eee')}; "
            f"border: 1px solid {t.get('border', '#444')}; border-radius: {scaled_px(6)}px; "
            f"padding: {scaled_px(6)}px {scaled_px(12)}px; font-size: {scaled_pt(11)}px; }}"
            f"QPushButton:hover {{ background: {t.get('hover', '#3a3a3a')}; }}"
        )
        self._copy_btn.clicked.connect(self._on_copy)
        self._copy_btn.setVisible(False)
        lay.addWidget(self._copy_btn)

        self._status_label = QLabel()
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet(f"color: {t.get('accent', '#5b7ff5')}; font-size: {scaled_pt(10)}px;")
        self._status_label.setVisible(False)
        lay.addWidget(self._status_label)

    def show_for_paths(self, paths: list[str], global_pos):
        self._paths = list(paths)
        self._url = None

        total_size = 0
        for p in self._paths:
            try:
                total_size += os.path.getsize(p)
            except OSError:
                pass

        count = len(self._paths)
        name = Path(self._paths[0]).name if count == 1 else ""
        size_str = _format_size(total_size)

        if count == 1:
            self._info_label.setText(f"{name}  ·  {size_str}")
        else:
            self._info_label.setText(tr("sharing.quick.file_count", count=count, size=size_str))

        self._url_label.setVisible(False)
        self._copy_btn.setVisible(False)
        self._status_label.setVisible(False)
        self._generate_btn.setEnabled(True)
        self._generate_btn.setText(tr("sharing.quick.generate"))
        self._password_check.setChecked(False)
        self._expiry_check.setChecked(False)

        self.adjustSize()
        x = max(0, global_pos.x() - self.width() // 2)
        y = max(0, global_pos.y() - self.height() // 2)
        self.move(x, y)
        self.show()

    def show_result(self, url: str):
        self._url = url
        self._url_label.setText(url)
        self._url_label.setVisible(True)
        self._copy_btn.setVisible(True)
        self._generate_btn.setEnabled(True)
        self._generate_btn.setText(tr("sharing.quick.generate"))
        self.adjustSize()

    def _on_generate(self):
        self._generate_btn.setEnabled(False)
        self._generate_btn.setText("...")
        data = {
            "paths": self._paths,
            "password": self._password_input.text().strip() if self._password_check.isChecked() else None,
            "expiry_hours": self._expiry_spin.value() if self._expiry_check.isChecked() else None,
        }
        self.share_requested.emit(data)

    def _on_copy(self):
        if self._url:
            QApplication.clipboard().setText(self._url)
            self._status_label.setText(tr("sharing.quick.copied"))
            self._status_label.setVisible(True)
            QTimer.singleShot(1500, self._status_label.hide)
