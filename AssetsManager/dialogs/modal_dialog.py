"""StandardModalDialog — lightweight single-page modal template.

Provides a unified single-page dialog framework with:
  - Standard geometry memory via AppSettings
  - Scale-aware min-size / layout
  - High-DPI dialog chrome QSS cascade from TabbedDialog
  - Built-in button bar with primary/secondary/ghost variants
  - Enter / Escape keyboard shortcuts
"""
from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea,
)

from AssetsManager import i18n
from AssetsManager.core import icons, themes
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.dialogs.tabbed_dialog import TabbedDialog

tr = i18n.tr


class StandardModalDialog(TabbedDialog):
    """Unified single-page modal dialog template."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        title: str = "",
        min_size: tuple[int, int] | None = None,
        ok_text: str = "",
        cancel_text: str = "",
        show_apply: bool = False,
        apply_text: str = "",
        scrollable: bool = False,
        show_cancel: bool = True,
    ):
        self._dialog_title_text = title
        self._ok_text = ok_text or tr("dialog.ok", default="OK")
        self._cancel_text = cancel_text or tr("dialog.cancel", default="Cancel")
        self._show_cancel = show_cancel
        self._show_apply = show_apply
        self._apply_text = apply_text or tr("dialog.apply", default="Apply")
        self._scrollable = scrollable
        self._header_icon_name = ""
        self._header_subtitle = ""

        # Default minimum size if not specified
        default_size = min_size or (scaled_px(420), scaled_px(320))
        super().__init__(parent, title=title, min_size=default_size)

    def _build_ui(self) -> None:
        """Build single-page layout with header, canvas, and button bar."""
        root = QVBoxLayout(self)
        root.setContentsMargins(scaled_px(16), scaled_px(16), scaled_px(16), scaled_px(16))
        root.setSpacing(scaled_px(12))
        self._root_layout = root

        # ── Header (optional icon & subtitle) ───────────────────
        self._header_frame = QWidget(self)
        header_layout = QVBoxLayout(self._header_frame)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(scaled_px(4))

        self._title_row = QWidget(self._header_frame)
        title_row_layout = QHBoxLayout(self._title_row)
        title_row_layout.setContentsMargins(0, 0, 0, 0)
        title_row_layout.setSpacing(scaled_px(8))

        self._icon_label = QLabel(self._title_row)
        self._icon_label.hide()
        title_row_layout.addWidget(self._icon_label)

        self._modal_title_label = self.make_heading(self._dialog_title_text)
        title_row_layout.addWidget(self._modal_title_label, 1)
        header_layout.addWidget(self._title_row)

        self._modal_subtitle_label = self.make_muted("")
        self._modal_subtitle_label.setWordWrap(True)
        self._modal_subtitle_label.hide()
        header_layout.addWidget(self._modal_subtitle_label)

        root.addWidget(self._header_frame)

        # ── Content Canvas ──────────────────────────────────────
        if self._scrollable:
            scroll = QScrollArea(self)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            content_widget = QWidget(scroll)
            self._content_layout = QVBoxLayout(content_widget)
            self._content_layout.setContentsMargins(0, 0, 0, 0)
            self._content_layout.setSpacing(scaled_px(8))
            scroll.setWidget(content_widget)
            root.addWidget(scroll, 1)
        else:
            self._content_container = QWidget(self)
            self._content_layout = QVBoxLayout(self._content_container)
            self._content_layout.setContentsMargins(0, 0, 0, 0)
            self._content_layout.setSpacing(scaled_px(8))
            root.addWidget(self._content_container, 1)

        self.setup_content(self._content_layout)

        # ── Button Bar ──────────────────────────────────────────
        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(0, 0, 0, 0)
        btn_bar.setSpacing(scaled_px(8))
        btn_bar.addStretch()

        if self._show_cancel:
            self._cancel_btn = QPushButton(self._cancel_text, self)
            themes.set_button_variant(self._cancel_btn, "ghost")
            self._cancel_btn.clicked.connect(self.reject)
            btn_bar.addWidget(self._cancel_btn)
        else:
            self._cancel_btn = None

        if self._show_apply:
            self._apply_btn = QPushButton(self._apply_text, self)
            themes.set_button_variant(self._apply_btn, "secondary")
            self._apply_btn.clicked.connect(self._on_apply_clicked)
            btn_bar.addWidget(self._apply_btn)
        else:
            self._apply_btn = None

        self._ok_btn = QPushButton(self._ok_text, self)
        themes.set_button_variant(self._ok_btn, "primary")
        self._ok_btn.setDefault(True)
        self._ok_btn.clicked.connect(self._on_ok_clicked)
        btn_bar.addWidget(self._ok_btn)

        root.addLayout(btn_bar)

    def set_header(self, title: str, subtitle: str = "", icon_name: str = "") -> None:
        """Set dialog title, optional subtitle, and semantic icon."""
        self._dialog_title_text = title
        self._modal_title_label.setText(title)
        self.setWindowTitle(title)

        self._header_subtitle = subtitle
        if subtitle:
            self._modal_subtitle_label.setText(subtitle)
            self._modal_subtitle_label.show()
        else:
            self._modal_subtitle_label.hide()

        self._header_icon_name = icon_name
        if icon_name:
            sz = scaled_px(20)
            self._icon_label.setPixmap(
                icons.icon(icon_name, color="icon_primary", size=sz).pixmap(QSize(sz, sz))
            )
            self._icon_label.show()
        else:
            self._icon_label.hide()

    def setup_content(self, layout: QVBoxLayout) -> None:
        """Subclasses override this hook to populate the dialog canvas."""

    def _on_ok_clicked(self) -> None:
        self.accept()

    def _on_apply_clicked(self) -> None:
        pass

    def _on_theme_changed(self, name: str) -> None:
        super()._on_theme_changed(name)
        if self._header_icon_name and hasattr(self, "_icon_label"):
            sz = scaled_px(20)
            self._icon_label.setPixmap(
                icons.icon(self._header_icon_name, color="icon_primary", size=sz).pixmap(QSize(sz, sz))
            )

    def retranslate_ui(self) -> None:
        """Refresh the modal title bar; the base refreshes the button row.

        The header title/subtitle may be either literal text or a
        pre-translated string captured at construction; only the window
        chrome is safe to re-derive here because ``set_header`` callers
        own the strings they passed.
        """
        if getattr(self, "_dialog_title_text", ""):
            self.setWindowTitle(self._dialog_title_text)
