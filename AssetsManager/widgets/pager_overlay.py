"""Full-screen, keyboard-driven viewer for long text content."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from AssetsManager import i18n
from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_pt, scaled_px
from AssetsManager.widgets.stylekit import StyleKit


def _tr(key: str, fallback: str, **values) -> str:
    """Translate pager strings while locale files catch up."""
    translated = i18n.tr(key)
    text = fallback if translated == key else translated
    return text.format(**values)


# Search is debounced (QTimer) only for large documents; small ones keep the
# snappy per-keystroke behavior.  Matches are capped so a common query in a
# huge file cannot freeze the overlay.
_MAX_SEARCH_MATCHES = 1000
_SEARCH_DEBOUNCE_MS = 150
_SEARCH_DEBOUNCE_CHARS = 200_000
# Files larger than this are truncated on read (show_file stays on the
# main thread and a multi-MB read would block the UI).
_MAX_FILE_BYTES = 2 * 1024 * 1024


def _find_matches(query: str, text: str, limit: int = _MAX_SEARCH_MATCHES) -> list[tuple[int, int]]:
    """Return case-insensitive match spans for query in text, at most `limit`."""
    matches = []
    for match in re.finditer(re.escape(query), text, re.IGNORECASE):
        matches.append((match.start(), match.end()))
        if len(matches) >= limit:
            break
    return matches


class PagerOverlay(QWidget):
    """Full-screen modal text viewer with vim-style navigation."""

    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("pagerOverlay")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        self._sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        self._pending_g = False
        self._search_matches: list[tuple[int, int]] = []
        self._search_index = -1
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(_SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._run_debounced_search)

        root = QVBoxLayout(self)
        root.setContentsMargins(
            scaled_px(24), scaled_px(20), scaled_px(24), scaled_px(20)
        )
        root.setSpacing(0)

        self._panel = QWidget(self)
        self._panel.setObjectName("pagerPanel")
        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)
        root.addWidget(self._panel)

        title_bar = QWidget(self._panel)
        title_bar.setObjectName("pagerTitleBar")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(
            scaled_px(14), scaled_px(8), scaled_px(8), scaled_px(8)
        )
        title_layout.setSpacing(scaled_px(8))

        self._title_label = QLabel(self._panel)
        self._title_label.setObjectName("pagerTitle")
        title_layout.addWidget(self._title_label, 1)

        self._close_button = QPushButton(_tr("pager.close", "Close"), self._panel)
        self._close_button.setObjectName("pagerClose")
        self._close_button.setProperty("buttonVariant", "ghost")
        self._close_button.clicked.connect(self.close)
        title_layout.addWidget(self._close_button)
        panel_layout.addWidget(title_bar)

        self._text_edit = QPlainTextEdit(self._panel)
        self._text_edit.setObjectName("pagerText")
        self._text_edit.setReadOnly(True)
        self._text_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._text_edit.setTabStopDistance(scaled_px(32))
        self._text_edit.installEventFilter(self)
        self._text_edit.verticalScrollBar().valueChanged.connect(self._update_status)
        panel_layout.addWidget(self._text_edit, 1)

        self._search_input = QLineEdit(self._panel)
        self._search_input.setObjectName("pagerSearch")
        self._search_input.setPlaceholderText(
            _tr("pager.search_placeholder", "Search text")
        )
        self._search_input.setClearButtonEnabled(True)
        self._search_input.hide()
        self._search_input.installEventFilter(self)
        self._search_input.textChanged.connect(self._on_search_text_changed)
        panel_layout.addWidget(self._search_input)

        self._status_label = QLabel(self._panel)
        self._status_label.setObjectName("pagerStatus")
        panel_layout.addWidget(self._status_label)

        self.refresh_theme()
        self._update_status()

    def show_text(self, title: str, content: str):
        """Display text content in the pager."""
        self._title_label.setText(title)
        self.setWindowTitle(title)
        self._text_edit.setPlainText(content)
        self._text_edit.moveCursor(QTextCursor.MoveOperation.Start)
        self._text_edit.verticalScrollBar().setValue(0)
        self._pending_g = False
        self._search_input.clear()
        self._hide_search()
        self._update_status()
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self._text_edit.setFocus(Qt.FocusReason.OtherFocusReason)

    def show_file(self, path: str):
        """Display file content in the pager.

        Files larger than 2 MB are truncated to the first 2 MB (with a
        note appended) so the main thread never blocks on a giant read.
        """
        file_path = Path(path)
        try:
            if file_path.stat().st_size > _MAX_FILE_BYTES:
                with file_path.open("r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read(_MAX_FILE_BYTES)
                content += _tr(
                    "pager.truncated",
                    "\n\n\u2026 (file truncated: showing first 2 MB)",
                )
            else:
                content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            content = _tr("pager.file_error", "Unable to read file: {error}", error=exc)
        self.show_text(file_path.name, content)

    def refresh_theme(self):
        """Re-apply styles after theme change."""
        self._sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        self.setStyleSheet(
            self._sk.dialog_css()
            + f"QWidget#pagerOverlay {{ background: {self._sk._alpha('base', 0.94)}; }}"
            + f"QWidget#pagerPanel {{ background: {self._sk.token('panel')}; "
            f"border: 1px solid {self._sk.token('border')}; "
            f"border-radius: {scaled_px(8)}px; }}"
            + f"QWidget#pagerTitleBar {{ background: {self._sk.token('header')}; "
            f"border-bottom: 1px solid {self._sk.token('border')}; }}"
            + f"QLabel#pagerTitle {{ color: {self._sk.token('heading')}; "
            f"font-size: {scaled_pt(14)}px; font-weight: bold; }}"
            + f"QPlainTextEdit#pagerText {{ background: {self._sk.token('base')}; "
            f"color: {self._sk.token('body')}; border: none; "
            f"padding: {scaled_px(10)}px; font-family: monospace; "
            f"font-size: {scaled_pt(11)}px; selection-background-color: "
            f"{self._sk.token('accent')}; }}"
            + f"QLineEdit#pagerSearch {{ margin: {scaled_px(6)}px {scaled_px(10)}px; "
            f"min-height: {scaled_px(28)}px; font-family: monospace; "
            f"font-size: {scaled_pt(11)}px; }}"
            + f"QLabel#pagerStatus {{ color: {self._sk.token('muted')}; "
            f"background: {self._sk.token('header')}; "
            f"border-top: 1px solid {self._sk.token('border')}; "
            f"padding: {scaled_px(6)}px {scaled_px(12)}px; "
            f"font-size: {scaled_pt(10)}px; }}"
        )
        self._apply_search_highlights()

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Type.KeyPress:
            return super().eventFilter(watched, event)

        if watched is self._search_input:
            if event.key() == Qt.Key.Key_Escape:
                self._hide_search()
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._select_next_match(-1 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1)
                return True
            return super().eventFilter(watched, event)

        if watched is self._text_edit and self._handle_navigation(event):
            return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if not self._handle_navigation(event):
            super().keyPressEvent(event)

    def _handle_navigation(self, event) -> bool:
        key = event.key()
        modifiers = event.modifiers()
        scrollbar = self._text_edit.verticalScrollBar()

        if modifiers & Qt.KeyboardModifier.ControlModifier and key in (
            Qt.Key.Key_D,
            Qt.Key.Key_U,
        ):
            direction = 1 if key == Qt.Key.Key_D else -1
            scrollbar.setValue(scrollbar.value() + direction * scrollbar.pageStep())
            self._pending_g = False
            return True
        if key == Qt.Key.Key_G and modifiers & Qt.KeyboardModifier.ShiftModifier:
            scrollbar.setValue(scrollbar.maximum())
            self._pending_g = False
            return True
        if modifiers != Qt.KeyboardModifier.NoModifier:
            self._pending_g = False
            return False
        if key == Qt.Key.Key_J:
            scrollbar.setValue(scrollbar.value() + scrollbar.singleStep())
        elif key == Qt.Key.Key_K:
            scrollbar.setValue(scrollbar.value() - scrollbar.singleStep())
        elif key == Qt.Key.Key_G:
            if self._pending_g:
                scrollbar.setValue(scrollbar.minimum())
                self._pending_g = False
            else:
                self._pending_g = True
            return True
        elif key == Qt.Key.Key_Slash:
            self._show_search()
            self._pending_g = False
        elif key == Qt.Key.Key_Escape:
            self.close()
            self._pending_g = False
        else:
            self._pending_g = False
            return False
        return True

    def _show_search(self):
        self._search_input.show()
        self._search_input.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._search_input.selectAll()

    def _hide_search(self):
        self._search_input.hide()
        self._text_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _on_search_text_changed(self, query: str):
        """Debounce search for large documents; search small ones directly."""
        if self._text_edit.document().characterCount() >= _SEARCH_DEBOUNCE_CHARS:
            self._search_timer.start()
        else:
            self._search(query)

    def _run_debounced_search(self):
        """Fire the actual search after the debounce interval elapsed."""
        self._search(self._search_input.text())

    def _search(self, query: str):
        self._search_matches = []
        self._search_index = -1
        if query:
            self._search_matches = _find_matches(
                query, self._text_edit.toPlainText(), limit=_MAX_SEARCH_MATCHES
            )
            if self._search_matches:
                self._search_index = 0
        self._apply_search_highlights()
        if self._search_index >= 0:
            self._reveal_match(self._search_index)
        self._update_status()

    def _apply_search_highlights(self):
        selections = []
        highlight = QTextCharFormat()
        highlight.setBackground(QColor(self._sk.token("accent")))
        highlight.setForeground(QColor(self._sk.token("on_accent", "#ffffff")))
        for start, end in self._search_matches:
            cursor = QTextCursor(self._text_edit.document())
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format = highlight
            selections.append(selection)
        self._text_edit.setExtraSelections(selections)

    def _select_next_match(self, offset: int):
        if not self._search_matches:
            return
        self._search_index = (self._search_index + offset) % len(self._search_matches)
        self._reveal_match(self._search_index)
        self._update_status()

    def _reveal_match(self, index: int):
        start, end = self._search_matches[index]
        cursor = self._text_edit.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self._text_edit.setTextCursor(cursor)
        self._text_edit.centerCursor()

    def _update_status(self, *_args):
        lines = self._text_edit.document().blockCount()
        scrollbar = self._text_edit.verticalScrollBar()
        span = scrollbar.maximum() - scrollbar.minimum()
        position = 100 if span == 0 else round(
            100 * (scrollbar.value() - scrollbar.minimum()) / span
        )
        current_match = self._search_index + 1 if self._search_index >= 0 else 0
        self._status_label.setText(
            _tr(
                "pager.status",
                "{lines} lines  |  {position}%  |  {current}/{matches} matches",
                lines=lines,
                position=position,
                current=current_match,
                matches=len(self._search_matches),
            )
        )

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)
