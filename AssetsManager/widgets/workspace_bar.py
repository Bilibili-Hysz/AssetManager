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

from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QRect, Property
from PySide6.QtWidgets import (
    QTabBar, QMenu, QLineEdit, QPushButton, QWidget, QHBoxLayout,
    QFrame,
)
from PySide6.QtGui import QPainter, QColor
from AssetsManager import i18n
from AssetsManager.core import themes
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.ui_scale import scaled_px, scaled_pt

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

    def closeEvent(self, event):
        """Disconnect bus signals on close."""
        try:
            bus().theme_changed.disconnect(self._bus_theme_conn)
        except (RuntimeError, TypeError):
            pass
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
        self._renamer_style = (
            f"QLineEdit {{ background: {t['panel']}; color: {t['heading']}; "
            f"border: 1px solid {alpha(t['accent'], 0.627)}; border-radius: {scaled_px(4)}px; "
            f"padding: 2px 6px; font-size: {scaled_pt(11)}px; selection-background-color: {alpha(t['accent'], 0.50)}; }}"
        )
        self.setStyleSheet(
            f"QTabBar {{ background: transparent; }}"
            f"QTabBar::tab {{ "
            f"  background: transparent; color: {t['muted']}; "
            f"  border: 1px solid transparent; "
            f"  border-top-left-radius: {scaled_px(6)}px; border-top-right-radius: {scaled_px(6)}px; "
            f"  padding: 2px 8px; margin-right: 1px; "
            f"  font-size: {scaled_pt(11)}px; min-width: 22px; max-width: 140px;"
            f"}} "
            f"QTabBar::tab:selected {{ "
            f"  color: {t['heading']}; "
            f"  background: {alpha(t['accent'], 0.25)}; "
            f"  border: 1px solid {alpha(t['accent'], 0.50)}; "
            f"  border-bottom: 2px solid {t['accent']};"
            f"}} "
            f"QTabBar::tab:hover:!selected {{ "
            f"  color: {t['body']}; "
            f"  background: {alpha(t['panel'], 0.50)}; "
            f"  border: 1px solid {alpha(t['border'], 0.50)}; "
            f"}} "
            f"QTabBar::close-button {{ "
            f"  background: transparent;"
            f"  margin: 0px; padding: 0px;"
            f"}} "
            f"QTabBar::close-button:hover {{ "
            f"  background: {alpha(t['accent'], 0.375)}; border-radius: {scaled_px(3)}px;"
            f"}} "
            f"QTabBar QToolButton {{ "
            f"  color: {t['muted']}; background: transparent; border: none;"
            f"}} "
            f"QTabBar QToolButton:hover {{ "
            f"  color: {t['heading']}; background: {alpha(t['panel'], 0.50)};"
            f"}} "
        )

    def refresh_theme(self, _name: str = ""):
        self._apply_style()

    # ── Public API ──────────────────────────────────────────────

    def add_library(self, path: str):
        name = Path(path).name or path
        existing = self.find_tab(path)
        if existing >= 0:
            self.setCurrentIndex(existing)
            return existing
        idx = self.addTab(name)
        self.setTabData(idx, path)
        self.setCurrentIndex(idx)
        self._on_current_changed(idx)
        # Initialize indicator position
        tab_rect = self.tabRect(idx)
        self._indicator_pos = tab_rect.x()
        self._indicator_width = tab_rect.width()
        self.update()
        return idx

    def find_tab(self, path: str) -> int:
        for i in range(self.count()):
            if str(self.tabData(i)) == path:
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
        self.removeTab(idx)

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
        menu.addAction(tr("workspace.duplicate"), lambda: self._duplicate(idx))
        menu.addSeparator()
        menu.addAction(tr("workspace.close"), lambda: self._on_close(idx))
        if self.count() > 1:
            menu.addAction(tr("workspace.close_others"), lambda: self._close_others(idx))
        menu.exec(self.mapToGlobal(pos))

    def _start_rename(self, idx):
        self._rename_idx = idx
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
        editor.returnPressed.connect(lambda: self._finish_rename(editor, idx))
        editor.show()

    def _finish_rename(self, editor, idx):
        name = editor.text().strip()
        editor.deleteLater()
        if name and idx == self._rename_idx:
            self.setTabText(idx, name)
        self._rename_idx = -1

    def _duplicate(self, idx):
        data = self.tabData(idx)
        if data:
            self.add_library(str(data))

    def _close_others(self, keep_idx):
        for i in range(self.count() - 1, -1, -1):
            if i != keep_idx:
                self.removeTab(i)


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
        self._add_btn = QPushButton("+")
        self._add_btn.setFixedSize(scaled_px(22), scaled_px(22))
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.clicked.connect(self.add_requested.emit)
        layout.addWidget(self._add_btn)

        self._apply_style()

    def _apply_style(self):
        t = themes.get()
        self._sep.setStyleSheet(
            f"QFrame {{ color: {t['border']}; background: {t['border']}; }}")
        self._add_btn.setStyleSheet(
            f"QPushButton {{ background: {alpha(t['accent'], 0.753)}; color: {t['heading']}; "
            f"border: 1px solid {t['accent']}; border-radius: {scaled_px(10)}px; "
            f"font-size: {scaled_pt(14)}px; font-weight: bold; }} "
            f"QPushButton:hover {{ background: {t['accent']}; color: {t['on_accent']}; "
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
            if path and Path(path).exists():
                self._tabs.add_library(path)

    def current_library(self) -> str | None:
        return self._tabs.current_library()
