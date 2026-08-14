"""Instance-independent UI helpers extracted from the file-list panel and grid.

Every symbol here was moved verbatim from ``_base.py`` or ``_grid_widget.py``;
the owning classes keep thin delegates with the same names, so call sites and
behavior are unchanged.  None of these helpers touch instance state, so they
become plain module functions used by both the panel and the grid canvas.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QMenu, QPushButton, QStyledItemDelegate

from AssetsManager.core import icons
from AssetsManager.core import themes
from AssetsManager.core.color_utils import _hex_to_rgb
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager import i18n
from AssetsManager.application.asset_filters import find_first_image
from AssetsManager.panels.file_list._commands import FileListCommand, FileListCommandContext

tr = i18n.tr


class _DetailsItemDelegate(QStyledItemDelegate):
    """Keep Details rows comfortably readable without per-row widgets."""

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), scaled_px(32)))
        return size


def _make_folder_highlight(t: dict) -> QColor:
    r, g, b = _hex_to_rgb(t["hover_overlay"])
    return QColor(r, g, b, 80)


def _first_image_in(dir_path: str) -> str | None:
    # Delegates to the shared application helper (capped scan to avoid a long
    # synchronous scandir on the GUI thread for huge directories).
    result = find_first_image(Path(dir_path), limit=500)
    return str(result) if result is not None else None


def _make_nav_button(icon_name, tooltip, callback):
    btn = QPushButton()
    btn.setIcon(icons.icon(icon_name, color="icon_secondary", size=scaled_px(16)))
    btn.setIconSize(QSize(scaled_px(16), scaled_px(16)))
    btn.setProperty("semanticIcon", icon_name)
    btn.setFixedSize(scaled_px(26), scaled_px(26))
    btn.setToolTip(tooltip)
    btn.setAccessibleName(tooltip)
    themes.set_button_variant(btn, "ghost")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.clicked.connect(callback)
    return btn


def _is_external_drop(event) -> bool:
    urls = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
    return bool(urls)


def _always(_context: FileListCommandContext) -> bool:
    return True


def _add_command_group(
    menu: QMenu,
    commands: tuple[FileListCommand, ...],
    context: FileListCommandContext,
    group: str,
) -> None:
    projected = [command for command in commands if command.group == group and command.visible_when(context)]
    if not projected:
        return
    if menu.actions():
        menu.addSeparator()
    for command in projected:
        action = menu.addAction(tr(command.label_key), command.invoke)
        action.setEnabled(command.enabled_when(context))
        if command.shortcut:
            action.setShortcut(command.shortcut)


def _save_search_term(term: str):
    from AssetsManager.controllers.file_list_controller import FileListController
    FileListController.save_search_term(term)
