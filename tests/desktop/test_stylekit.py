"""Tests for StyleKit — the self-contained UI styling toolkit."""


import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QWidget,
)

from AssetsManager.widgets.stylekit import StyleKit, _identity_px, _identity_pt


# ── Fixtures ──────────────────────────────────────────────────

_SAMPLE_THEME = {
    "base": "#12121a", "panel": "#1a1d28", "header": "#242838",
    "border": "#3d4260", "heading": "#e8ecf8", "body": "#b4bcd0",
    "muted": "#6b7394", "accent": "#5b7cf0", "success": "#40b86c",
    "warning": "#e8a838", "danger": "#f06060", "on_accent": "#000000",
    "hover_overlay": "#ffffff", "selected_overlay": "#5b7cf020",
    "border_focus": "#5b7cf0", "input_bg": "#1a1d28", "input_text": "#e8ecf8",
    "scrollbar_track": "#0f1118", "scrollbar_thumb": "#6b7394",
    "scrollbar_thumb_hover": "#8890b0", "disabled_text": "#4a5070",
    "disabled_bg": "#151820", "tooltip_bg": "#242838", "tooltip_text": "#e8ecf8",
    "properties": {
        "opacity": {"hover": 0.15, "focus": 0.10},
        "border_radius": {"sm": 4, "md": 6, "lg": 8},
        "spacing": {"sm": 4, "md": 8, "lg": 12},
    },
}


def _make_sk(**kwargs) -> StyleKit:
    """Create a StyleKit with sample theme and identity scale."""
    return StyleKit(theme=_SAMPLE_THEME, **kwargs)


# ── Token resolution ──────────────────────────────────────────


def test_token_direct_dict():
    sk = _make_sk()
    assert sk.token("accent") == "#5b7cf0"
    assert sk.token("nonexistent", "#fff") == "#fff"
    assert sk.token("nonexistent") == ""


def test_token_callable_theme():
    sk = StyleKit(theme=lambda: _SAMPLE_THEME)
    assert sk.token("accent") == "#5b7cf0"


def test_token_none_theme():
    sk = StyleKit(theme=None)
    assert sk.token("accent", "#fallback") == "#fallback"


def test_prop_nested_lookup():
    sk = _make_sk()
    assert sk.prop("opacity", "hover") == 0.15
    assert sk.prop("border_radius", "md") == 6
    assert sk.prop("nonexistent", "key", 42) == 42


def test_scaling_px():
    sk = StyleKit(theme=_SAMPLE_THEME, px=lambda v: v * 2)
    assert sk.px(10) == 20


def test_scaling_pt():
    sk = StyleKit(theme=_SAMPLE_THEME, pt=lambda v: v + 1)
    assert sk.pt(12) == 13


def test_identity_scaling():
    assert _identity_px(5) == 5
    assert _identity_pt(14) == 14


# ── State system ──────────────────────────────────────────────


def test_state_css_idle():
    sk = _make_sk()
    css = sk.state_css("idle")
    assert "border" in css
    assert "border-radius" in css


def test_state_css_uses_semantic_state_color():
    sk = _make_sk()
    css = sk.state_css("error")
    assert "rgba(240, 96, 96, 0.13)" in css
    assert "rgba(240, 96, 96, 0.38)" in css


def test_state_color():
    sk = _make_sk()
    assert sk.state_color("error") == "#f06060"
    assert sk.state_color("success") == "#40b86c"
    assert sk.state_color("loading") == "#5b7cf0"
    assert sk.state_color("unknown") == sk.token("body")


# ── QSS generation ────────────────────────────────────────────


def test_label_css_default():
    sk = _make_sk()
    css = sk.label_css()
    assert "QLabel" in css
    assert _SAMPLE_THEME["body"] in css


def test_label_css_custom():
    sk = _make_sk()
    css = sk.label_css("accent", size=16, bold=True, bg="panel")
    assert _SAMPLE_THEME["accent"] in css
    assert "16px" in css
    assert "font-weight: bold" in css
    assert _SAMPLE_THEME["panel"] in css


def test_heading_css():
    sk = _make_sk()
    css = sk.heading_css(size=17)
    assert "border-bottom" in css
    assert "rgba(" in css  # alpha() used for accent
    assert "font-size: 17px" in css


def test_alpha_accepts_tokens_and_resolved_colors_without_black_fallback():
    sk = _make_sk()
    assert sk._alpha("accent", 0.25) == "rgba(91, 124, 240, 0.25)"
    assert sk._alpha("#6b7394", 0.25) == "rgba(107, 115, 148, 0.25)"
    with pytest.raises(ValueError, match="Unknown theme token or invalid color"):
        sk._alpha("missing-token", 0.25)


