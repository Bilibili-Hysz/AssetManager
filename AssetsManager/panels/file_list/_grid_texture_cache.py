"""Owned texture cache for FileListGridWidget's card textures.

Extracted from ``FileListGridWidget`` unchanged: LRU ordering
(``move_to_end``/``popitem(last=False)``) and the 200-entry eviction threshold are
preserved verbatim. Byte accounting only happens while the injected ``recorder``
callable returns a non-None recorder.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Callable

from PySide6.QtGui import QPixmap

# Path texture cache limit — matching _grid_widget's original module constant.
_PATH_TEXTURE_CACHE_LIMIT = 200


class GridTextureCache:
    """Row-keyed card textures plus byte accounting and path-texture mapping."""

    def __init__(
        self,
        *,
        recorder: Callable[[], Any],
        session_token: Callable[[], str | None],
        generation: Callable[[], int | None],
        model: Callable[[], Any],
        scan_reset_pending: Callable[[], bool],
    ) -> None:
        self._recorder = recorder
        self._session_token = session_token
        self._generation = generation
        self._model = model
        self._scan_reset_pending = scan_reset_pending
        self._textures: OrderedDict[int, QPixmap] = OrderedDict()
        self._path_textures: OrderedDict[str, QPixmap] = OrderedDict()
        self._texture_bytes: dict[int, int] = {}
        self._texture_cache_bytes = 0

    def take_path_texture(self, path: str) -> QPixmap | None:
        """Pop and return the path-keyed texture cached for ``path`` (or None)."""
        return self._path_textures.pop(path, None)

    def _clear_textures(self) -> None:
        self._textures.clear()
        self._texture_bytes.clear()
        self._texture_cache_bytes = 0

    def _store_texture_bytes(self, row: int, texture: QPixmap) -> None:
        if self._recorder() is None:
            return
        previous = self._texture_bytes.pop(row, 0)
        byte_size = max(0, texture.width() * texture.height() * 4)
        self._texture_bytes[row] = byte_size
        self._texture_cache_bytes = max(0, self._texture_cache_bytes - previous + byte_size)

    def _cache_texture(self, row: int, texture: QPixmap) -> None:
        if row not in self._textures and len(self._textures) >= 200:
            evicted_row, _ = self._textures.popitem(last=False)
            self._remove_texture_bytes(evicted_row)
            self._record_texture_eviction()
        self._textures[row] = texture
        self._store_texture_bytes(row, texture)

    def _remove_texture_bytes(self, row: int) -> None:
        if self._recorder() is None:
            return
        self._texture_cache_bytes = max(0, self._texture_cache_bytes - self._texture_bytes.pop(row, 0))

    def _refresh_texture_accounting(self) -> None:
        self._texture_bytes = {
            row: max(0, texture.width() * texture.height() * 4)
            for row, texture in self._textures.items()
        }
        self._texture_cache_bytes = sum(self._texture_bytes.values())

    def _record_texture_eviction(self) -> None:
        recorder = self._recorder()
        if recorder is None:
            return
        try:
            recorder.record(
                "grid.texture_eviction",
                0.0,
                session_token=self._session_token(),
                generation=self._generation(),
                attributes={
                    "texture_cache_count": len(self._textures),
                    "texture_cache_bytes": self._texture_cache_bytes,
                },
            )
        except Exception:
            # Diagnostics must not affect texture cache eviction or rendering state.
            pass

    def _capture_path_textures(self) -> None:
        """Keep card textures available across sort/filter model resets."""
        if self._scan_reset_pending():
            self._path_textures.clear()
            return
        model = self._model()
        if model is None:
            return
        for row, texture in list(self._textures.items()):
            path = model.path_at(row)
            if not path:
                continue
            self._path_textures[path] = texture
            self._path_textures.move_to_end(path)
        while len(self._path_textures) > _PATH_TEXTURE_CACHE_LIMIT:
            self._path_textures.popitem(last=False)
