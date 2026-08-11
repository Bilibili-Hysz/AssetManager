"""Visual gallery for selecting an application theme."""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from AssetsManager import i18n
from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_pt, scaled_px
from AssetsManager.widgets.stylekit import StyleKit


class _ThemeCard(QWidget):
    """Clickable container that also handles clicks on its preview widgets."""

    clicked = Signal(str)

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.theme_name = name
        self._preview_style: StyleKit | None = None
        self.setObjectName("ThemeCard")
        self.setProperty("themeName", name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def watch_clicks_from(self, widget: QWidget) -> None:
        widget.installEventFilter(self)
        widget.setCursor(Qt.CursorShape.PointingHandCursor)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() != Qt.MouseButton.LeftButton:
                # Right/middle-click must not trigger the card; let the
                # event propagate to the watched widget (e.g. context menu).
                return False
            self.clicked.emit(self.theme_name)
            return True
        return super().eventFilter(watched, event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.theme_name)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ThemeGalleryDialog(QDialog):
    """Visual theme selection gallery."""

    theme_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.tr("settings.theme"))
        self.setModal(True)
        self.resize(scaled_px(600), scaled_px(500))
        self.setMinimumSize(scaled_px(520), scaled_px(400))

        self._cards: dict[str, _ThemeCard] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            scaled_px(16), scaled_px(16), scaled_px(16), scaled_px(16)
        )
        outer.setSpacing(scaled_px(12))

        self._scroll_area = QScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setObjectName("ThemeGalleryScroll")

        self._gallery = QWidget()
        self._gallery.setObjectName("ThemeGallery")
        self._grid_layout = QGridLayout(self._gallery)
        self._grid_layout.setContentsMargins(
            scaled_px(4), scaled_px(4), scaled_px(4), scaled_px(4)
        )
        self._grid_layout.setHorizontalSpacing(scaled_px(12))
        self._grid_layout.setVerticalSpacing(scaled_px(12))
        self._grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self._scroll_area.setWidget(self._gallery)
        outer.addWidget(self._scroll_area, 1)

        button_row = QHBoxLayout()
        button_row.addStretch()
        self._close_button = QPushButton(i18n.tr("dialog.close"), self)
        themes.set_button_variant(self._close_button, "secondary")
        self._close_button.clicked.connect(self.close)
        button_row.addWidget(self._close_button)
        outer.addLayout(button_row)

        self._load_themes()
        self.refresh_theme()

    def _load_themes(self):
        """Load all available themes and create preview cards."""
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._cards.clear()

        for index, name in enumerate(themes.names()):
            card = self._create_theme_card(name, themes.get(name))
            row, column = divmod(index, 3)
            self._grid_layout.addWidget(card, row, column)
            self._cards[name] = card

        self._update_selected_cards(themes.name())

    def _create_theme_card(self, name: str, theme_data: dict) -> _ThemeCard:
        """Create a preview card for a theme."""
        sk = StyleKit(theme_data, px=scaled_px, pt=scaled_pt)
        card = _ThemeCard(name, self._gallery)
        card.setFixedSize(scaled_px(164), scaled_px(126))
        card.clicked.connect(self._on_theme_clicked)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(
            scaled_px(9), scaled_px(7), scaled_px(9), scaled_px(7)
        )
        layout.setSpacing(scaled_px(5))

        title = QLabel(name, card)
        title.setObjectName("ThemeCardName")
        title.setStyleSheet(sk.label_css("heading", size=12, bold=True))
        layout.addWidget(title)

        colors = QHBoxLayout()
        colors.setSpacing(scaled_px(5))
        for token in ("accent", "base"):
            swatch = QFrame(card)
            swatch.setObjectName(f"{token}Swatch")
            swatch.setProperty("color", sk.token(token))
            swatch.setFixedSize(scaled_px(16), scaled_px(16))
            swatch.setToolTip(token.capitalize())
            swatch.setStyleSheet(
                f"QFrame#{token}Swatch {{ background: {sk.token(token)}; "
                f"border: 1px solid {sk.token('border')}; "
                f"border-radius: {scaled_px(3)}px; }}"
            )
            colors.addWidget(swatch)
            card.watch_clicks_from(swatch)
        colors.addStretch()
        layout.addLayout(colors)

        preview_row = QHBoxLayout()
        preview_row.setSpacing(scaled_px(5))
        preview_input = QLineEdit(card)
        preview_input.setObjectName("ThemeCardInput")
        preview_input.setReadOnly(True)
        preview_input.setFixedHeight(scaled_px(23))
        preview_input.setMaximumWidth(scaled_px(72))
        preview_button = QPushButton("Aa", card)
        preview_button.setObjectName("ThemeCardButton")
        preview_button.setFixedSize(scaled_px(38), scaled_px(23))
        preview_row.addWidget(preview_input)
        preview_row.addWidget(preview_button)
        layout.addLayout(preview_row)

        preview_check = QCheckBox("Aa", card)
        preview_check.setObjectName("ThemeCardCheck")
        preview_check.setChecked(True)
        layout.addWidget(preview_check)

        for widget in (title, preview_input, preview_button, preview_check):
            card.watch_clicks_from(widget)

        card._preview_style = sk  # Keep the card's StyleKit available for restyling.
        self._style_card(card, False)
        return card

    def _on_theme_clicked(self, name: str):
        """Apply the selected theme."""
        if name not in self._cards:
            return
        themes.set_theme(name)
        self._update_selected_cards(name)
        self.refresh_theme()
        self.theme_selected.emit(name)

    def refresh_theme(self):
        """Re-apply styles after theme change."""
        self._sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        self.setStyleSheet(
            self._sk.dialog_css()
            + f"QWidget#ThemeGallery, QScrollArea#ThemeGalleryScroll {{ "
            f"background: {self._sk.token('panel')}; }}"
        )
        self._update_selected_cards(themes.name())

    def _update_selected_cards(self, selected_name: str) -> None:
        for name, card in self._cards.items():
            selected = name == selected_name
            card.setProperty("selected", selected)
            self._style_card(card, selected)

    @staticmethod
    def _style_card(card: _ThemeCard, selected: bool) -> None:
        sk = card._preview_style
        if sk is None:
            return
        # The static part of the card stylesheet (dialog chrome + all rules
        # that do not depend on the selected state) is built once per card
        # and cached; only the #ThemeCard border/background is re-rendered
        # on every selection change.
        base = getattr(card, "_base_css", None)
        if base is None:
            base = (
                sk.dialog_css()
                + f"QWidget#ThemeCard:hover {{ background: {sk.token('header')}; }}"
                + f"QWidget#ThemeCard QPushButton {{ font-size: {scaled_pt(10)}px; "
                f"padding: 0; }}"
                + f"QWidget#ThemeCard QLineEdit {{ font-size: {scaled_pt(9)}px; "
                f"padding: 0 {scaled_px(4)}px; }}"
                + f"QWidget#ThemeCard QCheckBox {{ font-size: {scaled_pt(9)}px; }}"
            )
            card._base_css = base
        border = sk.token("accent") if selected else sk.token("border")
        border_width = 2 if selected else 1
        card.setStyleSheet(
            base
            + f"QWidget#ThemeCard {{ background: {sk.token('panel')}; "
            f"border: {border_width}px solid {border}; "
            f"border-radius: {scaled_px(8)}px; }}"
        )

    def showEvent(self, event) -> None:
        parent = self.parentWidget()
        if parent is not None:
            frame = self.frameGeometry()
            frame.moveCenter(parent.mapToGlobal(parent.rect().center()))
            self.move(frame.topLeft())
        super().showEvent(event)
