# Theme Editor Phase 2 — Preview Interface Implementation Plan
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real-time theme preview interface to the settings dialog showing all UI components in the selected theme.

**Architecture:** A new `ThemePreviewWidget` displays all UI components (buttons, inputs, labels, lists, tables, dialogs, etc.) styled with the selected theme. The settings dialog gets a left-right split layout with theme selection on the left and preview on the right.

**Tech Stack:** Python 3.12+, PySide6, themes system

**Spec:** `docs/compose/specs/2026-06-18-theme-editor-phase2-design.md`

---

## File Structure

### New Files
- `AssetsManager/widgets/theme_preview.py` — ThemePreviewWidget and ThemePreviewRenderer
- `AssetsManager/dialogs/theme_preview_dialog.py` — ThemePreviewDialog with split layout
- `tests/widgets/test_theme_preview.py` — Theme preview tests

### Modified Files
- `AssetsManager/dialogs/settings_dialog.py` — Add "Preview" button to theme section
- `AssetsManager/i18n/en.json` — Add preview-related i18n keys
- `AssetsManager/i18n/zh.json` — Add preview-related i18n keys
- `AssetsManager/i18n/ja.json` — Add preview-related i18n keys

---

### Task 1: Create ThemePreviewWidget

**Covers:** S1, S3

**Files:**
- Create: `AssetsManager/widgets/theme_preview.py`

- [ ] **Step 1: Create ThemePreviewWidget class**

