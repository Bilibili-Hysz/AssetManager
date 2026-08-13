"""Shared dock factory — creates consistent QDockWidgets with custom title bars.

All docks get a themed title bar with:
  - Title label
  - Float/pop-out button
  - Close button
  - Optional extra buttons (gear for settings, etc.)
  - Optional panel extension widget

Panels can provide extra buttons via a title_bar_buttons() method.
"""
from __future__ import annotations

from typing import Protocol, cast

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QDockWidget, QMainWindow, QMenu, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
)

from AssetsManager.panels.sidebar import SidebarPanel
from AssetsManager.panels.info import InfoPanel
from AssetsManager.panels.empty import EmptyPanel
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.panels.tag_tree import TagTreePanel
from AssetsManager.panels.image_viewer import ImageViewer
from AssetsManager.widgets.tab_container import TabContainer
from AssetsManager import i18n
from AssetsManager.core import icons
from AssetsManager.core import themes
from AssetsManager.core.signal_bus import get as bus

tr = i18n.tr

PANELS = {
    "sidebar":       ("dock.sidebar",      SidebarPanel),
    "file_list_tabs": ("dock.file_list",   TabContainer),
    "info":          ("dock.info",         InfoPanel),
    "tag_tree":      ("dock.tag_tree",     TagTreePanel),
    "image_viewer":  ("dock.image_viewer", ImageViewer),
    "empty":         ("dock.empty",        EmptyPanel),
}

_DOCK_TITLES: dict[QDockWidget, tuple[str, str, list]] = {}  # dock -> (i18n_key, title, extra_buttons)


class _DockPanel(Protocol):
    content_layout: QVBoxLayout

    def footer_bar(self) -> QWidget | None: ...

    def title_bar_buttons(self) -> list[QWidget]: ...

    def title_bar_extension(self) -> QWidget | None: ...

    def shutdown(self) -> None: ...


def create(title: str = "Panel", parent: QMainWindow | None = None, area=Qt.DockWidgetArea.RightDockWidgetArea,
           panel_type: str = "empty"):
    panel_info = PANELS.get(panel_type)
    if panel_info:
        i18n_key, panel_cls = panel_info
        title = tr(i18n_key)
    else:
        i18n_key = "dock.empty"
        panel_cls = EmptyPanel
    widget = panel_cls()

    dock = QDockWidget(title, parent)
    dock.setWidget(widget)
    dock.setMinimumWidth(scaled_px(120))
    dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable |
                     QDockWidget.DockWidgetFeature.DockWidgetFloatable)
    dock.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    dock.customContextMenuRequested.connect(lambda pos, d=dock, w=parent: _menu(pos, d, w))
    if parent is not None:
        parent.addDockWidget(area, dock)

    extra_buttons: list[QWidget] = []
    title_buttons = getattr(widget, "title_bar_buttons", None)
    if callable(title_buttons):
        buttons = title_buttons()
        if isinstance(buttons, list) and all(isinstance(button, QWidget) for button in buttons):
            extra_buttons = buttons
    dock.setTitleBarWidget(_build_title_bar(title, dock, extra_buttons))
    _DOCK_TITLES[dock] = (i18n_key, title, extra_buttons)

    _attach_footer(widget)

    return dock


def _attach_footer(widget: QWidget):
    footer_bar = getattr(widget, "footer_bar", None)
    footer = footer_bar() if callable(footer_bar) else None
    if isinstance(footer, QWidget):
        cast(_DockPanel, widget).content_layout.addWidget(footer)


