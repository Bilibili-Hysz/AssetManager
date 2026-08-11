"""Keyboard-driven fuzzy file picker."""
from __future__ import annotations

import os
from html import escape

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from AssetsManager import i18n
from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_pt, scaled_px
from AssetsManager.widgets.stylekit import StyleKit


_ROLE_FILE = Qt.ItemDataRole.UserRole


def _tr(key: str, fallback: str) -> str:
    """Translate picker strings that may not yet exist in locale files."""
    translated = i18n.tr(key)
    return fallback if translated == key else translated


class FilePickerDialog(QDialog):
    """Fuzzy file picker triggered by Ctrl+P."""

    file_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("filePickerDialog")
        self.setWindowTitle(_tr("file_picker.title", "File Picker"))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)

        self._files: list[dict] = []
        # path -> is_directory, computed once when the file list is set so
        # that filtering/keystrokes never re-stat files on the main thread.
        self._is_dir_cache: dict[str, bool] = {}
        self._sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            scaled_px(14), scaled_px(14), scaled_px(14), scaled_px(14)
        )
        layout.setSpacing(scaled_px(10))

        self._search_input = QLineEdit(self)
        self._search_input.setObjectName("filePickerSearch")
        self._search_input.setPlaceholderText(
            _tr("file_picker.placeholder", "Search files\u2026")
        )
        self._search_input.setClearButtonEnabled(True)
        self._search_input.installEventFilter(self)
        self._search_input.textChanged.connect(self._filter_files)
        layout.addWidget(self._search_input)

        self._file_list = QListWidget(self)
        self._file_list.setObjectName("filePickerResults")
        self._file_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._file_list.itemClicked.connect(self._on_file_selected)
        self._file_list.itemActivated.connect(self._on_file_selected)
        layout.addWidget(self._file_list, 1)

        shortcut_parent = parent if parent is not None else self
        self._open_shortcut = QShortcut(QKeySequence("Ctrl+P"), shortcut_parent)
        self._open_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._open_shortcut.activated.connect(self.open_picker)

        self.refresh_theme()
        self.resize(scaled_px(600), scaled_px(450))

    def set_file_list(self, files: list[dict]):
        """Set searchable files containing path, name, and tag values."""
        self._files = [
            {
                "path": str(file.get("path", "")),
                "name": str(file.get("name", "")),
                "tag": str(file.get("tag", "")),
            }
            for file in files
        ]
        # Precompute directory flags once here; _add_file only consults the
        # cache afterwards, so typing never re-stats every file.
        self._is_dir_cache = {
            file["path"]: os.path.isdir(file["path"]) or file["path"].endswith(("/", "\\"))
            for file in self._files
        }
        self._filter_files(self._search_input.text())

    def _filter_files(self, text: str):
        """Filter files by case-insensitive substring match."""
        query = text.strip().casefold()
        matches = [
            file
            for file in self._files
            if not query
            or any(query in file[field].casefold() for field in ("name", "path", "tag"))
        ]

        self._file_list.clear()
        for file in matches:
            self._add_file(file, text.strip())

        if self._file_list.count():
            self._file_list.setCurrentRow(0)

    def _add_file(self, file: dict, query: str):
        item = QListWidgetItem(self._file_list)
        item.setData(_ROLE_FILE, file)
        item.setText(file["name"])
        item.setSizeHint(QSize(0, scaled_px(58)))

        row = QWidget()
        row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(
            scaled_px(8), scaled_px(5), scaled_px(8), scaled_px(5)
        )
        row_layout.setSpacing(scaled_px(10))

        is_directory = self._is_dir_cache.get(file["path"], False) or file["path"].endswith(("/", "\\"))
        icon_label = QLabel("\U0001f4c1" if is_directory else "\U0001f4c4")
        icon_label.setStyleSheet(self._sk.label_css("body", size=16))
        row_layout.addWidget(icon_label)

        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(scaled_px(1))

        name_label = QLabel(self._highlight(file["name"], query))
        name_label.setTextFormat(Qt.TextFormat.RichText)
        name_label.setStyleSheet(self._sk.label_css("heading", size=12, bold=True))
        details_layout.addWidget(name_label)

        path_label = QLabel(self._highlight(file["path"], query))
        path_label.setTextFormat(Qt.TextFormat.RichText)
        path_label.setStyleSheet(self._sk.label_css("muted", size=10))
        details_layout.addWidget(path_label)
        row_layout.addWidget(details, 1)

        if file["tag"]:
            tag_label = QLabel(self._highlight(file["tag"], query))
            tag_label.setTextFormat(Qt.TextFormat.RichText)
            tag_label.setStyleSheet(
                self._sk.label_css("accent", size=10)
                + f"QLabel {{ background: {self._sk.token('header')}; "
                f"border: 1px solid {self._sk.token('border')}; "
                f"border-radius: {scaled_px(3)}px; "
                f"padding: {scaled_px(2)}px {scaled_px(6)}px; }}"
            )
            row_layout.addWidget(tag_label)

        self._file_list.setItemWidget(item, row)

    def _highlight(self, text: str, query: str) -> str:
        if not query:
            return escape(text)
        start = text.casefold().find(query.casefold())
        if start < 0:
            return escape(text)
        end = start + len(query)
        return (
            escape(text[:start])
            + f'<span style="color:{self._sk.token("accent")}; font-weight:600">'
            + escape(text[start:end])
            + "</span>"
            + escape(text[end:])
        )

    def _on_file_selected(self, item):
        """Emit the selected file path and close the picker."""
        file = item.data(_ROLE_FILE) if item is not None else None
        if not file:
            return
        self.accept()
        self.file_selected.emit(file["path"])

    def open_picker(self):
        """Show the picker with an empty, focused search field."""
        self._search_input.clear()
        self._center_on_parent()
        self.show()
        self.raise_()
        self.activateWindow()
        self._search_input.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def eventFilter(self, watched, event):
        if watched is self._search_input and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Down:
                self._move_selection(1)
                return True
            if event.key() == Qt.Key.Key_Up:
                self._move_selection(-1)
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._on_file_selected(self._file_list.currentItem())
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(watched, event)

    def _move_selection(self, offset: int):
        count = self._file_list.count()
        if not count:
            return
        row = self._file_list.currentRow()
        if row < 0:
            row = 0 if offset > 0 else count - 1
        else:
            row = (row + offset) % count
        self._file_list.setCurrentRow(row)

    def refresh_theme(self):
        """Re-apply styles after theme change."""
        self._sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        self.setStyleSheet(
            self._sk.dialog_css()
            + f"QLineEdit#filePickerSearch {{ min-height: {scaled_px(40)}px; "
            f"font-size: {scaled_pt(14)}px; padding: {scaled_px(5)}px "
            f"{scaled_px(10)}px; border-color: {self._sk.token('border_focus')}; }}"
            + f"QListWidget#filePickerResults::item {{ min-height: {scaled_px(54)}px; }}"
        )
        self._filter_files(self._search_input.text())

    def showEvent(self, event):
        self._center_on_parent()
        super().showEvent(event)

    def _center_on_parent(self):
        parent = self.parentWidget()
        if parent is None:
            return
        center = parent.mapToGlobal(parent.rect().center())
        frame = self.frameGeometry()
        frame.moveCenter(center)
        self.move(frame.topLeft())
