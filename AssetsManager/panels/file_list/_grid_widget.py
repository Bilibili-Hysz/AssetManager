"""GPU-free custom QWidget canvas for file list grid rendering.

Matches GridDelegate layout exactly: CARD_PAD=6, PREVIEW_MARGIN=4,
_TEXT_TOP_GAP=5, _TEXT_LINE_GAP=1, font 9pt bold + 8pt sub.

The class body is split by responsibility into three mixin modules:

  _grid_widget_render.py   — RenderMixin: QPainter drawing, texture baking
  _grid_widget_interact.py — InteractMixin: events, selection, scrolling
  _grid_widget_data.py     — DataMixin: model binding, layout, diagnostics

This module keeps the class identity: signals, constructor orchestration and
teardown. ``QPainter``, ``perf_counter`` and ``TimerHandle`` stay in this
module's namespace — the mixins resolve them lazily through this module so
tests can monkeypatch the widget's painter, clock and timer classes.
"""
from typing import TYPE_CHECKING

from time import perf_counter  # noqa: F401  (resolved lazily by the mixins; patched in tests)
from PySide6.QtCore import Qt, QRect, QPoint, Signal
from PySide6.QtGui import QPainter, QPixmap, QColor, QFont, QFontMetrics  # noqa: F401  (QPainter resolved lazily by the mixins)
from PySide6.QtWidgets import QWidget, QScrollBar, QSizePolicy
from AssetsManager.core import themes
from AssetsManager.core.timers import TimerHandle  # noqa: F401  (patched in tests)
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.panels.file_list._ui_helpers import _make_folder_highlight
from AssetsManager.panels.file_list._grid_texture_cache import GridTextureCache
from AssetsManager.panels.file_list._animator import Animator
from AssetsManager.panels.file_list._grid_widget_render import (  # noqa: F401
    RenderMixin, _FULL_REBUILD_TEXTURE_BUDGET,
)
from AssetsManager.panels.file_list._grid_widget_interact import InteractMixin
from AssetsManager.panels.file_list._grid_widget_data import DataMixin

if TYPE_CHECKING:
    from AssetsManager.panels.file_list._model import FileSystemModel
    from AssetsManager.panels.file_list._grid_layout import GridLayout


class FileListGridWidget(RenderMixin, InteractMixin, DataMixin, QWidget):
    """Batch-rendering grid that replaces QListView for local panel use."""
    clicked = Signal(int)
    double_clicked = Signal(int)
    context_menu = Signal(QPoint)
    selection_changed = Signal()
    rename_requested = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        t = themes.get()

        self._model: FileSystemModel | None = None
        self._model_rows = 0
        self._layout: GridLayout | None = None
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
        self._single_shot_handles: list = []
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

    def stop_animations(self) -> None:
        """Cancel panel-owned presentation and queued repaint work before teardown."""
        self._animator.stop()
        self._cancel_frame()
        self._full_rebuild_epoch += 1
        self._full_rebuild_update_queued = False
        self.cancel_pending_timers()