```python
"""Theme preview widget — displays all UI components styled with a theme."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QCheckBox, QRadioButton, QSlider,
    QProgressBar, QGroupBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QScrollArea, QSizePolicy,
)
from PySide6.QtCore import Qt
from AssetsManager.core.ui_scale import scaled_px, scaled_pt


class ThemePreviewWidget(QWidget):
    """Displays all UI components styled with the current theme."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(scaled_px(12))
        layout.setContentsMargins(scaled_px(8), scaled_px(8), scaled_px(8), scaled_px(8))

        # Scroll area for preview content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(scaled_px(16))

        # Section 1: Buttons
        content_layout.addWidget(self._create_button_section())
        # Section 2: Inputs
        content_layout.addWidget(self._create_input_section())
        # Section 3: Labels
        content_layout.addWidget(self._create_label_section())
        # Section 4: List
        content_layout.addWidget(self._create_list_section())
        # Section 5: Table
        content_layout.addWidget(self._create_table_section())
        # Section 6: Dialog mock
        content_layout.addWidget(self._create_dialog_section())
        # Section 7: Checkboxes/Radio
        content_layout.addWidget(self._create_check_radio_section())
        # Section 8: Slider/Progress
        content_layout.addWidget(self._create_slider_progress_section())
        # Section 9: GroupBox
        content_layout.addWidget(self._create_groupbox_section())

        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)

    def _create_button_section(self) -> QGroupBox:
        group = QGroupBox("Buttons")
        layout = QHBoxLayout(group)
        layout.setSpacing(scaled_px(8))

        primary = QPushButton("Primary")
        secondary = QPushButton("Secondary")
        danger = QPushButton("Danger")
        disabled = QPushButton("Disabled")
        disabled.setEnabled(False)

        layout.addWidget(primary)
        layout.addWidget(secondary)
        layout.addWidget(danger)
        layout.addWidget(disabled)
        return group

    def _create_input_section(self) -> QGroupBox:
        group = QGroupBox("Inputs")
        layout = QVBoxLayout(group)
        layout.setSpacing(scaled_px(8))

        row1 = QHBoxLayout()
        text_input = QLineEdit()
        text_input.setPlaceholderText("Text input")
        search_input = QLineEdit()
        search_input.setPlaceholderText("Search input")
        row1.addWidget(text_input)
        row1.addWidget(search_input)

        row2 = QHBoxLayout()
        password_input = QLineEdit()
        password_input.setPlaceholderText("Password input")
        password_input.setEchoMode(QLineEdit.EchoMode.Password)
        disabled_input = QLineEdit()
        disabled_input.setPlaceholderText("Disabled input")
        disabled_input.setEnabled(False)
        row2.addWidget(password_input)
        row2.addWidget(disabled_input)

        multiline = QTextEdit()
        multiline.setPlaceholderText("Multiline text area")
        multiline.setMaximumHeight(scaled_px(60))

        layout.addLayout(row1)
        layout.addLayout(row2)
        layout.addWidget(multiline)
        return group

    def _create_label_section(self) -> QGroupBox:
        group = QGroupBox("Labels")
        layout = QVBoxLayout(group)
        layout.setSpacing(scaled_px(4))

        heading = QLabel("Heading text")
        heading.setProperty("heading", True)
        body = QLabel("Body text")
        muted = QLabel("Muted text")
        muted.setProperty("muted", True)
        success = QLabel("Success text")
        success.setProperty("success", True)
        warning = QLabel("Warning text")
        warning.setProperty("warning", True)
        danger = QLabel("Danger text")
        danger.setProperty("danger", True)

        layout.addWidget(heading)
        layout.addWidget(body)
        layout.addWidget(muted)
        layout.addWidget(success)
        layout.addWidget(warning)
        layout.addWidget(danger)
        return group

    def _create_list_section(self) -> QGroupBox:
        group = QGroupBox("List")
        layout = QVBoxLayout(group)
        layout.setSpacing(scaled_px(2))

        items = ["Selected item", "Normal item", "Another item", "Disabled item"]
        for i, text in enumerate(items):
            label = QLabel(f"  {'●' if i == 0 else '○'} {text}")
            label.setProperty("list-item", True)
            if i == 0:
                label.setProperty("selected", True)
            if i == 3:
                label.setEnabled(False)
            layout.addWidget(label)
        return group

    def _create_table_section(self) -> QGroupBox:
        group = QGroupBox("Table")
        layout = QVBoxLayout(group)

        table = QTableWidget(4, 4)
        table.setHorizontalHeaderLabels(["Column 1", "Column 2", "Column 3", "Column 4"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)

        for row in range(4):
            for col in range(4):
                item = QTableWidgetItem(f"Data {row+1},{col+1}")
                table.setItem(row, col, item)

        table.setMaximumHeight(scaled_px(160))
        layout.addWidget(table)
        return group

    def _create_dialog_section(self) -> QGroupBox:
        group = QGroupBox("Dialog Mock")
        layout = QVBoxLayout(group)
        layout.setSpacing(scaled_px(4))

        # Title bar
        title_bar = QWidget()
        title_bar.setObjectName("dialogTitleBar")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(scaled_px(8), scaled_px(4), scaled_px(8), scaled_px(4))
        title = QLabel("Dialog Title")
        title.setProperty("heading", True)
        close_btn = QPushButton("×")
        close_btn.setFixedSize(scaled_px(20), scaled_px(20))
        title_layout.addWidget(title)
        title_layout.addStretch()
        title_layout.addWidget(close_btn)

        # Content area
        content = QLabel("Dialog content area — this simulates a typical dialog layout.")
        content.setWordWrap(True)
        content.setContentsMargins(scaled_px(12), scaled_px(8), scaled_px(12), scaled_px(8))

        # Button bar
        btn_bar = QWidget()
        btn_layout = QHBoxLayout(btn_bar)
        btn_layout.setContentsMargins(scaled_px(8), scaled_px(4), scaled_px(8), scaled_px(4))
        btn_layout.addStretch()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)

        layout.addWidget(title_bar)
        layout.addWidget(content)
        layout.addWidget(btn_bar)
        return group

    def _create_check_radio_section(self) -> QGroupBox:
        group = QGroupBox("Checkboxes & Radio")
        layout = QVBoxLayout(group)
        layout.setSpacing(scaled_px(4))

        cb1 = QCheckBox("Checked checkbox")
        cb1.setChecked(True)
        cb2 = QCheckBox("Unchecked checkbox")
        cb3 = QCheckBox("Disabled checkbox")
        cb3.setEnabled(False)

        rb1 = QRadioButton("Selected radio")
        rb1.setChecked(True)
        rb2 = QRadioButton("Unselected radio")

        layout.addWidget(cb1)
        layout.addWidget(cb2)
        layout.addWidget(cb3)
        layout.addWidget(rb1)
        layout.addWidget(rb2)
        return group

    def _create_slider_progress_section(self) -> QGroupBox:
        group = QGroupBox("Slider & Progress")
        layout = QVBoxLayout(group)
        layout.setSpacing(scaled_px(8))

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(60)

        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(75)

        layout.addWidget(slider)
        layout.addWidget(progress)
        return group

    def _create_groupbox_section(self) -> QGroupBox:
        group = QGroupBox("GroupBox")
        layout = QVBoxLayout(group)
        layout.setSpacing(scaled_px(4))

        inner = QGroupBox("Nested GroupBox")
        inner_layout = QVBoxLayout(inner)
        inner_layout.addWidget(QLabel("Content inside a group box"))
        inner_layout.addWidget(QPushButton("Button in group"))

        layout.addWidget(inner)
        return group
```

- [ ] **Step 2: Test the widget**

