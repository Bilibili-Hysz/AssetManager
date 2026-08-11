"""Compact, theme-aware footer status bar for the main window."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from AssetsManager import i18n
from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_pt, scaled_px
from AssetsManager.widgets.stylekit import StyleKit


tr = i18n.tr


class StatusBarWidget(QWidget):
    """Persistent footer showing library and file-list status."""

    _MAX_PATH_LENGTH = 56

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StatusBarWidget")

        self._sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)

        self.file_count_label = QLabel()
        self.selection_label = QLabel()
        self.path_label = QLabel()
        self.message_label = QLabel()

        self.path_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.path_label.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self.message_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._separators = [QLabel("|") for _ in range(2)]

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(self._sk.px(8), 0, self._sk.px(8), 0)
        self._layout.setSpacing(self._sk.px(6))
        self._layout.addWidget(self.file_count_label)
        self._layout.addWidget(self._separators[0])
        self._layout.addWidget(self.selection_label)
        self._layout.addStretch(1)
        self._layout.addWidget(self.path_label)
        self._layout.addWidget(self._separators[1])
        self._layout.addWidget(self.message_label)

        self.update_file_count(0)
        self.update_selection(0)
        self.update_path("")
        self.update_message("")
        self.refresh_theme()

    def update_file_count(self, count: int):
        """Update the total file count display."""
        self.file_count_label.setText(tr("statusbar.files", count=count))

    def update_selection(self, count: int):
        """Update the selected file count display."""
        self.selection_label.setText(tr("statusbar.selected", count=count))

    def update_path(self, path: str):
        """Update the current library path display (compact format)."""
        path = str(path or "")
        self.path_label.setText(self._compact_path(path))
        self.path_label.setToolTip(path)

    def update_message(self, text: str):
        """Update the status message."""
        self.message_label.setText(text)

    def refresh_theme(self):
        """Re-apply styles after theme change."""
        sk = self._sk
        self.setFixedHeight(sk.px(26))
        self._layout.setContentsMargins(sk.px(8), 0, sk.px(8), 0)
        self._layout.setSpacing(sk.px(6))
        self.setStyleSheet(
            f"QWidget#StatusBarWidget {{ background: {sk.token('header')}; "
            f"border-top: 1px solid {sk.token('border')}; }}")
        label_style = sk.muted_css(11)
        for label in (
                self.file_count_label, self.selection_label,
                self.path_label, self.message_label, *self._separators):
            label.setStyleSheet(label_style)

    @classmethod
    def _compact_path(cls, path: str) -> str:
        if len(path) <= cls._MAX_PATH_LENGTH:
            return path
        available = cls._MAX_PATH_LENGTH - 3
        left = available // 2
        right = available - left
        return f"{path[:left]}...{path[-right:]}"
