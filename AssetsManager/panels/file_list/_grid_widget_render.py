"""QPainter drawing and texture rendering for the file list grid widget.

``RenderMixin`` owns every painter path: the frame-level ``paintEvent``,
offscreen card texture baking, empty-state presentation, and the folder /
image / type-icon / badge primitives plus the interaction overlay painted on
top of cached card textures.

Data binding and layout computation live in ``_grid_widget_data.py``;
event handling and interaction live in ``_grid_widget_interact.py``;
``_grid_widget.py`` composes the three into FileListGridWidget.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import Qt, QRect, QRectF, QSize, QPoint
from PySide6.QtGui import QPainter, QPixmap, QColor, QPen, QFont, QFontMetrics, QPolygon
from PySide6.QtWidgets import QWidget

from AssetsManager.core import icons
from AssetsManager.core import themes
from AssetsManager.core.color_utils import contrast_on
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.widgets.elevation import shadow_params
from AssetsManager import i18n
from AssetsManager.application.asset_filters import FILTER_CATEGORY_LABELS
from AssetsManager.panels.file_list._common import (
    EXT_TO_CATEGORY, badge_color_for_extension, badge_label_for_extension,
)
from AssetsManager.panels.file_list._model import FileSystemModel
from AssetsManager.panels.file_list._grid_widget_data import (
    _PREVIEW_MARGIN, _TEXT_TOP_GAP, _TEXT_LINE_GAP,
)

if TYPE_CHECKING:
    from AssetsManager.panels.file_list._grid_layout import GridLayout
    from AssetsManager.panels.file_list._grid_texture_cache import GridTextureCache
    from AssetsManager.panels.file_list._animator import Animator

tr = i18n.tr

# Card drawing constants — matching GridDelegate exactly (scaled for DPI)
_CORNER_R = scaled_px(10)
_PREVIEW_R = scaled_px(8)
# Folder-tab glyph corner, canonical source: themes.metrics("radius_badge").
_BADGE_R = scaled_px(int(themes.metrics("radius_badge")))
_BADGE_H = scaled_px(14)

_BADGE_PAD_H = scaled_px(5)
_FULL_REBUILD_TEXTURE_BUDGET = 12
_ZOOM_FALLBACK_TEXTURE_BUDGET = 2
_ZOOM_TARGET_TEXTURE_BUDGET = 6


class RenderMixin:
    """QPainter drawing, texture baking and frame rendering."""

    if TYPE_CHECKING:
        # Host surface owned by FileListGridWidget / sibling mixins.
        _model: FileSystemModel | None
        _layout: GridLayout | None
        _cache: GridTextureCache
        _animator: Animator
        _dirty: set[int]
        _model_rows: int
        _selection: set[int]
        _hover_row: int
        _last_click_row: int
        _scroll_y: int
        _rubber_band_active: bool
        _rubber_band_rect: QRect
        _texture_dpr: float
        _full_rebuild_epoch: int
        _full_rebuild_pending: bool
        _zoom_relayout_active: bool
        _zoom_visible_rows: set[int]
        _zoom_fallback_textures: dict[int, QPixmap]
        _zoom_target_textures: dict[int, QPixmap]
        _performance_recorder: Any
        _performance_session_token: str | None
        _performance_generation: int | None
        _last_prioritized_key: tuple | None
        _thumb_size: int
        _clr_accent: QColor
        _clr_heading: QColor
        _clr_muted: QColor
        _clr_border: QColor
        _clr_base: QColor
        _clr_panel: QColor
        _clr_danger: QColor
        _clr_folder_highlight: QColor
        _font_name: QFont
        _font_sub: QFont
        _font_badge: QFont
        _fm_name: QFontMetrics
        _fm_sub: QFontMetrics
        _fm_badge: QFontMetrics

        def rect(self) -> QRect: ...
        def width(self) -> int: ...
        def height(self) -> int: ...
        def isVisible(self) -> bool: ...
        def parent(self) -> QWidget | None: ...
        def devicePixelRatioF(self) -> float: ...
        def hasFocus(self) -> bool: ...
        def _card_rect_in_item(self, item_rect: QRect) -> QRect: ...
        def _render_zoom_fallback(self, row: int, rect: QRect) -> QPixmap | None: ...
        def _render_zoom_target(self, row: int) -> QPixmap | None: ...
        def _zoom_texture_rect(self, rect: QRect, row: int | None = None) -> QRect: ...
        def _queue_full_rebuild_update(self) -> None: ...
        def _record_performance(
            self,
            name: str,
            started: float | None,
            session_token: str | None,
            generation: int | None,
            visible_count: int,
            texture_build_count: int | None = None,
            deferred_texture_count: int | None = None,
        ) -> None: ...
        def _record_texture_performance(
            self, started: float | None, session_token: str | None,
            generation: int | None, row: int,
        ) -> None: ...

    # ── Painting ────────────────────────────────────────────

    def _empty_state_presentation(self) -> tuple[str, str] | None:
        """Return the semantic icon and localized copy for an empty canvas."""
        state = getattr(self._model, "list_state", "") if self._model is not None else ""
        state_loading = getattr(self._model, "STATE_LOADING", "loading")
        state_error = getattr(self._model, "STATE_SCAN_ERROR", "scan_error")
        state_filtered = getattr(self._model, "STATE_EMPTY_FILTERED", "empty_filtered")
        state_empty = getattr(self._model, "STATE_EMPTY_FOLDER", "empty_folder")
        states = {
            state_loading: ("refresh", "filelist.state.loading"),
            state_error: ("folder", "filelist.state.scan_error"),
            state_filtered: ("search", "filelist.state.empty_filtered"),
            state_empty: ("folder", "filelist.empty"),
        }
        value = states.get(state)
        if value is None:
            return None
        icon_name, text_key = value
        return icon_name, tr(text_key)

    def _draw_empty_state(self, painter: QPainter) -> None:
        """Paint a calm, centered state without creating extra child widgets."""
        presentation = self._empty_state_presentation()
        if presentation is None:
            return
        icon_name, text = presentation
        icon_size = scaled_px(34)
        text_font = QFont()
        text_font.setPointSize(scaled_pt(int(themes.font_size("caption"))))
        text_font.setBold(True)
        text_metrics = QFontMetrics(text_font)
        gap = scaled_px(12)
        content_height = icon_size + gap + text_metrics.height()
        top = max(scaled_px(20), (self.height() - content_height) // 2)
        icon_rect = QRect(
            (self.width() - icon_size) // 2,
            top,
            icon_size,
            icon_size,
        )
        state_icon = icons.icon(
            icon_name,
            color="icon_muted",
            size=icon_size,
            fallback="file",
        )
        icon_pixmap = state_icon.pixmap(QSize(icon_size, icon_size))
        painter.drawPixmap(icon_rect, icon_pixmap)

        text_rect = QRect(
            scaled_px(20),
            icon_rect.bottom() + gap,
            max(1, self.width() - scaled_px(40)),
            text_metrics.height(),
        )
        painter.setFont(text_font)
        painter.setPen(self._clr_heading)
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            text,
        )
        if getattr(self._model, "list_state", "") == getattr(
            self._model, "STATE_LOADING", "loading"
        ):
            line_width = scaled_px(56)
            line_y = text_rect.bottom() + scaled_px(10)
            painter.setPen(QPen(self._clr_accent, scaled_px(2)))
            painter.drawLine(
                (self.width() - line_width) // 2,
                line_y,
                (self.width() + line_width) // 2,
                line_y,
            )

    def paintEvent(self, _evt):
        from AssetsManager.panels.file_list._grid_widget import QPainter, perf_counter
        if not self._model or not self.isVisible():
            return
        if self.width() == 0 or self.height() == 0:
            return
        recorder = self._performance_recorder
        started = perf_counter() if recorder is not None else None
        session_token = self._performance_session_token
        generation = self._performance_generation
        p = QPainter(cast(QWidget, self))
        # Cached textures already contain antialiased card geometry. Keep the
        # hot path pixmap-only; rounded overlays enable AA locally below.
        p.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform,
            self._zoom_relayout_active and not self._animator.reduce_motion,
        )
        dpr = max(1.0, float(self.devicePixelRatioF() or 1.0))
        if dpr != self._texture_dpr:
            self._texture_dpr = dpr
            self._full_rebuild_epoch += 1
            self._cache.clear()
            self._cache.clear_path_textures()
            self._dirty = set(range(self._model_rows))
            self._full_rebuild_pending = True
        if not themes.bg_enabled():
            p.fillRect(self.rect(), self._clr_panel)

        if self._model_rows == 0 or self._layout is None:
            # Defer to the layout-level EmptyStateWidget when it exists
            # (installed by _base_layout.py) to avoid dual empty-state rendering.
            parent = self.parent() if callable(getattr(self, 'parent', None)) else None
            if parent is None or not hasattr(parent, '_empty_state'):
                self._draw_empty_state(p)
            p.end()
            self._record_performance("grid.frame", started, session_token, generation, 0, 0)
            return

        sy = self._scroll_y
        vh = self.height()
        visible = self._layout.visible_rows(sy, vh)
        if self._zoom_relayout_active:
            visible = sorted(set(visible) | self._zoom_visible_rows)
        prioritize_sizes = getattr(self._model, "prioritize_dir_sizes", None)
        prioritize_key = (id(getattr(self._model, "entries", None)), tuple(visible))
        if (
            callable(prioritize_sizes)
            and getattr(self._model, "has_pending_dir_size_work", False)
            and prioritize_key != self._last_prioritized_key
        ):
            self._last_prioritized_key = prioritize_key
            visible_dir_paths = []
            for row in visible:
                entry = self._model.entry_at(row)
                if entry is not None and entry.is_dir():
                    visible_dir_paths.append(entry.path)
            prioritize_sizes(visible_dir_paths)
        if not visible:
            p.end()
            self._record_performance("grid.frame", started, session_token, generation, 0, 0)
            return

        texture_build_count = 0
        zoom_fallback_count = 0
        zoom_target_count = 0
        deferred_texture_count = 0
        # Clip to the repaint region. Qt clips the painter, but the loop would
        # otherwise still pay Python overhead + draw-call setup for every cell
        # on each partial update (hover/selection animation), turning a
        # one-cell repaint into a whole-grid repaint.
        update_rect = _evt.rect()
        # Scroll frames repaint the whole viewport; every visible cell
        # intersects it, so the per-cell Python-level intersects check is pure
        # overhead there and is skipped. Long-term band-level invalidation
        # would make scroll frames partial again (audit F-07).
        update_is_full = update_rect.contains(self.rect())
        skipped_dirty = False

        # ── Pass 1: ensure cell textures are built (budget-limited) ──
        for row in visible:
            rect = self._layout.rect_at(row)
            if rect is None:
                continue
            if not update_is_full and not update_rect.intersects(rect.translated(0, -sy)):
                skipped_dirty = skipped_dirty or (row in self._dirty)
                continue
            dirty = row in self._dirty
            tex = self._cache.texture_for(row)
            if tex is None and self._cache.has_path_textures and not self._zoom_relayout_active:
                path = self._model.path_at(row)
                if path:
                    cached = self._cache.take_path_texture(path)
                    if cached is not None:
                        tex = cached
                        self._cache.cache_texture(row, cached)
                        self._dirty.discard(row)
                        dirty = False
            if tex is not None:
                self._cache.touch(row)
            elif self._zoom_relayout_active:
                tex = self._zoom_fallback_textures.get(row)
                if (
                    tex is None
                    and row in self._zoom_visible_rows
                    and zoom_fallback_count < _ZOOM_FALLBACK_TEXTURE_BUDGET
                ):
                    tex = self._render_zoom_fallback(row, rect)
                    if tex is not None:
                        self._zoom_fallback_textures[row] = tex
                        zoom_fallback_count += 1
            if (dirty or not tex) and not self._zoom_relayout_active:
                if not self._full_rebuild_pending or texture_build_count < _FULL_REBUILD_TEXTURE_BUDGET:
                    texture_started = perf_counter() if recorder is not None else None
                    replacement = self._render_item(row, rect)
                    if replacement is not None:
                        self._cache.cache_texture(row, replacement)
                    self._record_texture_performance(texture_started, session_token, generation, row)
                    if replacement is not None:
                        self._dirty.discard(row)
                    texture_build_count += 1
                else:
                    deferred_texture_count += 1

        # During zoom, pre-render the target-size card textures (budget-limited)
        # so the finish_zoom commit can swap them in crisply instead of popping
        # each card one-by-one after the animation ends.
        if self._zoom_relayout_active:
            for row in sorted(self._zoom_visible_rows):
                if zoom_target_count >= _ZOOM_TARGET_TEXTURE_BUDGET:
                    break
                if row in self._zoom_target_textures:
                    continue
                target_tex = self._render_zoom_target(row)
                if target_tex is not None:
                    self._zoom_target_textures[row] = target_tex
                    zoom_target_count += 1

        # ── Pass 2: draw ──
        if self._zoom_relayout_active:
            # Zoom relayout interpolates card geometry per cell via the scale
            # animation, so it keeps its own per-cell path.
            p.translate(0, -sy)
            for row in visible:
                rect = self._layout.rect_at(row)
                if rect is None or (not update_is_full and not update_rect.intersects(rect.translated(0, -sy))):
                    continue
                tex = self._cache.texture_for(row) or self._zoom_fallback_textures.get(row)
                if tex is None:
                    continue
                op = self._animator.thumbnail_opacity(row)
                texture_rect = self._zoom_texture_rect(rect, row)
                if op < 1.0:
                    p.save()
                    p.setOpacity(op)
                    p.drawPixmap(texture_rect, tex)
                    p.restore()
                else:
                    p.drawPixmap(texture_rect, tex)
                self._draw_interaction_overlay(p, row, texture_rect, op)
        else:
            # ── Pass 2a: draw non-lifted cells directly (per-cell) ──
            # Each card texture is drawn at its translated position. Hover-lifted
            # cells are deferred to Pass 2b so their scale overlap stays above
            # neighbouring cards.
            for row in visible:
                rect = self._layout.rect_at(row)
                if rect is None or (not update_is_full and not update_rect.intersects(rect.translated(0, -sy))):
                    continue
                if not self._animator.reduce_motion and (
                    row == self._hover_row or self._animator.has_hover_progress(row)
                ):
                    continue
                vp = rect.translated(0, -sy)
                op = self._animator.thumbnail_opacity(row)
                tex = self._cache.texture_for(row)
                if tex is not None:
                    dirty = row in self._dirty
                    if op < 1.0:
                        p.save()
                        p.setOpacity(op)
                        if dirty:
                            p.drawPixmap(vp, tex)
                        else:
                            p.drawPixmap(vp.topLeft(), tex)
                        p.restore()
                    elif dirty:
                        p.drawPixmap(vp, tex)
                    else:
                        p.drawPixmap(vp.topLeft(), tex)
                else:
                    self._draw_texture_placeholder(p, vp)
            # ── Pass 2b: hover lift + interaction overlay (drawn on top) ──
            lift_scale = 1.075
            lift_dy = -5
            for row in visible:
                rect = self._layout.rect_at(row)
                if rect is None or (not update_is_full and not update_rect.intersects(rect.translated(0, -sy))):
                    continue
                vp = rect.translated(0, -sy)
                op = self._animator.thumbnail_opacity(row)
                tex = self._cache.texture_for(row)
                draw_rect = vp
                if row == self._hover_row and not self._animator.reduce_motion and tex is not None:
                    sw = int(vp.width() * lift_scale)
                    sh = int(vp.height() * lift_scale)
                    dx = (vp.width() - sw) // 2
                    target = QRect(vp.x() + dx, vp.y() + lift_dy, sw, sh)
                    draw_rect = target
                    ground_card = self._card_rect_in_item(vp)
                    self._draw_hover_shadow(p, ground_card, 1.0 * op)
                    if op < 1.0:
                        p.save()
                        p.setOpacity(op)
                        p.drawPixmap(target, tex)
                        p.restore()
                    else:
                        p.drawPixmap(target, tex)
                else:
                    pv = self._animator.hover_progress_value(row)
                    if pv is not None and pv > 0.01 and tex is not None:
                        s = 1.0 + 0.075 * pv
                        sw = int(vp.width() * s)
                        sh = int(vp.height() * s)
                        dx = (vp.width() - sw) // 2
                        dy = int(lift_dy * pv)
                        target = QRect(vp.x() + dx, vp.y() + dy, sw, sh)
                        draw_rect = target
                        ground_card = self._card_rect_in_item(vp)
                        self._draw_hover_shadow(p, ground_card, pv * op)
                        if op < 1.0:
                            p.save()
                            p.setOpacity(op)
                            p.drawPixmap(target, tex)
                            p.restore()
                        else:
                            p.drawPixmap(target, tex)
                self._draw_interaction_overlay(p, row, draw_rect, op)

        # ── Rubber band overlay ──
        if self._rubber_band_active and not self._rubber_band_rect.isNull():
            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rb = QColor(self._clr_accent)
            rb.setAlpha(35)
            p.setPen(QPen(self._clr_accent, 1.0))
            p.setBrush(rb)
            band = self._rubber_band_rect
            if not self._zoom_relayout_active:
                band = band.translated(0, -sy)
            p.drawRoundedRect(band, 3.0, 3.0)
            p.restore()

        p.end()
        self._record_performance(
            "grid.frame", started, session_token, generation, len(visible), texture_build_count, deferred_texture_count
        )
        if deferred_texture_count or (self._full_rebuild_pending and skipped_dirty):
            self._queue_full_rebuild_update()
        elif self._full_rebuild_pending:
            self._full_rebuild_pending = False

    def _render_item(self, row: int, item_rect: QRect) -> QPixmap | None:
        """Render static item content to an offscreen QPixmap."""
        from AssetsManager.panels.file_list._grid_widget import QPainter
        model = self._model
        if model is None:
            return None
        dpr = max(1.0, float(self.devicePixelRatioF() or 1.0))
        tex = QPixmap(int(item_rect.width() * dpr), int(item_rect.height() * dpr))
        tex.setDevicePixelRatio(dpr)
        tex.fill(Qt.GlobalColor.transparent)
        tp = QPainter(tex)
        tp.setRenderHint(QPainter.RenderHint.Antialiasing)
        tp.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        is_dir = model.data(model.index(row, 0), FileSystemModel.IS_DIR_ROLE)
        pixmap = model.data(model.index(row, 0), FileSystemModel.RAW_PIXMAP_ROLE)
        name = model.data(model.index(row, 0), Qt.ItemDataRole.DisplayRole)
        subtitle = model.data(model.index(row, 0), FileSystemModel.SUBTITLE_ROLE)
        card = self._card_rect_in_item(QRect(0, 0, item_rect.width(), item_rect.height()))

        # Interaction states are painted later so mouse movement and selection
        # changes do not invalidate this expensive thumbnail texture.
        r2, g2, b2 = self._clr_heading.red(), self._clr_heading.green(), self._clr_heading.blue()
        card_f = QRectF(
            float(card.x()) + 0.5,
            float(card.y()) + 0.5,
            float(card.width()) - 1.0,
            float(card.height()) - 1.0,
        )
        # Flat neutral tint instead of a gradient: the card must not cast any
        # color onto the thumbnail, so the asset stays the only color source
        # (design-language-unification-2026-09-03, P0-3).
        bg = QColor(r2, g2, b2, 6)
        border = QColor(r2, g2, b2, 24)
        tp.setPen(QPen(border, 1.0))
        tp.setBrush(bg)
        tp.drawRoundedRect(card_f, float(_CORNER_R), float(_CORNER_R))

        preview = QRect(card.x() + _PREVIEW_MARGIN, card.y() + _PREVIEW_MARGIN,
                        self._thumb_size, self._thumb_size)
        if is_dir:
            self._draw_folder(tp, preview, pixmap)
        elif pixmap and not pixmap.isNull():
            self._draw_image(tp, preview, pixmap)
        else:
            self._draw_type_icon(tp, preview, is_dir, name)
        # Failure marker: a file cell whose latest thumbnail load failed is
        # visually distinct from the blank "still loading" placeholder.
        if not is_dir and (pixmap is None or pixmap.isNull()):
            path = model.path_at(row)
            if path and model.is_thumbnail_failed(path):
                self._draw_failure_marker(tp, preview)

        # ── Category badge ──
        ext = ""
        if not is_dir:
            if name and "." in name:
                ext = name[name.rfind("."):].lower()
            if ext:
                self._draw_badge(tp, preview, ext)

        tp.setFont(self._font_name)
        tp.setPen(self._clr_heading)
        name_y = preview.bottom() + _TEXT_TOP_GAP
        text_left = preview.left()
        text_width = max(1, preview.width())
        name_rect = QRect(text_left, name_y, text_width, self._fm_name.height())
        elided = self._fm_name.elidedText(
            name or "", Qt.TextElideMode.ElideRight, name_rect.width())
        tp.drawText(name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, elided)

        if subtitle:
            tp.setFont(self._font_sub)
            tp.setPen(self._clr_muted)
            sub_y = name_rect.bottom() + _TEXT_LINE_GAP
            sub_rect = QRect(text_left, sub_y, text_width, self._fm_sub.height())
            elided_sub = self._fm_sub.elidedText(
                subtitle or "", Qt.TextElideMode.ElideRight, sub_rect.width())
            tp.drawText(sub_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                        elided_sub)

        tp.end()

        return tex

    def _draw_texture_placeholder(self, painter: QPainter, item_rect: QRect) -> None:
        card = self._card_rect_in_item(item_rect)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(self._clr_border, 1))
        painter.setBrush(QColor(self._clr_heading.red(), self._clr_heading.green(), self._clr_heading.blue(), 6))
        painter.drawRoundedRect(card, _CORNER_R, _CORNER_R)
        painter.restore()

    def _draw_failure_marker(self, tp: QPainter, preview: QRect) -> None:
        """Danger wedge in the preview's bottom-right corner: the thumbnail
        failed to load (distinct from the blank loading placeholder, no text)."""
        size = max(scaled_px(8), min(scaled_px(16), preview.width() // 4))
        br = preview.bottomRight()
        tp.save()
        tp.setPen(Qt.PenStyle.NoPen)
        tp.setBrush(self._clr_danger)
        tp.drawPolygon(QPolygon([
            br,
            QPoint(br.x() - size, br.y()),
            QPoint(br.x(), br.y() - size),
        ]))
        tp.restore()

    def _draw_hover_shadow(self, p: QPainter, card_rect: QRect, progress: float) -> None:
        """Render diffuse ambient ground shadow beneath a hover-lifted card.

        Alpha and vertical spread are derived from the canonical E1 shadow
        (``elevation.shadow_params(1)``) so custom-painted surfaces share the
        same depth vocabulary as elevation-based ones
        (design-language-unification-2026-09-03, P0-2).
        """
        if progress <= 0.01:
            return
        blur, off_x, off_y, alpha = shadow_params(1)
        a_outer = int(alpha * 0.25)
        a_mid = int(alpha * 0.39)
        a_contact = int(alpha * 0.50)
        spread_outer = off_y + 3
        spread_mid = off_y + 1
        spread_contact = max(1, off_y - 1)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        # Soft ambient diffuse shadow on the ground beneath lifted card:
        # Layer 1: Outer diffuse layer (wide, soft dispersion)
        s1 = card_rect.adjusted(
            int(-2 * progress),
            int(3 * progress),
            int(2 * progress),
            int(spread_outer * progress),
        )
        p.setBrush(QColor(0, 0, 0, int(a_outer * progress)))
        p.drawRoundedRect(s1, _CORNER_R + 2, _CORNER_R + 2)

        # Layer 2: Mid ambient layer
        s2 = card_rect.adjusted(
            0,
            int(2 * progress),
            0,
            int(spread_mid * progress),
        )
        p.setBrush(QColor(0, 0, 0, int(a_mid * progress)))
        p.drawRoundedRect(s2, _CORNER_R + 1, _CORNER_R + 1)

        # Layer 3: Contact/core shadow layer
        s3 = card_rect.adjusted(
            int(2 * progress),
            int(1 * progress),
            int(-2 * progress),
            int(spread_contact * progress),
        )
        p.setBrush(QColor(0, 0, 0, int(a_contact * progress)))
        p.drawRoundedRect(s3, _CORNER_R, _CORNER_R)
        p.restore()

    def _draw_interaction_overlay(self, p: QPainter, row: int, item_rect: QRect, opacity: float):
        """Paint selection, hover, and keyboard focus without rebuilding the cache."""
        selection_progress = (
            1.0 if row in self._selection else self._animator.selection_progress_value(row)
        )
        hover_progress = (
            1.0 if row == self._hover_row else self._animator.hover_progress_value(row) or 0.0
        )
        focus_row = -1
        if self.hasFocus():
            if self._last_click_row in self._selection:
                focus_row = self._last_click_row
            elif self._selection:
                focus_row = min(self._selection)
        if selection_progress <= 0.01 and hover_progress <= 0.01 and row != focus_row:
            return

        card = self._card_rect_in_item(QRect(0, 0, item_rect.width(), item_rect.height()))
        card.translate(item_rect.topLeft())
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setOpacity(opacity)
        if selection_progress > 0.01:
            fill = QColor(self._clr_accent)
            fill.setAlphaF((80 / 255) * selection_progress)
            border = QColor(self._clr_accent)
            border.setAlphaF((200 / 255) * selection_progress)
            p.setPen(QPen(border, 1.5))
            p.setBrush(fill)
        else:
            fill = QColor(self._clr_heading)
            fill.setAlphaF((20 / 255) * hover_progress)
            border = QColor(self._clr_heading)
            border.setAlphaF((50 / 255) * hover_progress)
            p.setPen(QPen(border, 1))
            p.setBrush(fill)
        p.drawRoundedRect(card, _CORNER_R, _CORNER_R)
        if row == focus_row:
            # Modern 2px double-layer rounded glowing solid ring:
            # Translucent faint glow ring overlaid with outer 2px highlight solid line.
            p.setBrush(Qt.BrushStyle.NoBrush)
            glow = QColor(self._clr_accent)
            glow.setAlpha(65)
            # Translucent faint glow ring
            p.setPen(QPen(glow, 3.5, Qt.PenStyle.SolidLine))
            p.drawRoundedRect(card.adjusted(1, 1, -1, -1), max(1, _CORNER_R - 1), max(1, _CORNER_R - 1))
            # Outer highlight solid line (2px)
            p.setPen(QPen(self._clr_accent, 2.0, Qt.PenStyle.SolidLine))
            p.drawRoundedRect(card.adjusted(1, 1, -1, -1), max(1, _CORNER_R - 1), max(1, _CORNER_R - 1))
        p.restore()

    # ── Folder / Image rendering ────────────────────────────

    def _folder_colors(self):
        """Folder colors — warm gold tones blended with theme accent.
        Matches delegate formula: accent*0.6+gold*0.4 (body), accent*0.4+gold*0.6 (front)."""
        accent = self._clr_accent
        body = QColor(
            int(accent.red() * 0.6 + 0xc9 * 0.4),
            int(accent.green() * 0.6 + 0xa0 * 0.4),
            int(accent.blue() * 0.6 + 0x63 * 0.4))
        front = QColor(
            int(accent.red() * 0.4 + 0xfb * 0.6),
            int(accent.green() * 0.4 + 0xd8 * 0.6),
            int(accent.blue() * 0.4 + 0x96 * 0.6))
        return body, front

    def _draw_folder(self, p: QPainter, rect: QRect, pixmap: QPixmap | None):
        body_c, front_c = self._folder_colors()
        icon_w = rect.width()
        icon_h = int(rect.height() * 0.85)
        folder = QRect(rect.x(), rect.y() + int(rect.height() * 0.15), icon_w, icon_h)
        tab_w = int(icon_w * 0.35)
        tab_h = max(5, int(icon_h * 0.10))
        tab_rect = QRect(folder.left(), folder.top() - tab_h, tab_w, tab_h + 5)
        has_image = pixmap is not None and not pixmap.isNull()
        front_h = int(icon_h * (0.25 if has_image else 0.70))
        front_rect = QRect(folder.left(), folder.bottom() - front_h, folder.width(), front_h)

        # Subtle folder shadow (two overlapping rects, no path merge)
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 20))
        p.drawRoundedRect(tab_rect.adjusted(1, 1, 1, 1), _BADGE_R, _BADGE_R)
        p.drawRoundedRect(folder.adjusted(1, 2, -1, -1), _BADGE_R, _BADGE_R)
        p.restore()

        # Tab + Body (two overlapping rects matching delegate — avoids antialias seam)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(body_c)
        p.drawRoundedRect(tab_rect, _BADGE_R, _BADGE_R)
        p.drawRoundedRect(folder, _BADGE_R, _BADGE_R)

        if has_image and pixmap is not None:
            img_rect = folder.adjusted(6, -15, -6, -8)
            scaled = pixmap.scaled(img_rect.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            px = img_rect.center().x() - scaled.width() // 2
            py = img_rect.bottom() - scaled.height()
            p.save()
            p.setClipRect(folder)
            p.drawPixmap(px, py, scaled)
            p.restore()

        p.setBrush(front_c)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(front_rect, _BADGE_R, _BADGE_R)
        p.setPen(QPen(self._clr_folder_highlight, 1))
        p.drawLine(front_rect.left() + 2, front_rect.top(),
                    front_rect.right() - 2, front_rect.top())

    def _draw_image(self, p: QPainter, rect: QRect, pixmap):
        bg = self._clr_base.lighter(120)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(rect, _PREVIEW_R, _PREVIEW_R)
        inner = rect.adjusted(3, 3, -3, -3)
        scaled = pixmap.scaled(inner.size(), Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        ix = inner.x() + (inner.width() - scaled.width()) // 2
        iy = inner.y() + (inner.height() - scaled.height()) // 2
        p.drawPixmap(ix, iy, scaled)

    def _draw_type_icon(self, p: QPainter, rect: QRect, is_dir: bool, name: str):
        if is_dir:
            body_c, _ = self._folder_colors()
            folder = QRect(rect.x(), rect.y() + int(rect.height() * 0.15),
                           rect.width(), int(rect.height() * 0.85))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(body_c)
            p.drawRoundedRect(folder, _BADGE_R, _BADGE_R)
        else:
            ext = name[name.rfind("."):].lower() if "." in name else ""
            clr = QColor(badge_color_for_extension(ext))
            clr.setAlpha(50)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(clr)
            p.drawRoundedRect(rect, _PREVIEW_R, _PREVIEW_R)
            p.setFont(self._font_sub)
            p.setPen(self._clr_muted)
            cat = EXT_TO_CATEGORY.get(ext, "Other")
            labels = dict(FILTER_CATEGORY_LABELS)
            label = labels.get(cat, cat)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                       self._fm_sub.elidedText(label, Qt.TextElideMode.ElideRight, rect.width()))

    # ── Badge ────────────────────────────────────────────────

    def _draw_badge(self, p: QPainter, preview_rect: QRect, ext: str):
        color = badge_color_for_extension(ext)
        label = badge_label_for_extension(ext)
        p.setFont(self._font_badge)
        bw = self._fm_badge.horizontalAdvance(label) + _BADGE_PAD_H * 2
        badge_rect = QRect(
            preview_rect.right() - bw - 2, preview_rect.top() + 2,
            bw, _BADGE_H,
        )
        qc = QColor(color)
        p.setBrush(qc)
        p.drawRoundedRect(badge_rect, _BADGE_R, _BADGE_R)
        text_color = QColor(contrast_on(qc.name()))
        p.setPen(text_color)
        p.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, label)
