import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from AssetsManager.core.settings import AppSettings
from AssetsManager.dialogs.tabbed_dialog import TabbedDialog
from AssetsManager.widgets.elevation import apply_elevation


class _VisualDialog(TabbedDialog):
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Visual test"))


class _TabbedVisualDialog(TabbedDialog):
    def _setup_tabs(self):
        self._add_tab(QWidget(), "General")


def _render_bytes(widget: QWidget, app: QApplication) -> bytes:
    widget.show()
    app.processEvents()
    image = widget.grab().toImage()
    return bytes(image.constBits()[:image.sizeInBytes()])


def _qss_rule(qss: str, selector: str) -> str:
    start = qss.index(f"{selector} {{")
    end = qss.index("}", start)
    return qss[start:end + 1]


def test_dialog_fade_respects_reduce_motion_setting():
    app = QApplication.instance() or QApplication([])
    settings = AppSettings.instance()
    original = settings.get("reduce_motion", False)
    settings.set("reduce_motion", True)
    dialog = _VisualDialog(min_size=(240, 120))
    try:
        dialog.show()
        app.processEvents()
        assert dialog.windowOpacity() == 1.0
        assert dialog._dialog_fade_anim is None
    finally:
        settings.set("reduce_motion", original)
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_elevation_reuses_existing_graphics_effect():
    app = QApplication.instance() or QApplication([])
    from PySide6.QtWidgets import QWidget

    widget = QWidget()
    try:
        first = apply_elevation(widget, level=1)
        second = apply_elevation(widget, level=2)
        assert first is second
        assert widget.graphicsEffect() is first
        assert second.blurRadius() > 0
    finally:
        widget.deleteLater()
        app.processEvents()


# ── Dialog QSS coverage tests ──────────────────────────────────


def test_dialog_qss_includes_checkbox_indicator():
    """_dialog_qss() styles QCheckBox::indicator for checked/unchecked."""
    dialog = _VisualDialog(min_size=(240, 120))
    try:
        qss = dialog._dialog_qss()
        assert "QCheckBox::indicator:checked" in qss
        assert "QCheckBox::indicator:unchecked" in qss
        assert "QCheckBox::indicator:hover" in qss
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dialog_qss_includes_tooltip():
    """_dialog_qss() styles QToolTip with theme tokens."""
    dialog = _VisualDialog(min_size=(240, 120))
    try:
        qss = dialog._dialog_qss()
        assert "QToolTip" in qss
        # Tooltip bg should be a hex color (resolved from tooltip_bg token)
        assert "QToolTip {" in qss or "QToolTip{" in qss
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dialog_qss_includes_double_spinbox():
    """_dialog_qss() styles QDoubleSpinBox alongside QSpinBox."""
    dialog = _VisualDialog(min_size=(240, 120))
    try:
        qss = dialog._dialog_qss()
        assert "QDoubleSpinBox" in qss
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dialog_qss_uses_qt_supported_focus_state():
    """Qt QSS supports :focus, not the web-only :focus-visible state."""
    dialog = _VisualDialog(min_size=(240, 120))
    try:
        qss = dialog._dialog_qss()
        assert ":focus" in qss
        assert "focus-visible" not in qss
    finally:
        dialog.close()
        dialog.deleteLater()


def test_status_style_uses_active_and_inactive_theme_colors():
    dialog = _VisualDialog(min_size=(240, 120))
    try:
        active = dialog.status_style(True)
        inactive = dialog.status_style(False)
        assert dialog._sk._alpha("accent", 0.13) in active
        assert dialog._sk._alpha("muted", 0.13) in inactive
        assert active != inactive
    finally:
        dialog.close()
        dialog.deleteLater()


def test_button_box_has_explicit_semantic_variants():
    dialog = _TabbedVisualDialog(min_size=(240, 120))
    try:
        ok_btn = dialog._button_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = dialog._button_box.button(QDialogButtonBox.StandardButton.Cancel)
        assert ok_btn.property("buttonVariant") == "primary"
        assert dialog._apply_btn.property("buttonVariant") == "secondary"
        assert cancel_btn.property("buttonVariant") == "ghost"
    finally:
        dialog.close()
        dialog.deleteLater()