def _build_title_bar(dock_title: str, dock: QDockWidget,
                     extra_buttons: list[QWidget]) -> QWidget:
    t = themes.get()
    bar = QWidget()
    bar.setProperty("is_custom_title", True)
    bar.setStyleSheet(
        f"background: {themes.header_for_dock()}; "
        f"border: 1px solid {t['border']}; "
        f"border-top-left-radius: {scaled_px(7)}px; border-top-right-radius: {scaled_px(7)}px; ")

    layout = QHBoxLayout(bar)
    layout.setContentsMargins(scaled_px(10), scaled_px(3), scaled_px(6), scaled_px(3))
    layout.setSpacing(scaled_px(4))

    title_label = QLabel(f"  {dock_title}")
    title_label.setStyleSheet(
        f"color: {t['heading']}; font-size: {scaled_pt(12)}px; font-weight: bold; "
        f"background: transparent; border: none; padding: {scaled_px(2)}px {scaled_px(4)}px;")
    layout.addWidget(title_label)

    # ── Panel extension slot ─────────────────────────────────
    panel = dock.widget()
    extension = getattr(panel, "title_bar_extension", None)
    if callable(extension):
        ext = extension()
        if isinstance(ext, QWidget):
            layout.addWidget(ext, 1)

    for btn in extra_buttons:
        semantic_icon = btn.property("semanticIcon")
        if semantic_icon and isinstance(btn, QPushButton):
            btn.setIcon(icons.icon(semantic_icon, color="icon_primary", size=scaled_px(15)))

    layout.addStretch()

    for btn in extra_buttons:
        layout.addWidget(btn)

    btn_style = (
        f"color: {t['heading']}; font-size: {scaled_pt(14)}px; font-weight: bold; "
        f"padding: 0; background: transparent; border: none; border-radius: {scaled_px(3)}px;")

    _dock = dock
    float_btn = QPushButton()
    float_btn.setIcon(icons.icon("maximize", color="icon_primary", size=scaled_px(15)))
    float_btn.setIconSize(QSize(scaled_px(15), scaled_px(15)))
    float_btn.setToolTip(tr("dock.float"))
    float_btn.setAccessibleName(tr("dock.float"))
    float_btn.setFixedSize(scaled_px(20), scaled_px(20))
    float_btn.setFlat(True)
    themes.set_button_variant(float_btn, "ghost")
    float_btn.setStyleSheet(btn_style)
    float_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    float_btn.clicked.connect(lambda: _dock.setFloating(not _dock.isFloating()))
    layout.addWidget(float_btn)

    close_btn = QPushButton()
    close_btn.setIcon(icons.icon("close", color="icon_primary", size=scaled_px(15)))
    close_btn.setIconSize(QSize(scaled_px(15), scaled_px(15)))
    close_btn.setToolTip(tr("dock.close"))
    close_btn.setAccessibleName(tr("dock.close"))
    close_btn.setFixedSize(scaled_px(20), scaled_px(20))
    close_btn.setFlat(True)
    themes.set_button_variant(close_btn, "ghost")
    close_btn.setStyleSheet(btn_style)
    close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    close_btn.clicked.connect(lambda: _close_dock(_dock))
    layout.addWidget(close_btn)

    return bar


def _menu(pos, dock, window):
    menu = QMenu(dock)
    menu.addAction(tr("dock.split_h"),
                   lambda: _split(dock, window, Qt.Orientation.Horizontal))
    menu.addAction(tr("dock.split_v"),
                   lambda: _split(dock, window, Qt.Orientation.Vertical))
    menu.addSeparator()
    menu.addAction(tr("dock.close"), lambda: _close_dock(dock, window))
    menu.exec(dock.mapToGlobal(pos))


def _close_dock(dock, window=None):
    panel = dock.widget()
    shutdown = getattr(panel, "shutdown", None)
    if callable(shutdown):
        shutdown()
    # The title-bar close button calls without a window; resolve the parent
    # so the dock is actually removed from the QMainWindow layout.
    if window is None:
        window = dock.parentWidget()
    if window is not None:
        window.removeDockWidget(dock)
    _DOCK_TITLES.pop(dock, None)
    dock.deleteLater()


def _split(dock, window, orientation):
    if window is None:
        return
    new_dock = create(tr("dock.new"), window, window.dockWidgetArea(dock))
    window.splitDockWidget(dock, new_dock, orientation)


def _close(dock, window):
    _close_dock(dock, window)


def _refresh_docks_on_theme(_name: str = ""):
    """Rebuild all dock title bars when theme changes."""
    for d, (i18n_key, title, btns) in list(_DOCK_TITLES.items()):
        try:
            if d.widget() is not None:
                d.setTitleBarWidget(_build_title_bar(title, d, btns))
        except RuntimeError:
            _DOCK_TITLES.pop(d, None)


def _refresh_docks_on_language(_code: str = ""):
    """Update dock titles when language changes."""
    for d, (i18n_key, _old_title, btns) in list(_DOCK_TITLES.items()):
        try:
            if d.widget() is not None:
                new_title = tr(i18n_key)
                _DOCK_TITLES[d] = (i18n_key, new_title, btns)
                d.setTitleBarWidget(_build_title_bar(new_title, d, btns))
        except RuntimeError:
            _DOCK_TITLES.pop(d, None)


def install_dock_refresh_handlers():
    """Install theme/language refresh handlers on the signal bus.

    Must be called once during application startup before any dock is created.
    """
    bus().theme_changed.connect(_refresh_docks_on_theme)
    bus().language_changed.connect(_refresh_docks_on_language)
