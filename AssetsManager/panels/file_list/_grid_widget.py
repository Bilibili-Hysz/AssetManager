"""GPU-free custom QWidget canvas for file list grid rendering.

Matches GridDelegate layout exactly: CARD_PAD=6, PREVIEW_MARGIN=4,
_TEXT_TOP_GAP=5, _TEXT_LINE_GAP=1, font 9pt bold + 8pt sub.
"""
from time import perf_counter
import weakref
from PySide6.QtCore import Qt, QSize, QRect, QPoint, QTimer, Signal, QEvent
from PySide6.QtGui import QPainter, QPixmap, QColor, QPen, QFont, QFontMetrics
from PySide6.QtWidgets import QWidget, QScrollBar, QSizePolicy
from AssetsManager.core import icons
from shiboken6 import Shiboken
from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager import i18n
from AssetsManager.panels.file_list._ui_helpers import _make_folder_highlight
from AssetsManager.panels.file_list._common import (
    EXT_TO_CATEGORY, badge_color_for_extension, badge_label_for_extension,
)
from AssetsManager.application.asset_filters import FILTER_CATEGORY_LABELS
from AssetsManager.panels.file_list._model import FileSystemModel
from AssetsManager.panels.file_list._grid_layout import GridLayout
from AssetsManager.panels.file_list._grid_texture_cache import GridTextureCache
from AssetsManager.panels.file_list._animator import Animator

tr = i18n.tr

# Category key → display label (e.g. "models" → "3D Models")
_CATEGORY_LABELS: dict[str, str] = dict(FILTER_CATEGORY_LABELS)

# Layout constants — matching GridDelegate exactly (scaled for DPI)
_CARD_PAD = scaled_px(6)
_PREVIEW_MARGIN = scaled_px(4)
_CORNER_R = scaled_px(10)
_PREVIEW_R = scaled_px(8)
_TEXT_TOP_GAP = scaled_px(5)
_TEXT_LINE_GAP = scaled_px(1)
_BADGE_H = scaled_px(14)
_BADGE_R = scaled_px(6)

_BADGE_PAD_H = scaled_px(5)
_FULL_REBUILD_TEXTURE_BUDGET = 12
_ZOOM_FALLBACK_TEXTURE_BUDGET = 2
_ZOOM_TARGET_TEXTURE_BUDGET = 6


