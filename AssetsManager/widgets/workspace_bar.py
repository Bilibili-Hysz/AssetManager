"""Workspace bar — library-level tab switcher integrated with the menu bar row.

Each tab represents a different asset library root. Provides:
  - Tab switching (navigates all panels to the selected library)
  - Right-click menu (Rename, Duplicate, Close, Close Others)
  - Inline rename (double-click tab title)
  - "+" button to open a new library
  - Drag to reorder
  - Theme-aware styling
  - Duplicate tab detection
  - Sliding indicator animation
"""
from pathlib import Path
import logging

from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QRect, QSize, Property, QSignalBlocker
from PySide6.QtWidgets import (
    QTabBar, QMenu, QLineEdit, QPushButton, QWidget, QHBoxLayout,
    QFrame,
)
from PySide6.QtGui import QPainter, QColor
from AssetsManager import i18n
from AssetsManager.core import icons, themes
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.ui_scale import scaled_px, scaled_pt

_log = logging.getLogger(__name__)

tr = i18n.tr


class WorkspaceBar(QTabBar):
    library_switched = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDocumentMode(True)
        self.setExpanding(False)
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setDrawBase(False)
        self.setUsesScrollButtons(True)
        self.currentChanged.connect(self._on_current_changed)
        self.tabCloseRequested.connect(self._on_close)
        self.tabBarDoubleClicked.connect(self._start_rename)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)

        self._rename_idx: int = -1
        self._indicator_pos = 0
        self._indicator_width = 0
        self._indicator_anim = QPropertyAnimation(self, b"indicator_pos")
        self._indicator_anim.setDuration(200)
        self._indicator_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._indicator_width_anim = QPropertyAnimation(self, b"indicator_width")
        self._indicator_width_anim.setDuration(200)
        self._indicator_width_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._apply_style()
        self._bus_theme_conn = bus().theme_changed.connect(self.refresh_theme)
        self._bus_lang_conn = bus().language_changed.connect(self.refresh_theme)

    def closeEvent(self, event):
        # closeEvent is only delivered to top-level widgets; a tab bar
        # embedded in a window never receives it.  Bus connections are torn
        # down by the QObject destructor instead, so there is nothing to do
        # here (kept for parity with the window-level contract).
        super().closeEvent(event)

    def _get_indicator_pos(self):
        return self._indicator_pos

    def _set_indicator_pos(self, pos):
        self._indicator_pos = pos
        self.update()

    indicator_pos = Property(int, _get_indicator_pos, _set_indicator_pos)

    def _get_indicator_width(self):
        return self._indicator_width

    def _set_indicator_width(self, width):
        self._indicator_width = width
        self.update()

    indicator_width = Property(int, _get_indicator_width, _set_indicator_width)

    def _apply_style(self):
        t = themes.get()
        radius_sm = scaled_px(int(themes.prop("border_radius", "sm")))
        radius_md = scaled_px(int(themes.prop("border_radius", "md")))
        spacing_sm = scaled_px(int(themes.prop("spacing", "sm")))
        hover = alpha(t["hover_overlay"], themes.prop("opacity", "hover"))
        pressed = alpha(t["accent"], 0.18)
        self._renamer_style = (
            f"QLineEdit {{ background: {t['panel']}; color: {t['heading']}; "
            f"border: 1px solid {alpha(t['accent'], 0.627)}; border-radius: {radius_sm}px; "
            f"padding: {scaled_px(2)}px {scaled_px(6)}px; font-size: {scaled_pt(11)}px; selection-background-color: {alpha(t['accent'], 0.50)}; }}"
        )
        self.setStyleSheet(
            f"QTabBar {{ background: transparent; }}"
            f"QTabBar::tab {{ "
            f"  background: transparent; color: {t['muted']}; "
            f"  border: 1px solid transparent; "
            f"  border-top-left-radius: {radius_md}px; border-top-right-radius: {radius_md}px; "
            f"  padding: {scaled_px(2)}px {spacing_sm}px; margin-right: {scaled_px(1)}px; "
            f"  font-size: {scaled_pt(11)}px; min-width: {scaled_px(22)}px; max-width: {scaled_px(140)}px;"
            f"}} "
            f"QTabBar::tab:selected {{ "
            f"  color: {t['heading']}; "
            f"  background: {alpha(t['accent'], 0.25)}; "
            f"  border: 1px solid {alpha(t['accent'], 0.50)}; "
            f"  border-bottom: 2px solid {t['accent']};"
            f"}} "
            f"QTabBar::tab:hover:!selected {{ "
            f"  color: {t['body']}; "
            f"  background: {hover}; "
            f"  border: 1px solid {t['border_subtle']}; "
            f"}} "
            f"QTabBar::tab:pressed:!selected {{ "
            f"  color: {t['heading']}; "
            f"  background: {pressed}; "
            f"  border: 1px solid {t['border_subtle']}; "
            f"}} "
            f"QTabBar::close-button {{ "
            f"  background: transparent;"
            f"  margin: 0px; padding: 0px;"
            f"}} "
            f"QTabBar::close-button:hover {{ "
            f"  background: {alpha(t['accent'], 0.375)}; border-radius: {radius_sm}px;"
            f"}} "
            f"QTabBar QToolButton {{ "
            f"  color: {t['muted']}; background: transparent; border: none;"
            f"}} "
            f"QTabBar QToolButton:hover {{ "
            f"  color: {t['heading']}; background: {hover}; border-radius: {radius_sm}px;"
            f"}} "
            f"QTabBar QToolButton:pressed {{ "
            f"  color: {t['heading']}; background: {pressed}; border-radius: {radius_sm}px;"
            f"}} "
        )

    def refresh_theme(self, _name: str = ""):
        self._apply_style()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._indicator_anim.stop()
        self._indicator_width_anim.stop()
        if self.count() > 0:
            r = self.tabRect(self.currentIndex())
            self._indicator_pos = r.x()
            self._indicator_width = r.width()
            self.update()

    # ── Public API ──────────────────────────────────────────────

    def add_library(self, path: str):
        canonical_path = str(Path(path).resolve())
        name = Path(canonical_path).name or canonical_path
        existing = self.find_tab(canonical_path)
        if existing >= 0:
            self.setCurrentIndex(existing)
            return existing
        # addTab() may select its first tab before its path is available.
        # Block the intermediate Qt signal and notify once the tab is complete.
        with QSignalBlocker(self):
            idx = self.addTab(name)
            self.setTabData(idx, canonical_path)
            self.setCurrentIndex(idx)
        self._on_current_changed(idx)
        # Initialize indicator position
        tab_rect = self.tabRect(idx)
        self._indicator_pos = tab_rect.x()
        self._indicator_width = tab_rect.width()
        self.update()
        return idx

    def find_tab(self, path: str) -> int:
        canonical_path = str(Path(path).resolve())
        for i in range(self.count()):
            if str(self.tabData(i)) == canonical_path:
                return i
        return -1

    def remove_library(self, path: str):
        idx = self.find_tab(path)
        if idx >= 0:
            self.removeTab(idx)

    def tab_paths(self) -> list[str]:
        return [str(self.tabData(i)) for i in range(self.count())
                if self.tabData(i) is not None]

    def current_library(self) -> str | None:
        data = self.tabData(self.currentIndex())
        return str(data) if data else None

    # ── Internal ────────────────────────────────────────────────

    def _on_current_changed(self, idx):
        if idx < 0:
            return
        data = self.tabData(idx)
        if data:
            self.library_switched.emit(str(data))

        # Animate indicator to new tab
        self._animate_indicator(idx)

    def _animate_indicator(self, idx):
        """Animate the indicator to the specified tab."""
        if idx < 0:
            return

        tab_rect = self.tabRect(idx)
        target_x = tab_rect.x()
        target_width = tab_rect.width()

        # Animate position
        self._indicator_anim.stop()
        self._indicator_anim.setStartValue(self._indicator_pos)
        self._indicator_anim.setEndValue(target_x)
        self._indicator_anim.start()

        # Animate width
        self._indicator_width_anim.stop()
        self._indicator_width_anim.setStartValue(self._indicator_width)
        self._indicator_width_anim.setEndValue(target_width)
        self._indicator_width_anim.start()

    def paintEvent(self, event):
        """Override to draw custom indicator."""
        super().paintEvent(event)

        if self.count() == 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        t = themes.get()
        color = QColor(t['accent'])

        # Draw indicator bar at bottom of tab
        indicator_rect = QRect(
            int(self._indicator_pos),
            self.height() - 3,
            int(self._indicator_width),
            3
        )
        painter.fillRect(indicator_rect, color)
        painter.end()

    def _on_close(self, idx):
        if self.count() <= 1:
            return
        current_path = self.current_library()
        self.currentChanged.disconnect(self._on_current_changed)
        try:
            self.removeTab(idx)
        finally:
            self.currentChanged.connect(self._on_current_changed)
        if self.current_library() != current_path:
            self._on_current_changed(self.currentIndex())

    # ── Context menu ────────────────────────────────────────────

    def _context_menu(self, pos):
        idx = self.tabAt(pos)
        if idx < 0:
            return
        data = self.tabData(idx)
        if not data:
            return

        menu = QMenu(self)
        menu.addAction(tr("workspace.rename"), lambda: self._start_rename(idx))
        menu.addSeparator()
        menu.addAction(tr("workspace.close"), lambda: self._on_close(idx))
        if self.count() > 1:
            menu.addAction(tr("workspace.close_others"), lambda: self._close_others(idx))
        menu.exec(self.mapToGlobal(pos))

    def _start_rename(self, idx):
        self._rename_idx = idx
        # Selecting the tab under rename would trigger a library switch;
        # block the signal for the duration of the inline editor.
        with QSignalBlocker(self):
            self.setCurrentIndex(idx)
        rect = self.tabRect(idx)
        editor = QLineEdit(self)
        editor.setText(self.tabText(idx))
        editor.selectAll()
        editor.setGeometry(rect)
        if hasattr(self, '_renamer_style'):
            editor.setStyleSheet(self._renamer_style)
        editor.setFocus()
        editor.editingFinished.connect(lambda: self._finish_rename(editor, idx))
        editor.show()

    def _finish_rename(self, editor, idx):
        name = editor.text().strip()
        editor.deleteLater()
        if name and idx == self._rename_idx:
            self.setTabText(idx, name)
        self._rename_idx = -1

    def _close_others(self, keep_idx):
        keep_path = self.tabData(keep_idx)
        current_path = self.current_library()
        self.currentChanged.disconnect(self._on_current_changed)
        try:
            for i in range(self.count() - 1, -1, -1):
                if self.tabData(i) != keep_path:
                    self.removeTab(i)
            self.setCurrentIndex(0)
        finally:
            self.currentChanged.connect(self._on_current_changed)
        if current_path != str(keep_path):
            self._on_current_changed(0)


