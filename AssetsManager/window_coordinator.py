"""Window coordinator — extracted from MainWindow for separation of concerns.

Owns the theme transition/refresh path (menu + status bar theming, fade
animation).  Language refresh and the recent-libraries menu live on
``MainWindow`` itself (its ``_refresh_language`` / ``_rebuild_recent_menu``
are the single wired implementations; earlier coordinator copies drifted and
were removed 2026-08-28).
"""
from __future__ import annotations

import logging

from typing import Any, Protocol, cast

from PySide6.QtCore import QObject, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import QApplication, QStatusBar

from AssetsManager.core import themes
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.settings import AppSettings
from AssetsManager.core.ui_scale import scaled_pt, scaled_px
from AssetsManager.widgets.stylekit import StyleKit
from AssetsManager import i18n

_log = logging.getLogger(__name__)
tr = i18n.tr


class CoordinatedWindow(Protocol):
    """The window surface ``WindowCoordinator`` drives.

    Naming it here keeps the coordinator decoupled from ``window.py`` (which
    imports this module) while still type-checking the attributes it reaches.
    ``MainWindow`` satisfies this protocol structurally; the ``QMainWindow``
    methods it inherits are redeclared below because a Protocol cannot derive
    from a concrete Qt class.
    """

    _menu_widget: Any
    _menu_bar: Any
    _share_status_label: Any
    _workspace: Any
    file_list: Any

    def refresh_bg(self, keep_rendered: bool = False) -> None: ...

    # Inherited from QMainWindow/QWidget.
    def setWindowTitle(self, title: str, /) -> None: ...
    def setWindowOpacity(self, level: float, /) -> None: ...
    def statusBar(self) -> QStatusBar: ...


class WindowCoordinator:
    """Theme, language, and menu coordination for MainWindow."""

    def __init__(self, window: CoordinatedWindow):
        self._window = window
        self._theme_generation = 0
        # The coordinator owns the fade animations it creates; holding the
        # references here keeps them alive without writing onto the window.
        self._theme_anim_in: QPropertyAnimation | None = None
        self._theme_anim_out: QPropertyAnimation | None = None

    # ── Theme ─────────────────────────────────────────────────────

    def apply_menu_theme(self) -> None:
        t = themes.get()
        w = self._window
        radius_sm = scaled_px(int(themes.prop("border_radius", "sm")))
        radius_md = scaled_px(int(themes.prop("border_radius", "md")))
        spacing_xs = scaled_px(int(themes.prop("spacing", "xs")))
        spacing_sm = scaled_px(int(themes.prop("spacing", "sm")))
        font_sm = scaled_pt(int(themes.prop("font_size", "sm")))
        hover = alpha(t["hover_overlay"], themes.prop("opacity", "hover"))
        pressed = alpha(t["accent"], 0.72)
        w._menu_widget.setStyleSheet(f"background: {t['header']};")
        w._menu_bar.setStyleSheet(
            f"QMenuBar {{ background: transparent; color: {t['heading']}; "
            f"border: none; padding: 2px {spacing_sm}px; font-size: {font_sm}px; }}"
            f"QMenuBar::item {{ padding: {spacing_xs}px 10px; border-radius: {radius_sm}px; }}"
            f"QMenuBar::item:selected {{ background: {hover}; }}"
            f"QMenu {{ background: {t['panel']}; color: {t['heading']}; "
            f"border: 1px solid {t['border']}; border-radius: {radius_md}px; padding: {spacing_xs}px; }}"
            f"QMenu::item {{ padding: 5px 28px 5px 12px; border-radius: {radius_sm}px; }}"
            f"QMenu::item:selected {{ background: {t['accent']}; color: {t['on_accent']}; }}"
            f"QMenu::item:pressed {{ background: {pressed}; color: {t['on_accent']}; }}"
        )

    def apply_status_bar_theme(self) -> None:
        t = themes.get()
        w = self._window
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        w._share_status_label.setStyleSheet(f"color: {t['muted']}; padding: 0 {scaled_px(8)}px;")
        w.statusBar().setStyleSheet(sk.status_bar_css())

    def on_theme_refresh(self) -> None:
        """Smooth theme transition animation."""
        self._theme_generation += 1
        self._stop_theme_animations()
        if AppSettings.instance().get("reduce_motion", False):
            self._apply_theme()
            return
        self._animate_theme_transition(self._theme_generation)

    def _stop_theme_animations(self) -> None:
        # The startup fade belongs to the window; the theme fades are ours.
        startup = getattr(self._window, "_startup_anim", None)
        for animation in (startup, self._theme_anim_out, self._theme_anim_in):
            if animation is not None:
                animation.stop()
        self._window.setWindowOpacity(1.0)

    def _apply_theme(self) -> None:
        w = self._window
        app = QApplication.instance()
        if app is not None:
            themes.apply_to(app)
        themes.apply_to(w)
        refresh_icons = getattr(w, "_refresh_ui_icons", None)
        if callable(refresh_icons):
            refresh_icons()
        self.apply_menu_theme()
        self.apply_status_bar_theme()
        w._workspace._apply_style()
        # Theme colors never affect the wallpaper output, so keep the
        # rendered-wallpaper cache and only schedule a repaint; dropping it
        # here would force a full image decode + effect-chain re-render
        # (CPU kuwahara can take seconds) on every theme switch.
        w.refresh_bg(keep_rendered=True)
        if hasattr(w.file_list, "_apply_list_theme"):
            w.file_list._apply_list_theme()

    def _animate_theme_transition(self, generation: int) -> None:
        w = self._window
        # QPropertyAnimation needs the concrete QObject; the protocol only
        # describes the surface this coordinator reads.
        w_obj = cast(QObject, w)
        anim_out = QPropertyAnimation(w_obj, b"windowOpacity")
        anim_out.setDuration(100)
        anim_out.setStartValue(1.0)
        anim_out.setEndValue(0.7)
        anim_out.setEasingCurve(QEasingCurve.Type.OutCubic)

        def on_fade_out_done():
            if generation != self._theme_generation:
                return
            self._apply_theme()
            anim_in = QPropertyAnimation(w_obj, b"windowOpacity")
            anim_in.setDuration(200)
            anim_in.setStartValue(0.7)
            anim_in.setEndValue(1.0)
            anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim_in.finished.connect(lambda: w.setWindowOpacity(1.0))
            anim_in.start()
            self._theme_anim_in = anim_in

        anim_out.finished.connect(on_fade_out_done)
        anim_out.start()
        self._theme_anim_out = anim_out
