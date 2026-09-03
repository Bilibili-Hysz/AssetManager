"""Theme preview widget displaying all UI components for live theme preview."""
import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QPushButton,
    QLineEdit,
    QTextEdit,
    QLabel,
    QListWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QCheckBox,
    QRadioButton,
    QSlider,
    QProgressBar,
    QScrollArea,
    QFrame,
    QButtonGroup,
    QGridLayout,
)

from AssetsManager.core import themes
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.ui_scale import scaled_px, scaled_pt

_log = logging.getLogger(__name__)


# ── Preview Sections ──────────────────────────────────────

class _ButtonSection(QGroupBox):
    """Primary, secondary, danger, and disabled buttons."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Buttons", parent)
        row = QHBoxLayout(self)
        row.setSpacing(scaled_px(8))

        primary = QPushButton("Primary")
        primary.setProperty("role", "primary")
        row.addWidget(primary)

        secondary = QPushButton("Secondary")
        secondary.setProperty("role", "secondary")
        row.addWidget(secondary)

        danger = QPushButton("Danger")
        danger.setProperty("role", "danger")
        row.addWidget(danger)

        disabled = QPushButton("Disabled")
        disabled.setEnabled(False)
        row.addWidget(disabled)


class _InputSection(QGroupBox):
    """Text, search, password, disabled, and multiline inputs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Inputs", parent)
        col = QVBoxLayout(self)
        col.setSpacing(scaled_px(6))

        text_input = QLineEdit()
        text_input.setPlaceholderText("Text input")
        col.addWidget(text_input)

        search_input = QLineEdit()
        search_input.setPlaceholderText("Search input")
        search_input.setProperty("input_type", "search")
        col.addWidget(search_input)

        password_input = QLineEdit()
        password_input.setPlaceholderText("Password input")
        password_input.setEchoMode(QLineEdit.EchoMode.Password)
        col.addWidget(password_input)

        disabled_input = QLineEdit()
        disabled_input.setPlaceholderText("Disabled input")
        disabled_input.setEnabled(False)
        col.addWidget(disabled_input)

        multiline = QTextEdit()
        multiline.setPlaceholderText("Multiline text edit")
        multiline.setMaximumHeight(scaled_px(60))
        col.addWidget(multiline)


class _LabelSection(QGroupBox):
    """Heading, body, muted, disabled, success, warning, danger labels."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Labels", parent)
        col = QVBoxLayout(self)
        col.setSpacing(scaled_px(4))

        for text, prop_value in [
            ("Heading Label", "heading"),
            ("Body Label", "body"),
            ("Muted Label", "muted"),
            ("Success Label", "success"),
            ("Warning Label", "warning"),
            ("Danger Label", "danger"),
        ]:
            lbl = QLabel(text)
            lbl.setProperty("label_role", prop_value)
            col.addWidget(lbl)

        disabled_lbl = QLabel("Disabled Label")
        disabled_lbl.setProperty("label_role", "disabled")
        disabled_lbl.setEnabled(False)
        col.addWidget(disabled_lbl)


class _ListSection(QGroupBox):
    """List with selected, normal, and disabled items."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("List", parent)
        layout = QVBoxLayout(self)

        lst = QListWidget()
        lst.setMaximumHeight(scaled_px(100))
        for label in ["Selected item", "Normal item", "Another item", "Disabled item"]:
            lst.addItem(label)
        lst.setCurrentRow(0)
        item = lst.item(3)
        if item is not None:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        layout.addWidget(lst)


