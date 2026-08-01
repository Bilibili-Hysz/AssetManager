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
from PySide6.QtCore import Qt, Signal, QSize, QPropertyAnimation, QEasingCurve
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
from AssetsManager.core.settings import AppSettings
from AssetsManager.core import icons

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
        self._header.setAccessibleName(self._title)
        self._header.setToolTip(self._title)
        self._update_header_presentation()
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
        self._update_header_presentation()
        self._apply_header_style()

    def refresh_scaled_geometry(self):
        self._header.setFixedHeight(scaled_px(28))
        self._header.setIconSize(QSize(scaled_px(14), scaled_px(14)))
        self._content_layout.setContentsMargins(
            scaled_px(8), scaled_px(4), 0, scaled_px(4))
        self._content_layout.setSpacing(scaled_px(6))
        self._apply_header_style()

    def _update_header_presentation(self):
        t = themes.get()
        icon_name = "chevron_down" if self._expanded else "chevron_right"
        self._header.setText(self._title)
        self._header.setIcon(
            icons.icon(icon_name, color=t["heading"], size=scaled_px(14)))
        self._header.setIconSize(QSize(scaled_px(14), scaled_px(14)))
        self._header.setAccessibleName(self._title)
        self._header.setToolTip(self._title)

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
        self._update_header_presentation()
        self._apply_header_style()