class FileListGridWidget(QWidget):
    """Batch-rendering grid that replaces QListView for local panel use."""

    clicked = Signal(int)
    double_clicked = Signal(int)
    context_menu = Signal(QPoint)
    selection_changed = Signal()
    rename_requested = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        t = themes.get()

        self._model = None
        self._model_rows = 0
        self._layout = None
        self._thumb_size = scaled_px(96)

        self._scroll_y = 0
        self._cache: GridTextureCache = GridTextureCache(
            recorder=lambda: self._performance_recorder,
            session_token=lambda: self._performance_session_token,
            generation=lambda: self._performance_generation,
            model=lambda: self._model,
            scan_reset_pending=lambda: getattr(self, "_scan_reset_pending", False),
        )
        self._zoom_relayout_active = False
        self._zoom_scale_x = 1.0
        self._zoom_scale_y = 1.0
        self._zoom_source_rects: list[QRect] = []
        self._zoom_target_rects: list[QRect] = []
        self._zoom_fallback_textures: dict[int, QPixmap] = {}
        self._zoom_target_textures: dict[int, QPixmap] = {}
        self._zoom_visible_rows: set[int] = set()
        self._zoom_anchor_y_offset = 0
        self._zoom_start_size = self._thumb_size
        self._zoom_target_size = self._thumb_size
        self._texture_dpr = max(1.0, float(self.devicePixelRatioF() or 1.0))
        self._dirty: set[int] = set()
        self._full_rebuild_pending = False
        self._full_rebuild_update_queued = False
        self._full_rebuild_epoch = 0
        self._frame_queued = False
        self._frame_epoch = 0
        # Last (entries identity, visible rows) fed to prioritize_dir_sizes;
        # the reprioritization is skipped on unchanged frames.
        self._last_prioritized_key: tuple | None = None
        self._frame_full = False
        self._frame_rect = QRect()
        self._frame_request_count = 0
        self._hover_row: int = -1
        self._selection: set[int] = set()
        self._last_click_row: int = -1
        self._last_click_pos: QPoint | None = None
        self._rubber_band_active = False
        self._rubber_band_origin: QPoint | None = None
        self._rubber_band_rect: QRect = QRect()
        self._click_pending_row: int = -1
        self._rename_editor = None
        self._rename_name: str | None = None
        self._rename_finish = None

        self._clr_accent = QColor(t["accent"])
        self._clr_heading = QColor(t["heading"])
        self._clr_body = QColor(t["body"])
        self._clr_muted = QColor(t["muted"])
        self._clr_base = QColor(t["base"])
        self._clr_panel = QColor(t["panel"])
        self._clr_border = QColor(t["border"])
        self._clr_folder_highlight = _make_folder_highlight(t)
        self._font_name = QFont()
        self._font_name.setPointSize(scaled_pt(9))
        self._font_name.setBold(True)
        self._fm_name = QFontMetrics(self._font_name)
        self._font_sub = QFont()
        self._font_sub.setPointSize(scaled_pt(8))
        self._fm_sub = QFontMetrics(self._font_sub)
        self._refresh_text_metrics()

        self._scrollbar = QScrollBar(Qt.Orientation.Vertical, self)
        self._scrollbar.valueChanged.connect(self._on_scroll)
        self._scrollbar.setSingleStep(30)
        self._scrollbar.setPageStep(300)
        self._apply_scrollbar_theme()

        # ── Animation state ────────────────────────────────────
        self._animator: Animator = Animator(
            parent=self,
            reduce_motion=self._detect_reduce_motion(),
            on_changed=self._on_anim_changed,
            host=self,
        )
        self._performance_recorder = None
        self._performance_session_token: str | None = None
        self._performance_generation: int | None = None

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(100, 100)

    def _on_anim_changed(self, changed_rows: set[int]) -> None:
        self._request_frame(changed_rows, overlay=True)

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

    def set_model(self, model):
        self._model = model
        model.modelReset.connect(self._on_model_reset)
        model.modelAboutToBeReset.connect(self._cache._capture_path_textures)
        model.scan_started.connect(self._on_scan_started)
        model.dataChanged.connect(self._on_data_changed)

    def set_layout_ref(self, layout):
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
            self._cache._refresh_texture_accounting()
        else:
            self._cache._texture_bytes.clear()
            self._cache._texture_cache_bytes = 0

    def set_performance_generation(self, generation: int) -> None:
        if self._performance_recorder is not None:
            self._performance_generation = generation

    def set_thumb_size(self, size: int):
        if size != self._thumb_size:
            self._cache._path_textures.clear()
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
        self._animator._entrance_queue.clear()
        self._animator._entrance_visible.clear()
        self._animator._thumb_opacity.clear()
        self._zoom_fallback_textures.clear()
        # An interrupted zoom leaves pre-rendered target textures behind. Commit
        # them so the committed cache tracks the zoom size instead of lagging at
        # the original (small) size — which would force the next animation to
        # upscale that small cache across several zoom steps and blur for a frame.
        if self._zoom_target_textures:
            for row, tex in self._zoom_target_textures.items():
                self._cache._cache_texture(row, tex)
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
            self._cache._cache_texture(row, tex)
        self._zoom_target_textures = {}
        self._cache._path_textures.clear()
        self._dirty = {r for r in range(self._model_rows) if r not in target_rows}
        if self._dirty:
            self._full_rebuild_epoch += 1
            self._full_rebuild_pending = True
        self._record_invalidation("zoom", self._model_rows, len(self._cache._textures))
        self._request_frame(full=True)

    def invalidate_textures(self):
        previous_count = len(self._cache._textures)
        self._full_rebuild_epoch += 1
        self._cache._path_textures.clear()
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
                self._cache._path_textures.pop(path, None)
            has_visible_texture = r in self._cache._textures
            self._dirty.add(r)
            if r not in self._animator._thumbnail_rows:
                self._animator._thumbnail_rows.add(r)
                # A texture contains the entire card, not just its preview.
                # Fading a replacement would briefly hide the whole card.
                if not has_visible_texture and not self._animator._reduce_motion and not self._zoom_relayout_active:
                    self._animator._thumb_opacity[r] = 0.0
        self._record_invalidation("thumbnail_batch", len(rows), len(self._cache._textures))
        if self._animator._thumb_opacity and not self._animator._anim_timer.isActive():
            self._animator._anim_timer.start()
        self._request_frame(rows)

    def start_thumbnail_delivery_measurement(self) -> float | None:
        """Return a timer only when scoped Grid diagnostics are enabled."""
        return perf_counter() if self._performance_recorder is not None else None

    def record_thumbnail_pixmap(self, started: float | None) -> None:
        self._record_thumbnail_delivery("grid.thumbnail_pixmap", started, 1)

    def record_thumbnail_batch(self, count: int) -> None:
        self._record_thumbnail_delivery("grid.thumbnail_batch", None, count)

    def _on_scan_started(self, _generation: int):
        """Drop path textures before a new filesystem scan can change files."""
        self._scan_reset_pending = True
        self._cache._path_textures.clear()

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
        previous_count = len(self._cache._textures)
        self._full_rebuild_epoch += 1
        self._cache._clear_textures()
        self._dirty.clear()
        self._full_rebuild_pending = False
        self._full_rebuild_update_queued = False
        self._selection.clear()
        self._animator._thumb_opacity.clear()
        self._animator._thumbnail_rows.clear()
        self._animator._hover_progress.clear()
        self._animator._selection_progress.clear()
        self._animator._entrance_queue.clear()
        self._animator._entrance_visible.clear()
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
            FileSystemModel.SUBTITLE_ROLE,
            FileSystemModel.IS_DIR_ROLE,
        }
        if roles and not roles.intersection(static_roles):
            return
        changed_count = bottom_right.row() - top_left.row() + 1
        previous_count = len(self._cache._textures)
        for r in range(top_left.row(), bottom_right.row() + 1):
            path = self._model.path_at(r) if self._model is not None else None
            if path:
                self._cache._path_textures.pop(path, None)
            self._dirty.add(r)
            self._cache._textures.pop(r, None)
            self._cache._remove_texture_bytes(r)
        self._record_invalidation("model_data", changed_count, previous_count)
        self._request_frame(range(top_left.row(), bottom_right.row() + 1))

    def selection_model_rows(self) -> set[int]:
        return self._selection.copy()

    def select_all(self):
        old = self._selection.copy()
        self._selection = set(range(self._model_rows))
        self._animator._apply_selection_progress(old)
        if old != self._selection:
            self.selection_changed.emit()
        self._request_frame(self._selection | old, overlay=True)

    def clear_selection(self):
        old = self._selection.copy()
        self._selection.clear()
        self._animator._apply_selection_progress(old)
        self.selection_changed.emit()
        self._request_frame(old, overlay=True)

    # ── Layout update ───────────────────────────────────────

    def update_layout(self, item_count: int, widget_width: int, *, relayout_only: bool = False):
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
            self._layout.compute(item_count, max(widget_width - 20, 100),
                                 self._thumb_size, item_hint=self._item_hint)
            th = self._layout.total_height
            self._scrollbar.setRange(0, max(0, th - self.height()))
            to_del = [r for r in self._cache._textures if r >= item_count]
            for r in to_del:
                del self._cache._textures[r]
                self._cache._remove_texture_bytes(r)
            if not relayout_only and not self._cache._textures:
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
        text_font.setPointSize(scaled_pt(11))
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

    def showEvent(self, event):
        super().showEvent(event)
        if self._animator._pending_presentation is not None:
            QTimer.singleShot(0, self._animator._present_pending_generation)

    def paintEvent(self, _evt):
        if not self._model or not self.isVisible():
            return
        if self.width() == 0 or self.height() == 0:
            return
        recorder = self._performance_recorder
        started = perf_counter() if recorder is not None else None
        session_token = self._performance_session_token
        generation = self._performance_generation
        p = QPainter(self)
        # Cached textures already contain antialiased card geometry. Keep the
        # hot path pixmap-only; rounded overlays enable AA locally below.
        p.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform,
            self._zoom_relayout_active and not self._animator._reduce_motion,
        )
        dpr = max(1.0, float(self.devicePixelRatioF() or 1.0))
        if dpr != self._texture_dpr:
            self._texture_dpr = dpr
            self._full_rebuild_epoch += 1
            self._cache._clear_textures()
            self._cache._path_textures.clear()
            self._dirty = set(range(self._model_rows))
            self._full_rebuild_pending = True
        if not themes.bg_enabled():
            p.fillRect(self.rect(), self._clr_panel)

        if self._model_rows == 0 or self._layout is None:
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
        skipped_dirty = False

        # ── Pass 1: ensure cell textures are built (budget-limited) ──
        for row in visible:
            rect = self._layout.rect_at(row)
            if rect is None:
                continue
            if not update_rect.intersects(rect.translated(0, -sy)):
                skipped_dirty = skipped_dirty or (row in self._dirty)
                continue
            dirty = row in self._dirty
            tex = self._cache._textures.get(row)
            if tex is None and self._cache._path_textures and not self._zoom_relayout_active:
                path = self._model.path_at(row)
                if path:
                    cached = self._cache.take_path_texture(path)
                    if cached is not None:
                        tex = cached
                        self._cache._cache_texture(row, cached)
                        self._dirty.discard(row)
                        dirty = False
            if tex is not None:
                self._cache._textures.move_to_end(row)
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
                        self._cache._cache_texture(row, replacement)
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
                if rect is None or not update_rect.intersects(rect.translated(0, -sy)):
                    continue
                tex = self._cache._textures.get(row) or self._zoom_fallback_textures.get(row)
                if tex is None:
                    continue
                op = self._animator._thumb_opacity.get(row, 1.0)
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
                if rect is None or not update_rect.intersects(rect.translated(0, -sy)):
                    continue
                if not self._animator._reduce_motion and (row == self._hover_row or row in self._animator._hover_progress):
                    continue
                vp = rect.translated(0, -sy)
                op = self._animator._thumb_opacity.get(row, 1.0)
                tex = self._cache._textures.get(row)
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
                if rect is None or not update_rect.intersects(rect.translated(0, -sy)):
                    continue
                vp = rect.translated(0, -sy)
                op = self._animator._thumb_opacity.get(row, 1.0)
                tex = self._cache._textures.get(row)
                draw_rect = vp
                if row == self._hover_row and not self._animator._reduce_motion and tex is not None:
                    sw = int(vp.width() * lift_scale)
                    sh = int(vp.height() * lift_scale)
                    dx = (vp.width() - sw) // 2
                    target = QRect(vp.x() + dx, vp.y() + lift_dy, sw, sh)
                    draw_rect = target
                    if op < 1.0:
                        p.save()
                        p.setOpacity(op)
                        p.drawPixmap(target, tex)
                        p.restore()
                    else:
                        p.drawPixmap(target, tex)
                elif row in self._animator._hover_progress:
                    pv = self._animator._hover_progress[row]
                    if pv > 0.01 and tex is not None:
                        s = 1.0 + 0.075 * pv
                        sw = int(vp.width() * s)
                        sh = int(vp.height() * s)
                        dx = (vp.width() - sw) // 2
                        dy = int(lift_dy * pv)
                        target = QRect(vp.x() + dx, vp.y() + dy, sw, sh)
                        draw_rect = target
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
            rb = QColor(self._clr_accent)
            rb.setAlpha(30)
            p.setPen(QPen(self._clr_accent, 1))
            p.setBrush(rb)
            band = self._rubber_band_rect
            if not self._zoom_relayout_active:
                band = band.translated(0, -sy)
            p.drawRect(band)

        p.end()
        self._record_performance(
            "grid.frame", started, session_token, generation, len(visible), texture_build_count, deferred_texture_count
        )
        if deferred_texture_count or (self._full_rebuild_pending and skipped_dirty):
            self._queue_full_rebuild_update()
        elif self._full_rebuild_pending:
            self._full_rebuild_pending = False

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

        QTimer.singleShot(0, flush)

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

    def stop_animations(self) -> None:
        """Cancel panel-owned presentation and queued repaint work before teardown."""
        self._animator.stop()
        self._cancel_frame()
        self._full_rebuild_epoch += 1
        self._full_rebuild_update_queued = False

    def discard_pending_presentation(self, generation: int) -> None:
        """Discard a hidden presentation superseded by an empty newer commit."""
        self._animator.discard_pending_presentation(generation)

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
        recorder = self._performance_recorder
        if recorder is None or started is None:
            return
        try:
            attributes = {
                "visible_item_count": visible_count,
                "queued_entrance_count": len(self._animator._entrance_queue),
            }
            if texture_build_count is not None:
                attributes.update(
                    texture_cache_count=len(self._cache._textures),
                    texture_cache_bytes=self._cache._texture_cache_bytes,
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

    def _render_item(self, row: int, item_rect: QRect) -> QPixmap | None:
        """Render static item content to an offscreen QPixmap."""
        dpr = max(1.0, float(self.devicePixelRatioF() or 1.0))
        tex = QPixmap(int(item_rect.width() * dpr), int(item_rect.height() * dpr))
        tex.setDevicePixelRatio(dpr)
        tex.fill(Qt.GlobalColor.transparent)
        tp = QPainter(tex)
        tp.setRenderHint(QPainter.RenderHint.Antialiasing)
        tp.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        is_dir = self._model.data(self._model.index(row, 0), FileSystemModel.IS_DIR_ROLE)
        pixmap = self._model.data(self._model.index(row, 0), FileSystemModel.RAW_PIXMAP_ROLE)
        name = self._model.data(self._model.index(row, 0), Qt.ItemDataRole.DisplayRole)
        subtitle = self._model.data(self._model.index(row, 0), FileSystemModel.SUBTITLE_ROLE)
        card = self._card_rect_in_item(QRect(0, 0, item_rect.width(), item_rect.height()))

        # Interaction states are painted later so mouse movement and selection
        # changes do not invalidate this expensive thumbnail texture.
        r2, g2, b2 = self._clr_heading.red(), self._clr_heading.green(), self._clr_heading.blue()
        fill = QColor(r2, g2, b2, 10)
        border = QColor(r2, g2, b2, 20)
        tp.setPen(QPen(border, 1))
        tp.setBrush(fill)
        tp.drawRoundedRect(card, _CORNER_R, _CORNER_R)

        preview = QRect(card.x() + _PREVIEW_MARGIN, card.y() + _PREVIEW_MARGIN,
                        self._thumb_size, self._thumb_size)
        if is_dir:
            self._draw_folder(tp, preview, pixmap)
        elif pixmap and not pixmap.isNull():
            self._draw_image(tp, preview, pixmap)
        else:
            self._draw_type_icon(tp, preview, is_dir, name)

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

        QTimer.singleShot(0, update)

    def _draw_interaction_overlay(self, p: QPainter, row: int, item_rect: QRect, opacity: float):
        """Paint selection and hover without rebuilding the cached item texture."""
        selection_progress = 1.0 if row in self._selection else self._animator._selection_progress.get(row, 0.0)
        hover_progress = 1.0 if row == self._hover_row else self._animator._hover_progress.get(row, 0.0)
        if selection_progress <= 0.01 and hover_progress <= 0.01:
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

    def _draw_folder(self, p: QPainter, rect: QRect, pixmap):
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
        p.drawRoundedRect(tab_rect.adjusted(1, 1, 1, 1), 4, 4)
        p.drawRoundedRect(folder.adjusted(1, 2, -1, -1), 5, 5)
        p.restore()

        # Tab + Body (two overlapping rects matching delegate — avoids antialias seam)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(body_c)
        p.drawRoundedRect(tab_rect, 4, 4)
        p.drawRoundedRect(folder, 5, 5)

        if has_image:
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
        p.drawRoundedRect(front_rect, 5, 5)
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
            p.drawRoundedRect(folder, 5, 5)
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
            label = _CATEGORY_LABELS.get(cat, cat)
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
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawRoundedRect(badge_rect, _BADGE_R, _BADGE_R)
        text_color = QColor("white") if QColor(color).lightness() < 128 else QColor("black")
        p.setPen(text_color)
        p.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, label)

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
            f"border-radius:{scaled_px(3)}px; min-height:{scaled_px(24)}px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}")

    def refresh_theme(self):
        previous_count = len(self._cache._textures)
        self._full_rebuild_epoch += 1
        self._rebuild_theme()
        self._cache._clear_textures()
        self._cache._path_textures.clear()
        self._dirty = set(range(self._model_rows))
        self._full_rebuild_pending = True
        self._record_invalidation("theme", self._model_rows, previous_count)
        self._request_frame(full=True)

    def refresh_scale(self):
        """Refresh scale-dependent metrics and repaint cached card textures."""
        previous_count = len(self._cache._textures)
        self._full_rebuild_epoch += 1
        self._refresh_text_metrics()
        self._apply_scrollbar_theme()
        self._cache._clear_textures()
        self._cache._path_textures.clear()
        self._dirty = set(range(self._model_rows))
        self._full_rebuild_pending = True
        self._record_invalidation("scale", self._model_rows, previous_count)
        self._relayout_scrollbar()
        self._request_frame(full=True)

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
        super().resizeEvent(event)
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
                    self._animator._apply_selection_progress(old_selection)
                    self._request_frame(self._selection | old_selection, overlay=True)
            elif event.button() == Qt.MouseButton.LeftButton:
                self._rubber_band_active = True
                self._rubber_band_origin = QPoint(pos)
                self._rubber_band_rect = QRect(pos.x(), pos.y(), 0, 0)
                if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                    old_sel = self._selection.copy()
                    self._selection.clear()
                    self._animator._apply_selection_progress(old_sel)
                self.selection_changed.emit()
                self._request_frame(full=True)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        pos = event.position().toPoint()
        pos.setY(pos.y() + self._scroll_y)
        if self._layout:
            row = self._layout.row_at(pos.x(), pos.y())
            if row >= 0:
                self.double_clicked.emit(row)
        super().mouseDoubleClickEvent(event)

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
                    if not self._animator._reduce_motion:
                        for r in preview_sel - self._selection:
                            self._animator._selection_progress.setdefault(r, 0.0)
                        for r in self._selection - preview_sel:
                            if r not in self._animator._selection_progress:
                                self._animator._selection_progress[r] = 1.0
                        if not self._animator._anim_timer.isActive():
                            self._animator._anim_timer.start()
                    self._selection = preview_sel
                    self.selection_changed.emit()
            self._request_frame(full=True)
        elif self._layout:
            # Freeze hover during potential drag (left button held on an item)
            if (event.buttons() & Qt.MouseButton.LeftButton
                    and not self._rubber_band_active
                    and self._click_pending_row >= 0):
                super().mouseMoveEvent(event)
                return
            row = self._layout.row_at(pos.x(), pos.y())
            if self._hover_row != row:
                old = self._hover_row
                self._hover_row = row
                if not self._animator._reduce_motion:
                    if old >= 0:
                        self._animator._hover_progress.setdefault(old, 1.0)
                    if row >= 0:
                        self._animator._hover_progress.setdefault(row, 0.0)
                    if not self._animator._anim_timer.isActive():
                        self._animator._anim_timer.start()
                self._request_frame([old, row], overlay=True)
        super().mouseMoveEvent(event)

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
                if not self._animator._reduce_motion and final_sel:
                    for r in final_sel:
                        self._animator._selection_progress.setdefault(r, 0.0)
                    if not self._animator._anim_timer.isActive():
                        self._animator._anim_timer.start()
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
                self._animator._apply_selection_progress(old_sel)
                self.clicked.emit(row)
                self.selection_changed.emit()
                self._request_frame(self._selection | old_sel, overlay=True)
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        # Use actual cursor position, not entry-point (entry may be at y=0 above first item)
        pos = self.mapFromGlobal(self.cursor().pos())
        pos.setY(pos.y() + self._scroll_y)
        if self._layout:
            row = self._layout.row_at(pos.x(), pos.y())
            if row >= 0 and self._hover_row != row:
                old = self._hover_row
                self._hover_row = row
                if not self._animator._reduce_motion:
                    if old >= 0:
                        self._animator._hover_progress.setdefault(old, 1.0)
                    self._animator._hover_progress.setdefault(row, 0.0)
                    if not self._animator._anim_timer.isActive():
                        self._animator._anim_timer.start()
                self._request_frame([old, row], overlay=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._hover_row >= 0:
            old = self._hover_row
            self._hover_row = -1
            if not self._animator._reduce_motion:
                self._animator._hover_progress.setdefault(old, 1.0)
                if not self._animator._anim_timer.isActive():
                    self._animator._anim_timer.start()
            self._request_frame([old], overlay=True)
        super().leaveEvent(event)

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
            super().keyPressEvent(event)

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
        if not self._layout:
            return
        rect = self._layout.rect_at(row)
        if rect is None:
            return
        name = self._model.data(self._model.index(row, 0), Qt.ItemDataRole.DisplayRole) or ""
        editor = QLineEdit(self)
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
        editor.installEventFilter(self)

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


