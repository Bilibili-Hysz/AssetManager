"""Data binding, layout computation and diagnostics for the file list grid widget.

``DataMixin`` owns non-visual state: model/session binding, grid geometry and
text metrics, the zoom relayout timeline, texture invalidation and rebuild
bookkeeping, thumbnail commit plumbing, theme/scale refresh, and the scoped
performance telemetry recorders.

Drawing lives in ``_grid_widget_render.py``; event handling and interaction
live in ``_grid_widget_interact.py``; ``_grid_widget.py`` composes the three.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, QRect, QSize, QPoint
from PySide6.QtGui import QColor, QFont, QFontMetrics

from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt

from AssetsManager.panels.file_list._model import FileSystemModel
from AssetsManager.panels.file_list._grid_layout import GridLayout

if TYPE_CHECKING:
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QScrollBar

    from AssetsManager.panels.file_list._grid_texture_cache import GridTextureCache
    from AssetsManager.panels.file_list._animator import Animator

# Layout constants — matching GridDelegate exactly (scaled for DPI)
_CARD_PAD = scaled_px(6)
_PREVIEW_MARGIN = scaled_px(4)
_TEXT_TOP_GAP = scaled_px(5)
_TEXT_LINE_GAP = scaled_px(1)


class DataMixin:
    """Data binding, layout computation and diagnostics."""

    if TYPE_CHECKING:
        # Host surface owned by FileListGridWidget / sibling mixins.
        _cache: GridTextureCache
        _animator: Animator
        _scrollbar: QScrollBar
        _selection: set[int]
        _scroll_y: int
        _dirty: set[int]
        _zoom_fallback_textures: dict[int, QPixmap]
        _full_rebuild_epoch: int
        _full_rebuild_pending: bool
        _performance_recorder: Any
        _performance_session_token: str | None
        _performance_generation: int | None

        def width(self) -> int: ...
        def height(self) -> int: ...
        def rect(self) -> QRect: ...
        def _request_frame(self, rows=None, *, full: bool = False, overlay: bool = False) -> None: ...
        def _relayout_scrollbar(self) -> None: ...
        def _cancel_frame(self) -> None: ...
        def _render_item(self, row: int, item_rect: QRect) -> QPixmap | None: ...

    def _update_item_hint(self):
        """Item size matching GridDelegate.sizeHint."""
        self._item_w = _CARD_PAD * 2 + _PREVIEW_MARGIN * 2 + self._thumb_size + 2
        self._item_h = _CARD_PAD * 2 + _PREVIEW_MARGIN * 2 + self._thumb_size + self._t_h + 2
        self._item_hint = QSize(self._item_w, self._item_h)

    def _refresh_text_metrics(self) -> None:
        """Refresh card text metrics after theme or UI-scale changes."""
        self._font_name = QFont()
        self._font_name.setPointSize(scaled_pt(9))
        self._font_name.setBold(True)
        self._fm_name = QFontMetrics(self._font_name)
        self._font_sub = QFont()
        self._font_sub.setPointSize(scaled_pt(8))
        self._fm_sub = QFontMetrics(self._font_sub)
        self._font_badge = QFont()
        self._font_badge.setPointSize(scaled_pt(8))
        self._font_badge.setBold(True)
        self._fm_badge = QFontMetrics(self._font_badge)
        self._t_h = _TEXT_TOP_GAP + self._fm_name.height() + _TEXT_LINE_GAP + self._fm_sub.height()
        self._update_item_hint()

    # ── Public API ──────────────────────────────────────────

    def set_model(self, model: FileSystemModel):
        self._model = model
        model.modelReset.connect(self._on_model_reset)
        model.modelAboutToBeReset.connect(self._cache.capture_path_textures)
        model.scan_started.connect(self._on_scan_started)
        model.dataChanged.connect(self._on_data_changed)

    def set_layout_ref(self, layout: GridLayout):
        self._layout = layout

    def set_performance_context(self, recorder, session_token: str | None, generation: int | None) -> None:
        """Bind optional scoped diagnostics without changing visual state."""
        try:
            self._performance_recorder = recorder if recorder is not None and recorder.enabled else None
        except Exception:
            self._performance_recorder = None
        self._performance_session_token = session_token if self._performance_recorder is not None else None
        self._performance_generation = generation if self._performance_recorder is not None else None
        if self._performance_recorder is not None:
            self._cache.refresh_accounting()
        else:
            self._cache.clear_byte_accounting()

    def set_performance_generation(self, generation: int) -> None:
        if self._performance_recorder is not None:
            self._performance_generation = generation

    def set_thumb_size(self, size: int):
        if size != self._thumb_size:
            self._cache.clear_path_textures()
        self._thumb_size = size
        self._update_item_hint()

    def _zoom_anchor_row(
        self,
        rows: set[int],
        rects: list[QRect],
        anchor_pos: QPoint | None = None,
    ) -> int:
        """Pick the card nearest the pointer, or the viewport center."""
        valid_rows = [row for row in rows if 0 <= row < len(rects)]
        if not valid_rows:
            return -1
        if anchor_pos is not None and self.rect().contains(anchor_pos):
            anchor_x = anchor_pos.x()
            anchor_y = self._scroll_y + anchor_pos.y()
        else:
            anchor_x = self.width() // 2
            anchor_y = self._scroll_y + self.height() // 2
        return min(
            valid_rows,
            key=lambda row: (
                abs(rects[row].center().y() - anchor_y),
                abs(rects[row].center().x() - anchor_x),
                row,
            ),
        )

    def begin_zoom(self, target_size: int, anchor_pos: QPoint | None = None) -> None:
        """Capture the current visual cards and their target layout."""
        if self._layout is None:
            return
        previous_zoom_visible = self._zoom_visible_rows.copy()
        source_rects = [
            self._current_visual_rect(rect, row)
            for row, rect in enumerate(self._layout._rects)
        ]
        source_visible_rows = set(self._layout.visible_rows(self._scroll_y, self.height()))
        source_visible_rows.update(previous_zoom_visible)
        viewport_top = self._scroll_y
        viewport_bottom = viewport_top + self.height()
        source_visible_rows = {
            row for row in source_visible_rows
            if 0 <= row < len(source_rects)
            and source_rects[row].bottom() >= viewport_top
            and source_rects[row].top() <= viewport_bottom
        }
        if not source_visible_rows:
            source_visible_rows = set(self._layout.visible_rows(self._scroll_y, self.height()))

        # Zoom owns the visual timeline. Entrance and thumbnail fades would
        # otherwise advance only the already-textured rows while the rest of
        # the viewport follows the geometry interpolation.
        self._animator.cancel_entrance()
        self._zoom_fallback_textures.clear()
        # An interrupted zoom leaves pre-rendered target textures behind. Commit
        # them so the committed cache tracks the zoom size instead of lagging at
        # the original (small) size — which would force the next animation to
        # upscale that small cache across several zoom steps and blur for a frame.
        if self._zoom_target_textures:
            for row, tex in self._zoom_target_textures.items():
                self._cache.cache_texture(row, tex)
        self._zoom_target_textures = {}
        self._zoom_source_rects = source_rects
        self._zoom_start_size = self._thumb_size
        self._zoom_target_size = target_size
        target_hint = QSize(
            _CARD_PAD * 2 + _PREVIEW_MARGIN * 2 + target_size + 2,
            _CARD_PAD * 2 + _PREVIEW_MARGIN * 2 + target_size + self._t_h + 2,
        )
        target_layout = GridLayout()
        target_layout.compute(
            self._model_rows,
            max(self.width() - 20, 100),
            target_size,
            item_hint=target_hint,
        )
        self._zoom_target_rects = target_layout._rects
        anchor_row = self._zoom_anchor_row(
            source_visible_rows,
            self._zoom_source_rects,
            anchor_pos,
        )
        if 0 <= anchor_row < len(self._zoom_target_rects):
            source_anchor = self._zoom_source_rects[anchor_row]
            target_anchor = self._zoom_target_rects[anchor_row]
            pointer_content_pos = (
                QPoint(anchor_pos.x(), self._scroll_y + anchor_pos.y())
                if anchor_pos is not None
                else None
            )
            if pointer_content_pos is not None and source_anchor.contains(pointer_content_pos):
                relative_y = (
                    (pointer_content_pos.y() - source_anchor.top())
                    / max(1, source_anchor.height())
                )
                source_focus_y = source_anchor.top() + source_anchor.height() * relative_y
                target_focus_y = target_anchor.top() + target_anchor.height() * relative_y
                self._zoom_anchor_y_offset = round(source_focus_y - target_focus_y)
            else:
                self._zoom_anchor_y_offset = (
                    source_anchor.center().y() - target_anchor.center().y()
                )
        else:
            self._zoom_anchor_y_offset = 0
        target_scroll = max(0, self._scroll_y - self._zoom_anchor_y_offset)
        self._zoom_visible_rows = source_visible_rows
        self._zoom_visible_rows.update(target_layout.visible_rows(target_scroll, self.height()))
        self._zoom_relayout_active = bool(self._zoom_source_rects)

    def set_zoom_thumb_size(self, size: int) -> None:
        """Advance a precomputed zoom layout without discrete column reflow."""
        self._thumb_size = size
        if not self._zoom_relayout_active:
            self._update_item_hint()
            return
        self._request_frame(full=True)

    def finish_zoom(self) -> None:
        """Commit the target layout while retaining the active zoom anchor."""
        if not self._zoom_relayout_active:
            return
        self._scrollbar.setValue(max(0, self._scroll_y - self._zoom_anchor_y_offset))
        self._zoom_relayout_active = False
        self._zoom_source_rects.clear()
        self._zoom_target_rects.clear()
        self._zoom_fallback_textures.clear()
        self._zoom_visible_rows.clear()
        self._zoom_anchor_y_offset = 0
        # Swap in the target-size textures pre-rendered during the animation so
        # the visible cards stay crisp. Rows that were never pre-rendered (off
        # screen, or budget-exhausted) keep their stale source-size texture and
        # are marked dirty for the paced rebuild.
        target_rows = set(self._zoom_target_textures)
        for row, tex in self._zoom_target_textures.items():
            self._cache.cache_texture(row, tex)
        self._zoom_target_textures = {}
        self._cache.clear_path_textures()
        self._dirty = {r for r in range(self._model_rows) if r not in target_rows}
        if self._dirty:
            self._full_rebuild_epoch += 1
            self._full_rebuild_pending = True
        self._record_invalidation("zoom", self._model_rows, self._cache.texture_count)
        self._request_frame(full=True)

    def invalidate_textures(self):
        previous_count = self._cache.texture_count
        self._full_rebuild_epoch += 1
        self._cache.clear_path_textures()
        # Keep the prior card textures on screen until their replacements are
        # ready. Clearing them made a paced rebuild visibly turn into blanks.
        self._dirty = set(range(self._model_rows))
        self._full_rebuild_pending = True
        self._record_invalidation("explicit", self._model_rows, previous_count)
        self._request_frame(full=True)

    def set_scrolling(self, active: bool = True):
        if active and self._full_rebuild_pending:
            # Stop spending the full-rebuild budget on rows that just left view.
            self._full_rebuild_update_queued = False
            self._full_rebuild_epoch += 1

    def commit_thumbnail_rows(self, rows: list[int]) -> None:
        """Apply one authoritative visual invalidation for a validated thumbnail batch."""
        for r in rows:
            path = self._model.path_at(r) if self._model is not None else None
            if path:
                self._cache.discard_path_texture(path)
            has_visible_texture = self._cache.has_texture(r)
            self._dirty.add(r)
            self._animator.begin_thumbnail_fade(
                r,
                has_visible_texture=has_visible_texture,
                # A texture contains the entire card, not just its preview.
                # Fading a replacement would briefly hide the whole card.
                allow_fade=not self._zoom_relayout_active,
            )
        self._record_invalidation("thumbnail_batch", len(rows), self._cache.texture_count)
        if self._animator.has_thumbnail_fades():
            self._animator.ensure_running()
        self._request_frame(rows)

    def start_thumbnail_delivery_measurement(self) -> float | None:
        """Return a timer only when scoped Grid diagnostics are enabled."""
        from AssetsManager.panels.file_list._grid_widget import perf_counter
        return perf_counter() if self._performance_recorder is not None else None

    def record_thumbnail_pixmap(self, started: float | None) -> None:
        self._record_thumbnail_delivery("grid.thumbnail_pixmap", started, 1)

    def record_thumbnail_batch(self, count: int) -> None:
        self._record_thumbnail_delivery("grid.thumbnail_batch", None, count)

    def _on_scan_started(self, _generation: int):
        """Drop path textures before a new filesystem scan can change files."""
        self._scan_reset_pending = True
        self._cache.clear_path_textures()

    def mark_scan_settled(self) -> None:
        """Clear the scan-reset guard after a reused scan skipped model reset.

        ``_scan_reset_pending`` is otherwise only cleared in ``_on_model_reset``;
        a no-change ``preserve_existing`` scan emits ``scan_committed`` without a
        reset, which would otherwise make the next sort/filter drop the path
        texture cache and rebuild every card.
        """
        self._scan_reset_pending = False

    def _on_model_reset(self):
        self._scan_reset_pending = False
        previous_count = self._cache.texture_count
        self._full_rebuild_epoch += 1
        self._cache.clear()
        self._dirty.clear()
        self._full_rebuild_pending = False
        self._full_rebuild_update_queued = False
        self._selection.clear()
        self._animator.reset_for_model_reset()
        self._cancel_frame()
        self._record_invalidation("model_reset", self._model_rows, previous_count)

    def _on_data_changed(self, top_left, bottom_right, roles):
        roles = set(roles or [])
        if FileSystemModel.RAW_PIXMAP_ROLE in roles:
            self.commit_thumbnail_rows(list(range(top_left.row(), bottom_right.row() + 1)))
            return
        static_roles = {
            Qt.ItemDataRole.DisplayRole,
            Qt.ItemDataRole.EditRole,
            Qt.ItemDataRole.DecorationRole,
            FileSystemModel.IS_DIR_ROLE,
        }
        if FileSystemModel.SUBTITLE_ROLE in roles:
            remaining = roles - {FileSystemModel.SUBTITLE_ROLE}
            if not remaining.intersection(static_roles):
                # Directory-size subtitle updates rewrite only the cached card's
                # subtitle band in place instead of invalidating and re-rendering
                # the thumbnail, folder art, name, and badge (F-08, no overlay
                # layer). Rows without a cached texture fall back to the normal
                # dirty/rebuild path.
                for row in range(top_left.row(), bottom_right.row() + 1):
                    self._patch_subtitle_texture(row)
                self._request_frame(range(top_left.row(), bottom_right.row() + 1))
                return
        if roles and not roles.intersection(static_roles | {FileSystemModel.SUBTITLE_ROLE}):
            return
        changed_count = bottom_right.row() - top_left.row() + 1
        previous_count = self._cache.texture_count
        for r in range(top_left.row(), bottom_right.row() + 1):
            path = self._model.path_at(r) if self._model is not None else None
            if path:
                self._cache.discard_path_texture(path)
            self._dirty.add(r)
            self._cache.drop_texture(r)
        self._record_invalidation("model_data", changed_count, previous_count)
        self._request_frame(range(top_left.row(), bottom_right.row() + 1))

    def is_zoom_active(self) -> bool:
        """True while the zoom relayout timeline owns the visual geometry."""
        return self._zoom_relayout_active

    # ── Layout update ───────────────────────────────────────

    def update_layout(self, item_count: int, widget_width: int, *, relayout_only: bool = False):
        """Update layout for the given item count and widget width.

        Short-circuit: when the column count (and the geometry inputs that
        determine it — item count and item hint) don't change, all rects stay
        identical because the grid anchors the first column (_x0 is fixed), so
        the O(N) rect rebuild in GridLayout.compute is skipped. Window-drag
        resizes within the same column band then cost O(1) instead of rebuild
        every row rect (10-100 ms spikes on large directories).
        """
        previous_item_count = self._model_rows
        keep_zoom_anchor = bool(self._zoom_source_rects) and not relayout_only
        self._zoom_relayout_active = relayout_only or keep_zoom_anchor
        if not relayout_only and not keep_zoom_anchor:
            self._zoom_scale_x = 1.0
            self._zoom_scale_y = 1.0
            self._zoom_source_rects.clear()
            self._zoom_target_rects.clear()
            self._zoom_fallback_textures.clear()
            self._zoom_visible_rows.clear()
            self._zoom_anchor_y_offset = 0
        self._model_rows = item_count
        if item_count > 0:
            self._has_been_populated = True
        if self._layout:
            layout_width = max(widget_width - 20, 100)
            # P0-1 short-circuit: rects depend only on (cols, count, item hint)
            # because the first column is anchored (_x0 is fixed). Dragging the
            # window edge inside the same column band therefore leaves every
            # rect identical — skip the O(N) rect rebuild in GridLayout.compute
            # (10k+ cards rebuilt per resize event is the 10-100 ms drag spike).
            new_cols = max(1, layout_width // max(1, self._item_hint.width()))
            need_relayout = (
                not self._layout._rects
                or new_cols != self._layout.columns
                or item_count != self._layout.count
                or self._thumb_size != self._layout.item_size
                or self._item_hint != self._layout.item_hint
            )
            if need_relayout:
                self._layout.compute(item_count, layout_width,
                                     self._thumb_size, item_hint=self._item_hint)
            th = self._layout.total_height
            self._scrollbar.setRange(0, max(0, th - self.height()))
            self._cache.drop_rows_above(item_count)
            if not relayout_only and not self._cache.has_textures:
                self._dirty |= set(range(item_count))
            elif not relayout_only and item_count > previous_item_count:
                self._dirty |= set(range(previous_item_count, item_count))
            self._request_frame(full=True)

    # ── Card rect helper ─────────────────────────────────────

    def _card_rect_in_item(self, item_rect: QRect) -> QRect:
        """Card within item: inset by CARD_PAD on all sides (matches delegate)."""
        return QRect(
            item_rect.x() + _CARD_PAD, item_rect.y() + _CARD_PAD,
            item_rect.width() - _CARD_PAD * 2, item_rect.height() - _CARD_PAD * 2,
        )

    def _record_performance(
        self,
        name: str,
        started: float | None,
        session_token: str | None,
        generation: int | None,
        visible_count: int,
        texture_build_count: int | None = None,
        deferred_texture_count: int | None = None,
    ) -> None:
        from AssetsManager.panels.file_list._grid_widget import perf_counter
        recorder = self._performance_recorder
        if recorder is None or started is None:
            return
        try:
            attributes = {
                "visible_item_count": visible_count,
                "queued_entrance_count": self._animator.queued_entrance_count,
            }
            if texture_build_count is not None:
                attributes.update(
                    texture_cache_count=self._cache.texture_count,
                    texture_cache_bytes=self._cache.texture_cache_bytes,
                    texture_build_count=texture_build_count,
                    deferred_texture_count=deferred_texture_count or 0,
                )
            recorder.record(
                name,
                (perf_counter() - started) * 1000,
                session_token=session_token,
                generation=generation,
                attributes=attributes,
            )
        except Exception:
            # Diagnostics must not affect paint, animation, or timer state.
            pass

    def _record_texture_performance(
        self, started: float | None, session_token: str | None, generation: int | None, row: int
    ) -> None:
        from AssetsManager.panels.file_list._grid_widget import perf_counter
        recorder = self._performance_recorder
        if recorder is None or started is None:
            return
        try:
            recorder.record(
                "grid.texture",
                (perf_counter() - started) * 1000,
                session_token=session_token,
                generation=generation,
                attributes={"row": row},
            )
        except Exception:
            # Diagnostics must not affect paint, texture cache, or animation state.
            pass

    def _record_invalidation(self, reason: str, item_count: int, texture_cache_count: int) -> None:
        recorder = self._performance_recorder
        if recorder is None:
            return
        try:
            recorder.record(
                "grid.invalidation",
                0.0,
                session_token=self._performance_session_token,
                generation=self._performance_generation,
                attributes={
                    "reason": reason,
                    "item_count": item_count,
                    "texture_cache_count": texture_cache_count,
                },
            )
        except Exception:
            # Diagnostics must not affect cache invalidation or rendering state.
            pass

    def _record_thumbnail_delivery(self, name: str, started: float | None, count: int) -> None:
        from AssetsManager.panels.file_list._grid_widget import perf_counter
        recorder = self._performance_recorder
        if recorder is None:
            return
        try:
            elapsed_ms = (perf_counter() - started) * 1000 if started is not None else 0.0
            recorder.record(
                name,
                elapsed_ms,
                session_token=self._performance_session_token,
                generation=self._performance_generation,
                attributes={"count": count},
            )
        except Exception:
            # Diagnostics must not affect thumbnail delivery or batch notification.
            pass

    def _subtitle_rect_for(self, item_rect: QRect) -> QRect:
        """Return the subtitle band inside ``item_rect`` (matches _render_item)."""
        card = self._card_rect_in_item(QRect(0, 0, item_rect.width(), item_rect.height()))
        preview = QRect(
            card.x() + _PREVIEW_MARGIN,
            card.y() + _PREVIEW_MARGIN,
            self._thumb_size,
            self._thumb_size,
        )
        name_y = preview.bottom() + _TEXT_TOP_GAP
        sub_y = name_y + self._fm_name.height() + _TEXT_LINE_GAP
        return QRect(preview.left(), sub_y, max(1, preview.width()), self._fm_sub.height())

    def _patch_subtitle_texture(self, row: int) -> bool:
        """Rewrite one cached card's subtitle band in place.

        Returns True when a cached texture was patched, False when the row has
        no cached texture and must go through the normal dirty rebuild path.
        """
        from AssetsManager.panels.file_list._grid_widget import QPainter
        tex = self._cache.texture_for(row)
        if tex is None or tex.isNull():
            self._dirty.add(row)
            return False
        if self._model is None:
            self._dirty.add(row)
            return False
        subtitle = self._model.data(
            self._model.index(row, 0), FileSystemModel.SUBTITLE_ROLE
        )
        size = tex.deviceIndependentSize()
        item_rect = QRect(0, 0, int(size.width()), int(size.height()))
        band = self._subtitle_rect_for(item_rect)
        painter = QPainter(tex)
        try:
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            # Erase the previous baked text with the exact card fill color.
            # CompositionMode_Source replaces the pixels (instead of blending
            # over the old glyphs) so the band returns to its original fill.
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.fillRect(
                band,
                QColor(
                    self._clr_heading.red(),
                    self._clr_heading.green(),
                    self._clr_heading.blue(),
                    10,
                ),
            )
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            if subtitle:
                painter.setFont(self._font_sub)
                painter.setPen(self._clr_muted)
                painter.drawText(
                    band,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                    self._fm_sub.elidedText(
                        subtitle, Qt.TextElideMode.ElideRight, band.width()
                    ),
                )
        finally:
            painter.end()
        return True

    def _render_zoom_fallback(self, row: int, rect: QRect) -> QPixmap | None:
        """Render a source-sized temporary card for a newly visible zoom row."""
        if row >= len(self._zoom_source_rects):
            return None
        source_rect = self._zoom_source_rects[row]
        original_size = self._thumb_size
        try:
            self._thumb_size = self._zoom_start_size
            return self._render_item(row, source_rect)
        finally:
            self._thumb_size = original_size

    def _render_zoom_target(self, row: int) -> QPixmap | None:
        """Pre-render a target-sized card so the post-zoom commit stays crisp."""
        rects = self._zoom_target_rects
        if row < 0 or row >= len(rects):
            return None
        original_size = self._thumb_size
        try:
            self._thumb_size = self._zoom_target_size
            return self._render_item(row, rects[row])
        finally:
            self._thumb_size = original_size

    def _zoom_progress(self) -> float:
        distance = self._zoom_target_size - self._zoom_start_size
        if distance == 0:
            return 1.0
        progress = (self._thumb_size - self._zoom_start_size) / distance
        return max(0.0, min(1.0, progress))

    def _current_visual_rect(self, rect: QRect, row: int | None = None) -> QRect:
        """Return the card geometry currently presented on screen."""
        if (
            self._zoom_relayout_active
            and row is not None
            and row < len(self._zoom_source_rects)
            and row < len(self._zoom_target_rects)
        ):
            start = self._zoom_source_rects[row]
            end = self._zoom_target_rects[row]
            progress = self._zoom_progress()
            return QRect(
                round(start.x() + (end.x() - start.x()) * progress),
                round(start.y() + (end.y() + self._zoom_anchor_y_offset - start.y()) * progress),
                max(1, round(start.width() + (end.width() - start.width()) * progress)),
                max(1, round(start.height() + (end.height() - start.height()) * progress)),
            )
        width = max(1, round(rect.width() * self._zoom_scale_x))
        height = max(1, round(rect.height() * self._zoom_scale_y))
        first_rect = self._layout.rect_at(0) if self._layout is not None else None
        origin_x = first_rect.x() if first_rect is not None else 0
        origin_y = first_rect.y() if first_rect is not None else 0
        return QRect(
            origin_x + round((rect.x() - origin_x) * self._zoom_scale_x),
            origin_y + round((rect.y() - origin_y) * self._zoom_scale_y),
            width,
            height,
        )

    def _zoom_texture_rect(self, rect: QRect, row: int | None = None) -> QRect:
        return self._current_visual_rect(rect, row)

    # ── Theme ────────────────────────────────────────────────

    def _rebuild_theme(self):
        t = themes.get()
        self._clr_accent = QColor(t["accent"])
        self._clr_heading = QColor(t["heading"])
        self._clr_body = QColor(t["body"])
        self._clr_muted = QColor(t["muted"])
        self._clr_base = QColor(t["base"])
        self._clr_panel = QColor(t["panel"])
        self._clr_border = QColor(t["border"])
        self._refresh_text_metrics()
        self._apply_scrollbar_theme()

    def _apply_scrollbar_theme(self):
        t = themes.get()
        self._scrollbar.setStyleSheet(
            f"QScrollBar:vertical {{ background: transparent; width:{scaled_px(6)}px; }}"
            f"QScrollBar::handle:vertical {{ background: {t['scrollbar_thumb']}; "
            f"border-radius:{scaled_px(int(themes.prop('border_radius', 'sm')))}px; min-height:{scaled_px(24)}px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}")

    def refresh_theme(self):
        previous_count = self._cache.texture_count
        self._full_rebuild_epoch += 1
        self._rebuild_theme()
        self._cache.clear()
        self._cache.clear_path_textures()
        self._dirty = set(range(self._model_rows))
        self._full_rebuild_pending = True
        self._record_invalidation("theme", self._model_rows, previous_count)
        self._request_frame(full=True)

    def refresh_scale(self):
        """Refresh scale-dependent metrics and repaint cached card textures."""
        previous_count = self._cache.texture_count
        self._full_rebuild_epoch += 1
        self._refresh_text_metrics()
        self._apply_scrollbar_theme()
        self._cache.clear()
        self._cache.clear_path_textures()
        self._dirty = set(range(self._model_rows))
        self._full_rebuild_pending = True
        self._record_invalidation("scale", self._model_rows, previous_count)
        self._relayout_scrollbar()
        self._request_frame(full=True)