class TabbedDialog(QDialog):
    """Unified theme template — handles QSS, tabs, buttons, and theme refresh."""

    settings_changed = Signal()
    _ID_SEQ = 0
    supports_runtime_refresh = False

    def __init__(self, parent=None, title="Dialog", min_size=(360, 400)):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(*min_size)
        self.resize(*min_size)
        self._t = themes.get()
        self._bus_connected = False
        self._refresh_bus_connected = False
        self._heading_labels: list[QLabel] = []
        self._muted_labels: list[QLabel] = []
        self._tab_label_keys: dict[int, str] = {}
        self._dialog_fade_anim: QPropertyAnimation | None = None

        if hasattr(self, '_setup_tabs') and type(self)._setup_tabs is not TabbedDialog._setup_tabs:
            # Subclass uses tabbed layout
            self.setStyleSheet(self._dialog_qss())
            self._setup_tabbed_ui()
        else:
            # Subclass uses single-page layout (_build_ui)
            self._build_ui()

    def showEvent(self, event):
        super().showEvent(event)
        self._start_dialog_fade()
        if not self._bus_connected:
            self._bus_connected = True
            from AssetsManager.core.signal_bus import get as bus
            bus().theme_changed.connect(self._on_theme_changed)
            if self.supports_runtime_refresh:
                bus().language_changed.connect(self._on_language_changed)
                bus().ui_scale_changed.connect(self._on_ui_scale_changed)
                self._refresh_bus_connected = True

    def closeEvent(self, event):
        self._stop_dialog_fade()
        self._disconnect_bus()
        super().closeEvent(event)

    def done(self, result):
        # accept()/reject() hide modal dialogs without necessarily closing them.
        self._stop_dialog_fade()
        self._disconnect_bus()
        super().done(result)

    def _disconnect_bus(self):
        if not self._bus_connected:
            return
        from AssetsManager.core.signal_bus import get as bus
        try:
            bus().theme_changed.disconnect(self._on_theme_changed)
            if self._refresh_bus_connected:
                bus().language_changed.disconnect(self._on_language_changed)
                bus().ui_scale_changed.disconnect(self._on_ui_scale_changed)
        except (RuntimeError, TypeError):
            pass
        self._bus_connected = False
        self._refresh_bus_connected = False

    # ── Theme ─────────────────────────────────────────────────

    @staticmethod
    def _reduce_motion() -> bool:
        try:
            return bool(AppSettings.instance().get("reduce_motion", False))
        except Exception:
            return False

    def _stop_dialog_fade(self):
        if self._dialog_fade_anim is not None:
            self._dialog_fade_anim.stop()
            self._dialog_fade_anim = None
        self.setWindowOpacity(1.0)

    def _start_dialog_fade(self):
        self._stop_dialog_fade()
        if self._reduce_motion():
            return
        self.setWindowOpacity(0.0)
        animation = QPropertyAnimation(self, b"windowOpacity", self)
        animation.setDuration(150)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda: self.setWindowOpacity(1.0))
        animation.start()
        self._dialog_fade_anim = animation

    def _on_theme_changed(self, _name):
        self._t = themes.get()
        self.setStyleSheet(self._dialog_qss())
        if hasattr(self, '_tabs'):
            self._tabs.setStyleSheet(self._tab_qss())
        self._refresh_static_labels()
        for section in self.findChildren(_CollapsibleSection):
            section.refresh_theme()
        self._refresh_semantic_button_icons()
        for scroll_area in self.findChildren(QScrollArea):
            self._apply_viewport_color(scroll_area)

    def _on_language_changed(self, _code: str):
        if hasattr(self, "_button_box"):
            ok_btn = self._button_box.button(QDialogButtonBox.StandardButton.Ok)
            cancel_btn = self._button_box.button(QDialogButtonBox.StandardButton.Cancel)
            if ok_btn:
                ok_btn.setText(tr("dialog.ok"))
            if cancel_btn:
                cancel_btn.setText(tr("dialog.cancel"))
            if hasattr(self, "_apply_btn"):
                self._apply_btn.setText(tr("dialog.apply"))
        if hasattr(self, "_tabs"):
            for index, key in self._tab_label_keys.items():
                self._tabs.setTabText(index, tr(key))
        self.retranslate_ui()

    def _on_ui_scale_changed(self, _scale: float):
        self._on_theme_changed("")
        for section in self.findChildren(_CollapsibleSection):
            section.refresh_scaled_geometry()
        self._refresh_semantic_button_icons()
        if hasattr(self, "_tabs") and hasattr(self, "_root_layout"):
            self._root_layout.setContentsMargins(
                scaled_px(12), scaled_px(12), scaled_px(12), scaled_px(12))
            self._root_layout.setSpacing(scaled_px(10))
        self.refresh_scaled_geometry(_scale)
        layout = self.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()

    def retranslate_ui(self):
        """Refresh subclass-owned visible text without reconstructing controls."""

    def refresh_scaled_geometry(self, _scale: float | None = None):
        """Refresh subclass-owned scaled constraints without changing dialog state."""

    def _refresh_semantic_button_icons(self):
        t = self._t
        for button in self.findChildren(QPushButton):
            icon_name = button.property("semanticIcon")
            if not icon_name:
                continue
            color_name = str(button.property("semanticIconColor") or "heading")
            color = t.get(color_name, t["heading"])
            button.setIcon(icons.icon(str(icon_name), color=color, size=scaled_px(15)))
            button.setIconSize(QSize(scaled_px(15), scaled_px(15)))

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
            f"QListWidget {{ background: {t['input_bg']}; color: {t['input_text']}; "
            f"border: 1px solid {t['border']}; border-radius: {scaled_px(4)}px; "
            f"padding: {scaled_px(2)}px; }}"
            f"QListWidget::item {{ padding: {scaled_px(5)}px {scaled_px(6)}px; "
            f"border-radius: {scaled_px(3)}px; }}"
            f"QListWidget::item:hover {{ background: {hover}; }}"
            f"QListWidget::item:selected {{ background: {alpha(t['accent'], 0.25)}; "
            f"color: {t['heading']}; }}"
            f"QProgressBar {{ background: {t['input_bg']}; color: {t['body']}; "
            f"border: 1px solid {t['border']}; border-radius: {scaled_px(3)}px; "
            f"text-align: center; }}"
            f"QProgressBar::chunk {{ background: {t['accent']}; "
            f"border-radius: {scaled_px(2)}px; }}"
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
            f"QPushButton:focus {{ border: 1px solid {t['border_focus']}; }}"
            f"QPushButton[buttonVariant=\"primary\"] {{ "
            f"background: {t['accent']}; color: {t['on_accent']}; }}"
            f"QPushButton[buttonVariant=\"primary\"]:hover {{ "
            f"background: {alpha(t['accent'], 0.85)}; }}"
            f"QPushButton[buttonVariant=\"secondary\"] {{ "
            f"background: {t['panel']}; color: {t['heading']}; "
            f"border: 1px solid {t['border']}; }}"
            f"QPushButton[buttonVariant=\"secondary\"]:hover {{ "
            f"background: {hover}; }}"
            f"QPushButton[buttonVariant=\"ghost\"] {{ "
            f"background: transparent; color: {t['body']}; "
            f"border: 1px solid transparent; }}"
            f"QPushButton[buttonVariant=\"ghost\"]:hover {{ "
            f"background: {hover}; color: {t['heading']}; }}"
            f"QPushButton[buttonVariant=\"danger\"] {{ "
            f"background: {t['danger']}; color: {t['on_accent']}; }}"
            f"QPushButton[buttonVariant=\"danger\"]:hover {{ "
            f"background: {alpha(t['danger'], 0.85)}; }}"
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
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(scaled_px(12), scaled_px(12), scaled_px(12), scaled_px(12))
        self._root_layout.setSpacing(scaled_px(10))

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(self._tab_qss())
        self._setup_tabs()
        self._root_layout.addWidget(self._tabs)

        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self._apply_btn = self._button_box.addButton(tr("dialog.apply"), QDialogButtonBox.ButtonRole.ApplyRole)
        self._apply_btn.clicked.connect(self._on_apply)
        self._apply_btn.clicked.connect(self.settings_changed.emit)
        self._button_box.accepted.connect(self._on_accept)
        self._button_box.rejected.connect(self.reject)
        for btn in self._button_box.buttons():
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._root_layout.addWidget(self._button_box)

        self._set_default_tab_order(self._button_box)

    def _set_default_tab_order(self, btn_box):
        """Set tab order: tab widget → OK → Apply → Cancel."""
        ok_btn = btn_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = btn_box.button(QDialogButtonBox.StandardButton.Cancel)
        apply_btn = btn_box.button(QDialogButtonBox.StandardButton.Apply)
        if ok_btn:
            self.setTabOrder(self._tabs, ok_btn)
        if apply_btn and ok_btn:
            self.setTabOrder(ok_btn, apply_btn)
        if cancel_btn and apply_btn:
            self.setTabOrder(apply_btn, cancel_btn)
        elif cancel_btn and ok_btn:
            self.setTabOrder(ok_btn, cancel_btn)

    def _setup_tabs(self):
        pass

    def _add_tab(self, widget, label, scrollable=False, label_key: str | None = None):
        widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        if scrollable:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.viewport().setAutoFillBackground(True)
            self._apply_viewport_color(scroll)
            scroll.setWidget(widget)
            widget.setAutoFillBackground(False)
            index = self._tabs.addTab(scroll, label)
        else:
            index = self._tabs.addTab(widget, label)
        if label_key is not None:
            self._tab_label_keys[index] = label_key

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
        themes.set_button_variant(btn, "primary")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if callback:
            btn.clicked.connect(callback)
        return btn

    def make_secondary_btn(self, text, callback=None):
        btn = QPushButton(text)
        btn.setObjectName(f"__td_secondary_{self._next_id()}")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        themes.set_button_variant(btn, "secondary")
        if callback:
            btn.clicked.connect(callback)
        return btn

    @staticmethod
    def make_gear_btn(callback) -> QPushButton:
        t = themes.get()
        btn = QPushButton()
        btn.setIcon(icons.icon("settings", color=t['heading'], size=scaled_px(16)))
        btn.setIconSize(QSize(scaled_px(16), scaled_px(16)))
        btn.setToolTip(tr("panel.settings"))
        btn.setAccessibleName(tr("panel.settings"))
        btn.setFixedSize(scaled_px(20), scaled_px(20))
        btn.setFlat(True)
        themes.set_button_variant(btn, "ghost")
        btn.setStyleSheet(
            f"color: {t['heading']}; padding: 0; background: transparent; "
            f"border: none; border-radius: {scaled_px(3)}px;")
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
        btn.setProperty("semanticIcon", "folder")
        btn.setProperty("semanticIconColor", "heading")
        btn.setIcon(icons.icon("folder", color=self._t["heading"], size=scaled_px(15)))
        btn.setIconSize(QSize(scaled_px(15), scaled_px(15)))
        btn.setAccessibleName(f"{label_text}: {tr('dialog.browse')}")
        btn.setToolTip(tr("dialog.browse"))
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

    @staticmethod
    def refresh_radio_group_geometry(group: QGroupBox):
        layout = group.layout()
        if layout is None:
            return
        layout.setSpacing(scaled_px(2))
        layout.setContentsMargins(scaled_px(12), scaled_px(16), scaled_px(12), scaled_px(8))

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