class _TableSection(QGroupBox):
    """Table with header and data rows."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Table", parent)
        layout = QVBoxLayout(self)

        table = QTableWidget(3, 3)
        table.setHorizontalHeaderLabels(["Name", "Type", "Size"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setMaximumHeight(scaled_px(120))
        data = [
            ("image.png", "PNG", "2.4 MB"),
            ("document.pdf", "PDF", "1.1 MB"),
            ("archive.zip", "ZIP", "512 KB"),
        ]
        for row_idx, (name, ftype, size) in enumerate(data):
            table.setItem(row_idx, 0, QTableWidgetItem(name))
            table.setItem(row_idx, 1, QTableWidgetItem(ftype))
            table.setItem(row_idx, 2, QTableWidgetItem(size))
        layout.addWidget(table)


class _DialogSection(QGroupBox):
    """Mini dialog preview with title bar, content, and button bar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Dialog Preview", parent)
        outer = QVBoxLayout(self)

        frame = QFrame()
        frame.setProperty("dialog_frame", True)
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        title_bar = QLabel("Dialog Title")
        title_bar.setProperty("dialog_title", True)
        title_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_bar.setMaximumHeight(scaled_px(28))
        frame_layout.addWidget(title_bar)

        content = QLabel("Dialog content area with a sample message.")
        content.setProperty("dialog_content", True)
        content.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.setWordWrap(True)
        frame_layout.addWidget(content)

        btn_bar = QWidget()
        btn_bar.setProperty("dialog_button_bar", True)
        btn_layout = QHBoxLayout(btn_bar)
        btn_layout.setContentsMargins(
            scaled_px(8), scaled_px(6), scaled_px(8), scaled_px(6)
        )
        btn_layout.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.setProperty("role", "primary")
        btn_layout.addWidget(ok_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setProperty("role", "secondary")
        btn_layout.addWidget(cancel_btn)
        frame_layout.addWidget(btn_bar)

        outer.addWidget(frame)


class _CheckRadioSection(QGroupBox):
    """Checkboxes and radio buttons."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Checkboxes & Radio Buttons", parent)
        row = QHBoxLayout(self)
        row.setSpacing(scaled_px(16))

        check_col = QVBoxLayout()
        check_col.setSpacing(scaled_px(4))
        for label, checked in [("Checked", True), ("Unchecked", False), ("Disabled", False)]:
            cb = QCheckBox(label)
            cb.setChecked(checked)
            if label == "Disabled":
                cb.setEnabled(False)
            check_col.addWidget(cb)
        row.addLayout(check_col)

        radio_col = QVBoxLayout()
        radio_col.setSpacing(scaled_px(4))
        group = QButtonGroup(self)
        for i, label in enumerate(["Option A", "Option B", "Disabled"]):
            rb = QRadioButton(label)
            if i == 0:
                rb.setChecked(True)
            if label == "Disabled":
                rb.setEnabled(False)
            group.addButton(rb)
            radio_col.addWidget(rb)
        row.addLayout(radio_col)


class _SliderProgressSection(QGroupBox):
    """Slider and progress bar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Sliders & Progress", parent)
        col = QVBoxLayout(self)
        col.setSpacing(scaled_px(8))

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(60)
        col.addWidget(slider)

        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(60)
        col.addWidget(progress)

        indeterminate = QProgressBar()
        indeterminate.setRange(0, 0)
        indeterminate.setProperty("indeterminate", True)
        col.addWidget(indeterminate)


class _GroupBoxSection(QGroupBox):
    """Nested group boxes to show border/title styling."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Group Boxes", parent)
        outer = QVBoxLayout(self)

        inner = QGroupBox("Nested Group")
        inner_layout = QVBoxLayout(inner)
        inner_layout.addWidget(QLabel("Content inside a nested group box."))
        outer.addWidget(inner)


_COLOR_LABELS: dict[str, str] = {
    "base": "Base",
    "panel": "Panel",
    "header": "Header",
    "border": "Border",
    "heading": "Heading",
    "body": "Body",
    "muted": "Muted",
    "accent": "Accent",
    "on_accent": "On Accent",
    "success": "Success",
    "warning": "Warning",
    "danger": "Danger",
    "input_bg": "Input BG",
    "input_text": "Input Text",
    "border_focus": "Border Focus",
    "disabled_text": "Disabled Text",
    "disabled_bg": "Disabled BG",
    "hover_overlay": "Hover Overlay",
    "selected_overlay": "Selected Overlay",
}


class _ColorSwatchSection(QGroupBox):
    """Clickable color swatches for theme colors."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Colors", parent)
        self._swatches: dict[str, QLabel] = {}
        self._on_click = None

        grid = QGridLayout(self)
        grid.setSpacing(scaled_px(6))

        for idx, (color_name, display_name) in enumerate(_COLOR_LABELS.items()):
            row, col = divmod(idx, 3)
            swatch = QLabel()
            swatch.setFixedSize(scaled_px(32), scaled_px(32))
            swatch.setProperty("color-swatch", True)
            swatch.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch.setToolTip(display_name)
            swatch.mousePressEvent = lambda e, name=color_name: self._handle_click(name)
            self._swatches[color_name] = swatch

            lbl = QLabel(display_name)
            lbl.setProperty("label_role", "muted")

            cell = QVBoxLayout()
            cell.setSpacing(scaled_px(2))
            cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.addWidget(swatch, alignment=Qt.AlignmentFlag.AlignCenter)
            cell.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignCenter)
            grid.addLayout(cell, row, col)

    def set_on_click(self, callback) -> None:
        self._on_click = callback

    def _handle_click(self, color_name: str) -> None:
        if self._on_click:
            self._on_click(color_name)

    def update_swatch(self, color_name: str, color_hex: str) -> None:
        swatch = self._swatches.get(color_name)
        if swatch:
            radius_sm = scaled_px(int(themes.prop("border_radius", "sm")))
            swatch.setStyleSheet(
                f"background: {color_hex}; border: {scaled_px(1)}px solid {themes.color('border')}; border-radius: {radius_sm}px;"
            )

    def set_all_colors(self, colors: dict[str, str]) -> None:
        for name, hex_val in colors.items():
            self.update_swatch(name, hex_val)


