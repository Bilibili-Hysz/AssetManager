"""Typed host contracts for the FileListPanel mixins.

``FileListPanel`` composes ``NavigationMixin`` and ``ActionsMixin``; those
mixins reach into a fixed set of host attributes/methods.  This module names
those surfaces explicitly so the host dependency is documented in one place
instead of scattered through ``if TYPE_CHECKING:`` blocks, and so the host can
be type-checked against them (both protocols are satisfied by
``FileListPanel``).
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Protocol

from PySide6.QtCore import QFileSystemWatcher, QModelIndex
from PySide6.QtWidgets import QComboBox, QHBoxLayout

if TYPE_CHECKING:
    from AssetsManager.panels.file_list._detail_model import DetailModel
    from AssetsManager.panels.file_list._loader import ThumbnailLoader
    from AssetsManager.panels.file_list._model import FileSystemModel


class FileListHost(Protocol):
    """The host surface required by ``NavigationMixin``."""

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


class FileListActionsHost(Protocol):
    """The host surface required by ``ActionsMixin``.

    Mirrors the ``if TYPE_CHECKING:`` block in ``_actions.py``; keep the two in
    sync.  ``ActionsMixin`` also reaches ``_lib_root`` and ``navigate_to``,
    which ``NavigationMixin`` supplies on the composed panel.
    """

    _model: FileSystemModel
    _detail_model: DetailModel
    _detail_view: Any
    _current: Path
    _tags_port: Any
    file_selected: Any
    file_double_clicked: Any

    @property
    def _lib_root(self) -> str | None: ...
    @property
    def _view_mode(self) -> str: ...

    def navigate_to(self, path, *, set_root: bool = False) -> None: ...
    def _post_refresh(self) -> None: ...
    def _view_selected_rows(self) -> list[QModelIndex]: ...
    def _view_edit_index(self, idx: QModelIndex) -> bool: ...
    def _get_scoped_services(self) -> Any: ...
    def _get_file_operation_service(self) -> Any: ...
    def _get_tag_service(self) -> Any: ...
    def _is_current_operation_session(self, session) -> bool: ...
    def _request_operation_selection(self, session, paths) -> None: ...
    def _deletion_selection_candidates(self, paths) -> tuple[str, ...]: ...
    def _show_operation_feedback(
        self,
        session,
        operation: str,
        *,
        changed_count: int = 0,
        errors: tuple[str, ...] = (),
        warnings: tuple[object, ...] = (),
        running: bool = False,
    ) -> None: ...