def test_opaque_state_colors_are_distinct_from_their_base_tokens():
    sk = _make_sk()
    assert sk._lighter("accent") != sk.token("accent")
    assert sk._darker("accent") != sk.token("accent")
    assert sk._lighter("danger") != sk.token("danger")
    assert sk._darker("danger") != sk.token("danger")


def test_muted_css():
    sk = _make_sk()
    css = sk.muted_css()
    assert _SAMPLE_THEME["muted"] in css


def test_dialog_css_covers_all_widgets():
    sk = _make_sk()
    css = sk.dialog_css()
    selectors = [
        "QDialog", "QScrollArea", "QLabel", "QLineEdit", "QTextEdit",
        "QSpinBox", "QDoubleSpinBox", "QComboBox", "QListWidget",
        "QProgressBar", "QRadioButton", "QCheckBox", "QGroupBox",
        "QSlider", "QPushButton", "QScrollBar", "QToolTip", "QMessageBox",
    ]
    for sel in selectors:
        assert sel in css, f"Missing selector: {sel}"


def test_dialog_css_button_variants():
    sk = _make_sk()
    css = sk.dialog_css()
    for variant in ("primary", "secondary", "ghost", "danger"):
        assert f'buttonVariant="{variant}"' in css


def _render_bytes(widget: QWidget, app: QApplication) -> bytes:
    widget.show()
    app.processEvents()
    image = widget.grab().toImage()
    return bytes(image.constBits()[:image.sizeInBytes()])


@pytest.mark.parametrize(
    "widget_factory",
    [
        lambda: QLineEdit("Focus"),
        lambda: QCheckBox("Focus"),
        lambda: QRadioButton("Focus"),
    ],
)
def test_supported_focus_state_changes_actual_render(widget_factory):
    app = QApplication.instance() or QApplication([])
    widget = widget_factory()
    widget.resize(140, 36)
    widget.setStyleSheet(_make_sk().dialog_css())
    try:
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        _render_bytes(widget, app)
        widget.clearFocus()
        app.processEvents()
        assert not widget.hasFocus()
        normal = _render_bytes(widget, app)
        widget.activateWindow()
        widget.setFocus(Qt.FocusReason.TabFocusReason)
        app.processEvents()
        assert widget.hasFocus()
        assert _render_bytes(widget, app) != normal
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()


def test_button_focus_uses_qt_state_and_widget_reports_focus():
    app = QApplication.instance() or QApplication([])
    button = QPushButton("Focus")
    button.resize(140, 36)
    qss = _make_sk().dialog_css()
    button.setStyleSheet(qss)
    try:
        button.show()
        button.setFocus(Qt.FocusReason.TabFocusReason)
        app.processEvents()
        assert button.hasFocus()
        assert "QPushButton:focus" in qss
        assert "focus-visible" not in qss
    finally:
        button.close()
        button.deleteLater()
        app.processEvents()


def test_input_read_only_and_disabled_states_change_actual_pixels():
    app = QApplication.instance() or QApplication([])
    edit = QLineEdit()
    edit.resize(140, 36)
    edit.setStyleSheet(_make_sk().dialog_css())
    try:
        _render_bytes(edit, app)
        center = edit.rect().center()
        normal = edit.grab().toImage().pixelColor(center).name()

        edit.setReadOnly(True)
        app.processEvents()
        read_only = edit.grab().toImage().pixelColor(center).name()

        edit.setEnabled(False)
        app.processEvents()
        disabled = edit.grab().toImage().pixelColor(center).name()

        assert normal == _SAMPLE_THEME["input_bg"]
        assert read_only == _SAMPLE_THEME["header"]
        assert disabled == _SAMPLE_THEME["disabled_bg"]
        assert len({normal, read_only, disabled}) == 3
    finally:
        edit.close()
        edit.deleteLater()
        app.processEvents()


def test_button_pressed_property_and_disabled_render_are_distinct():
    app = QApplication.instance() or QApplication([])
    button = QPushButton("State")
    button.resize(140, 36)
    button.setStyleSheet(_make_sk().dialog_css())
    try:
        normal = _render_bytes(button, app)
        button.setDown(True)
        app.processEvents()
        assert button.isDown()
        pressed = _render_bytes(button, app)
        button.setDown(False)
        button.setEnabled(False)
        app.processEvents()
        assert not button.isEnabled()
        disabled = _render_bytes(button, app)
        assert pressed != normal
        assert disabled != normal
        assert disabled != pressed
        assert "QPushButton:pressed" in button.styleSheet()
    finally:
        button.close()
        button.deleteLater()
        app.processEvents()


