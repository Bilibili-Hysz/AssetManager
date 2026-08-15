"""Typed host contract for the FileListPanel mixins.

``FileListPanel`` composes ``NavigationMixin`` and ``ActionsMixin``; those
mixins reach into a fixed set of host attributes/methods.  This module names
that surface explicitly so the host dependency is documented in one place
instead of scattered through ``if TYPE_CHECKING:`` blocks, and so the host can
be type-checked against it (``FileListHost`` is satisfied by ``FileListPanel``).
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Protocol

from PySide6.QtCore import QFileSystemWatcher
from PySide6.QtWidgets import QComboBox, QHBoxLayout

if TYPE_CHECKING:
    from AssetsManager.panels.file_list._loader import ThumbnailLoader
    from AssetsManager.panels.file_list._model import FileSystemModel


class FileListHost(Protocol):
    """The host surface required by ``NavigationMixin``.

    ``ActionsMixin`` adds its own surface on top of this; that surface is
    intentionally not enumerated here yet because ``_actions.py`` is not part
    of the pyright whitelist (typing it fully is a separate follow-up).
    """

    _model: FileSystemModel
    _loader: ThumbnailLoader
    _fs_watcher: QFileSystemWatcher
    _first_image_cache: dict[str, str | None]
    _last_click_row: int
    _current: Path
    _root: Path | None
    _history: list[str]
    _forward_list: list[str]
    _view_memory: dict[str, str]

    @property
    def _view_mode(self) -> str: ...
    _view_combo: QComboBox
    _bc_layout: QHBoxLayout
    folder_entered: Any

    def _configure_library_runtime(self, root: str) -> None: ...
    def _populate_details(self) -> None: ...
    def _post_refresh(self) -> None: ...
    def _clear_selection_for_navigation(self) -> None: ...
    def _update_status(self) -> None: ...
    def _load_visible(self) -> None: ...
    def _run_in_background(self, func: Callable[[], None]) -> None: ...