def test_custom_apply_button_participates_in_default_tab_order():
    dialog = _TabbedVisualDialog(min_size=(240, 120))
    try:
        app = QApplication.instance() or QApplication([])
        ok_btn = dialog._button_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = dialog._button_box.button(QDialogButtonBox.StandardButton.Cancel)
        assert dialog._button_box.button(QDialogButtonBox.StandardButton.Apply) is None
        dialog.show()
        ok_btn.setFocus(Qt.FocusReason.TabFocusReason)
        app.processEvents()
        assert app.focusWidget() is ok_btn
        QTest.keyClick(ok_btn, Qt.Key.Key_Tab)
        assert app.focusWidget() is dialog._apply_btn
        QTest.keyClick(dialog._apply_btn, Qt.Key.Key_Tab)
        assert app.focusWidget() is cancel_btn
    finally:
        dialog.close()
        dialog.deleteLater()


def test_local_dialog_buttons_render_visible_keyboard_focus():
    app = QApplication.instance() or QApplication([])
    dialog = _VisualDialog(min_size=(320, 180))
    section, _content = dialog.make_collapsible("Advanced")
    gear = dialog.make_gear_btn(lambda: None)
    dialog.layout().addWidget(section)
    dialog.layout().addWidget(gear)
    try:
        dialog.show()
        app.processEvents()
        for button in (section._header, gear):
            button.clearFocus()
            app.processEvents()
            normal = _render_bytes(button, app)
            dialog.activateWindow()
            button.setFocus(Qt.FocusReason.TabFocusReason)
            app.processEvents()
            assert button.hasFocus()
            assert _render_bytes(button, app) != normal
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_done_invokes_dialog_closed_hook():
    """done() must fire the _on_dialog_closed hook on accept/reject paths."""
    QApplication.instance() or QApplication([])
    calls = []
    dialog = _VisualDialog(min_size=(240, 120))
    dialog._on_dialog_closed = lambda: calls.append("closed")

    dialog.done(0)

    assert calls == ["closed"]


def test_close_event_invokes_dialog_closed_hook():
    """Window close must also fire the _on_dialog_closed hook.

    QDialog close() runs closeEvent and then reject()/done(), so the hook may
    fire more than once; the hook contract requires idempotence.
    """
    app = QApplication.instance() or QApplication([])
    calls = []
    dialog = _VisualDialog(min_size=(240, 120))
    dialog._on_dialog_closed = lambda: calls.append("closed")
    dialog.show()
    app.processEvents()

    dialog.close()

    assert calls.count("closed") >= 1
    dialog.deleteLater()
    app.processEvents()


# ── Heading accent + Slider theme tests ────────────────────────


def test_make_heading_has_accent_border():
    """make_heading() labels include accent-colored bottom border."""
    dialog = _VisualDialog(min_size=(240, 120))
    try:
        heading = dialog.make_heading("Test Section")
        ss = heading.styleSheet()
        assert "border-bottom" in ss
        # accent color is resolved to rgba() at runtime
        assert "rgba(" in ss
        assert "padding-bottom" in ss
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dialog_qss_includes_slider():
    """_dialog_qss() styles QSlider with theme tokens."""
    dialog = _VisualDialog(min_size=(240, 120))
    try:
        qss = dialog._dialog_qss()
        assert "QSlider::groove:horizontal" in qss
        assert "QSlider::handle:horizontal" in qss
        assert "QSlider::sub-page:horizontal" in qss
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dialog_qss_slider_uses_theme_accent():
    """Slider handle uses the current theme's accent color."""
    dialog = _VisualDialog(min_size=(240, 120))
    try:
        t = dialog._t
        qss = dialog._dialog_qss()
        assert t["accent"] in _qss_rule(qss, "QSlider::handle:horizontal")
        assert t["accent"] in _qss_rule(qss, "QSlider::sub-page:horizontal")
    finally:
        dialog.close()
        dialog.deleteLater()