def test_tab_css():
    sk = _make_sk()
    css = sk.tab_css()
    assert "QTabWidget::pane" in css
    assert "QTabBar::tab" in css
    assert "QTabBar::tab:selected" in css


def test_tab_css_scales_all_padding_and_margin_values():
    sk = StyleKit(theme=_SAMPLE_THEME, px=lambda value: value * 3)
    css = sk.tab_css()
    assert "padding: 12px 36px" in css
    assert "margin-right: 6px" in css


def test_slider_margin_preserves_negative_sign_with_clamping_scaler():
    sk = StyleKit(theme=_SAMPLE_THEME, px=lambda value: max(1, value * 2))
    css = sk.dialog_css()
    assert "margin: -10px 0" in css


def test_font_size_resolves_theme_token_then_builtin_fallback():
    sk = _make_sk()
    assert sk.font_size("sm") == 12
    assert sk.font_size("caption") == 11
    themed = StyleKit(theme={
        "properties": {"font_size": {"caption": 15, "xxl": 26}},
    })
    assert themed.font_size("caption") == 15
    assert themed.font_size("xxl") == 26
    assert themed.font_size("missing", default=14) == 14


def test_button_css_variants_are_token_backed():
    sk = _make_sk()
    primary = sk.button_css("primary", font_size_key="md")
    assert _SAMPLE_THEME["accent"] in primary
    assert "font-size: 13px" in primary
    assert "QPushButton:disabled" in primary
    ghost = sk.button_css("ghost", font_size_key="caption",
                          padding_y=0, padding_x=0)
    assert _SAMPLE_THEME["muted"] in ghost
    assert "font-size: 11px" in ghost
    assert "padding: 0px 0px" in ghost


def test_switch_nav_and_status_bar_generators():
    sk = _make_sk()
    switch = sk.switch_css()
    assert "QToolButton:checked" in switch
    assert _SAMPLE_THEME["accent"] in switch
    nav = sk.nav_css()
    assert "QFrame" in nav
    assert "QPushButton:checked" in nav
    status = sk.status_bar_css()
    assert "QStatusBar" in status
    assert _SAMPLE_THEME["header"] in status
    assert "font-size: 11px" in status


# ── Animation helpers ─────────────────────────────────────────


def test_reduce_motion_returns_bool():
    result = StyleKit.reduce_motion()
    assert isinstance(result, bool)


# ── Widget factories ──────────────────────────────────────────


def test_make_heading():
    app = QApplication.instance() or QApplication([])
    sk = _make_sk()
    label = sk.make_heading("Section Title")
    try:
        assert label.text() == "Section Title"
        ss = label.styleSheet()
        assert "border-bottom" in ss
        assert "rgba(" in ss
    finally:
        label.deleteLater()
        app.processEvents()


def test_make_muted():
    app = QApplication.instance() or QApplication([])
    sk = _make_sk()
    label = sk.make_muted("Secondary text")
    try:
        assert label.text() == "Secondary text"
        ss = label.styleSheet()
        assert _SAMPLE_THEME["muted"] in ss
    finally:
        label.deleteLater()
        app.processEvents()


def test_make_status_badge():
    app = QApplication.instance() or QApplication([])
    sk = _make_sk()
    badge = sk.make_status_badge("error")
    try:
        assert badge is not None
        labels = badge.findChildren(QLabel)
        texts = [lb.text() for lb in labels]
        assert texts == ["Error"]
        assert badge.property("semanticIcon") == "close"
        assert badge.property("stateColor") == _SAMPLE_THEME["danger"]
    finally:
        badge.deleteLater()
        app.processEvents()


def test_make_pill_button():
    app = QApplication.instance() or QApplication([])
    sk = _make_sk()
    btn = sk.make_pill_button("Click Me", variant="secondary")
    try:
        assert btn.text() == "Click Me"
        assert btn.property("buttonVariant") == "secondary"
    finally:
        btn.deleteLater()
        app.processEvents()


# ── from_theme integration ────────────────────────────────────


def test_from_theme():
    """StyleKit.from_theme() creates a kit that reads from a themes module."""
    class FakeThemes:
        @staticmethod
        def get():
            return _SAMPLE_THEME
    sk = StyleKit.from_theme(FakeThemes)
    assert sk.token("accent") == "#5b7cf0"
