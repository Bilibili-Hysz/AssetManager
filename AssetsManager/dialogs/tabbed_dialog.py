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
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal, QSize, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QSpinBox, QCheckBox, QGroupBox, QComboBox, QFrame,
    QDialogButtonBox, QTabWidget, QScrollArea, QRadioButton, QWidget,
)
from AssetsManager import i18n
from AssetsManager.core.color_utils import alpha
from AssetsManager.core import themes
from AssetsManager.core.settings import AppSettings
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.core import icons
from AssetsManager.widgets.stylekit import StyleKit

tr = i18n.tr
_log = logging.getLogger(__name__)


class _DialogButtonBar(QWidget):
    """Manual dialog button bar with a fixed, cross-platform visual order.

    QDialogButtonBox delegates button ordering to the platform theme: on
    Windows the primary button lands leftmost, while StandardModalDialog
    (hand-built in modal_dialog.py) puts it rightmost — two muscle memories
    in one app.  This bar mirrors StandardModalDialog's order
    (stretch | Cancel | Apply | OK) and reimplements the small
    QDialogButtonBox surface TabbedDialog relies on (button / buttons /
    addButton / buttonRole / accepted / rejected).
    """

    accepted = Signal()
    rejected = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ok_btn = QPushButton(tr("dialog.ok"), self)
        self._cancel_btn = QPushButton(tr("dialog.cancel"), self)
        self._apply_btn: QPushButton | None = None
        self._ok_btn.setDefault(True)
        self._ok_btn.clicked.connect(self.accepted)
        self._cancel_btn.clicked.connect(self.rejected)
        bar = QHBoxLayout(self)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(scaled_px(8))
        bar.addStretch()
        bar.addWidget(self._cancel_btn)
        self._insert_index = bar.count()  # between Cancel and OK
        bar.addWidget(self._ok_btn)

    def addButton(self, text: str, role: QDialogButtonBox.ButtonRole) -> QPushButton:
        """Add a custom button; TabbedDialog only ever adds Apply."""
        btn = QPushButton(text, self)
        self.layout().insertWidget(self._insert_index, btn)
        self._insert_index += 1
        self._apply_btn = btn
        return btn

    def button(self, standard: QDialogButtonBox.StandardButton) -> QPushButton | None:
        if standard == QDialogButtonBox.StandardButton.Ok:
            return self._ok_btn
        if standard == QDialogButtonBox.StandardButton.Cancel:
            return self._cancel_btn
        return None

    def buttons(self) -> list[QPushButton]:
        btns = [self._ok_btn, self._cancel_btn]
        if self._apply_btn is not None:
            btns.append(self._apply_btn)
        return btns

    def buttonRole(self, btn: QPushButton) -> QDialogButtonBox.ButtonRole:
        if btn is self._ok_btn:
            return QDialogButtonBox.ButtonRole.AcceptRole
        if btn is self._cancel_btn:
            return QDialogButtonBox.ButtonRole.RejectRole
        return QDialogButtonBox.ButtonRole.ApplyRole


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
        self._sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        self._bus_connected = False
        self._refresh_bus_connected = False
        self._heading_labels: list[QLabel] = []
        self._muted_labels: list[QLabel] = []
        self._tab_label_keys: dict[int, str] = {}
        self._dialog_fade_anim: QPropertyAnimation | None = None
        self._geometry_restored = False

        # Single contract: dialog chrome QSS applies to EVERY subclass,
        # tabbed or single-page (audit D5 — the _build_ui branch used to rely
        # on each subclass remembering to apply it; ShareQrDialog forgot).
        self.setStyleSheet(self._dialog_qss())
        if hasattr(self, '_setup_tabs') and type(self)._setup_tabs is not TabbedDialog._setup_tabs:
            # Subclass uses tabbed layout
            self._setup_tabbed_ui()
        else:
            # Subclass uses single-page layout (_build_ui)
            self._build_ui()

    def showEvent(self, event):
        super().showEvent(event)
        # Restore the geometry saved by the last closed dialog of the same
        # identity once per instance.  Subclass default sizes applied after
        # super().__init__ (e.g. SharingSettingsDialog.resize) stay in force
        # when there is no archive; restoring here (not in __init__) keeps
        # that default until the dialog is actually presented.
        if not self._geometry_restored:
            self._geometry_restored = True
            self._restore_saved_geometry()
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
        self._save_dialog_geometry()
        self._disconnect_bus()
        self._on_dialog_closed()
        super().closeEvent(event)

    def done(self, result):
        # accept()/reject() hide modal dialogs without necessarily closing them.
        self._stop_dialog_fade()
        self._save_dialog_geometry()
        self._disconnect_bus()
        self._on_dialog_closed()
        super().done(result)

    def _on_dialog_closed(self):
        """Dismissal hook invoked on every close path (window close and
        accept()/reject()/done()). Subclasses stop timers, cancel background
        workers, and detach callbacks here once the dialog is no longer
        visible. Idempotence is the subclass's responsibility; no-op by
        default.
        """

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

    # ── Geometry persistence ─────────────────────────────────

    def _geometry_settings_key(self) -> str:
        """Settings key for this dialog identity (objectName, else class name)."""
        identity = self.objectName() or type(self).__name__
        return f"dialog_geometry_{identity}"

    def _restore_saved_geometry(self) -> None:
        """Restore the geometry saved by the last close of a same-identity
        dialog.  Without an archive the constructor's ``min_size`` resize
        (and any subclass default resize) stands.  Malformed persisted data
        is ignored so a hand-edited settings file cannot break the dialog.
        """
        try:
            geom = AppSettings.instance().get(self._geometry_settings_key())
            if isinstance(geom, str) and geom:
                self.restoreGeometry(bytes.fromhex(geom))
        except (TypeError, ValueError):
            _log.warning(
                "Ignoring malformed saved geometry for %s", self._geometry_settings_key(),
                exc_info=True)
        except Exception:
            _log.exception("Failed to restore dialog geometry")

    def _save_dialog_geometry(self) -> None:
        """Persist the current geometry for the next dialog of this identity.

        Called on every dismissal path (window close and accept/reject/done);
        redundant calls persist the same geometry, so they are harmless.
        """
        try:
            settings = AppSettings.instance()
            settings.set(
                self._geometry_settings_key(),
                bytes(self.saveGeometry().data()).hex())
            settings.save()
        except Exception:
            _log.exception("Failed to save dialog geometry")

    # ── Theme ─────────────────────────────────────────────────

    def _stop_dialog_fade(self):
        if self._dialog_fade_anim is not None:
            self._dialog_fade_anim.stop()
            self._dialog_fade_anim = None
        self.setWindowOpacity(1.0)

    def _start_dialog_fade(self):
        self._stop_dialog_fade()
        if StyleKit.reduce_motion():
            return
        self.setWindowOpacity(0.0)
        animation = QPropertyAnimation(self, b"windowOpacity", self)
        animation.setDuration(themes.motion("fast"))
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda: self.setWindowOpacity(1.0))
        animation.start()
        self._dialog_fade_anim = animation

    def _on_theme_changed(self, _name):
        self._t = themes.get()
        self._sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        self.setStyleSheet(self._dialog_qss())
        if hasattr(self, '_tabs'):
            self._tabs.setStyleSheet(self._tab_qss())
        self._refresh_static_labels()
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
            button.setIcon(icons.icon(str(icon_name), color=color, size=scaled_px(themes.metrics("icon_sm"))))
            button.setIconSize(QSize(scaled_px(themes.metrics("icon_sm")), scaled_px(themes.metrics("icon_sm"))))

    def _refresh_static_labels(self):
        sk = self._sk
        for label in self._heading_labels:
            label.setStyleSheet(sk.heading_css())
        for label in self._muted_labels:
            label.setStyleSheet(sk.muted_css())

    def _dialog_qss(self) -> str:
        """Single QSS string for the entire dialog. Cascades to all children."""
        return self._sk.dialog_css()

    def _tab_qss(self) -> str:
        return self._sk.tab_css()

    # ── Tabbed layout (used by subclasses with _setup_tabs) ───

    def _setup_tabbed_ui(self):
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(scaled_px(12), scaled_px(12), scaled_px(12), scaled_px(12))
        self._root_layout.setSpacing(scaled_px(10))

        self._tabs = self._create_tab_container()
        self._tabs.setStyleSheet(self._tab_qss())
        self._setup_tabs()
        self._root_layout.addWidget(self._tabs)

        # Fixed order (stretch | Cancel | Apply | OK) matches StandardModalDialog
        # so both dialog families share one muscle memory
        # (design-language-unification-2026-09-03, P0-5).
        self._button_box = _DialogButtonBar(self)
        self._apply_btn = self._button_box.addButton(tr("dialog.apply"), QDialogButtonBox.ButtonRole.ApplyRole)
        self._apply_btn.clicked.connect(self._on_apply)
        self._apply_btn.clicked.connect(self.settings_changed.emit)
        self._button_box.accepted.connect(self._on_accept)
        self._button_box.rejected.connect(self.reject)
        for btn in self._button_box.buttons():
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn = self._button_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = self._button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_btn:
            themes.set_button_variant(ok_btn, "primary")
        themes.set_button_variant(self._apply_btn, "secondary")
        if cancel_btn:
            themes.set_button_variant(cancel_btn, "ghost")
        self._root_layout.addWidget(self._button_box)

        self._set_default_tab_order(self._button_box)

    def _set_default_tab_order(self, btn_box):
        """Set tab order: tab widget → OK → Apply → Cancel."""
        ok_btn = btn_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = btn_box.button(QDialogButtonBox.StandardButton.Cancel)
        apply_btn = getattr(self, "_apply_btn", None)
        if apply_btn is None or btn_box.buttonRole(apply_btn) != QDialogButtonBox.ButtonRole.ApplyRole:
            apply_btn = next(
                (
                    button
                    for button in btn_box.buttons()
                    if btn_box.buttonRole(button) == QDialogButtonBox.ButtonRole.ApplyRole
                ),
                None,
            )
        if ok_btn:
            self.setTabOrder(self._tabs, ok_btn)
        if apply_btn and ok_btn:
            self.setTabOrder(ok_btn, apply_btn)
        if cancel_btn and apply_btn:
            self.setTabOrder(apply_btn, cancel_btn)
        elif cancel_btn and ok_btn:
            self.setTabOrder(ok_btn, cancel_btn)

    def _create_tab_container(self):
        """Factory hook for the page container.

        Subclasses may return any QWidget implementing the small surface
        TabbedDialog actually uses — ``addTab(widget, label)``,
        ``setTabText(index, text)`` and ``setStyleSheet`` — to swap the
        tab paradigm (e.g. SettingsDialog uses a left-rail shell).
        """
        return QTabWidget()

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
        label.setStyleSheet(self._sk.heading_css())
        self._heading_labels.append(label)
        return label

    def make_muted(self, text):
        label = QLabel(text)
        label.setStyleSheet(self._sk.muted_css())
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
        hover_bg = alpha(t["accent"], 0.13)
        focus_color = t.get("border_focus", t["accent"])
        btn = QPushButton()
        btn.setIcon(icons.icon("settings", color="icon_primary", size=scaled_px(16)))
        btn.setIconSize(QSize(scaled_px(16), scaled_px(16)))
        btn.setToolTip(tr("panel.settings"))
        btn.setAccessibleName(tr("panel.settings"))
        btn.setFixedSize(scaled_px(themes.metrics("hit_area")), scaled_px(themes.metrics("hit_area")))
        btn.setFlat(True)
        btn.setStyleSheet(
            f"QPushButton {{ color: {themes.color('heading')}; padding: 0; background: transparent; "
            f"border: {scaled_px(1)}px solid transparent; "
            f"border-radius: {scaled_px(int(themes.prop('border_radius', 'sm')))}px; }}"
            f"QPushButton:hover {{ background: {hover_bg}; }}"
            f"QPushButton:focus {{ background: {hover_bg}; "
            f"border: {scaled_px(1)}px solid {focus_color}; }}")
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
        btn.setIcon(icons.icon("folder", color="icon_primary", size=scaled_px(themes.metrics("icon_sm"))))
        btn.setIconSize(QSize(scaled_px(themes.metrics("icon_sm")), scaled_px(themes.metrics("icon_sm"))))
        btn.setAccessibleName(f"{label_text}: {tr('dialog.browse')}")
        btn.setToolTip(tr("dialog.browse"))
        btn.setFixedWidth(scaled_px(60))
        row.addWidget(btn)
        return row, edit

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

    def _btn_shape(self, sk):
        """Tokenized geometry shared by the local button style helpers."""
        px, pt = sk.px, sk.pt
        return {
            "radius": px(int(sk.prop("border_radius", "sm", 8))),
            "pad_y": px(int(sk.prop("spacing", "sm", 8))),
            "pad_x": px(int(sk.prop("spacing", "lg", 16))),
            "font": pt(int(sk.prop("font_size", "md", 13))),
        }

    def primary_btn_style(self):
        sk = self._sk
        shape = self._btn_shape(sk)
        focus_color = sk.token('border_focus', sk.token('accent'))
        hover_bg = sk.lighter('accent', 110)
        pressed_bg = sk.darker('accent', 115)
        return (f"QPushButton {{ background: {sk.token('accent')}; color: {sk.token('on_accent')}; "
                f"border: {scaled_px(1)}px solid transparent; "
                f"border-radius: {shape['radius']}px; padding: {shape['pad_y']}px {shape['pad_x']}px; "
                f"font-size: {shape['font']}px; font-weight: bold; }}"
                f"QPushButton:hover {{ background: {hover_bg}; }}"
                f"QPushButton:pressed {{ background: {pressed_bg}; }}"
                f"QPushButton:focus {{ border: {scaled_px(1)}px solid {focus_color}; }}")

    def status_style(self, active):
        sk = self._sk
        px = sk.px
        c = sk.token('accent') if active else sk.token('muted')
        return (f"QFrame {{ background: {sk.alpha(c, 0.13)}; border: {scaled_px(1)}px solid {sk.alpha(c, 0.38)}; "
                f"border-radius: {px(int(sk.prop('border_radius', 'sm', 8)))}px; "
                f"padding: {px(int(sk.prop('spacing', 'sm', 8)))}px; }}")

    def toggle_btn_style(self, active):
        sk = self._sk
        shape = self._btn_shape(sk)
        focus_color = sk.token('border_focus', sk.token('accent'))
        if active:
            base, hover_bg, pressed_bg = (
                sk.token('danger'), sk.lighter('danger', 110), sk.darker('danger', 115))
        else:
            base, hover_bg, pressed_bg = (
                sk.token('accent'), sk.lighter('accent', 110), sk.darker('accent', 115))
        return (f"QPushButton {{ background: {base}; color: {sk.token('on_accent')}; "
                f"border: {scaled_px(1)}px solid transparent; "
                f"border-radius: {shape['radius']}px; padding: {shape['pad_y']}px {shape['pad_x']}px; "
                f"font-size: {shape['font']}px; font-weight: bold; }}"
                f"QPushButton:hover {{ background: {hover_bg}; }}"
                f"QPushButton:pressed {{ background: {pressed_bg}; }}"
                f"QPushButton:focus {{ border: {scaled_px(1)}px solid {focus_color}; }}")