# ── Main Widget ───────────────────────────────────────────

class ThemePreviewWidget(QWidget):
    """Displays all UI component sections for live theme preview.

    Used in split dialog where left side has theme selection and
    right side shows the preview. Each section is a QGroupBox
    with descriptive title.
    """

    color_changed = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ThemePreviewWidget")
        self._theme_data: dict = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setObjectName("ThemePreviewScroll")

        container = QWidget()
        container.setObjectName("ThemePreviewContainer")
        layout = QVBoxLayout(container)
        layout.setSpacing(scaled_px(12))
        layout.setContentsMargins(
            scaled_px(8), scaled_px(8), scaled_px(8), scaled_px(8)
        )

        self._sections: list[QGroupBox] = [
            _ButtonSection(container),
            _InputSection(container),
            _LabelSection(container),
            _ListSection(container),
            _TableSection(container),
            _DialogSection(container),
            _CheckRadioSection(container),
            _SliderProgressSection(container),
            _GroupBoxSection(container),
        ]
        for section in self._sections:
            layout.addWidget(section)
        layout.addStretch()
        scroll.setWidget(container)
        outer.addWidget(scroll, 1)

        self._color_toolbar = _ColorSwatchSection()
        self._color_toolbar.set_on_click(self._open_color_picker)
        self._color_toolbar.setMaximumWidth(scaled_px(200))
        outer.addWidget(self._color_toolbar)

    def sections(self) -> list[QGroupBox]:
        """Return all preview sections."""
        return list(self._sections)

    def color_section(self) -> _ColorSwatchSection:
        """Return the color swatch section."""
        return self._color_toolbar

    def set_theme_data(self, theme_data: dict) -> None:
        self._theme_data = dict(theme_data)

    def theme_data(self) -> dict:
        """Return a copy of the currently previewed (possibly edited) theme data."""
        return dict(self._theme_data)

    def _get_current_color(self, color_name: str) -> QColor:
        colors = {k: self._theme_data[k] for k in self._theme_data if k != "properties"}
        # Fall back to the active theme so a missing swatch never shows an
        # arbitrary gray that does not exist anywhere in the product.
        hex_val = colors.get(color_name, themes.color(color_name))
        return QColor(hex_val)

    def _open_color_picker(self, color_name: str) -> None:
        from AssetsManager.dialogs.color_picker_dialog import ColorPickerDialog

        current = self._get_current_color(color_name)
        dlg = ColorPickerDialog(initial_color=current, parent=self)
        dlg.color_selected.connect(lambda c, name=color_name: self._on_color_picked(name, c))
        dlg.exec()

    def _on_color_picked(self, color_name: str, color: QColor) -> None:
        hex_val = color.name()
        self._color_toolbar.update_swatch(color_name, hex_val)
        self._theme_data[color_name] = hex_val
        self.color_changed.emit(color_name, hex_val)


# ── Renderer ──────────────────────────────────────────────

