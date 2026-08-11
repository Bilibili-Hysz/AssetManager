"""Custom frameless title bar — extensible design.

Layout:
  [Menu Bar] [Extension Area —— stretch ——] [_ □ X]

Any panel can add widgets to the extension area via add_extension().
The tab bar is just one consumer — mounted via mount_tab_bar().
Other panels can add filters, tool buttons, search bars, etc.

Provides window dragging, themed min/max/close, double-click maximize,
and border resize via nativeEvent on Windows.
"""
from PySide6.QtCore import Qt, QPoint, QSize
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QMenuBar, QPushButton,
    QSizePolicy,
)
from AssetsManager import i18n
from AssetsManager.core import icons, themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.widgets.stylekit import StyleKit

tr = i18n.tr


class TitleBarWidget(QWidget):
    """Custom frameless title bar — extensible design.

    NOTE: refresh_theme() is provided but this class is not currently
    instantiated by any consumer. Dock title bars are built by
    dock_factory._build_title_bar which already refreshes on theme change.
    If this class is adopted in the future, call refresh_theme() from the
    host window's theme-change handler.
    """
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self._window = window
        self._drag_pos: QPoint | None = None

        self._sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        self._apply_styles()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(self._sk.px(4), 0, 0, 0)
        layout.setSpacing(0)

        # ── Menu area ──────────────────────────────────────────
        self._menu_bar = QMenuBar()
        self._menu_bar.setNativeMenuBar(False)
        self._menu_bar.setStyleSheet(self._menu_bar_css())
        layout.addWidget(self._menu_bar)

        # ── Extension area (stretchable slot for panels) ────────
        self._extension_area = QWidget()
        self._extension_area.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._extension_layout = QHBoxLayout(self._extension_area)
        self._extension_layout.setContentsMargins(
            self._sk.px(4), self._sk.px(2), self._sk.px(4), self._sk.px(2))
        self._extension_layout.setSpacing(0)
        layout.addWidget(self._extension_area, 1)

        # ── Window controls ────────────────────────────────────
        btn_base = self._control_btn_css(variant="normal")
        close_style = self._control_btn_css(variant="close")

        self._window_controls = []
        for icon_name, label, slot, style, is_close in [
            ("minimize", tr("window.minimize"), self._on_minimize, btn_base, False),
            ("maximize", tr("window.maximize"), self._on_maximize, btn_base, False),
            ("close", tr("window.close"), self._on_close, close_style, True),
        ]:
            btn = QPushButton()
            btn.setIcon(icons.icon(icon_name, color="icon_secondary",
                                   size=self._sk.px(16)))
            btn.setIconSize(QSize(self._sk.px(16), self._sk.px(16)))
            btn.setToolTip(label)
            btn.setAccessibleName(label)
            btn.setProperty("semanticIcon", icon_name)
            btn.setProperty("isCloseControl", is_close)
            btn.setFixedSize(self._sk.px(36), self._sk.px(28))
            btn.setStyleSheet(style)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(slot)
            layout.addWidget(btn)
            self._window_controls.append(btn)

    # ── Internal CSS helpers ────────────────────────────────

    def _apply_styles(self):
        sk = self._sk
        self.setFixedHeight(sk.px(34))
        self.setStyleSheet(
            f"TitleBarWidget {{ background: {sk.token('header')}; "
            f"border-bottom: 1px solid {sk.token('border')}; }}")

    def _menu_bar_css(self) -> str:
        sk = self._sk
        return (
            f"QMenuBar {{ background: transparent; color: {sk.token('heading')}; "
            f"border: none; padding: {sk.px(4)}px {sk.px(6)}px; "
            f"font-size: {sk.pt(12)}px; }}"
            f"QMenuBar::item:selected {{ background: {sk._alpha('accent', 0.38)}; "
            f"border-radius: {sk.px(4)}px; }}"
        )

    def _control_btn_css(self, variant: str = "normal") -> str:
        sk = self._sk
        hover_bg = (sk._alpha("accent", 0.25) if variant == "normal"
                    else sk.token("danger"))
        hover_color = "white" if variant == "close" else sk.token("body")
        return (
            f"QPushButton {{ background: transparent; color: {sk.token('body')}; "
            f"border: none; font-size: {sk.pt(14)}px; padding: 0; margin: 0; }} "
            f"QPushButton:hover {{ background: {hover_bg}; color: {hover_color}; }} "
        )

    # ── Public API ──────────────────────────────────────────────

    def refresh_theme(self):
        """Re-apply styles after a theme change."""
        self._sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        self._apply_styles()
        self._menu_bar.setStyleSheet(self._menu_bar_css())
        btn_normal = self._control_btn_css(variant="normal")
        btn_close = self._control_btn_css(variant="close")
        for btn in getattr(self, "_window_controls", ()):
            icon_name = str(btn.property("semanticIcon") or "file")
            btn.setIcon(icons.icon(icon_name, color="icon_secondary",
                                   size=self._sk.px(16)))
            btn.setIconSize(QSize(self._sk.px(16), self._sk.px(16)))
            btn.setStyleSheet(
                btn_close if btn.property("isCloseControl") else btn_normal)

    def menu_bar(self) -> QMenuBar:
        """Return the integrated menu bar for building menus."""
        return self._menu_bar

    def add_extension(self, widget, stretch=0):
        """Add any widget to the title bar's extension area.

        Use this to insert panel-specific controls (filters, buttons,
        search bars, etc.) between the menu and window controls.
        """
        self._extension_layout.addWidget(widget, stretch)

    def mount_tab_bar(self, tab_bar):
        """Convenience: mount a QTabBar with stretch=1 (fills available space)."""
        self.add_extension(tab_bar, stretch=1)

    # ── Window dragging ────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and self._window:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self._window.move(self._window.pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_maximize()
        super().mouseDoubleClickEvent(event)

    # ── Window control slots ───────────────────────────────────

    def _on_minimize(self):
        if self._window:
            self._window.showMinimized()

    def _on_maximize(self):
        if self._window:
            if self._window.isMaximized():
                self._window.showNormal()
            else:
                self._window.showMaximized()
            # No theme refresh needed here: the control icons and styles do
            # not depend on the maximized state, and refresh_theme() would
            # rebuild every control's icon and stylesheet on every toggle.

    def _on_close(self):
        if self._window:
            self._window.close()
