"""TabbedDialog — Theme template for tabbed dialog windows.

SINGLE-FILE design: inherit this class for dialog-based UI with tabs,
single-page popups, or settings windows. NOT for panels or main windows.

Applicable scenarios:
  - Multi-tab settings dialogs (SettingsDialog, SharingSettingsDialog)
  - Single-page popups with OK/Cancel buttons
  - Any QDialog subclass that needs consistent theming

NOT applicable:
  - Panels → use PanelContent (panels/base.py)
  - Main windows → use QMainWindow with manual QSS

Spacing scale (use scaled_px for DPI awareness):
  - Dialog content margins / spacing: 12–16px
  - Group box content margins / spacing: 8–12px
  - Compact rows (chips, inline controls): 4–6px

Error display convention:
  - Non-critical errors: inline status labels (QLabel updated in-place)
  - Critical / blocking errors: QMessageBox with appropriate icon

Usage (tabbed dialog):
    class MySettings(TabbedDialog):
        def __init__(self, parent=None):
            super().__init__(parent, title="My Settings")

        def _setup_tabs(self):
            tab = QWidget()
            layout = QVBoxLayout(tab)
            layout.addWidget(self.make_radio_group("Theme", {...}, current, on_changed))
            self._add_tab(tab, "General", scrollable=True)

        def _on_apply(self):
            # save settings
            pass

Usage (single-page popup):
    class MyPopup(TabbedDialog):
        def __init__(self, parent=None):
            super().__init__(parent, title="Popup")

        def _build_ui(self):
            layout = QVBoxLayout(self)
            self.setStyleSheet(self._dialog_qss())
            layout.addWidget(self.make_heading("Confirm?"))
            layout.addWidget(self.make_primary_btn("Yes", self.accept))

Architecture:
    self._dialog_qss()   → single dialog-level QSS (cascades to all children)
    self.setStyleSheet()  → called once on init and on every theme change
    No per-widget setStyleSheet — everything inherits from the dialog QSS.
    ObjectName prefix __td_ distinguishes primary/secondary buttons.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QSpinBox, QCheckBox, QGroupBox, QComboBox, QFrame,
    QDialogButtonBox, QWidget, QTabWidget, QScrollArea, QRadioButton,
)
from AssetsManager import i18n
from AssetsManager.core.color_utils import alpha
from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt

tr = i18n.tr


class _CollapsibleSection(QWidget):
    """Section with clickable header that toggles content visibility."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._expanded = False
        self._title = title
        self._header = QPushButton()
        self._header.setCheckable(True)
        self._header.setChecked(False)
        self._update_header_text()
        self._apply_header_style()
        self._header.toggled.connect(self._on_toggle)
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.setFixedHeight(scaled_px(28))

        self._content = QWidget()
        self._content.setVisible(False)
        self._content.setStyleSheet(
            "QWidget { background: transparent; } QLabel { color: inherit; }")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(scaled_px(8), scaled_px(4), 0, scaled_px(4))
        self._content_layout.setSpacing(scaled_px(6))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header)
        layout.addWidget(self._content)

    def content_layout(self) -> QVBoxLayout:
        return self._content_layout

    def refresh_theme(self):
        self._apply_header_style()

    def _update_header_text(self):
        arrow = "\u25BE" if self._expanded else "\u25B8"
        self._header.setText(f"  {arrow} {self._title}")

    def _apply_header_style(self):
        t = themes.get()
        bg = alpha(t["accent"], 0.19) if self._expanded else "transparent"
        hover_bg = alpha(t["accent"], 0.13)
        self._header.setStyleSheet(
            f"QPushButton {{ text-align: left; font-weight: bold; font-size: {scaled_pt(12)}px; "
            f"color: {t['heading']}; background: {bg}; border: 1px solid {t['border']}40; "
            f"border-radius: {scaled_px(4)}px; padding: 4px 8px; }}"
            f"QPushButton:hover {{ background: {hover_bg}; }}")

    def _on_toggle(self, checked):
        self._expanded = checked
        self._content.setVisible(checked)
        self._update_header_text()
        self._apply_header_style()


