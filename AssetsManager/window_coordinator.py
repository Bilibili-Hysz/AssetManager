"""Window coordinator — extracted from MainWindow for separation of concerns.

Handles theme transitions, language refresh, recent menu rebuild,
and status bar theming.  Kept as a standalone module callable from
any window instance so MainWindow stays thin.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import QApplication, QMainWindow
from pathlib import Path

from AssetsManager.core import themes
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.settings import AppSettings
from AssetsManager.core.ui_scale import scaled_pt, scaled_px
from AssetsManager import i18n

_log = logging.getLogger(__name__)
tr = i18n.tr


class WindowCoordinator:
    """Theme, language, and menu coordination for MainWindow."""

    def __init__(self, window: QMainWindow):
        self._window = window
        self._theme_generation = 0

    # ── Theme ─────────────────────────────────────────────────────

    def apply_menu_theme(self) -> None:
        t = themes.get()
        w = self._window
        w._menu_widget.setStyleSheet(f"background: {t['header']};")
        w._menu_bar.setStyleSheet(
            f"QMenuBar {{ background: transparent; color: {t['heading']}; "
            f"border: none; padding: 2px 8px; font-size: {scaled_pt(12)}px; }}"
            f"QMenuBar::item {{ padding: 3px 10px; border-radius: {scaled_px(4)}px; }}"
            f"QMenuBar::item:selected {{ background: {alpha(t['accent'], 0.313)}; }}"
            f"QMenu {{ background: {t['panel']}; color: {t['heading']}; "
            f"border: 1px solid {t['border']}; border-radius: {scaled_px(6)}px; padding: 4px; }}"
            f"QMenu::item {{ padding: 5px 28px 5px 12px; border-radius: {scaled_px(4)}px; }}"
            f"QMenu::item:selected {{ background: {t['accent']}; }}"
        )

    def apply_status_bar_theme(self) -> None:
        t = themes.get()
        w = self._window
        w._share_status_label.setStyleSheet(f"color: {t['muted']}; padding: 0 8px;")
        w.statusBar().setStyleSheet(
            f"QStatusBar {{ background: {t['header']}; color: {t['body']}; "
            f"border-top: 1px solid {t['border']}; font-size: {scaled_pt(11)}px; }}"
            f"QStatusBar::item {{ border: none; }}"
        )

    def on_theme_refresh(self) -> None:
        """Smooth theme transition animation."""
        self._theme_generation += 1
        self._stop_theme_animations()
        if AppSettings.instance().get("reduce_motion", False):
            self._apply_theme()
            return
        self._animate_theme_transition(self._theme_generation)

    def _stop_theme_animations(self) -> None:
        for name in ("_startup_anim", "_theme_anim_out", "_theme_anim_in"):
            animation = getattr(self._window, name, None)
            if animation is not None:
                animation.stop()
        self._window.setWindowOpacity(1.0)

    def _apply_theme(self) -> None:
        w = self._window
        QApplication.instance().setStyleSheet(themes.stylesheet())
        themes.apply_to(w)
        self.apply_menu_theme()
        self.apply_status_bar_theme()
        w._workspace._apply_style()
        w.refresh_bg()
        if hasattr(w.file_list, "_apply_list_theme"):
            w.file_list._apply_list_theme()

    def _animate_theme_transition(self, generation: int) -> None:
        w = self._window
        anim_out = QPropertyAnimation(w, b"windowOpacity")
        anim_out.setDuration(100)
        anim_out.setStartValue(1.0)
        anim_out.setEndValue(0.7)
        anim_out.setEasingCurve(QEasingCurve.Type.OutCubic)

        def on_fade_out_done():
            if generation != self._theme_generation:
                return
            self._apply_theme()
            anim_in = QPropertyAnimation(w, b"windowOpacity")
            anim_in.setDuration(200)
            anim_in.setStartValue(0.7)
            anim_in.setEndValue(1.0)
            anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim_in.finished.connect(lambda: w.setWindowOpacity(1.0))
            anim_in.start()
            w._theme_anim_in = anim_in

        anim_out.finished.connect(on_fade_out_done)
        anim_out.start()
        w._theme_anim_out = anim_out

    # ── Language ───────────────────────────────────────────────────

    def refresh_language(self) -> None:
        w = self._window
        w.setWindowTitle(tr("app.name"))
        w._menu_lib.setTitle(tr("menu.library"))
        w._menu_act_open.setText(tr("menu.open_library"))
        w._recent_menu.setTitle(tr("menu.recent_libraries"))
        w._menu_act_refresh.setText(tr("menu.refresh"))
        w._menu_act_settings.setText(tr("menu.settings"))
        if hasattr(w, '_menu_tools'):
            w._menu_tools.setTitle(tr("menu.tools"))
        w._share_toggle_btn.setToolTip(tr("sharing.toggle_tooltip"))
        self.apply_menu_theme()
        self.apply_status_bar_theme()

    def rebuild_recent_menu(self) -> None:
        w = self._window
        w._recent_menu.clear()
        settings = AppSettings.instance()
        recents = settings.get_list("recent_libraries", [])
        if not recents:
            w._recent_menu.addAction(tr("menu.recent_empty")).setEnabled(False)
            return
        for p in recents:
            path = Path(p)
            label = f"{path.name} — {p}"
            if len(label) > 60:
                label = label[:57] + "..."
            w._recent_menu.addAction(
                label, lambda checked, p=p: w._open_path(p))
