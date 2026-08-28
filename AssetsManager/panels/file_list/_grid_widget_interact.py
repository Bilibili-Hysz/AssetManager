"""Interaction and event handling for the file list grid widget.

``InteractMixin`` owns every input path: mouse, keyboard and wheel events,
rubber-band and hover selection, scrolling, inline rename, frame-request
coalescing with its one-shot timer plumbing, and the animator-facing
presentation API.

Drawing lives in ``_grid_widget_render.py``; data binding and layout live in
``_grid_widget_data.py``; ``_grid_widget.py`` composes the three.
"""
from __future__ import annotations

import weakref
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import Qt, QRect, QPoint, QEvent
from PySide6.QtWidgets import QWidget, QScrollBar

from shiboken6 import Shiboken

from AssetsManager.core.timers import TimerHandle
from AssetsManager.core.ui_scale import scaled_px

if TYPE_CHECKING:
    from AssetsManager.panels.file_list._grid_layout import GridLayout
    from AssetsManager.panels.file_list._model import FileSystemModel
    from AssetsManager.panels.file_list._animator import Animator


class InteractMixin:
    """Event handling, selection, scrolling and frame scheduling."""

    if TYPE_CHECKING:
        # Host surface owned by FileListGridWidget / sibling mixins.
        _layout: GridLayout | None
        _model: FileSystemModel | None
        _model_rows: int
        _animator: Animator
        _scroll_y: int
        _scrollbar: QScrollBar
        _full_rebuild_epoch: int
        _full_rebuild_pending: bool
        _full_rebuild_update_queued: bool
        _performance_recorder: Any
        _performance_session_token: str | None
        _performance_generation: int | None
        clicked: Any
        double_clicked: Any
        context_menu: Any
        selection_changed: Any
        rename_requested: Any

        def update(self, *args: Any) -> None: ...
        def rect(self) -> QRect: ...
        def width(self) -> int: ...
        def height(self) -> int: ...
        def mapFromGlobal(self, pos: QPoint) -> QPoint: ...
        def cursor(self) -> Any: ...
        def set_scrolling(self, active: bool = True) -> None: ...
        def update_layout(self, item_count: int, widget_width: int, *, relayout_only: bool = False) -> None: ...

    def _on_anim_changed(self, changed_rows: set[int]) -> None:
        self._request_frame(changed_rows, overlay=True)

    def selection_model_rows(self) -> set[int]:
        return self._selection.copy()

    def select_all(self):
        old = self._selection.copy()
        self._selection = set(range(self._model_rows))
        self._animator.apply_selection_progress(old)
        if old != self._selection:
            self.selection_changed.emit()
        self._request_frame(self._selection | old, overlay=True)

    def clear_selection(self):
        old = self._selection.copy()
        self._selection.clear()
        self._animator.apply_selection_progress(old)
        self.selection_changed.emit()
        self._request_frame(old, overlay=True)

    def reduce_motion_enabled(self) -> bool:
        """Expose the animator's reduce-motion mode without leaking internals."""
        return self._animator.reduce_motion

    def set_selection_rows(self, rows: set[int]) -> None:
        """Replace the selection from the panel with fade-out seeding."""
        old = self._selection.copy()
        self._selection = set(rows)
        if old != self._selection:
            self._animator.apply_selection_progress(old)
            self.selection_changed.emit()
            self.update()

    def _schedule_once(self, interval_ms: int, callback):
        """Schedule an owned one-shot timer, cancelable on shutdown."""
        self._single_shot_handles = [
            handle for handle in self._single_shot_handles if handle.is_active()
        ]
        handle = TimerHandle.schedule(cast(QWidget, self), interval_ms, callback)
        self._single_shot_handles.append(handle)
        return handle

    def cancel_pending_timers(self) -> None:
        for handle in self._single_shot_handles:
            handle.cancel()
        self._single_shot_handles.clear()

    def showEvent(self, event):
        QWidget.showEvent(cast(QWidget, self), event)
        if self._animator.has_pending_presentation():
            self._schedule_once(0, self._animator.present_pending)

    def _cancel_frame(self) -> None:
        self._frame_epoch += 1
        self._frame_queued = False
        self._frame_full = False
        self._frame_rect = QRect()
        self._frame_request_count = 0

    def _request_frame(self, rows=None, *, full: bool = False, overlay: bool = False) -> None:
        """Coalesce visual invalidations until Qt can schedule one repaint."""
        self._frame_request_count += 1
        if full or self._frame_full:
            self._frame_full = True
        elif rows is not None and self._layout is not None and hasattr(self._layout, "rect_at"):
            for row in rows:
                rect = self._layout.rect_at(row)
                if rect is None:
                    continue
                padding = (
                    max(scaled_px(8), int(max(rect.width(), rect.height()) * 0.05) + scaled_px(6))
                    if overlay else scaled_px(2)
                )
                viewport_rect = rect.translated(0, -self._scroll_y).adjusted(
                    -padding, -padding, padding, padding)
                viewport_rect = viewport_rect.intersected(self.rect())
                if not viewport_rect.isEmpty():
                    self._frame_rect = (
                        viewport_rect if self._frame_rect.isNull() else self._frame_rect.united(viewport_rect)
                    )
        elif rows is not None:
            self._frame_full = True
        if self._frame_queued:
            return
        self._frame_queued = True
        epoch = self._frame_epoch
        widget_ref = weakref.ref(self)

        def flush() -> None:
            widget = widget_ref()
            if widget is not None and Shiboken.isValid(widget):
                widget._flush_frame(epoch)

        self._schedule_once(0, flush)

    def _flush_frame(self, epoch: int) -> None:
        if epoch != self._frame_epoch:
            return
        self._frame_queued = False
        full = self._frame_full
        rect = self._frame_rect
        request_count = self._frame_request_count
        self._frame_full = False
        self._frame_rect = QRect()
        self._frame_request_count = 0
        self._record_frame_request(full, rect, request_count)
        if full:
            self.update()
        elif not rect.isEmpty():
            self.update(rect)

    def _record_frame_request(self, full: bool, rect: QRect, request_count: int) -> None:
        recorder = self._performance_recorder
        if recorder is None:
            return
        try:
            recorder.record(
                "grid.frame_request",
                0.0,
                session_token=self._performance_session_token,
                generation=self._performance_generation,
                attributes={
                    "full": full,
                    "coalesced_request_count": request_count,
                    "dirty_width": 0 if full else rect.width(),
                    "dirty_height": 0 if full else rect.height(),
                },
            )
        except Exception:
            # Diagnostics must not affect frame scheduling or repaint state.
            pass

    # ── Animation engine ─────────────────────────────────────

    @staticmethod
    def _detect_reduce_motion() -> bool:
        try:
            from AssetsManager.core.settings import AppSettings
            return AppSettings.instance().get("reduce_motion", False)
        except Exception:
            return False

    def begin_presentation(self, generation: int, visible_rows: list[int], animate: bool = True) -> bool:
        """Commit one content generation and optionally start its one-shot entrance."""
        return self._animator.begin_presentation(generation, visible_rows, animate)

    def discard_pending_presentation(self, generation: int) -> None:
        """Discard a hidden presentation superseded by an empty newer commit."""
        self._animator.discard_pending_presentation(generation)

    def _queue_full_rebuild_update(self) -> None:
        if self._full_rebuild_update_queued:
            return
        self._full_rebuild_update_queued = True
        epoch = self._full_rebuild_epoch
        widget_ref = weakref.ref(self)

        def update() -> None:
            widget = widget_ref()
            if widget is None or not Shiboken.isValid(widget):
                return
            widget._full_rebuild_update_queued = False
            if epoch != widget._full_rebuild_epoch:
                return
            if widget._full_rebuild_pending:
                widget._request_frame(full=True)

        self._schedule_once(0, update)

    # ── Scroll ───────────────────────────────────────────────

    def _relayout_scrollbar(self):
        if self.width() <= 0 or self.height() <= 0:
            return
        scrollbar_w = scaled_px(6)
        self._scrollbar.setGeometry(self.width() - scrollbar_w, 0, scrollbar_w, self.height())

    def scroll_to(self, row: int):
        if self._layout:
            rect = self._layout.rect_at(row)
            if rect:
                self._scrollbar.setValue(rect.top() - self.height() // 4)

    def _on_scroll(self, value: int):
        self._scroll_y = value
        self.set_scrolling()
        # Scrolling shifts the whole visible content, so the full viewport must
        # be repainted every frame. Each visible card texture is re-drawn at its
        # new offset (cheap per-cell drawPixmap); a partial repaint would leave
        # stale pixels in the region that did not receive a new cell.
        self._request_frame(full=True)

    # ── Resize ───────────────────────────────────────────────

    def resizeEvent(self, event):
        QWidget.resizeEvent(cast(QWidget, self), event)
        self._relayout_scrollbar()
        if self._model_rows > 0:
            self.update_layout(self._model_rows, self.width())
        self._request_frame(full=True)

    # ── Mouse events ─────────────────────────────────────────

    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        pos.setY(pos.y() + self._scroll_y)
        old_selection = self._selection.copy()
        if self._layout:
            row = self._layout.row_at(pos.x(), pos.y())
            if row >= 0:
                if event.button() == Qt.MouseButton.LeftButton:
                    if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                        if row in self._selection:
                            self._selection.discard(row)
                        else:
                            self._selection.add(row)
                        self.clicked.emit(row)
                    elif (event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                          and self._last_click_row >= 0):
                        lo = min(row, self._last_click_row)
                        hi = max(row, self._last_click_row)
                        self._selection = set(range(lo, hi + 1))
                        self.clicked.emit(row)
                    else:
                        self._click_pending_row = row
                        if row not in self._selection:
                            self._selection = {row}
                            self.clicked.emit(row)
                    self._last_click_row = row
                    self._hover_row = row
                    self.selection_changed.emit()
                    # Seed selection progress for animation
                    self._animator.apply_selection_progress(old_selection)
                    self._request_frame(self._selection | old_selection, overlay=True)
            elif event.button() == Qt.MouseButton.LeftButton:
                self._rubber_band_active = True
                self._rubber_band_origin = QPoint(pos)
                self._rubber_band_rect = QRect(pos.x(), pos.y(), 0, 0)
                if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                    old_sel = self._selection.copy()
                    self._selection.clear()
                    self._animator.apply_selection_progress(old_sel)
                self.selection_changed.emit()
                self._request_frame(full=True)
        QWidget.mousePressEvent(cast(QWidget, self), event)

    def mouseDoubleClickEvent(self, event):
        pos = event.position().toPoint()
        pos.setY(pos.y() + self._scroll_y)
        if self._layout:
            row = self._layout.row_at(pos.x(), pos.y())
            if row >= 0:
                self.double_clicked.emit(row)
        QWidget.mouseDoubleClickEvent(cast(QWidget, self), event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        pos.setY(pos.y() + self._scroll_y)
        if self._rubber_band_active and self._rubber_band_origin:
            self._rubber_band_rect = QRect(self._rubber_band_origin, pos).normalized()
            if self._layout:
                preview_sel = set()
                visible = self._layout.visible_rows(self._scroll_y, self.height())
                for r in visible:
                    item_rect = self._layout.rect_at(r)
                    if item_rect and self._rubber_band_rect.intersects(item_rect):
                        preview_sel.add(r)
                if preview_sel != self._selection:
                    # Seed selection progress for animation
                    if not self._animator.reduce_motion:
                        for r in preview_sel - self._selection:
                            self._animator.setdefault_selection_progress(r, 0.0)
                        for r in self._selection - preview_sel:
                            if not self._animator.has_selection_progress(r):
                                self._animator.setdefault_selection_progress(r, 1.0)
                        self._animator.ensure_running()
                    self._selection = preview_sel
                    self.selection_changed.emit()
            self._request_frame(full=True)
        elif self._layout:
            # Freeze hover during potential drag (left button held on an item)
            if (event.buttons() & Qt.MouseButton.LeftButton
                    and not self._rubber_band_active
                    and self._click_pending_row >= 0):
                QWidget.mouseMoveEvent(cast(QWidget, self), event)
                return
            row = self._layout.row_at(pos.x(), pos.y())
            if self._hover_row != row:
                old = self._hover_row
                self._hover_row = row
                if not self._animator.reduce_motion:
                    if old >= 0:
                        self._animator.setdefault_hover_progress(old, 1.0)
                    if row >= 0:
                        self._animator.setdefault_hover_progress(row, 0.0)
                    self._animator.ensure_running()
                self._request_frame([old, row], overlay=True)
        QWidget.mouseMoveEvent(cast(QWidget, self), event)

    def mouseReleaseEvent(self, event):
        if self._rubber_band_active:
            self._rubber_band_active = False
            if self._layout and not self._rubber_band_rect.isNull():
                final_sel = set()
                rect = self._rubber_band_rect
                ih = self._layout._item_h
                first_row = max(0, rect.top() // ih)
                last_row = min(self._model_rows - 1, (rect.bottom() + ih - 1) // ih)
                for r in range(first_row, last_row + 1):
                    item_rect = self._layout.rect_at(r)
                    if item_rect and rect.intersects(item_rect):
                        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                            self._selection.discard(r)
                        else:
                            self._selection.add(r)
                            final_sel.add(r)
                # Seed progress for final selection
                if not self._animator.reduce_motion and final_sel:
                    for r in final_sel:
                        self._animator.setdefault_selection_progress(r, 0.0)
                    self._animator.ensure_running()
                self.selection_changed.emit()
            self._rubber_band_origin = None
            self._rubber_band_rect = QRect()
            self._request_frame(full=True)
        elif self._click_pending_row >= 0:
            row = self._click_pending_row
            self._click_pending_row = -1
            # This widget never initiates a QDrag itself (external drags are
            # owned by the parent panel for the QListView path), so no started
            # drag can race the click-to-deselect logic below. The previous
            # getattr(self, "_drag_started", False) guard was never set by
            # anyone and has been removed as dead code.
            if row in self._selection and len(self._selection) > 1:
                old_sel = self._selection.copy()
                self._selection = {row}
                self._animator.apply_selection_progress(old_sel)
                self.clicked.emit(row)
                self.selection_changed.emit()
                self._request_frame(self._selection | old_sel, overlay=True)
        QWidget.mouseReleaseEvent(cast(QWidget, self), event)

    def enterEvent(self, event):
        # Use actual cursor position, not entry-point (entry may be at y=0 above first item)
        pos = self.mapFromGlobal(self.cursor().pos())
        pos.setY(pos.y() + self._scroll_y)
        if self._layout:
            row = self._layout.row_at(pos.x(), pos.y())
            if row >= 0 and self._hover_row != row:
                old = self._hover_row
                self._hover_row = row
                if not self._animator.reduce_motion:
                    if old >= 0:
                        self._animator.setdefault_hover_progress(old, 1.0)
                    self._animator.setdefault_hover_progress(row, 0.0)
                    self._animator.ensure_running()
                self._request_frame([old, row], overlay=True)
        QWidget.enterEvent(cast(QWidget, self), event)

    def leaveEvent(self, event):
        if self._hover_row >= 0:
            old = self._hover_row
            self._hover_row = -1
            if not self._animator.reduce_motion:
                self._animator.setdefault_hover_progress(old, 1.0)
                self._animator.ensure_running()
            self._request_frame([old], overlay=True)
        QWidget.leaveEvent(cast(QWidget, self), event)

    def contextMenuEvent(self, event):
        self.context_menu.emit(event.globalPos())

    # ── Keyboard ─────────────────────────────────────────────

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        cols = self._layout.columns if self._layout else 1
        if key == Qt.Key.Key_Home:
            self._scrollbar.setValue(0)
        elif key == Qt.Key.Key_End:
            self._scrollbar.setValue(self._scrollbar.maximum())
        elif key == Qt.Key.Key_PageUp:
            self._scrollbar.triggerAction(QScrollBar.SliderAction.SliderPageStepSub)
        elif key == Qt.Key.Key_PageDown:
            self._scrollbar.triggerAction(QScrollBar.SliderAction.SliderPageStepAdd)
        elif key == Qt.Key.Key_Space:
            if self._hover_row >= 0:
                if self._hover_row in self._selection:
                    self._selection.discard(self._hover_row)
                else:
                    self._selection.add(self._hover_row)
                self._last_click_row = self._hover_row
                self.selection_changed.emit()
                self._request_frame([self._hover_row], overlay=True)
        elif key == Qt.Key.Key_Up:
            self._step_mod_arrow(-cols, mods)
        elif key == Qt.Key.Key_Down:
            self._step_mod_arrow(cols, mods)
        elif key == Qt.Key.Key_Left:
            if self._selection:
                row = next(iter(self._selection))
                if row % cols > 0:
                    self._step_mod_arrow(-1, mods)
        elif key == Qt.Key.Key_Right:
            if self._selection:
                row = next(iter(self._selection))
                if row % cols < cols - 1:
                    self._step_mod_arrow(1, mods)
        elif key == Qt.Key.Key_A and mods & Qt.KeyboardModifier.ControlModifier:
            self.select_all()
        else:
            QWidget.keyPressEvent(cast(QWidget, self), event)

    def _step_mod_arrow(self, delta: int, mods):
        if not self._selection:
            return
        # Anchor on the last clicked row, clamping the never-clicked (-1) case.
        base_row = max(0, self._last_click_row)
        new_row = max(0, min(self._model_rows - 1, base_row + delta))
        if mods & Qt.KeyboardModifier.ShiftModifier:
            lo = min(new_row, base_row)
            hi = max(new_row, base_row)
            self._selection = set(range(lo, hi + 1))
        elif mods & Qt.KeyboardModifier.ControlModifier:
            # Ctrl+Arrow: move focus only, don't change selection
            self._last_click_row = new_row
            self.scroll_to(new_row)
            self._request_frame(full=True)
            return
        else:
            self._selection = {new_row}
        self._last_click_row = new_row
        self.scroll_to(new_row)
        self.selection_changed.emit()
        self._request_frame(full=True)

    # ── Inline rename ────────────────────────────────────────

    def _start_rename(self, row: int):
        from PySide6.QtWidgets import QLineEdit
        if not self._layout or self._model is None:
            return
        rect = self._layout.rect_at(row)
        if rect is None:
            return
        name = self._model.data(self._model.index(row, 0), Qt.ItemDataRole.DisplayRole) or ""
        editor = QLineEdit(cast(QWidget, self))
        editor.setText(name)
        editor.selectAll()
        editor.setGeometry(rect.x(), rect.y() - self._scroll_y,
                           rect.width(), editor.sizeHint().height())
        editor.setFocus()
        editor.show()
        finished = False
        self._rename_editor = editor
        self._rename_name = name

        def _finish():
            nonlocal finished
            if finished:
                return
            finished = True
            new_name = editor.text().strip()
            self._rename_editor = None
            self._rename_name = None
            self._rename_finish = None
            editor.deleteLater()
            if new_name and new_name != name:
                self.rename_requested.emit(row, new_name)

        self._rename_finish = _finish
        editor.editingFinished.connect(_finish)
        # Close the editor on Escape without committing: the filter reverts
        # any edits first so _finish() sees the original name.
        editor.installEventFilter(cast(QWidget, self))

    def eventFilter(self, obj, event):
        editor = self._rename_editor
        finish = self._rename_finish
        if (
            editor is not None
            and finish is not None
            and obj is editor
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
        ):
            editor.setText(self._rename_name or "")
            finish()
            editor.clearFocus()
            return True
        return False

    # ── Wheel / zoom ─────────────────────────────────────────

    def wheelEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            event.ignore()
            return
        self._scrollbar.wheelEvent(event)
        self._scroll_y = self._scrollbar.value()