class ThemePreviewRenderer:
    """Applies a theme's colors and properties to a ThemePreviewWidget."""

    def apply_theme(self, widget: ThemePreviewWidget, theme_data: dict) -> None:
        """Apply theme to preview widget via generated stylesheet."""
        widget.set_theme_data(theme_data)
        colors = {k: theme_data[k] for k in theme_data if k != "properties"}
        properties = theme_data.get("properties", {})
        qss = self._build_stylesheet(colors, properties)
        widget.setStyleSheet(qss)
        widget.color_section().set_all_colors(colors)

    def _build_stylesheet(self, colors: dict, properties: dict) -> str:
        """Build QSS from theme colors and properties."""
        c = colors
        br = properties.get("border_radius", {})
        fs = properties.get("font_size", {})
        op = properties.get("opacity", {})

        # Radius fallbacks mirror core/themes.py canonical defaults (8/10/14),
        # NOT arbitrary values — the preview must agree with the real renderer.
        r_sm = scaled_px(br.get("sm", 8))
        r_md = scaled_px(br.get("md", 10))
        r_lg = scaled_px(br.get("lg", 14))
        hover_op = op.get("hover", 0.15)
        hov = alpha(c.get("hover_overlay", themes.color("hover_overlay")), hover_op)

        # Color fallbacks resolve against the *currently active* theme so a
        # partially-edited preview inherits coherent values instead of the
        # legacy arbitrary-gray hexes.
        base = c.get("base", themes.color("base"))
        panel = c.get("panel", themes.color("panel"))
        header = c.get("header", themes.color("header"))
        border = c.get("border", themes.color("border"))
        heading = c.get("heading", themes.color("heading"))
        body = c.get("body", themes.color("body"))
        muted = c.get("muted", themes.color("muted"))
        accent = c.get("accent", themes.color("accent"))
        on_accent = c.get("on_accent", themes.color("on_accent"))
        success = c.get("success", themes.color("success"))
        warning = c.get("warning", themes.color("warning"))
        danger = c.get("danger", themes.color("danger"))
        input_bg = c.get("input_bg", panel)
        input_text = c.get("input_text", heading)
        border_focus = c.get("border_focus", accent)
        disabled_text = c.get("disabled_text", muted)
        disabled_bg = c.get("disabled_bg", base)
        sel_overlay = c.get("selected_overlay", accent)

        pt_body = scaled_pt(fs.get("body", 11))
        pt_heading = scaled_pt(fs.get("heading", 13))
        pt_progress = scaled_pt(fs.get("progress", 9))

        qss = f"""
        /* ── Preview Container ────────────────── */
        #ThemePreviewWidget, #ThemePreviewScroll, #ThemePreviewContainer {{
            background: {base};
            border: none;
        }}

        /* ── GroupBox ─────────────────────────── */
        QGroupBox {{
            color: {heading};
            border: {scaled_px(1)}px solid {border};
            border-radius: {r_lg}px;
            margin-top: {scaled_px(12)}px;
            padding-top: {scaled_px(16)}px;
            font-size: {pt_heading}px;
            font-weight: bold;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: {scaled_px(10)}px;
            padding: 0 {scaled_px(5)}px;
        }}

        /* ── Labels ───────────────────────────── */
        QLabel {{
            color: {body};
            font-size: {pt_body}px;
            background: transparent;
        }}
        QLabel[label_role="heading"] {{
            color: {heading};
            font-size: {pt_heading}px;
            font-weight: bold;
        }}
        QLabel[label_role="body"] {{
            color: {body};
        }}
        QLabel[label_role="muted"] {{
            color: {muted};
        }}
        QLabel[label_role="success"] {{
            color: {success};
        }}
        QLabel[label_role="warning"] {{
            color: {warning};
        }}
        QLabel[label_role="danger"] {{
            color: {danger};
        }}
        QLabel[label_role="disabled"] {{
            color: {disabled_text};
        }}
        QLabel:disabled {{
            color: {disabled_text};
        }}

        /* ── Buttons ──────────────────────────── */
        QPushButton {{
            background: {accent};
            color: {on_accent};
            border: none;
            border-radius: {r_md}px;
            padding: {scaled_px(6)}px {scaled_px(16)}px;
            font-size: {pt_body}px;
        }}
        QPushButton:hover {{
            background: {hov};
        }}
        QPushButton:pressed {{
            background: {muted};
        }}
        QPushButton:disabled {{
            background: {disabled_bg};
            color: {disabled_text};
        }}
        QPushButton[role="primary"] {{
            background: {accent};
            color: {on_accent};
        }}
        QPushButton[role="secondary"] {{
            background: {border};
            color: {heading};
        }}
        QPushButton[role="danger"] {{
            background: {danger};
            color: {on_accent};
        }}

        /* ── Inputs ───────────────────────────── */
        QLineEdit, QTextEdit {{
            background: {input_bg};
            color: {input_text};
            border: {scaled_px(1)}px solid {border};
            border-radius: {r_sm}px;
            padding: {scaled_px(4)}px {scaled_px(6)}px;
            font-size: {pt_body}px;
            selection-background-color: {sel_overlay};
        }}
        QLineEdit:focus, QTextEdit:focus {{
            border-color: {border_focus};
        }}
        QLineEdit:disabled, QTextEdit:disabled {{
            background: {disabled_bg};
            color: {disabled_text};
        }}

        /* ── List ─────────────────────────────── */
        QListWidget {{
            background: {panel};
            color: {body};
            border: {scaled_px(1)}px solid {border};
            border-radius: {r_sm}px;
            outline: none;
            font-size: {pt_body}px;
        }}
        QListWidget::item {{
            padding: {scaled_px(3)}px {scaled_px(6)}px;
        }}
        QListWidget::item:selected {{
            background: {accent};
            color: {on_accent};
            border-radius: {r_sm}px;
        }}
        QListWidget::item:disabled {{
            color: {disabled_text};
        }}

        /* ── Table ────────────────────────────── */
        QTableWidget {{
            background: {panel};
            color: {body};
            border: {scaled_px(1)}px solid {border};
            border-radius: {r_sm}px;
            gridline-color: {border};
            font-size: {pt_body}px;
        }}
        QTableWidget::item {{
            padding: {scaled_px(3)}px {scaled_px(6)}px;
        }}
        QTableWidget::item:selected {{
            background: {accent};
            color: {on_accent};
        }}
        QHeaderView::section {{
            background: {header};
            color: {heading};
            border: {scaled_px(1)}px solid {border};
            padding: {scaled_px(4)}px {scaled_px(6)}px;
            font-weight: bold;
            font-size: {pt_body}px;
        }}

        /* ── Dialog Preview ───────────────────── */
        QFrame[dialog_frame="true"] {{
            background: {panel};
            border: {scaled_px(1)}px solid {border};
            border-radius: {r_md}px;
        }}
        QLabel[dialog_title="true"] {{
            background: {header};
            color: {heading};
            font-weight: bold;
            font-size: {pt_heading}px;
            padding: {scaled_px(6)}px;
            border-top-left-radius: {r_md}px;
            border-top-right-radius: {r_md}px;
            border-bottom: {scaled_px(1)}px solid {border};
        }}
        QLabel[dialog_content="true"] {{
            color: {body};
            padding: {scaled_px(12)}px;
        }}
        QWidget[dialog_button_bar="true"] {{
            background: {header};
            border-top: {scaled_px(1)}px solid {border};
            border-bottom-left-radius: {r_md}px;
            border-bottom-right-radius: {r_md}px;
        }}

        /* ── Checkboxes & Radios ──────────────── */
        QCheckBox, QRadioButton {{
            color: {body};
            font-size: {pt_body}px;
            spacing: {scaled_px(4)}px;
        }}
        QCheckBox:disabled, QRadioButton:disabled {{
            color: {disabled_text};
        }}

        /* ── Slider & Progress ────────────────── */
        QSlider::groove:horizontal {{
            background: {border};
            height: {scaled_px(4)}px;
            border-radius: {r_sm}px;
        }}
        QSlider::handle:horizontal {{
            background: {accent};
            width: {scaled_px(14)}px;
            height: {scaled_px(14)}px;
            margin: -{scaled_px(5)}px 0;
            border-radius: {r_md}px;
        }}
        QSlider::sub-page:horizontal {{
            background: {accent};
            border-radius: {r_sm}px;
        }}
        QProgressBar {{
            background: {border};
            color: {on_accent};
            border: none;
            border-radius: {r_sm}px;
            height: {scaled_px(12)}px;
            text-align: center;
            font-size: {pt_progress}px;
        }}
        QProgressBar::chunk {{
            background: {accent};
            border-radius: {r_sm}px;
        }}
        QProgressBar[indeterminate="true"] {{
            color: transparent;
        }}
        """
        return qss
