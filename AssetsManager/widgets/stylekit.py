"""StyleKit — lightweight, reusable Qt styling toolkit.

A self-contained module for PySide6/Qt applications that provides:

  1. **Token resolution** — safe theme token lookup with fallbacks
  2. **QSS generation** — centralized stylesheet builder from theme dict
  3. **State-driven styling** — loading/error/retry/success/idle visual states
  4. **Animation helpers** — pulse/fade with reduce_motion degradation
  5. **Widget factories** — themed heading, muted label, status badge, pill button

Design principles:
  - Zero coupling to any specific project (no AssetsManager imports)
  - Works with any theme dict that follows the token schema below
  - Scale functions (scaled_px/scaled_pt) are injectable
  - All QSS is generated at call time, no caching (callers cache if needed)

Token schema (expected keys in theme dict):
  Colors: base, panel, header, border, heading, body, muted, accent,
          success, warning, danger, on_accent, hover_overlay, selected_overlay,
          border_focus, input_bg, input_text, scrollbar_track, scrollbar_thumb,
          scrollbar_thumb_hover, disabled_text, disabled_bg,
          tooltip_bg, tooltip_text
  Nested: properties.opacity.hover, properties.border_radius.md, etc.

Usage (standalone):
    from stylekit import StyleKit
    sk = StyleKit(theme_dict, px= scaled_px_fn, pt=scaled_pt_fn)
    label.setStyleSheet(sk.label_css("heading", size=14, bold=True))
    widget.setStyleSheet(sk.state_css("error"))
    if not sk.reduce_motion():
        anim.start()

Usage (integrated with project themes module):
    from AssetsManager.core import themes
    from AssetsManager.widgets.stylekit import StyleKit
    sk = StyleKit.from_theme(themes)  # reads current theme dynamically
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QPushButton,
)


# ── Default scale functions (identity) ────────────────────────

def _identity_px(px: int) -> int:
    """Default: return the value unchanged (no scaling)."""
    return px


def _identity_pt(pt: int) -> int:
    """Default: return the value unchanged (no scaling)."""
    return pt


# ── State definitions ─────────────────────────────────────────

_STATES = {
    "idle": ("", "body"),
    "loading": ("clock", "accent"),
    "success": ("check", "success"),
    "error": ("close", "danger"),
    "retry": ("refresh", "warning"),
}

# Semantic font-size steps. Kept in sync with
# ``AssetsManager.core.themes._FONT_SIZE_FALLBACKS`` (locked by
# tests/unit/test_style_sources.py) so custom themes that predate the
# extended font_size keys still resolve a readable size.
_FONT_SIZE_FALLBACKS = {
    "xxs": 9,
    "xs": 10,
    "caption": 11,
    "sm": 12,
    "md": 13,
    "lg": 14,
    "xl": 16,
    "xxl": 22,
}


class StyleKit:
    """Centralized styling toolkit for PySide6 applications.

    Parameters:
        theme: Theme dict with color tokens. If callable, called on each access.
        px: Scaling function for pixel values (default: identity).
        pt: Scaling function for point values (default: identity).
    """

    def __init__(self, theme: dict | Callable[[], dict] | None = None,
                 px: Callable[[int], int] = _identity_px,
                 pt: Callable[[int], int] = _identity_pt):
        self._theme = theme
        self._px = px
        self._pt = pt

    @classmethod
    def from_theme(cls, themes_module, **kwargs) -> "StyleKit":
        """Create from a project's themes module (must have .get() -> dict).

        The theme is resolved dynamically on each token access.
        """
        def _resolve():
            return themes_module.get()
        return cls(theme=_resolve, **kwargs)

    # ── Token resolution ──────────────────────────────────────

    @property
    def t(self) -> dict:
        """Current theme dict (resolved if callable)."""
        if callable(self._theme):
            return self._theme()
        return self._theme or {}

    def token(self, name: str, default: str = "") -> str:
        """Resolve a single color token."""
        return self.t.get(name, default)

    def prop(self, category: str, key: str, default: float = 0) -> int | float:
        """Resolve a property value (e.g. prop('border_radius', 'md'))."""
        return self.t.get("properties", {}).get(category, {}).get(key, default)

    def font_size(self, key: str, default: int = 12) -> int:
        """Resolve a semantic font-size token in unscaled points.

        Falls back to the built-in semantic map when a theme predates the
        extended ``font_size`` keys instead of collapsing to 0px.
        """
        value = self.prop("font_size", key)
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
        return _FONT_SIZE_FALLBACKS.get(key, default)

    # ── Scaling shortcuts ─────────────────────────────────────

    def px(self, value: int) -> int:
        return self._px(value)

    def pt(self, value: int) -> int:
        return self._pt(value)

    def _signed_px(self, value: int) -> int:
        """Scale signed geometry without passing a negative value to clamping scalers."""
        if value == 0:
            return 0
        scaled = abs(self._px(abs(value)))
        return -scaled if value < 0 else scaled

    # ── Animation ─────────────────────────────────────────────

    @staticmethod
    def reduce_motion() -> bool:
        """Check the global reduce_motion setting."""
        try:
            from AssetsManager.core.settings import AppSettings
            return bool(AppSettings.instance().get("reduce_motion", False))
        except Exception:
            return False


    # ── QSS: label ────────────────────────────────────────────

    def label_css(self, color: str = "body", size: int = 12,
                  bold: bool = False, bg: str = "transparent") -> str:
        """Generate QSS for a QLabel."""
        parts = [
            f"color: {self.token(color)}",
            f"font-size: {self.pt(size)}px",
            f"background: {self.token(bg) if bg in self.t else bg}",
        ]
        if bold:
            parts.append("font-weight: bold")
        return f"QLabel {{ {'; '.join(parts)}; }}"

    def heading_css(self, size: int = 14) -> str:
        """Section heading with accent underline."""
        return (
            f"QLabel {{ color: {self.token('heading')}; font-weight: bold; "
            f"font-size: {self.pt(size)}px; background: transparent; "
            f"border-bottom: 2px solid {self._alpha('accent', 0.50)}; "
            f"padding-bottom: {self.px(4)}px; "
            f"margin-bottom: {self.px(2)}px; }}"
        )

    def muted_css(self, size: int = 11) -> str:
        """Muted/secondary text label."""
        return self.label_css("muted", size=size)

    # ── QSS: state styling ────────────────────────────────────

    def state_css(self, state: str = "idle") -> str:
        """Generate QSS for a stateful widget (icon color, bg, border)."""
        _, color_key = _STATES.get(state, _STATES["idle"])
        color = self.token(color_key, self.token("body"))
        return (
            f"color: {color}; "
            f"background: {self._alpha(color, 0.13)}; "
            f"border: 1px solid {self._alpha(color, 0.38)}; "
            f"border-radius: {self.px(int(self.prop('border_radius', 'sm', 8)))}px; "
            f"padding: {self.px(int(self.prop('spacing', 'sm', 8)))}px;"
        )

    def state_color(self, state: str = "idle") -> str:
        """Return the theme color for a given state."""
        _, color_key = _STATES.get(state, _STATES["idle"])
        return self.token(color_key, self.token("body"))

    # ── QSS: dialog chrome ────────────────────────────────────

    def dialog_css(self) -> str:
        """Full QSS for a themed dialog. Covers all common Qt widgets."""
        t = self.t
        hover = self._alpha("hover_overlay", self.prop("opacity", "hover", 0.15))
        accent_hover = self._lighter("accent", 110)
        accent_pressed = self._darker("accent", 115)
        danger_hover = self._lighter("danger", 110)
        danger_pressed = self._darker("danger", 115)
        px, pt = self.px, self.pt
        # Tokenized geometry — fallbacks mirror D_Default.json properties.
        br_sm = px(int(self.prop("border_radius", "sm", 8)))
        br_md = px(int(self.prop("border_radius", "md", 10)))
        sp_xs = px(int(self.prop("spacing", "xs", 4)))
        sp_sm = px(int(self.prop("spacing", "sm", 8)))
        sp_md = px(int(self.prop("spacing", "md", 12)))
        sp_lg = px(int(self.prop("spacing", "lg", 16)))
        fs_sm = pt(int(self.prop("font_size", "sm", 12)))
        return (
            # ── Container ───────────────────────────────────────
            f"QDialog {{ background: {t.get('panel', t.get('base', ''))}; color: {t.get('body', t.get('base', ''))}; }}"
            f"QScrollArea {{ border: none; background: {t.get('panel', t.get('base', ''))}; }}"
            f"QLabel {{ color: {t.get('body', t.get('base', ''))}; background: transparent; }}"
            # ── Inputs ──────────────────────────────────────────
            f"QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{ "
            f"background: {t.get('input_bg', t.get('base', ''))}; color: {t.get('input_text', t.get('base', ''))}; "
            f"border: 1px solid {t.get('border', t.get('base', ''))}; border-radius: {br_sm}px; "
            f"padding: {sp_xs}px {sp_sm}px; }}"
            f"QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ "
            f"border: 2px solid {t.get('border_focus', t.get('base', ''))}; }}"
            f"QLineEdit:read-only, QTextEdit:read-only, "
            f"QSpinBox:read-only, QDoubleSpinBox:read-only {{ "
            f"background: {t.get('header', t.get('disabled_bg', t.get('base', '')))}; color: {t.get('muted', t.get('base', ''))}; "
            f"border-color: {t.get('muted', t.get('base', ''))}; }}"
            f"QLineEdit:disabled, QTextEdit:disabled, "
            f"QSpinBox:disabled, QDoubleSpinBox:disabled {{ "
            f"background: {t.get('disabled_bg', t.get('base', ''))}; color: {t.get('disabled_text', t.get('base', ''))}; "
            f"border-color: {t.get('disabled_bg', t.get('base', ''))}; }}"
            f"QComboBox {{ "
            f"background: {t.get('input_bg', t.get('base', ''))}; color: {t.get('input_text', t.get('base', ''))}; "
            f"border: 1px solid {t.get('border', t.get('base', ''))}; border-radius: {br_sm}px; "
            f"padding: {sp_xs}px {sp_sm}px; }}"
            f"QComboBox:focus {{ border: 2px solid {t.get('border_focus', t.get('base', ''))}; }}"
            f"QComboBox:disabled {{ background: {t.get('disabled_bg', t.get('base', ''))}; "
            f"color: {t.get('disabled_text', t.get('base', ''))}; border-color: {t.get('disabled_bg', t.get('base', ''))}; }}"
            f"QComboBox::drop-down {{ border: none; }}"
            # ── List ────────────────────────────────────────────
            f"QListWidget {{ background: {t.get('input_bg', t.get('base', ''))}; color: {t.get('input_text', t.get('base', ''))}; "
            f"border: 1px solid {t.get('border', t.get('base', ''))}; border-radius: {br_sm}px; "
            f"padding: {sp_xs}px; }}"
            f"QListWidget::item {{ padding: {sp_sm}px {sp_sm}px; "
            f"border-radius: {br_sm}px; }}"
            f"QListWidget::item:hover {{ background: {hover}; }}"
            f"QListWidget::item:selected {{ background: {self._alpha('accent', 0.25)}; "
            f"color: {t.get('heading', t.get('base', ''))}; }}"
            # ── Progress ────────────────────────────────────────
            f"QProgressBar {{ background: {t.get('input_bg', t.get('base', ''))}; color: {t.get('body', t.get('base', ''))}; "
            f"border: 1px solid {t.get('border', t.get('base', ''))}; border-radius: {br_sm}px; "
            f"text-align: center; }}"
            f"QProgressBar::chunk {{ background: {t.get('accent', t.get('base', ''))}; "
            f"border-radius: {br_sm}px; }}"
            # ── Radio + Checkbox ────────────────────────────────
            f"QRadioButton, QCheckBox {{ color: {t.get('body', t.get('base', ''))}; background: transparent; "
            f"spacing: {sp_sm}px; }}"
            f"QRadioButton:focus, QCheckBox:focus {{ color: {t.get('border_focus', t.get('base', ''))}; }}"
            f"QRadioButton:disabled, QCheckBox:disabled {{ color: {t.get('disabled_text', t.get('base', ''))}; }}"
            f"QRadioButton:checked {{ color: {t.get('accent', t.get('base', ''))}; font-weight: bold; }}"
            f"QRadioButton::indicator {{ width: {px(14)}px; height: {px(14)}px; }}"
            f"QRadioButton::indicator:checked {{ background: {t.get('accent', t.get('base', ''))}; "
            f"border: 2px solid {t.get('accent', t.get('base', ''))}; border-radius: {br_md}px; }}"
            f"QRadioButton::indicator:unchecked {{ background: {t.get('input_bg', t.get('base', ''))}; "
            f"border: 2px solid {t.get('border', t.get('base', ''))}; border-radius: {br_md}px; }}"
            f"QRadioButton::indicator:hover {{ border-color: {t.get('accent', t.get('base', ''))}; }}"
            f"QRadioButton::indicator:focus {{ border-color: {t.get('border_focus', t.get('base', ''))}; }}"
            f"QRadioButton::indicator:disabled {{ background: {t.get('disabled_bg', t.get('base', ''))}; "
            f"border-color: {t.get('disabled_text', t.get('base', ''))}; }}"
            f"QCheckBox::indicator {{ width: {px(14)}px; height: {px(14)}px; }}"
            f"QCheckBox::indicator:checked {{ background: {t.get('accent', t.get('base', ''))}; "
            f"border: 2px solid {t.get('accent', t.get('base', ''))}; border-radius: {br_sm}px; }}"
            f"QCheckBox::indicator:unchecked {{ background: {t.get('input_bg', t.get('base', ''))}; "
            f"border: 2px solid {t.get('border', t.get('base', ''))}; border-radius: {br_sm}px; }}"
            f"QCheckBox::indicator:hover {{ border-color: {t.get('accent', t.get('base', ''))}; }}"
            f"QCheckBox::indicator:focus {{ border-color: {t.get('border_focus', t.get('base', ''))}; }}"
            f"QCheckBox::indicator:disabled {{ background: {t.get('disabled_bg', t.get('base', ''))}; "
            f"border-color: {t.get('disabled_text', t.get('base', ''))}; }}"
            # ── Group box ───────────────────────────────────────
            f"QGroupBox {{ color: {t.get('heading', t.get('base', ''))}; border: 1px solid {t.get('border', t.get('base', ''))}; "
            f"border-radius: {br_md}px; margin-top: {sp_sm}px; "
            f"padding-top: {sp_md}px; background: transparent; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: {sp_md}px; "
            f"padding: 0 {sp_sm}px; }}"
            # ── Slider ──────────────────────────────────────────
            f"QSlider::groove:horizontal {{ background: {t.get('border', t.get('base', ''))}; "
            f"height: {px(4)}px; border-radius: {br_sm}px; }}"
            f"QSlider::handle:horizontal {{ background: {t.get('accent', t.get('base', ''))}; "
            f"width: {px(14)}px; height: {px(14)}px; "
            f"margin: {self._signed_px(-5)}px 0; border-radius: {br_md}px; "
            f"border: 2px solid {t.get('accent', t.get('base', ''))}; }}"
            f"QSlider::handle:horizontal:hover {{ "
            f"background: {self._alpha('accent', 0.85)}; "
            f"border-color: {self._alpha('accent', 0.85)}; }}"
            f"QSlider::sub-page:horizontal {{ background: {t.get('accent', t.get('base', ''))}; "
            f"border-radius: {br_sm}px; }}"
            # ── Push buttons ────────────────────────────────────
            f"QPushButton {{ background: {t.get('accent', t.get('base', ''))}; color: {t.get('on_accent', t.get('base', ''))}; "
            f"border: none; border-radius: {br_sm}px; "
            f"padding: {sp_sm}px {sp_lg}px; }}"
            f"QPushButton:hover {{ background: {hover}; }}"
            f"QPushButton[buttonVariant=\"primary\"] {{ "
            f"background: {t.get('accent', t.get('base', ''))}; color: {t.get('on_accent', t.get('base', ''))}; }}"
            f"QPushButton[buttonVariant=\"primary\"]:hover {{ "
            f"background: {accent_hover}; }}"
            f"QPushButton[buttonVariant=\"primary\"]:pressed {{ "
            f"background: {accent_pressed}; }}"
            f"QPushButton[buttonVariant=\"secondary\"] {{ "
            f"background: {t.get('panel', t.get('base', ''))}; color: {t.get('heading', t.get('base', ''))}; "
            f"border: 1px solid {t.get('border', t.get('base', ''))}; }}"
            f"QPushButton[buttonVariant=\"secondary\"]:hover {{ "
            f"background: {hover}; }}"
            f"QPushButton[buttonVariant=\"secondary\"]:pressed {{ "
            f"background: {self._alpha('accent', 0.20)}; }}"
            f"QPushButton[buttonVariant=\"ghost\"] {{ "
            f"background: transparent; color: {t.get('body', t.get('base', ''))}; "
            f"border: 1px solid transparent; }}"
            f"QPushButton[buttonVariant=\"ghost\"]:hover {{ "
            f"background: {hover}; color: {t.get('heading', t.get('base', ''))}; }}"
            f"QPushButton[buttonVariant=\"ghost\"]:pressed {{ "
            f"background: {self._alpha('accent', 0.20)}; }}"
            f"QPushButton[buttonVariant=\"danger\"] {{ "
            f"background: {t.get('danger', t.get('base', ''))}; color: {t.get('on_accent', t.get('base', ''))}; }}"
            f"QPushButton[buttonVariant=\"danger\"]:hover {{ "
            f"background: {danger_hover}; }}"
            f"QPushButton[buttonVariant=\"danger\"]:pressed {{ "
            f"background: {danger_pressed}; }}"
            f"QPushButton:focus {{ border: 2px solid {t.get('border_focus', t.get('base', ''))}; }}"
            f"QPushButton:pressed {{ background: {accent_pressed}; }}"
            f"QPushButton:disabled {{ background: {t.get('disabled_bg', t.get('base', ''))}; "
            f"color: {t.get('disabled_text', t.get('base', ''))}; border: 1px solid {t.get('disabled_bg', t.get('base', ''))}; }}"
            # ── Scrollbar ───────────────────────────────────────
            f"QScrollBar:vertical {{ background: {t.get('scrollbar_track', t.get('base', ''))}; "
            f"width: {px(8)}px; }}"
            f"QScrollBar::handle:vertical {{ background: {t.get('scrollbar_thumb', t.get('base', ''))}; "
            f"border-radius: {br_sm}px; min-height: {px(20)}px; }}"
            # ── ToolTip ─────────────────────────────────────────
            f"QToolTip {{ background: {t.get('tooltip_bg', t.get('header', t.get('base', '')))}; "
            f"color: {t.get('tooltip_text', t.get('heading', t.get('base', '')))}; "
            f"border: 1px solid {t.get('border', t.get('base', ''))}; "
            f"border-radius: {br_sm}px; "
            f"padding: {sp_xs}px {sp_sm}px; "
            f"font-size: {fs_sm}px; }}"
            # ── QMessageBox ─────────────────────────────────────
            f"QMessageBox {{ background: {t.get('panel', t.get('base', ''))}; color: {t.get('body', t.get('base', ''))}; }}"
            f"QMessageBox QLabel {{ color: {t.get('body', t.get('base', ''))}; font-size: {fs_sm}px; }}"
        )

    def tab_css(self) -> str:
        """QSS for QTabWidget used inside dialogs."""
        t = self.t
        px = self.px
        br_md = px(int(self.prop("border_radius", "md", 10)))
        sp_sm = px(int(self.prop("spacing", "sm", 8)))
        sp_lg = px(int(self.prop("spacing", "lg", 16)))
        return (
            f"QTabWidget::pane {{ border: 1px solid {t.get('border', t.get('base', ''))}; "
            f"border-radius: {br_md}px; background: {t.get('panel', t.get('base', ''))}; }}"
            f"QTabBar::tab {{ background: {t.get('base', '')}; color: {t.get('muted', t.get('base', ''))}; "
            f"border: 1px solid {t.get('border', t.get('base', ''))}; padding: {sp_sm}px {sp_lg}px; "
            f"margin-right: {px(2)}px; "
            f"border-top-left-radius: {br_md}px; border-top-right-radius: {br_md}px; }}"
            f"QTabBar::tab:selected {{ background: {t.get('panel', t.get('base', ''))}; color: {t.get('heading', t.get('base', ''))}; "
            f"border-bottom-color: {t.get('panel', t.get('base', ''))}; }}"
            f"QTabBar::tab:hover:!selected {{ "
            f"background: {self._alpha('hover_overlay', self.prop('opacity', 'hover', 0.15))}; color: {t.get('body', t.get('base', ''))}; }}"
        )

    # ── QSS: reusable widget generators ──────────────────────

    def button_css(self, variant: str = "primary", *,
                   font_size_key: str = "sm",
                   padding_y: int | None = None,
                   padding_x: int | None = None) -> str:
        """Token-driven QPushButton QSS shared by dialogs and shell windows.

        Variants mirror the ``buttonVariant`` property vocabulary. Padding
        defaults to spacing tokens; callers may pass scaled pixel values
        (including ``0``) for compact icon-only layouts.
        """
        radius = self.px(int(self.prop("border_radius", "sm", 8)))
        pad_y = self.px(int(self.prop("spacing", "sm", 8))) if padding_y is None else padding_y
        pad_x = self.px(int(self.prop("spacing", "lg", 16))) if padding_x is None else padding_x
        size = self.pt(self.font_size(font_size_key))
        hover = self._alpha("hover_overlay", self.prop("opacity", "hover", 0.15))
        pressed = self._alpha("accent", 0.18)
        normalized = str(variant).strip().lower()
        if normalized == "ghost":
            base = (
                f"background: transparent; color: {self.token('muted', self.token('body'))}; "
                f"border: 1px solid transparent;")
            hover_rule = f"background: {hover}; color: {self.token('body', self.token('heading'))};"
        elif normalized == "secondary":
            base = (
                f"background: {self.token('panel', self.token('base'))}; "
                f"color: {self.token('heading', self.token('body'))}; "
                f"border: 1px solid {self.token('border_subtle', self.token('border'))};")
            hover_rule = f"background: {hover};"
        elif normalized == "danger":
            base = (
                f"background: {self.token('danger', self.token('accent'))}; "
                f"color: {self.token('on_accent', self.token('heading'))}; border: none;")
            hover_rule = f"background: {self._lighter('danger', 110)};"
            pressed = self._darker("danger", 115)
        else:
            # Primary (and unknown variants fall back to primary): hover and
            # pressed use the canonical opaque HSV lighter/darker recipe so
            # every accent button in the app feels identical (audit B4/D1).
            base = (
                f"background: {self.token('accent', self.token('base'))}; "
                f"color: {self.token('on_accent', self.token('heading'))}; border: none;")
            hover_rule = f"background: {self._lighter('accent', 110)};"
            pressed = self._darker("accent", 115)
        return (
            f"QPushButton {{ {base} border-radius: {radius}px; "
            f"padding: {pad_y}px {pad_x}px; font-size: {size}px; font-weight: bold; }}"
            f"QPushButton:hover {{ {hover_rule} }}"
            f"QPushButton:focus {{ border: 1px solid {self.token('border_focus', self.token('accent'))}; }}"
            f"QPushButton:pressed {{ background: {pressed}; }}"
            f"QPushButton:disabled {{ background: {self._alpha('muted', 0.25)}; "
            f"color: {self.token('muted', self.token('body'))}; }}"
        )

    def switch_css(self) -> str:
        """QToolButton toggle-switch QSS for on/off settings rows."""
        accent = self.token("accent", self.token("body"))
        muted = self.token("muted", self.token("body"))
        hover = self._alpha("hover_overlay", self.prop("opacity", "hover", 0.15))
        radius = self.px(12)
        return (
            f"QToolButton {{ background: {muted}; border-radius: {radius}px; "
            f"border: 1px solid {self.token('border_subtle', self.token('border'))}; }}"
            f"QToolButton:hover {{ background: {hover}; border-color: {accent}; }}"
            f"QToolButton:checked {{ background: {accent}; border-color: {accent}; }}"
            f"QToolButton:checked:hover {{ background: {self._alpha(accent, 0.85)}; }}"
            f"QToolButton:pressed {{ background: {self._alpha(accent, 0.18)}; }}"
            f"QToolButton:focus {{ border: 2px solid {self.token('border_focus', accent)}; }}"
        )

    def nav_css(self) -> str:
        """QFrame + QPushButton navigation-rail QSS for settings shells."""
        radius = self.px(int(self.prop("border_radius", "sm", 8)))
        pad_y = self.px(int(self.prop("spacing", "sm", 8)))
        pad_x = self.px(int(self.prop("spacing", "md", 12)))
        hover = self._alpha("hover_overlay", self.prop("opacity", "hover", 0.15))
        pressed = self._alpha("accent", 0.18)
        focus = self.token("border_focus", self.token("accent", self.token("body")))
        accent = self.token("accent", self.token("body"))
        on_accent = self.token("on_accent", self.token("heading", self.token("body")))
        body = self.token("body", self.token("heading", ""))
        return (
            f"QFrame {{ background: {self.token('base', self.token('panel', ''))}; "
            f"border: 1px solid {self.token('border_subtle', self.token('border', ''))}; "
            f"border-radius: {radius}px; }}"
            f"QPushButton {{ text-align: left; background: transparent; color: {body}; "
            f"border: none; border-radius: {radius}px; padding: {pad_y}px {pad_x}px; }}"
            f"QPushButton:hover {{ background: {hover}; }}"
            f"QPushButton:pressed {{ background: {pressed}; }}"
            f"QPushButton:focus {{ background: {hover}; border: 1px solid {focus}; }}"
            f"QPushButton:checked {{ background: {accent}; color: {on_accent}; font-weight: bold; }}"
        )

    def tree_css(self) -> str:
        """Compact, theme-aware QTreeWidget QSS shared by sidebar/tag panels."""
        font_size = self.pt(self.font_size("sm"))
        pad_xs = self.px(int(self.prop("spacing", "xs", 4)))
        pad_sm = self.px(int(self.prop("spacing", "sm", 8)))
        radius_sm = self.px(int(self.prop("border_radius", "sm", 8)))
        hover = self._alpha("hover_overlay", self.prop("opacity", "hover", 0.15))
        selected = self._alpha("selected_overlay", 0.28)
        body = self.token("body", self.token("heading", ""))
        heading = self.token("heading", body)
        muted = self.token("muted", body)
        return (
            f"QTreeWidget {{"
            f"  background: transparent; color: {body}; border: none; outline: none; "
            f"  font-size: {font_size}px; "
            f"}}"
            f"QTreeWidget::item {{"
            f"  padding: {pad_xs}px {pad_sm}px; "
            f"  border: none; border-radius: {radius_sm}px; "
            f"}}"
            f"QTreeWidget::item:hover {{"
            f"  background: {hover}; "
            f"}}"
            f"QTreeWidget::item:selected {{"
            f"  background: {selected}; color: {heading}; "
            f"}}"
            f"QTreeWidget::item:selected:focus {{"
            f"  background: {selected}; color: {heading}; "
            f"}}"
            f"QTreeWidget::item:disabled {{ color: {muted}; }}"
        )

    def status_bar_css(self) -> str:
        """QStatusBar chrome QSS shared by shell windows."""
        size = self.pt(self.font_size("caption"))
        return (
            f"QStatusBar {{ background: {self.token('header', self.token('panel', ''))}; "
            f"color: {self.token('body', self.token('heading', ''))}; "
            f"border-top: 1px solid {self.token('border', self.token('border_subtle', ''))}; "
            f"font-size: {size}px; }}"
            f"QStatusBar::item {{ border: none; }}"
        )

    # ── Widget factories ──────────────────────────────────────

    def make_heading(self, text: str, parent: QWidget | None = None) -> QLabel:
        """Create a themed section heading with accent underline."""
        label = QLabel(text, parent)
        label.setStyleSheet(self.heading_css())
        return label

    def make_muted(self, text: str, parent: QWidget | None = None) -> QLabel:
        """Create a muted/secondary text label."""
        label = QLabel(text, parent)
        label.setStyleSheet(self.muted_css())
        return label

    def make_status_badge(self, state: str = "idle",
                          parent: QWidget | None = None) -> QWidget:
        """Create a status badge carrying semantic icon metadata and visible text."""
        icon_name, color_key = _STATES.get(state, _STATES["idle"])
        color = self.token(color_key, self.token("body"))
        badge = QWidget(parent)
        badge.setProperty("semanticIcon", icon_name)
        badge.setProperty("stateColor", color)
        badge.setStyleSheet(
            f"background: {self._alpha(color_key, 0.13)}; "
            f"border: 1px solid {self._alpha(color_key, 0.38)}; "
            f"border-radius: {self.px(int(self.prop('border_radius', 'md', 10)))}px; "
            f"padding: {self.px(int(self.prop('spacing', 'xs', 4)))}px {self.px(int(self.prop('spacing', 'sm', 8)))}px;")
        row = QHBoxLayout(badge)
        row.setContentsMargins(self.px(int(self.prop("spacing", "sm", 8))),
                               self.px(int(self.prop("spacing", "xs", 4))),
                               self.px(int(self.prop("spacing", "sm", 8))),
                               self.px(int(self.prop("spacing", "xs", 4))))
        row.setSpacing(self.px(int(self.prop("spacing", "xs", 4))))
        text = QLabel(state.capitalize())
        text.setStyleSheet(
            f"color: {color}; font-size: {self.pt(11)}px; font-weight: bold; "
            f"background: transparent;")
        row.addWidget(text)
        return badge

    def make_pill_button(self, text: str, variant: str = "primary",
                         parent: QWidget | None = None) -> QPushButton:
        """Create a pill-shaped button (purely visual, not clickable)."""
        btn = QPushButton(text, parent)
        btn.setProperty("buttonVariant", variant)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    # ── Internal helpers ──────────────────────────────────────

    def alpha(self, color_or_token: str, opacity: float) -> str:
        """Return rgba() for either a theme token name or an already resolved color.

        Public derived-color API (Design System audit 2026-09-03, I1): the
        sanctioned dialect for state fills in presentation code. Consumers
        must use ``sk.alpha/lighter/darker`` — not token dict access or
        private names.
        """
        resolved = self.token(color_or_token) if color_or_token in self.t else color_or_token
        color = QColor(resolved)
        if not color.isValid():
            raise ValueError(
                f"Unknown theme token or invalid color: {color_or_token!r}"
            )
        clamped_opacity = max(0.0, min(1.0, opacity))
        return (
            f"rgba({color.red()}, {color.green()}, {color.blue()}, "
            f"{clamped_opacity:.2f})"
        )

    def lighter(self, color_or_token: str, factor: int = 110) -> str:
        """Return an opaque lighter variant suitable for a QSS state fill.

        Canonical hover algorithm — same HSV formula as
        ``AssetsManager.core.color_utils.lighter``.
        """
        return self._adjust_lightness(color_or_token, factor, lighter=True)

    def darker(self, color_or_token: str, factor: int = 115) -> str:
        """Return an opaque darker variant suitable for a QSS state fill.

        Canonical pressed algorithm — see :meth:`lighter`.
        """
        return self._adjust_lightness(color_or_token, factor, lighter=False)

    # Deprecated private spellings kept for in-class callers during the
    # gradual migration to the public derived-color API; do not use in new
    # code (G3 will forbid them outside stylekit).
    _alpha = alpha
    _lighter = lighter
    _darker = darker

    def _adjust_lightness(
        self,
        color_or_token: str,
        factor: int,
        *,
        lighter: bool,
    ) -> str:
        resolved = self.token(color_or_token) if color_or_token in self.t else color_or_token
        color = QColor(resolved)
        if not color.isValid():
            raise ValueError(
                f"Unknown theme token or invalid color: {color_or_token!r}"
            )
        adjusted = color.lighter(max(100, factor)) if lighter else color.darker(max(100, factor))
        return adjusted.name(QColor.NameFormat.HexRgb)
