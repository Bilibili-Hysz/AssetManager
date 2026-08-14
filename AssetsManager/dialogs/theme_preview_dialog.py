"""Theme preview dialog — left-right split with theme selection and preview."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QWidget,
    QListWidget, QListWidgetItem, QPushButton, QInputDialog, QMessageBox,
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
        self._baseline_data: dict = {}
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

        custom_row = QHBoxLayout()
        new_btn = QPushButton(tr("settings.new_theme"))
        new_btn.clicked.connect(self._on_new_custom_theme)
        save_btn = QPushButton(tr("settings.save_as_custom"))
        save_btn.clicked.connect(self._on_save_as_custom)
        custom_row.addWidget(new_btn)
        custom_row.addWidget(save_btn)
        left_layout.addLayout(custom_row)

        self._preview = ThemePreviewWidget()
        self._preview.color_changed.connect(self._on_color_changed)

        splitter.addWidget(left)
        splitter.addWidget(self._preview)
        splitter.setSizes([scaled_px(200), scaled_px(600)])
        layout.addWidget(splitter)

    def _load_themes(self):
        self._theme_list.clear()
        loader = themes._get_loader()
        groups = loader.list_themes()
        for group_name in ("Dark", "Light", "User"):
            themes_data = groups.get(group_name, [])
            if not themes_data:
                continue
            header_text = group_name
            if group_name == "Dark":
                header_text = tr("settings.dark_mode")
            elif group_name == "Light":
                header_text = tr("settings.light_mode")
            elif group_name == "User":
                header_text = tr("settings.custom_themes")
            header = QListWidgetItem(header_text)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            f = header.font()
            f.setBold(True)
            header.setFont(f)
            self._theme_list.addItem(header)
            for theme_data in themes_data:
                name = theme_data.get("name", "")
                accent = theme_data.get("colors", {}).get("accent", "#888888")
                pixmap = QPixmap(scaled_px(12), scaled_px(12))
                pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(pixmap)
                painter.setBrush(QColor(accent))
                painter.setPen(Qt.PenStyle.NoPen)
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
        raw = loader.get_theme(name)
        if raw:
            # Flatten: merge colors dict with properties at top level
            flat = dict(raw.get("colors", {}))
            flat["properties"] = raw.get("properties", {})
            self._baseline_data = flat
            self._renderer.apply_theme(self._preview, flat)

    def _theme_data(self) -> dict:
        """Return the currently previewed (possibly edited) theme data."""
        return self._preview.theme_data()

    def _preview_is_dirty(self) -> bool:
        """Whether the preview colors/properties differ from the loaded theme."""
        return self._theme_data() != self._baseline_data

    def _write_custom_theme(self, name: str) -> bool:
        """Persist the previewed edits back into a U_-prefixed custom theme."""
        data = self._theme_data()
        colors = {k: v for k, v in data.items() if k != "properties"}
        return themes._get_loader().save_custom_theme(
            name, colors, data.get("properties", {})
        )

    def _on_color_changed(self, color_name: str, hex_val: str) -> None:
        data = self._theme_data()
        data[color_name] = hex_val
        self._renderer.apply_theme(self._preview, data)

    def _on_apply(self):
        current = self._theme_list.currentItem()
        if current is None:
            return
        name = current.data(Qt.ItemDataRole.UserRole)
        if not name:
            return
        loader = themes._get_loader()

        if loader.is_custom_theme(name):
            # Custom themes are editable: write the previewed colors back to
            # the U_ JSON file before applying them.
            if self._preview_is_dirty():
                if not self._write_custom_theme(name):
                    QMessageBox.warning(
                        self, tr("dialog.error"), tr("settings.theme_save_failed"))
                    return
                themes.reload_themes()
            themes.set_theme(name)
            self.accept()
            return

        # Built-in themes are read-only. Edited preview colors must not be
        # silently discarded: offer to save them as a custom variant first.
        if self._preview_is_dirty():
            answer = QMessageBox.question(
                self, tr("dialog.confirm"), tr("settings.builtin_read_only"))
            if answer == QMessageBox.StandardButton.Yes:
                self._on_save_as_custom()
                return
        themes.set_theme(name)
        self.accept()

    def _on_new_custom_theme(self):
        from AssetsManager.core.themes import _get_loader
        loader = _get_loader()
        name, ok = QInputDialog.getText(self, tr("settings.new_theme"), tr("settings.theme_name"))
        if not ok or not name.strip():
            return
        name = name.strip()
        groups = loader.list_themes()
        all_themes = []
        for group_name in ("Dark", "Light"):
            for theme_data in groups.get(group_name, []):
                all_themes.append(theme_data.get("name", ""))
        if not all_themes:
            return
        base, ok = QInputDialog.getItem(self, tr("settings.base_theme"), tr("settings.select_base"), all_themes, 0, False)
        if not ok:
            return
        if loader.create_custom_theme(name, base):
            themes.reload_themes()
            self._load_themes()
            for i in range(self._theme_list.count()):
                item = self._theme_list.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole) == name:
                    self._theme_list.setCurrentItem(item)
                    break
        else:
            QMessageBox.warning(self, tr("dialog.error"), tr("settings.theme_exists"))

    def _on_save_as_custom(self):
        from AssetsManager.core.themes import _get_loader
        loader = _get_loader()
        name, ok = QInputDialog.getText(self, tr("settings.save_as_custom"), tr("settings.theme_name"))
        if not ok or not name.strip():
            return
        name = name.strip()
        theme_data = self._theme_data()
        if not theme_data:
            return
        base_name = self._current_theme_name or themes.name()
        if loader.create_custom_theme(name, base_name):
            colors = {k: v for k, v in theme_data.items() if k != "properties"}
            if not loader.save_custom_theme(
                name, colors, theme_data.get("properties", {})
            ):
                loader.delete_custom_theme(name)
                QMessageBox.warning(
                    self, tr("dialog.error"), tr("settings.theme_save_failed"))
                return
            themes.reload_themes()
            self._load_themes()
            for i in range(self._theme_list.count()):
                item = self._theme_list.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole) == name:
                    self._theme_list.setCurrentItem(item)
                    break
        else:
            QMessageBox.warning(self, tr("dialog.error"), tr("settings.theme_exists"))
