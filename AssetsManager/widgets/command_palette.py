"""Keyboard-driven command, file, and tag search palette."""
from __future__ import annotations

from html import escape
from typing import Callable

from PySide6.QtCore import QEvent, Qt, Signal
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
from AssetsManager.core import icons, themes
from AssetsManager.core.ui_scale import scaled_pt, scaled_px
from AssetsManager.widgets.stylekit import StyleKit


_ROLE_RESULT = Qt.ItemDataRole.UserRole

# Canonical display order of result groups (registration may arrive in any
# order; headings are inserted at their canonical position).
_GROUP_ORDER = ("command", "file", "tag")
_GROUP_TITLES = {
    "command": ("command_palette.commands", "Commands"),
    "file": ("command_palette.files", "Files"),
    "tag": ("command_palette.tags", "Tags"),
}


def _tr(key: str, fallback: str) -> str:
    """Translate new palette strings while locale files catch up."""
    translated = i18n.tr(key)
    return fallback if translated == key else translated


class CommandPalette(QDialog):
    """Fuzzy-search command palette triggered by Ctrl+K."""

    command_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("commandPalette")
        self.setWindowTitle(_tr("command_palette.title", "Command Palette"))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)

        self._commands: list[dict] = []
        self._files: list[dict] = []
        self._tags: list[dict] = []
        # Incremental list state: kind -> heading/current item of each group.
        # Registration appends in O(1) instead of rebuilding the whole list.
        self._group_headings: dict[str, QListWidgetItem] = {}
        self._group_last: dict[str, QListWidgetItem] = {}
        self._sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            scaled_px(14), scaled_px(14), scaled_px(14), scaled_px(14)
        )
        layout.setSpacing(scaled_px(10))

        self._search_input = QLineEdit(self)
        self._search_input.setObjectName("commandPaletteSearch")
        self._search_input.setPlaceholderText(
            _tr("command_palette.placeholder", "Type a command or search\u2026")
        )
        self._search_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._search_input.setClearButtonEnabled(True)
        self._search_input.installEventFilter(self)
        self._search_input.textChanged.connect(self._filter_results)
        layout.addWidget(self._search_input)

        self._results_list = QListWidget(self)
        self._results_list.setObjectName("commandPaletteResults")
        self._results_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._results_list.itemClicked.connect(self._on_result_selected)
        self._results_list.itemActivated.connect(self._on_result_selected)
        layout.addWidget(self._results_list, 1)

        shortcut_parent = parent if parent is not None else self
        self._open_shortcut = QShortcut(QKeySequence("Ctrl+K"), shortcut_parent)
        self._open_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._open_shortcut.activated.connect(self.open_palette)

        self.refresh_theme()
        self.resize(scaled_px(500), scaled_px(400))
        self._filter_results("")

    def register_command(
        self,
        category: str,
        name: str,
        callback: Callable,
        shortcut: str = "",
        icon: str = "",
    ):
        """Register a searchable command."""
        self._commands.append(
            {
                "kind": "command",
                "category": category,
                "name": name,
                "callback": callback,
                "shortcut": shortcut,
                "icon": icon or "wrench",
                "search": f"{category} {name} {shortcut}",
                "value": name,
            }
        )
        self._append_result(self._commands[-1])

    def register_file(self, path: str, name: str):
        """Register a searchable file."""
        self._files.append(
            {
                "kind": "file",
                "category": "",
                "name": name,
                "callback": None,
                "shortcut": path,
                "icon": "file",
                "search": f"{name} {path}",
                "value": path,
            }
        )
        self._append_result(self._files[-1])

    def register_tag(self, name: str):
        """Register a searchable tag."""
        self._tags.append(
            {
                "kind": "tag",
                "category": "",
                "name": name,
                "callback": None,
                "shortcut": "",
                "icon": "tag",
                "search": name,
                "value": name,
            }
        )
        self._append_result(self._tags[-1])

    def _group_title(self, kind: str) -> str:
        key, fallback = _GROUP_TITLES[kind]
        return _tr(key, fallback)

    def _append_result(self, record: dict):
        """Insert a newly registered record into the visible list (O(1)).

        Registration no longer rebuilds the whole list on every call;
        the list is kept current incrementally.  A full rebuild happens on
        open (open_palette) and on every text change (_filter_results).
        """
        query = self._search_input.text()
        if query and query.casefold() not in record["search"].casefold():
            return
        kind = record["kind"]
        heading = self._group_headings.get(kind)
        if heading is None:
            heading = self._insert_heading(kind)
        last = self._group_last.get(kind) or heading
        row = self._results_list.row(last) + 1
        self._add_result(record, query, row=row)
        item = self._results_list.item(row)
        self._group_last[kind] = item
        if self._results_list.currentItem() is None:
            self._results_list.setCurrentRow(row)

    def _insert_heading(self, kind: str) -> QListWidgetItem:
        """Add a group heading at its canonical position; returns the item."""
        title = self._group_title(kind)
        # Insert after the last visible record of the groups ordered before
        # this one, so incremental registration preserves the canonical group
        # order regardless of registration order.
        anchor = None
        for other in _GROUP_ORDER:
            if other == kind:
                break
            last_item = self._group_last.get(other)
            if last_item is not None:
                anchor = last_item
        row = self._results_list.row(anchor) + 1 if anchor is not None else 0
        heading = self._add_heading(title, row=row)
        self._group_headings[kind] = heading
        self._group_last[kind] = heading
        return heading

    def open_palette(self):
        """Show the palette, ready for a new search."""
        self._search_input.clear()
        self._filter_results("")
        self._center_on_parent()
        self.show()
        self.raise_()
        self.activateWindow()
        self._search_input.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _filter_results(self, text: str):
        """Filter results based on input text (case-insensitive substring)."""
        query = text.strip().casefold()
        groups = (
            ("command", self._group_title("command"), self._commands),
            ("file", self._group_title("file"), self._files),
            ("tag", self._group_title("tag"), self._tags),
        )

        self._results_list.clear()
        self._group_headings = {}
        self._group_last = {}
        for kind, heading_title, records in groups:
            matches = [record for record in records if query in record["search"].casefold()]
            if not matches:
                continue
            heading = self._add_heading(heading_title)
            self._group_headings[kind] = heading
            self._group_last[kind] = heading
            for record in matches:
                item = self._add_result(record, text.strip())
                self._group_last[kind] = item

        self._select_result(0)

    def _add_heading(self, text: str, row: int | None = None) -> QListWidgetItem:
        item = QListWidgetItem()
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setSizeHint(item.sizeHint().expandedTo(self._heading_size_hint()))
        if row is None:
            self._results_list.addItem(item)
        else:
            self._results_list.insertItem(row, item)
        label = QLabel(text)
        label.setStyleSheet(self._sk.label_css("muted", size=10, bold=True))
        label.setContentsMargins(scaled_px(6), scaled_px(4), 0, scaled_px(2))
        self._results_list.setItemWidget(item, label)
        return item

    def _heading_size_hint(self):
        from PySide6.QtCore import QSize

        return QSize(0, scaled_px(28))

    def _add_result(self, record: dict, query: str, row: int | None = None) -> QListWidgetItem:
        item = QListWidgetItem()
        item.setData(_ROLE_RESULT, record)
        item.setText(record["name"])
        result_icon = icons.icon(
            record["icon"],
            color="icon_secondary",
            size=scaled_px(18),
            fallback="file",
        )
        item.setIcon(result_icon)
        item.setSizeHint(item.sizeHint().expandedTo(self._result_size_hint()))
        if row is None:
            self._results_list.addItem(item)
        else:
            self._results_list.insertItem(row, item)

        row = QWidget()
        row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(scaled_px(6), 0, scaled_px(8), 0)
        row_layout.setSpacing(scaled_px(8))

        icon_label = QLabel()
        icon_label.setPixmap(result_icon.pixmap(scaled_px(18), scaled_px(18)))
        icon_label.setStyleSheet(self._sk.label_css("body", size=12))
        row_layout.addWidget(icon_label)

        name_label = QLabel(self._highlight(record["name"], query))
        name_label.setTextFormat(Qt.TextFormat.RichText)
        name_label.setStyleSheet(self._sk.label_css("body", size=12))
        row_layout.addWidget(name_label, 1)

        detail = record["shortcut"] or record["category"]
        detail_label = QLabel(escape(detail))
        detail_label.setStyleSheet(self._sk.label_css("muted", size=10))
        row_layout.addWidget(detail_label)

        self._results_list.setItemWidget(item, row)

    def _result_size_hint(self):
        from PySide6.QtCore import QSize

        return QSize(0, scaled_px(38))

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

    def _on_result_selected(self, item):
        """Execute the selected command and publish its palette value."""
        record = item.data(_ROLE_RESULT) if item is not None else None
        if not record:
            return
        self.accept()
        self.command_selected.emit(record["value"])
        callback = record.get("callback")
        if callback is not None:
            callback()

    def _result_items(self) -> list[QListWidgetItem]:
        return [
            self._results_list.item(index)
            for index in range(self._results_list.count())
            if self._results_list.item(index).data(_ROLE_RESULT) is not None
        ]

    def _select_result(self, offset: int):
        items = self._result_items()
        if not items:
            self._results_list.setCurrentRow(-1)
            return
        current = self._results_list.currentItem()
        try:
            index = items.index(current) + offset
        except ValueError:
            index = 0 if offset >= 0 else len(items) - 1
        self._results_list.setCurrentItem(items[index % len(items)])

    def eventFilter(self, watched, event):
        if watched is self._search_input and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Down:
                self._select_result(1)
                return True
            if event.key() == Qt.Key.Key_Up:
                self._select_result(-1)
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._on_result_selected(self._results_list.currentItem())
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(watched, event)

    def refresh_theme(self):
        """Re-apply styles after theme change."""
        self._sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        self.setStyleSheet(
            self._sk.dialog_css()
            + f"QLineEdit#commandPaletteSearch {{ min-height: {scaled_px(38)}px; "
            f"font-size: {scaled_pt(14)}px; padding: {scaled_px(5)}px {scaled_px(10)}px; }}"
            + f"QListWidget#commandPaletteResults::item {{ min-height: {scaled_px(34)}px; }}"
        )
        self._filter_results(self._search_input.text())

    def showEvent(self, event):
        self._center_on_parent()
        super().showEvent(event)

    def _center_on_parent(self):
        parent = self.parentWidget()
        if parent is None:
            return
        frame = self.frameGeometry()
        frame.moveCenter(parent.geometry().center())
        self.move(frame.topLeft())
