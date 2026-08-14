"""Tag style editor dialog — set a tag's color, icon, and category.

The persisted side (``tag_metadata`` table + ``TagService.set_tag_metadata``)
already existed with no production caller; this dialog is the missing UI
entry point (gap G2-1).  It reuses :class:`ColorPickerDialog` for the color
swatch and the semantic :mod:`AssetsManager.core.icons` registry for the
built-in icon table.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)
from AssetsManager.core import icons
from AssetsManager.core.constants import DEFAULT_LAN_THEME_COLOR
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager import i18n

tr = i18n.tr


class TagStyleDialog(QDialog):
    """Edit one tag's visual metadata.

    Emits :attr:`saved` with ``(tag, color, icon, category)`` when the user
    accepts; the caller owns persisting via ``TagService.set_tag_metadata``.
    """

    saved = Signal(str, str, str, str)

    def __init__(self, tag: str, color: str = "", icon: str = "",
                 category: str = "", parent=None):
        super().__init__(parent)
        self._tag = tag
        self._color = color or ""
        self._icon = icons.normalize(icon, fallback="tag") if icon else ""
        self._category = category or ""
        self.setWindowTitle(tr("tagstyle.title", name=tag))
        self.setMinimumSize(scaled_px(380), scaled_px(230))
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(scaled_px(10))
        form = QFormLayout()
        form.setSpacing(scaled_px(8))

        # ── Color ─────────────────────────────────────────────
        color_row = QHBoxLayout()
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(scaled_px(90), scaled_px(28))
        self._color_btn.clicked.connect(self._pick_color)
        self._color_btn.setAccessibleName(tr("tagstyle.color"))
        self._clear_color_btn = QPushButton(tr("tagstyle.clear"))
        self._clear_color_btn.setAccessibleName(tr("tagstyle.clear_color"))
        self._clear_color_btn.clicked.connect(self._clear_color)
        color_row.addWidget(self._color_btn)
        color_row.addWidget(self._clear_color_btn)
        color_row.addStretch()
        self._apply_color_swatch()
        form.addRow(tr("tagstyle.color"), color_row)

        # ── Icon ──────────────────────────────────────────────
        self._icon_combo = QComboBox()
        self._icon_combo.setAccessibleName(tr("tagstyle.icon"))
        self._icon_combo.addItem(tr("tagstyle.no_icon"), "")
        for name in icons.names():
            self._icon_combo.addItem(icons.icon(name, size=scaled_px(16)), name, name)
        self._select_current_icon()
        form.addRow(tr("tagstyle.icon"), self._icon_combo)

        # ── Category ──────────────────────────────────────────
        self._category_input = QLineEdit(self._category)
        self._category_input.setPlaceholderText(tr("tagstyle.category_placeholder"))
        self._category_input.setAccessibleName(tr("tagstyle.category"))
        form.addRow(tr("tagstyle.category"), self._category_input)

        layout.addLayout(form)
        layout.addStretch()

        # ── Buttons ───────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton(tr("tagstyle.ok"))
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton(tr("tagstyle.cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _pick_color(self):
        from AssetsManager.dialogs.color_picker_dialog import ColorPickerDialog

        current = QColor(self._color) if self._color else QColor(DEFAULT_LAN_THEME_COLOR)
        dialog = ColorPickerDialog(initial_color=current, parent=self)
        dialog.color_selected.connect(self._on_color_picked)
        dialog.exec()

    def _on_color_picked(self, color: QColor):
        self._color = color.name()
        self._apply_color_swatch()

    def _clear_color(self):
        self._color = ""
        self._apply_color_swatch()

    def _apply_color_swatch(self):
        color = self._color or ""
        self._color_btn.setText(color or tr("tagstyle.no_color"))
        text = self._contrast_text(color)
        self._color_btn.setStyleSheet(
            f"QPushButton {{ background: {color or 'transparent'}; "
            f"border: 1px solid #555; border-radius: {scaled_px(4)}px; "
            f"color: {text}; }}"
        )

    @staticmethod
    def _contrast_text(color: str) -> str:
        """Pick black or white text for readability on the swatch background."""
        if not color:
            return "#cccccc"
        qcolor = QColor(color)
        if not qcolor.isValid():
            return "#cccccc"
        return "#1b1b1b" if qcolor.lightness() > 160 else "#ffffff"

    def _select_current_icon(self):
        index = self._icon_combo.findData(self._icon)
        self._icon_combo.setCurrentIndex(index if index >= 0 else 0)

    def _on_ok(self):
        self.saved.emit(
            self._tag,
            self._color,
            str(self._icon_combo.currentData() or ""),
            self._category_input.text().strip(),
        )
        self.accept()