class TabbedDialog(QDialog):
    """Unified theme template — handles QSS, tabs, buttons, and theme refresh."""

    settings_changed = Signal()
    _ID_SEQ = 0

    def __init__(self, parent=None, title="Dialog", min_size=(360, 400)):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(*min_size)
        self.resize(*min_size)
        self._t = themes.get()
        self._theme_connected = False
        self._heading_labels: list[QLabel] = []
        self._muted_labels: list[QLabel] = []

        if hasattr(self, '_setup_tabs') and type(self)._setup_tabs is not TabbedDialog._setup_tabs:
            # Subclass uses tabbed layout
            self.setStyleSheet(self._dialog_qss())
            self._setup_tabbed_ui()
        else:
            # Subclass uses single-page layout (_build_ui)
            self._build_ui()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._theme_connected:
            self._theme_connected = True
            from AssetsManager.core.signal_bus import get as bus
            bus().theme_changed.connect(self._on_theme_changed)

    def closeEvent(self, event):
        if self._theme_connected:
            from AssetsManager.core.signal_bus import get as bus
            try:
                bus().theme_changed.disconnect(self._on_theme_changed)
            except (RuntimeError, TypeError):
                pass
            self._theme_connected = False
        super().closeEvent(event)

    # ── Theme ─────────────────────────────────────────────────

    def _on_theme_changed(self, _name):
        self._t = themes.get()
        self.setStyleSheet(self._dialog_qss())
        if hasattr(self, '_tabs'):
            self._tabs.setStyleSheet(self._tab_qss())
        self._refresh_static_labels()
        for section in self.findChildren(_CollapsibleSection):
            section.refresh_theme()
        for scroll_area in self.findChildren(QScrollArea):
            self._apply_viewport_color(scroll_area)

    def _refresh_static_labels(self):
        t = self._t
        for label in self._heading_labels:
            label.setStyleSheet(
                f"QLabel {{ color: {t['heading']}; font-weight: bold; background: transparent; }}")
        for label in self._muted_labels:
            label.setStyleSheet(
                f"QLabel {{ color: {t['muted']}; font-size: {scaled_pt(11)}px; background: transparent; }}")

    def _dialog_qss(self) -> str:
        """Single QSS string for the entire dialog. Cascades to all children."""
        t = self._t
        hover = alpha(t["hover_overlay"], t["properties"].get("opacity", {}).get("hover", 0.15))
        return (
            f"QDialog {{ background: {t['panel']}; color: {t['body']}; }}"
            f"QScrollArea {{ border: none; background: {t['panel']}; }}"
            f"QLabel {{ color: {t['body']}; background: transparent; }}"
            f"QLineEdit, QTextEdit, QSpinBox {{ "
            f"background: {t['input_bg']}; color: {t['input_text']}; "
            f"border: 1px solid {t['border']}; border-radius: {scaled_px(4)}px; padding: 3px 6px; }}"
            f"QComboBox {{ "
            f"background: {t['input_bg']}; color: {t['input_text']}; "
            f"border: 1px solid {t['border']}; border-radius: {scaled_px(4)}px; padding: 3px 6px; }}"
            f"QComboBox::drop-down {{ border: none; }}"
            f"QRadioButton, QCheckBox {{ color: {t['body']}; background: transparent; }}"
            f"QRadioButton:checked {{ color: {t['accent']}; font-weight: bold; }}"
            f"QRadioButton::indicator:checked {{ background: {t['accent']}; border: 2px solid {t['accent']}; "
            f"border-radius: {scaled_px(7)}px; width: 14px; height: 14px; }}"
            f"QGroupBox {{ color: {t['heading']}; border: 1px solid {t['border']}; "
            f"border-radius: {scaled_px(6)}px; margin-top: 8px; padding-top: 12px; "
            f"background: transparent; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; }}"
            f"QPushButton {{ background: {t['accent']}; color: {t['on_accent']}; "
            f"border: none; border-radius: {scaled_px(4)}px; padding: 6px 16px; }}"
            f"QPushButton:hover {{ background: {hover}; }}"
            f"QScrollBar:vertical {{ background: {t['scrollbar_track']}; width: 8px; }}"
            f"QScrollBar::handle:vertical {{ background: {t['scrollbar_thumb']}; "
            f"border-radius: {scaled_px(4)}px; min-height: 20px; }}"
            f"QPushButton[objectName^=\"__td_secondary_\"] {{ "
            f"background: {t['panel']}; color: {t['heading']}; "
            f"border: 1px solid {t['border']}; border-radius: {scaled_px(6)}px; padding: 8px 16px; }}"
            f"QPushButton[objectName^=\"__td_secondary_\"]:hover {{ "
            f"background: {hover}; }}"
            f"QPushButton[objectName^=\"__td_primary_\"] {{ "
            f"background: {t['accent']}; color: {t['on_accent']}; "
            f"border: none; border-radius: {scaled_px(6)}px; padding: 8px 16px; font-weight: bold; }}"
            f"QPushButton[objectName^=\"__td_primary_\"]:hover {{ "
            f"background: {alpha(t['accent'], 0.85)}; }}"
        )

    def _tab_qss(self) -> str:
        t = self._t
        return (
            f"QTabWidget::pane {{ border: 1px solid {t['border']}; "
            f"border-radius: {scaled_px(6)}px; background: {t['panel']}; }}"
            f"QTabBar::tab {{ background: {t['base']}; color: {t['muted']}; "
            f"border: 1px solid {t['border']}; padding: 8px 16px; margin-right: 2px; "
            f"border-top-left-radius: {scaled_px(6)}px; border-top-right-radius: {scaled_px(6)}px; }}"
            f"QTabBar::tab:selected {{ background: {t['panel']}; color: {t['heading']}; "
            f"border-bottom-color: {t['panel']}; }}"
            f"QTabBar::tab:hover:!selected {{ background: {alpha(t['hover_overlay'], 0.13)}; color: {t['body']}; }}"
        )

    # ── Tabbed layout (used by subclasses with _setup_tabs) ───

    def _setup_tabbed_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(scaled_px(12), scaled_px(12), scaled_px(12), scaled_px(12))
        root.setSpacing(scaled_px(10))

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(self._tab_qss())
        self._setup_tabs()
        root.addWidget(self._tabs)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        apply_btn = btn_box.addButton(tr("dialog.apply"), QDialogButtonBox.ButtonRole.ApplyRole)
        apply_btn.clicked.connect(self._on_apply)
        apply_btn.clicked.connect(self.settings_changed.emit)
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        for btn in btn_box.buttons():
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        root.addWidget(btn_box)

        self._set_default_tab_order(btn_box)

    def _set_default_tab_order(self, btn_box):
        """Set tab order: tab widget → OK → Apply → Cancel."""
        ok_btn = btn_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = btn_box.button(QDialogButtonBox.StandardButton.Cancel)
        apply_btn = btn_box.button(QDialogButtonBox.ButtonRole.ApplyRole)
        if ok_btn:
            self.setTabOrder(self._tabs, ok_btn)
        if apply_btn and ok_btn:
            self.setTabOrder(ok_btn, apply_btn)
        if cancel_btn and apply_btn:
            self.setTabOrder(apply_btn, cancel_btn)

    def _setup_tabs(self):
        pass

    def _add_tab(self, widget, label, scrollable=False):
        widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        if scrollable:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.viewport().setAutoFillBackground(True)
            self._apply_viewport_color(scroll)
            scroll.setWidget(widget)
            widget.setAutoFillBackground(False)
            self._tabs.addTab(scroll, label)
        else:
            self._tabs.addTab(widget, label)

    def _apply_viewport_color(self, scroll):
        pal = scroll.viewport().palette()
        pal.setColor(scroll.viewport().backgroundRole(), QColor(self._t["panel"]))
        scroll.viewport().setPalette(pal)

    # ── Single-page layout (used by subclasses without _setup_tabs) ─

    def _build_ui(self):
        pass

    # ── Apply / Accept ────────────────────────────────────────

    def _on_apply(self):
        pass

    def _on_accept(self):
        self._on_apply()
        self.accept()

    # ── Widget Factories ─────────────────────────────────────

    def make_label(self, text):
        return QLabel(text)

    def make_heading(self, text):
        label = QLabel(text)
        t = self._t
        label.setStyleSheet(
            f"QLabel {{ color: {t['heading']}; font-weight: bold; background: transparent; }}")
        self._heading_labels.append(label)
        return label

    def make_muted(self, text):
        label = QLabel(text)
        t = self._t
        from AssetsManager.core.ui_scale import scaled_pt
        label.setStyleSheet(
            f"QLabel {{ color: {t['muted']}; font-size: {scaled_pt(11)}px; background: transparent; }}")
        self._muted_labels.append(label)
        return label

    def make_input(self, placeholder="", text=""):
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        if text:
            edit.setText(text)
        return edit

    def make_spinbox(self, min_val=0, max_val=100, value=0):
        sb = QSpinBox()
        sb.setRange(min_val, max_val)
        sb.setValue(value)
        return sb

    def make_checkbox(self, text, checked=False):
        chk = QCheckBox(text)
        chk.setChecked(checked)
        return chk

    def make_combobox(self, items):
        combo = QComboBox()
        combo.addItems(items)
        return combo

    def make_groupbox(self, title):
        return QGroupBox(title)

    @classmethod
    def _next_id(cls) -> int:
        cls._ID_SEQ += 1
        return cls._ID_SEQ

    def make_primary_btn(self, text, callback=None):
        btn = QPushButton(text)
        btn.setObjectName(f"__td_primary_{self._next_id()}")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if callback:
            btn.clicked.connect(callback)
        return btn

    def make_secondary_btn(self, text, callback=None):
        btn = QPushButton(text)
        btn.setObjectName(f"__td_secondary_{self._next_id()}")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if callback:
            btn.clicked.connect(callback)
        return btn

    @staticmethod
    def make_gear_btn(callback) -> QPushButton:
        from AssetsManager.core.ui_scale import scaled_px, scaled_pt
        t = themes.get()
        btn = QPushButton("⚙")
        btn.setToolTip(tr("panel.settings"))
        btn.setFixedSize(scaled_px(20), scaled_px(20))
        btn.setFlat(True)
        btn.setStyleSheet(
            f"color: {t['heading']}; font-size: {scaled_pt(13)}px; font-weight: bold; "
            f"padding: 0; background: transparent; border: none; border-radius: {scaled_px(3)}px;")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if callback:
            btn.clicked.connect(callback)
        return btn

    def make_labeled_row(self, label_text, widget):
        row = QHBoxLayout()
        row.addWidget(self.make_label(label_text))
        row.addWidget(widget)
        return row

    def make_browse_row(self, label_text, placeholder="", callback=None):
        from AssetsManager.core.ui_scale import scaled_px
        row = QHBoxLayout()
        row.addWidget(self.make_label(label_text))
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        row.addWidget(edit)
        btn = self.make_secondary_btn(tr("dialog.browse"), callback)
        btn.setFixedWidth(scaled_px(60))
        row.addWidget(btn)
        return row, edit

    def make_collapsible(self, title):
        section = _CollapsibleSection(title)
        return section, section.content_layout()

    def make_radio_group(self, title, options, current, on_changed=None):
        from PySide6.QtWidgets import QButtonGroup as _BtnGrp
        from AssetsManager.core.ui_scale import scaled_px
        group = self.make_groupbox(title)
        gl = QVBoxLayout(group)
        gl.setSpacing(scaled_px(2))
        gl.setContentsMargins(scaled_px(12), scaled_px(16), scaled_px(12), scaled_px(8))
        btn_group = _BtnGrp(self)
        for key, label in options.items():
            rb = QRadioButton(label)
            rb.setMinimumHeight(scaled_px(24))
            rb.setProperty("option_key", key)
            if key == current:
                rb.setChecked(True)
            btn_group.addButton(rb)
            gl.addWidget(rb)
        gl.addStretch()
        if on_changed:
            btn_group.buttonClicked.connect(
                lambda btn: on_changed(btn.property("option_key")))
        return group, btn_group

    # ── Style helpers (used by SharingSettingsDialog) ──────────

    def primary_btn_style(self):
        t = self._t
        return (f"QPushButton {{ background: {t['accent']}; color: {t['on_accent']}; border: none; "
                f"border-radius: {scaled_px(6)}px; padding: 8px 16px; font-size: {scaled_pt(13)}px; font-weight: bold; }}"
                f"QPushButton:hover {{ background: {alpha(t['accent'], 0.85)}; }}")

    def status_style(self, active):
        t = self._t
        c = t["accent"] if active else t["panel"]
        return (f"QFrame {{ background: {alpha(c, 0.13)}; border: 1px solid {alpha(c, 0.38)}; "
                f"border-radius: {scaled_px(6)}px; padding: 8px; }}")

    def toggle_btn_style(self, active):
        t = self._t
        if active:
            return (f"QPushButton {{ background: {t['danger']}; color: {t['on_accent']}; border: none; "
                    f"border-radius: {scaled_px(6)}px; padding: 8px 16px; font-size: {scaled_pt(13)}px; font-weight: bold; }}"
                    f"QPushButton:hover {{ background: {alpha(t['danger'], 0.87)}; }}")
        else:
            return (f"QPushButton {{ background: {t['accent']}; color: {t['on_accent']}; border: none; "
                    f"border-radius: {scaled_px(6)}px; padding: 8px 16px; font-size: {scaled_pt(13)}px; font-weight: bold; }}"
                    f"QPushButton:hover {{ background: {alpha(t['accent'], 0.85)}; }}")
