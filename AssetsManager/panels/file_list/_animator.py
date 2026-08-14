"""Animation engine for FileListGridWidget (fade, hover, selection, entrance).

Extracted from ``FileListGridWidget`` unchanged: the fade-in +0.12 step, the
hover/selection 0.30 damping and the entrance ``len // 12`` stagger are preserved
verbatim. The ``_reduce_motion`` short-circuit branch is unchanged. The widget
remains the owner of repaint scheduling and performance recording via the
injected ``on_changed`` callback and the ``host`` reference.
"""
from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QTimer

if TYPE_CHECKING:
    from AssetsManager.panels.file_list._grid_widget import FileListGridWidget


class Animator:
    """Owns the grid's animation state and per-tick progression logic."""

    def __init__(
        self,
        parent,
        reduce_motion: bool,
        on_changed: Callable[[set[int]], None],
        host: FileListGridWidget,
    ) -> None:
        self._host = host
        self._on_changed = on_changed
        self._reduce_motion = reduce_motion
        self._thumb_opacity: dict[int, float] = {}
        self._thumbnail_rows: set[int] = set()
        self._hover_progress: dict[int, float] = {}
        self._selection_progress: dict[int, float] = {}
        self._anim_timer = QTimer(parent)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._anim_tick)
        self._entrance_queue: list[int] = []
        self._entrance_visible: set[int] = set()
        self._presented_generation = -1
        self._pending_presentation: tuple[int, list[int], bool] | None = None

    def begin_presentation(self, generation: int, visible_rows: list[int], animate: bool = True) -> bool:
        """Commit one content generation and optionally start its one-shot entrance."""
        host = self._host
        if generation <= self._presented_generation or (
            self._pending_presentation is not None and generation <= self._pending_presentation[0]
        ):
            return False
        if not host.isVisible() or host.width() == 0 or host.height() == 0:
            self._pending_presentation = (generation, list(visible_rows), animate)
            return True
        self._start_presentation(generation, visible_rows, animate)
        return True

    def _present_pending_generation(self) -> None:
        host = self._host
        pending = self._pending_presentation
        if pending is None or not host.isVisible() or host.width() == 0 or host.height() == 0:
            return
        self._pending_presentation = None
        self._start_presentation(*pending)

    def discard_pending_presentation(self, generation: int) -> None:
        """Discard a hidden presentation superseded by an empty newer commit."""
        if self._pending_presentation is not None and self._pending_presentation[0] <= generation:
            self._pending_presentation = None

    def _start_presentation(self, generation: int, visible_rows: list[int], animate: bool) -> None:
        self._presented_generation = generation
        self._entrance_queue.clear()
        self._entrance_visible.clear()
        if self._reduce_motion or not animate:
            return
        self._entrance_queue.extend(row for row in visible_rows if 0 <= row < self._host._model_rows)
        if self._entrance_queue and not self._anim_timer.isActive():
            self._anim_timer.start()

    def _apply_selection_progress(self, old_selection: set[int]) -> None:
        """Seed deselected rows for the selection overlay fade-out."""
        if self._reduce_motion:
            return
        for r in old_selection - self._host._selection:
            self._selection_progress[r] = 1.0
        if self._selection_progress and not self._anim_timer.isActive():
            self._anim_timer.start()

    def stop(self) -> None:
        """Cancel timer and queued entrance state before teardown."""
        self._anim_timer.stop()
        self._entrance_queue.clear()
        self._entrance_visible.clear()
        self._pending_presentation = None

    def _anim_tick(self):
        """Process all animations: fade, hover, selection, entrance stagger."""
        host = self._host
        recorder = host._performance_recorder
        started = perf_counter() if recorder is not None else None
        session_token = host._performance_session_token
        generation = host._performance_generation
        active = False
        changed_rows: set[int] = set()

        if self._reduce_motion and self._hover_progress:
            changed_rows.update(self._hover_progress)
            self._hover_progress.clear()

        # Thumbnail fade-in: linear step per frame
        for row in list(self._thumb_opacity):
            v = self._thumb_opacity[row] + 0.12
            if v >= 1.0:
                del self._thumb_opacity[row]
            else:
                self._thumb_opacity[row] = v
                active = True
            changed_rows.add(row)

        # Hover fade-out (only deselected rows are animated)
        for row in list(self._hover_progress):
            target = 1.0 if row == host._hover_row else 0.0
            cur = self._hover_progress[row]
            cur += (target - cur) * 0.30
            if abs(cur - target) < 0.01:
                if target == 0.0:
                    del self._hover_progress[row]
                else:
                    self._hover_progress[row] = 1.0
                changed_rows.add(row)
                continue
            self._hover_progress[row] = cur
            active = True
            changed_rows.add(row)

        # Selection fade-out (only deselected rows are animated)
        for row in list(self._selection_progress):
            cur = self._selection_progress[row]
            cur += (0.0 - cur) * 0.30
            if abs(cur) < 0.01:
                del self._selection_progress[row]
                changed_rows.add(row)
                continue
            self._selection_progress[row] = cur
            active = True
            changed_rows.add(row)

        # Entrance stagger: reveal next item in queue each tick
        if self._entrance_queue and not host._zoom_relayout_active:
            n = max(1, len(self._entrance_queue) // 12)
            for _ in range(n):
                if self._entrance_queue:
                    r = self._entrance_queue.pop(0)
                    self._entrance_visible.add(r)
                    self._thumb_opacity[r] = 0.0
                    changed_rows.add(r)
            active = True

        if not active:
            self._anim_timer.stop()
        self._on_changed(changed_rows)
        visible_count = 0
        if recorder is not None and host._layout is not None:
            visible_count = len(host._layout.visible_rows(host._scroll_y, host.height()))
        host._record_performance("grid.animation_tick", started, session_token, generation, visible_count)