```python
"""Tests for ThemePreviewWidget."""
import pytest
from AssetsManager.widgets.theme_preview import ThemePreviewWidget


def test_theme_preview_widget_creation(qapp):
    widget = ThemePreviewWidget()
    assert widget is not None
    assert widget.layout() is not None


def test_theme_preview_has_all_sections(qapp):
    widget = ThemePreviewWidget()
    # Check that all sections are created
    assert widget.findChild(QGroupBox, "Buttons") is not None
```

- [ ] **Step 3: Run quality gate**

```
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

- [ ] **Step 4: Commit**

```bash
git add AssetsManager/widgets/theme_preview.py tests/widgets/test_theme_preview.py
git commit -m "feat: add ThemePreviewWidget with all UI component sections"
```

---

### Task 2: Create ThemePreviewRenderer

**Covers:** S2

**Files:**
- Modify: `AssetsManager/widgets/theme_preview.py`

- [ ] **Step 1: Add ThemePreviewRenderer class**

```python
class ThemePreviewRenderer:
    """Applies theme data to a ThemePreviewWidget."""

    @staticmethod
    def apply_theme(widget: ThemePreviewWidget, theme_data: dict):
        """Apply theme to all preview sections."""
        colors = theme_data.get("colors", {})
        properties = theme_data.get("properties", {})

        # Build stylesheet
        stylesheet = ThemePreviewRenderer._build_stylesheet(colors, properties)
        widget.setStyleSheet(stylesheet)

    @staticmethod
    def _build_stylesheet(colors: dict, properties: dict) -> str:
        """Build QSS stylesheet from theme data."""
        base = colors.get("base", "#1a1a1a")
        panel = colors.get("panel", "#252525")
        header = colors.get("header", "#2d2d2d")
        border = colors.get("border", "#555555")
        heading = colors.get("heading", "#e0e0e0")
        body = colors.get("body", "#b0b0b0")
        muted = colors.get("muted", "#666666")
        accent = colors.get("accent", "#606060")
        success = colors.get("success", "#44c98a")
        warning = colors.get("warning", "#f0a040")
        danger = colors.get("danger", "#e05555")

        border_radius = properties.get("border_radius", {})
        sm = border_radius.get("sm", 4)
        md = border_radius.get("md", 6)
        lg = border_radius.get("lg", 8)

        return f"""
            QWidget {{
                background: {base};
                color: {body};
                font-size: {scaled_pt(12)}px;
            }}
            QGroupBox {{
                border: 1px solid {border};
                border-radius: {scaled_px(md)}px;
                margin-top: {scaled_px(8)}px;
                padding-top: {scaled_px(12)}px;
                color: {heading};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {scaled_px(10)}px;
                padding: 0 {scaled_px(5)}px;
            }}
            QPushButton {{
                background: {accent};
                color: {heading};
                border: 1px solid {accent};
                border-radius: {scaled_px(sm)}px;
                padding: {scaled_px(4)}px {scaled_px(12)}px;
            }}
            QPushButton:hover {{
                background: {accent};
                border-color: {accent};
            }}
            QPushButton:disabled {{
                background: {muted};
                border-color: {muted};
                color: {base};
            }}
            QLineEdit, QTextEdit {{
                background: {panel};
                color: {heading};
                border: 1px solid {border};
                border-radius: {scaled_px(sm)}px;
                padding: {scaled_px(4)}px {scaled_px(8)}px;
            }}
            QLineEdit:focus, QTextEdit:focus {{
                border-color: {accent};
            }}
            QLineEdit:disabled, QTextEdit:disabled {{
                background: {base};
                color: {muted};
            }}
            QCheckBox::indicator, QRadioButton::indicator {{
                width: {scaled_px(16)}px;
                height: {scaled_px(16)}px;
                border: 1px solid {border};
                border-radius: {scaled_px(sm)}px;
                background: {panel};
            }}
            QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
                background: {accent};
                border-color: {accent};
            }}
            QSlider::groove:horizontal {{
                height: {scaled_px(4)}px;
                background: {border};
                border-radius: {scaled_px(2)}px;
            }}
            QSlider::handle:horizontal {{
                width: {scaled_px(16)}px;
                height: {scaled_px(16)}px;
                margin: {scaled_px(-6)}px 0;
                background: {accent};
                border-radius: {scaled_px(8)}px;
            }}
            QProgressBar {{
                border: 1px solid {border};
                border-radius: {scaled_px(sm)}px;
                text-align: center;
                background: {panel};
            }}
            QProgressBar::chunk {{
                background: {accent};
                border-radius: {scaled_px(sm)}px;
            }}
            QTableWidget {{
                background: {panel};
                border: 1px solid {border};
                border-radius: {scaled_px(sm)}px;
                gridline-color: {border};
            }}
            QHeaderView::section {{
                background: {header};
                color: {heading};
                border: none;
                border-right: 1px solid {border};
                padding: {scaled_px(4)}px;
            }}
            QLabel[heading="true"] {{
                color: {heading};
                font-weight: bold;
                font-size: {scaled_pt(14)}px;
            }}
            QLabel[muted="true"] {{
                color: {muted};
            }}
            QLabel[success="true"] {{
                color: {success};
            }}
            QLabel[warning="true"] {{
                color: {warning};
            }}
            QLabel[danger="true"] {{
                color: {danger};
            }}
            QLabel[selected="true"] {{
                background: {accent};
                color: {heading};
                border-radius: {scaled_px(sm)}px;
                padding: {scaled_px(2)}px {scaled_px(4)}px;
            }}
            #dialogTitleBar {{
                background: {header};
                border-radius: {scaled_px(md)}px {scaled_px(md)}px 0 0;
            }}
        """
