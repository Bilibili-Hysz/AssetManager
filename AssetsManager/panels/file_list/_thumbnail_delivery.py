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
        if self._model.is_shutdown:
            return
        if image is None or image.isNull():
            return
        started = self._grid_widget.start_thumbnail_delivery_measurement()
        # Defensive downscale: workers usually deliver at self._size, but
        # original/high quality modes can hand back full-size images whose
        # main-thread QPixmap.fromImage would stall the UI.
        if image.width() > 512 or image.height() > 512:
            image = image.scaled(
                512, 512, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
        pixmap = QPixmap.fromImage(image)
        self._grid_widget.record_thumbnail_pixmap(started)
        index = self._model.index(row, 0)
        if not index.isValid() or self._model.path_at(row) != path:
            return
        entry = self._model.entry_at(row)
        if entry is not None:
            self._model.set_raw_pixmap(entry.path, pixmap)
        self._model.clear_thumbnail_failed(path)
        # Deliberate bypass: FileSystemModel.setData(DecorationRole) stores the
        # icon without emitting dataChanged. Thumbnail invalidation is owned by
        # this coordinator (batched below into commit_thumbnail_rows), so a
        # per-item model signal would double-invalidate the grid. Do not "fix"
        # setData to emit dataChanged without removing this batching.
        self._model.setData(index, QIcon(pixmap), Qt.ItemDataRole.DecorationRole)
        self._batch[row] = path
        self._timer.start()

    def handle_failed(self, path: str) -> None:
        """Repaint the cell whose thumbnail load failed (danger marker).

        Runs on the main thread via the loader's queued ``thumbnail_failed``
        signal.  The path is validated against the current row layout so a
        stale failure cannot mark the wrong entry after a refresh.
        """
        if self._model.is_shutdown:
            return
        row = self._model.row_for_path(path)
        if row < 0 or self._model.path_at(row) != path:
            return
        self._model.mark_thumbnail_failed(path)
        self._grid_widget.invalidate_failed_row(row)

    def flush(self) -> None:
        if self._model.is_shutdown:
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
