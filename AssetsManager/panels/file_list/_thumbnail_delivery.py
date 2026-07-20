"""Main-thread thumbnail delivery and Grid batch coordination."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QIcon, QPixmap

if TYPE_CHECKING:
    from AssetsManager.panels.file_list._grid_widget import FileListGridWidget
    from AssetsManager.panels.file_list._model import FileSystemModel


class ThumbnailDeliveryCoordinator:
    """Apply validated thumbnail results and coalesce Grid invalidations."""

    def __init__(self, model: FileSystemModel, grid_widget: FileListGridWidget) -> None:
        self._model = model
        self._grid_widget = grid_widget
        self._batch: dict[int, str] = {}
        self._timer = QTimer(grid_widget)
        self._timer.setSingleShot(True)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self.flush)

    def clear(self) -> None:
        self._batch.clear()
        self._timer.stop()

    def handle_ready(self, row: int, path: str, image) -> None:
        if self._model._is_shutdown:
            return
        if image is None or image.isNull():
            return
        started = self._grid_widget.start_thumbnail_delivery_measurement()
        pixmap = QPixmap.fromImage(image)
        self._grid_widget.record_thumbnail_pixmap(started)
        index = self._model.index(row, 0)
        if not index.isValid() or self._model.path_at(row) != path:
            return
        entry = self._model.entry_at(row)
        if entry is not None:
            self._model._raw_pixmaps[entry.path] = pixmap
        self._model.setData(index, QIcon(pixmap), Qt.ItemDataRole.DecorationRole)
        self._batch[row] = path
        self._timer.start()

    def flush(self) -> None:
        if self._model._is_shutdown:
            self.clear()
            return
        if not self._batch:
            return
        rows = [
            row for row, path in self._batch.items()
            if self._model.index(row, 0).isValid() and self._model.path_at(row) == path
        ]
        self._batch.clear()
        if not rows:
            return
        rows.sort()
        self._grid_widget.record_thumbnail_batch(len(rows))
        self._grid_widget.commit_thumbnail_rows(rows)