```

- [ ] **Step 2: Run quality gate**

```
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

- [ ] **Step 3: Commit**

```bash
git add AssetsManager/widgets/theme_preview.py
git commit -m "feat: add ThemePreviewRenderer for applying themes to preview"
```

---

### Task 3: Create ThemePreviewDialog

**Covers:** S1, S2

**Files:**
- Create: `AssetsManager/dialogs/theme_preview_dialog.py`

- [ ] **Step 1: Create ThemePreviewDialog class**

```python
"""Theme preview dialog — left-right split with theme selection and preview."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QWidget,
    QListWidget, QListWidgetItem, QPushButton, QLabel, QFrame,
)
from PySide6.QtGui import QPixmap, QPainter, QColor, QIcon
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.core import themes
from AssetsManager.widgets.theme_preview import ThemePreviewWidget, ThemePreviewRenderer
from AssetsManager import i18n
tr = i18n.tr


class ThemePreviewDialog(QDialog):
    """Dialog with theme selection on left and preview on right."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings.theme_preview"))
        self.setMinimumSize(scaled_px(800), scaled_px(500))
        self._setup_ui()
        self._load_themes()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel — theme selection
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setSpacing(scaled_px(8))
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

        # Right panel — preview
        self._preview = ThemePreviewWidget()

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
        if not name or name == "__header__":
            return
        loader = themes._get_loader()
        theme_data = loader.get(name)
        if theme_data:
            ThemePreviewRenderer.apply_theme(self._preview, theme_data)

    def _on_apply(self):
        current = self._theme_list.currentItem()
        if current is None:
            return
        name = current.data(Qt.ItemDataRole.UserRole)
        if name and name != "__header__":
            themes.set_theme(name)
            self.accept()
```

- [ ] **Step 2: Run quality gate**

```
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

- [ ] **Step 3: Commit**

```bash
git add AssetsManager/dialogs/theme_preview_dialog.py
git commit -m "feat: add ThemePreviewDialog with split layout"
```

---

### Task 4: Integrate Preview into Settings Dialog

**Covers:** S1

**Files:**
- Modify: `AssetsManager/dialogs/settings_dialog.py`

- [ ] **Step 1: Add Preview button to theme section**

In `_setup_theme_section()`, add a "Preview" button next to the theme list:

```python
# After theme_layout.addWidget(self._theme_list)
preview_btn = self.make_secondary_btn(tr("settings.theme_preview"), self._on_preview_theme)
theme_layout.addWidget(preview_btn)
```

- [ ] **Step 2: Add preview handler**

```python
def _on_preview_theme(self):
    """Open theme preview dialog."""
    from AssetsManager.dialogs.theme_preview_dialog import ThemePreviewDialog
    dlg = ThemePreviewDialog(self)
    dlg.exec()
```

- [ ] **Step 3: Add i18n keys**

In `en.json`:
```json
"settings.theme_preview": "Preview Theme",
"settings.apply_theme": "Apply Theme"
```

Add corresponding translations in `zh.json` and `ja.json`.

- [ ] **Step 4: Run quality gate**

```
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add AssetsManager/dialogs/settings_dialog.py AssetsManager/i18n/
git commit -m "feat: add theme preview button to settings dialog"
```

---

### Task 5: Final Integration and Testing

**Covers:** S1, S2, S3

**Files:**
- All modified files

- [ ] **Step 1: Run full quality gate**

```
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

- [ ] **Step 2: Manual testing checklist**

- [ ] Preview dialog opens from settings
- [ ] All 9 preview sections render correctly
- [ ] Theme selection updates preview in real-time
- [ ] "Apply" button applies theme to main application
- [ ] Preview works with all built-in themes
- [ ] Preview works with custom themes

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat: complete theme editor phase 2 — preview interface"
```