class WorkspaceSection(QWidget):
    """Self-contained workspace area: [divider] [tabs] [+] — use in menu bar row."""

    library_switched = Signal(str)
    add_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Separator line between menu items and workspace
        self._sep = QFrame()
        self._sep.setFrameShape(QFrame.Shape.VLine)
        self._sep.setFrameShadow(QFrame.Shadow.Plain)
        self._sep.setFixedWidth(scaled_px(1))
        layout.addWidget(self._sep)

        # Gap after separator
        layout.addSpacing(scaled_px(6))

        # Tab bar
        self._tabs = WorkspaceBar()
        self._tabs.library_switched.connect(self.library_switched.emit)
        self._tabs.setMinimumWidth(0)
        layout.addWidget(self._tabs, 0)

        # Gap before add button
        layout.addSpacing(2)

        # Add button
        self._add_btn = QPushButton()
        self._add_btn.setFixedSize(scaled_px(22), scaled_px(22))
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setToolTip(tr("workspace.add_library"))
        self._add_btn.setAccessibleName(tr("workspace.add_library"))
        self._add_btn.clicked.connect(self.add_requested.emit)
        layout.addWidget(self._add_btn)

        self._apply_style()

    def _apply_style(self):
        t = themes.get()
        radius_md = scaled_px(int(themes.prop("border_radius", "md")))
        pressed = alpha(t["accent"], 0.18)
        self._sep.setStyleSheet(
            f"QFrame {{ color: {t['border_subtle']}; background: {t['border_subtle']}; }}")
        themes.set_button_variant(self._add_btn, "primary")
        self._add_btn.setIcon(icons.icon("plus", color="icon_primary", size=scaled_px(12)))
        self._add_btn.setIconSize(QSize(scaled_px(12), scaled_px(12)))
        self._add_btn.setStyleSheet(
            f"QPushButton {{ background: {alpha(t['accent'], 0.753)}; color: {t['heading']}; "
            f"border: 1px solid {t['accent']}; border-radius: {radius_md}px; }} "
            f"QPushButton:hover {{ background: {t['accent']}; color: {t['on_accent']}; "
            f"border: 1px solid {t['accent']}; }} "
            f"QPushButton:pressed {{ background: {pressed}; color: {t['on_accent']}; "
            f"border: 1px solid {t['accent']}; }} ")
        self._tabs._apply_style()

    def add_library(self, path: str):
        return self._tabs.add_library(path)

    def find_tab(self, path: str) -> int:
        return self._tabs.find_tab(path)

    def tab_paths(self) -> list[str]:
        return self._tabs.tab_paths()

    def restore_tabs(self, paths: list[str]):
        for path in paths:
            # Hand-edited settings may contain non-string entries; skip them
            # instead of letting a TypeError abort the whole restore.
            if not isinstance(path, str) or not path:
                continue
            try:
                if Path(path).exists():
                    self._tabs.add_library(path)
            except Exception:
                # A single broken workspace entry must not prevent the
                # application from starting (restore runs during the
                # main-window constructor).  Drop a tab that was already
                # added by the failed restore so it cannot keep pointing at
                # a library the window never opened a session for.
                try:
                    self._tabs.remove_library(path)
                except Exception:
                    pass
                _log.exception("Failed to restore workspace tab: %s", path)

    def current_library(self) -> str | None:
        return self._tabs.current_library()
