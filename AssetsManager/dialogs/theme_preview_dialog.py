"""Theme preview dialog — left-right split with theme selection and preview."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QWidget,
    QListWidget, QListWidgetItem, QPushButton,
)
from PySide6.QtGui import QPixmap, QPainter, QColor, QIcon
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.core import themes
from AssetsManager.widgets.theme_preview import ThemePreviewWidget, ThemePreviewRenderer
from AssetsManager import i18n
tr = i18n.tr


class ThemePreviewDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings.theme_preview"))
        self.setMinimumSize(scaled_px(800), scaled_px(500))
        self._renderer = ThemePreviewRenderer()
        self._current_theme_name: str | None = None
        self._setup_ui()
        self._load_themes()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(scaled_px(8), scaled_px(8), scaled_px(8), scaled_px(8))
        self._theme_list = QListWidget()
        self._theme_list.currentItemChanged.connect(self._on_theme_selected)
        left_layout.addWidget(self._theme_list)

        btn_row = QHBoxLayout()
        apply_btn = QPushButton(tr("settings.apply_theme"))
        apply_btn.clicked.connect(self._on_apply)
        close_btn = QPushButton(tr("dialog.close"))
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(close_btn)
        left_layout.addLayout(btn_row)

        self._preview = ThemePreviewWidget()
        self._preview.color_changed.connect(self._on_color_changed)

        splitter.addWidget(left)
        splitter.addWidget(self._preview)
        splitter.setSizes([scaled_px(200), scaled_px(600)])
        layout.addWidget(splitter)

    def _load_themes(self):
        loader = themes._get_loader()
        groups = loader.list_themes()
        for group_name in ("Dark", "Light"):
            themes_data = groups.get(group_name, [])
            if not themes_data:
                continue
            header = QListWidgetItem(group_name)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            f = header.font()
            f.setBold(True)
            header.setFont(f)
            self._theme_list.addItem(header)
            for theme_data in themes_data:
                name = theme_data.get("name", "")
                accent = theme_data.get("colors", {}).get("accent", "#888888")
                pixmap = QPixmap(scaled_px(12), scaled_px(12))
                pixmap.fill(QColor(accent))
                painter = QPainter(pixmap)
                painter.setPen(QColor(accent).darker(120))
                painter.drawRoundedRect(0, 0, scaled_px(12) - 1, scaled_px(12) - 1, 3, 3)
                painter.end()
                item = QListWidgetItem(QIcon(pixmap), f"  {name}")
                item.setData(Qt.ItemDataRole.UserRole, name)
                self._theme_list.addItem(item)

        current = themes.name()
        for i in range(self._theme_list.count()):
            item = self._theme_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == current:
                self._theme_list.setCurrentItem(item)
                break

    def _on_theme_selected(self, current, _previous):
        if current is None:
            return
        name = current.data(Qt.ItemDataRole.UserRole)
        if not name:
            return
        self._current_theme_name = name
        loader = themes._get_loader()
        theme_data = loader.get_theme(name)
        if theme_data:
            self._renderer.apply_theme(self._preview, theme_data)

    def _on_color_changed(self, color_name: str, hex_val: str) -> None:
        self._renderer.apply_theme(self._preview, self._preview._theme_data)

    def _on_apply(self):
        current = self._theme_list.currentItem()
        if current is None:
            return
        name = current.data(Qt.ItemDataRole.UserRole)
        if name:
            themes.set_theme(name)
            self.accept()
