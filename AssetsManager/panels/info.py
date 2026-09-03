"""Info panel — splitter layout, dynamic preview, metadata, tags, notes.

Layout: QSplitter(preview / metadata scroll) + fixed Actions bar at bottom.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import cast

from PySide6.QtCore import (
    Qt, Signal, QSize, QPropertyAnimation, QEasingCurve, QObject, QTimer,
    QByteArray, QBuffer, QIODevice,
)
from PySide6.QtWidgets import (
    QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QTextEdit,
    QGroupBox, QWidget, QInputDialog, QSplitter, QScrollArea, QFrame,
    QSizePolicy,
)
from PySide6.QtGui import QImage, QPixmap

from AssetsManager.panels.base import PanelContent
from AssetsManager.panels._ai_tag_common import ai_tag_error_text, ai_tagging_enabled
from AssetsManager.application.desktop_ports import TagsViewPort
from AssetsManager.application.thumbnail_service import MAX_THUMBNAIL_SOURCE_BYTES
from AssetsManager.core.cache import LRUCache
from AssetsManager.core.constants import IMAGE_EXTS
from AssetsManager.core.file_snapshot import read_snapshot
from AssetsManager.core.settings import AppSettings
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.core.workers import BoundedPool, CancellableRunnable, CancellationToken
from AssetsManager.core import themes, icons
from AssetsManager.core.color_utils import alpha
from AssetsManager.widgets.stylekit import StyleKit
from AssetsManager.widgets.tag_chip import create_tag_chip, tag_color_from
from AssetsManager.panels._info_parts import (
    _DragLabel,
    _PreviewLabel,
    _FlowLayout,
    _AsyncRequest,
    _FileInfoTask,
    _LinkScanTask,
    format_info_size,
)

from AssetsManager import i18n

_log = logging.getLogger(__name__)
tr = i18n.tr

PREVIEW_LOAD_MAX = 2000
_MAX_ANIMATED_TAGS = 8
# Hidden chips are pooled for reuse instead of being rebuilt on every file
# switch. The pool is LRU-bounded so browsing a huge tag vocabulary cannot
# accumulate one live QWidget per tag seen over a long session.
_TAG_CHIP_POOL_LIMIT = 96


class InfoPanel(PanelContent):
    open_requested = Signal(str)
    copy_path_requested = Signal(str)
    view_fullscreen = Signal(str)  # request viewer panel
    navigate_requested = Signal(str)  # request file-list navigation

    panel_state_key = "info_panel_layout"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._library_root = ""
        self._scoped_services = None
        self._metadata_port = None
        self._tags_port: "TagsViewPort | None" = None
        self._controller = None
        self._current_path = ""
        self._preview_pixmap: QPixmap | None = None
        self._preview_icon_name = ""
        self._preview_state = "empty"  # empty | loading | image | fallback
        self._notes_timer = None
        self._notes_save_path: str | None = None
        self._rendered_tags: tuple[str, ...] = ()
        self._sidebar_depth = 2
        self._branch_depths: dict[str, int] = {}
        self._pending_task: _FileInfoTask | None = None
        self._size_tasks: dict[_AsyncRequest, QObject] = {}
        self._link_scan_task = None
        self._async_generation = 0
        self._async_request: _AsyncRequest | None = None
        self._info_pool = BoundedPool(2)
        self._info_token = CancellationToken()
        self._link_token = CancellationToken()
        self._size_pool = BoundedPool(1)
        self._size_token = CancellationToken()
        self._reduce_motion = self._detect_reduce_motion()

        # ── Splitter ──────────────────────────────────────────

        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.setHandleWidth(5)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.content_layout.addWidget(self._splitter, 1)

        # ── Preview area (top pane) ───────────────────────────

        self._preview_host = QWidget()
        self._preview_host.setStyleSheet("background: transparent;")
        preview_layout = QVBoxLayout(self._preview_host)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        self._preview = _PreviewLabel(parent=self)
        self._preview.view_fullscreen.connect(self._on_preview_double_click)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumHeight(scaled_px(60))
        self._preview.setCursor(Qt.CursorShape.PointingHandCursor)
        self._preview.setToolTip(tr("info.preview_dbl_click"))
        preview_layout.addWidget(self._preview, 1)

        self._empty_preview_state = QWidget()
        empty_layout = QVBoxLayout(self._empty_preview_state)
        empty_layout.setContentsMargins(scaled_px(12), scaled_px(12), scaled_px(12), scaled_px(12))
        empty_layout.setSpacing(scaled_px(8))
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_preview_icon = QLabel()
        self._empty_preview_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_preview_icon.setAccessibleName(tr("info.no_file_selected"))
        empty_layout.addWidget(self._empty_preview_icon, 0, Qt.AlignmentFlag.AlignCenter)
        self._empty_preview_label = QLabel()
        self._empty_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_preview_label.setWordWrap(True)
        self._empty_preview_label.setAccessibleName(tr("info.no_file_selected"))
        empty_layout.addWidget(self._empty_preview_label, 0, Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self._empty_preview_state, 1)
        self._empty_preview_state.hide()
        self._splitter.addWidget(self._preview_host)
        # Install event filter AFTER all children are set up
        self._preview_host.installEventFilter(self)

        # ── Metadata area (bottom pane, scrollable with sticky MicroTabBar) ───
        from AssetsManager.widgets.micro_tab_bar import MicroTabBar

        self._details_container = QWidget()
        self._details_container.setStyleSheet("background: transparent;")
        details_container_layout = QVBoxLayout(self._details_container)
        details_container_layout.setContentsMargins(0, scaled_px(2), 0, 0)
        details_container_layout.setSpacing(scaled_px(4))

        self._section_preference: dict[str, bool] = {"meta": True, "tags": True, "notes": True}
        self._tab_bar = MicroTabBar([
            tr("info.all"),
            tr("info.title"),
            tr("info.tags"),
            tr("info.notes"),
        ], parent=self)
        self._tab_bar.current_changed.connect(self._on_info_tab_changed)
        details_container_layout.addWidget(self._tab_bar)

        self._details_scroll = QScrollArea()
        self._details_scroll.setWidgetResizable(True)
        self._details_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._details_scroll.viewport().setStyleSheet(
            "background: transparent;")

        details_widget = QWidget()
        details_widget.setStyleSheet("background: transparent;")
        details_layout = QVBoxLayout(details_widget)
        details_layout.setContentsMargins(scaled_px(2), scaled_px(2), scaled_px(2), scaled_px(2))
        details_layout.setSpacing(scaled_px(4))

        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        meta = QGroupBox(tr("info.title"))
        meta.setStyleSheet(self._group_css(sk))
        self._meta_grp = meta
        meta_layout = QVBoxLayout(meta)
        meta_layout.setSpacing(scaled_px(2))

        self._name = QLabel("—")
        self._name.setStyleSheet(
            sk.label_css("heading", size=14, bold=True)
            + f" QLabel {{ padding: {sk.px(2)}px 0; }}")
        self._name.setWordWrap(True)
        meta_layout.addWidget(self._name)

        # Star rating (0-5; NULL/unrated renders all stars muted).
        self._rating_row = self._make_rating_row()
        meta_layout.addWidget(self._rating_row)

        # Registered metadata fields (key -> QWidget)
        self._fields: dict[str, QWidget] = {}
        self._fields_layout = meta_layout

        self._register_field("type", tr("info.field_type"), "—")
        self._register_field("size", tr("info.field_size"), "—")
        self._register_field("summary", tr("info.field_contains"), "")
        self._fields["summary"].hide()
        self._register_field("date", tr("info.field_modified"), "—")
        self._register_field("path", tr("info.field_path"), "—")

        self._field_link = self._make_link_field()
        meta_layout.addWidget(self._field_link)

        from AssetsManager.widgets.dominant_palette_strip import DominantPaletteStrip
        self._palette_strip = DominantPaletteStrip(parent=self)
        meta_layout.addWidget(self._palette_strip)

        # Plugin metadata fields (populated dynamically)
        self._plugin_fields_widget = QWidget()
        self._plugin_fields_widget.setStyleSheet("background: transparent;")
        self._plugin_fields_layout = QVBoxLayout(self._plugin_fields_widget)
        self._plugin_fields_layout.setContentsMargins(0, 0, 0, 0)
        self._plugin_fields_layout.setSpacing(scaled_px(2))
        self._plugin_fields_widget.setVisible(False)
        self._plugin_field_rows: dict[str, QWidget] = {}
        meta_layout.addWidget(self._plugin_fields_widget)

        details_layout.addWidget(meta)

        # Tags
        tags_grp = QGroupBox(tr("info.tags"))
        tags_grp.setStyleSheet(self._group_css(sk))
        self._tags_grp = tags_grp
        tags_outer = QVBoxLayout(tags_grp)
        tags_outer.setSpacing(scaled_px(4))

        self._tags_flow = QWidget()
        self._tags_flow.setStyleSheet("background: transparent;")
        flow_layout = _FlowLayout(self._tags_flow, margin=0, spacing=scaled_px(4))
        self._tags_flow_layout = flow_layout
        self._tags_widgets: list[QWidget] = []
        self._tag_chip_pool: dict[str, QWidget] = {}
        tags_outer.addWidget(self._tags_flow)

        add_row = QHBoxLayout()
        self._add_tag_btn = QPushButton(tr("info.add_tag"))
        self._add_tag_btn.setIcon(icons.icon("tag", color="icon_muted", size=scaled_px(14)))
        self._add_tag_btn.setIconSize(QSize(scaled_px(14), scaled_px(14)))
        self._add_tag_btn.setAccessibleName(tr("info.add_tag"))
        self._add_tag_btn.clicked.connect(self._add_tag)
        self._add_tag_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {sk.token('muted')}; "
            f"border: {scaled_px(1)}px dashed {sk.token('border')}; "
            f"border-radius: {sk.px(int(themes.prop('border_radius', 'sm')))}px; "
            f"padding: {sk.px(int(themes.prop('spacing', 'xs')))}px {sk.px(int(themes.prop('spacing', 'md')))}px; "
            f"font-size: {sk.pt(int(themes.prop('font_size', 'sm')))}px; }}"
            f"QPushButton:hover {{ background: {alpha(sk.token('hover_overlay'), themes.prop('opacity', 'hover'))}; }}"
            f"QPushButton:pressed {{ background: {alpha(sk.token('accent'), 0.28)}; }}")
        self._add_tag_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_row.addWidget(self._add_tag_btn)
        self._manage_btn = QPushButton(tr("info.manage_tags"))
        self._manage_btn.setIcon(icons.icon("settings", color="icon_muted", size=scaled_px(14)))
        self._manage_btn.setIconSize(QSize(scaled_px(14), scaled_px(14)))
        self._manage_btn.setAccessibleName(tr("info.manage_tags"))
        self._manage_btn.clicked.connect(self._open_tag_editor)
        self._manage_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {sk.token('muted')}; "
            f"border: {scaled_px(1)}px solid {sk.token('border')}; "
            f"border-radius: {sk.px(int(themes.prop('border_radius', 'sm')))}px; "
            f"padding: {sk.px(int(themes.prop('spacing', 'xs')))}px {sk.px(int(themes.prop('spacing', 'md')))}px; "
            f"font-size: {sk.pt(int(themes.prop('font_size', 'sm')))}px; }}"
            f"QPushButton:hover {{ background: {alpha(sk.token('hover_overlay'), themes.prop('opacity', 'hover'))}; }}"
            f"QPushButton:pressed {{ background: {alpha(sk.token('accent'), 0.28)}; }}")
        self._manage_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_row.addWidget(self._manage_btn)
        self._browse_btn = QPushButton(tr("info.browse_tags"))
        self._browse_btn.setIcon(icons.icon("tag", color="icon_muted", size=scaled_px(14)))
        self._browse_btn.setIconSize(QSize(scaled_px(14), scaled_px(14)))
        self._browse_btn.setAccessibleName(tr("info.browse_tags"))
        self._browse_btn.setToolTip(tr("info.browse_tags_tooltip"))
        self._browse_btn.clicked.connect(self._open_tag_browser)
        self._browse_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {sk.token('muted')}; "
            f"border: {scaled_px(1)}px solid {sk.token('border')}; "
            f"border-radius: {sk.px(int(themes.prop('border_radius', 'sm')))}px; "
            f"padding: {sk.px(int(themes.prop('spacing', 'xs')))}px {sk.px(int(themes.prop('spacing', 'md')))}px; "
            f"font-size: {sk.pt(int(themes.prop('font_size', 'sm')))}px; }}"
            f"QPushButton:hover {{ background: {alpha(sk.token('hover_overlay'), themes.prop('opacity', 'hover'))}; }}"
            f"QPushButton:pressed {{ background: {alpha(sk.token('accent'), 0.28)}; }}")
        self._browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_row.addWidget(self._browse_btn)
        # H2-c: AI tagging button — invisible until the user explicitly
        # enables AI tagging in settings (zero behavior change when off).
        self._ai_tag_btn = QPushButton(tr("info.ai_tag"))
        self._ai_tag_btn.setIcon(icons.icon("tag", color="icon_muted", size=scaled_px(14)))
        self._ai_tag_btn.setIconSize(QSize(scaled_px(14), scaled_px(14)))
        self._ai_tag_btn.setAccessibleName(tr("info.ai_tag"))
        self._ai_tag_btn.setToolTip(tr("info.ai_tag_tooltip"))
        self._ai_tag_btn.clicked.connect(self._ai_tag)
        self._ai_tag_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {sk.token('muted')}; "
            f"border: {scaled_px(1)}px solid {sk.token('border')}; "
            f"border-radius: {sk.px(int(themes.prop('border_radius', 'sm')))}px; "
            f"padding: {sk.px(int(themes.prop('spacing', 'xs')))}px {sk.px(int(themes.prop('spacing', 'md')))}px; "
            f"font-size: {sk.pt(int(themes.prop('font_size', 'sm')))}px; }}"
            f"QPushButton:hover {{ background: {alpha(sk.token('hover_overlay'), themes.prop('opacity', 'hover'))}; }}"
            f"QPushButton:pressed {{ background: {alpha(sk.token('accent'), 0.28)}; }}")
        self._ai_tag_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ai_tag_btn.setVisible(ai_tagging_enabled())
        add_row.addWidget(self._ai_tag_btn)
        add_row.addStretch()
        tags_outer.addLayout(add_row)
        details_layout.addWidget(tags_grp)

        # Notes — fills space between Tags and Actions
        notes_grp = QGroupBox(tr("info.notes"))
        notes_grp.setStyleSheet(self._group_css(sk))
        self._notes_grp = notes_grp
        notes_layout = QVBoxLayout(notes_grp)
        self._notes = QTextEdit()
        self._notes.setMinimumHeight(scaled_px(12))
        self._notes.setPlaceholderText(tr("info.notes_placeholder"))
        self._notes.textChanged.connect(self._schedule_notes_save)
        notes_layout.addWidget(self._notes)
        details_layout.addWidget(notes_grp, 1)

        self._details_scroll.setWidget(details_widget)
        details_container_layout.addWidget(self._details_scroll, 1)
        self._splitter.addWidget(self._details_container)
        # ── Actions (fixed at bottom, outside scroll) ──────────

        act_bar = QWidget()
        self._act_bar = act_bar
        act_bar.setStyleSheet(f"background: transparent; "
                              f"border-top: {scaled_px(1)}px solid {sk.token('border_subtle')};")
        act_bar.setFixedHeight(scaled_px(28))
        act_layout = QHBoxLayout(act_bar)
        act_layout.setContentsMargins(scaled_px(10), scaled_px(4), scaled_px(10), scaled_px(4))
        act_layout.setSpacing(scaled_px(8))
        act_layout.addStretch()
        self._open_btn = QPushButton(tr("info.open"))
        self._open_btn.setIcon(icons.icon("folder", color="icon_primary", size=scaled_px(themes.metrics("icon_sm"))))
        self._open_btn.setIconSize(QSize(scaled_px(themes.metrics("icon_sm")), scaled_px(themes.metrics("icon_sm"))))
        self._open_btn.setAccessibleName(tr("info.open"))
        self._open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_btn.setEnabled(False)
        self._open_btn.setToolTip(tr("info.select_file_first"))
        self._open_btn.setStyleSheet(sk.button_css(
            "primary", font_size_key="sm",
            padding_y=sk.px(int(themes.prop("spacing", "xs"))),
            padding_x=sk.px(int(themes.prop("spacing", "md")))))
        self._open_btn.clicked.connect(lambda: self.open_requested.emit(self._current_path))
        self._copy_btn = QPushButton(tr("info.copy_path"))
        self._copy_btn.setIcon(icons.icon("file", color="icon_secondary", size=scaled_px(themes.metrics("icon_sm"))))
        self._copy_btn.setIconSize(QSize(scaled_px(themes.metrics("icon_sm")), scaled_px(themes.metrics("icon_sm"))))
        self._copy_btn.setAccessibleName(tr("info.copy_path"))
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setEnabled(False)
        self._copy_btn.setToolTip(tr("info.select_file_first"))
        self._copy_btn.setStyleSheet(sk.button_css(
            "secondary", font_size_key="sm",
            padding_y=sk.px(int(themes.prop("spacing", "xs"))),
            padding_x=sk.px(int(themes.prop("spacing", "md")))))
        self._copy_btn.clicked.connect(lambda: self.copy_path_requested.emit(self._current_path))
        act_layout.addWidget(self._open_btn)
        act_layout.addWidget(self._copy_btn)
        act_layout.addStretch()

        # ── Initial ────────────────────────────────────────────

        self._splitter.setSizes([160, 400])
        self._saved_splitter_sizes = [160, 400]
        # Debounce splitter drags: each move event would otherwise trigger a
        # full SmoothTransformation rescale of the preview on the UI thread.
        self._preview_rescale_timer = QTimer(self)
        self._preview_rescale_timer.setSingleShot(True)
        self._preview_rescale_timer.setInterval(150)
        self._preview_rescale_timer.timeout.connect(self._apply_scaled_preview)
        # Epoch dedupe for _apply_scaled_preview: remember the last (target
        # size, source pixmap) actually rendered so duplicate triggers — the
        # panel resizeEvent plus the preview label's own Resize event from
        # layout propagation, and re-armed timer fires — skip the expensive
        # SmoothTransformation rescale instead of running it again.
        self._last_scaled_size: tuple[int, int] = (0, 0)
        self._last_scaled_pixmap: QPixmap | None = None
        self._show_empty_state()
        self._restore_layout_state()
        # Debounce splitter drags for persistence too. Connected AFTER restore
        # so applying saved sizes cannot schedule an immediate save-back.
        self._layout_save_timer = QTimer(self)
        self._layout_save_timer.setSingleShot(True)
        self._layout_save_timer.setInterval(500)
        self._layout_save_timer.timeout.connect(self._save_layout_state)
        self._splitter.splitterMoved.connect(self._on_splitter_moved)

        # Subscribe to domain events through a Qt bridge for UI-safe delivery.
        from AssetsManager.domain.events import (
            AssetNotesChanged, AssetRatingChanged, AssetTagsChanged, AssetUrlsChanged,
        )
        self._connect_domain_event(AssetTagsChanged, self._on_domain_tags_changed)
        self._connect_domain_event(AssetNotesChanged, self._on_domain_notes_changed)
        self._connect_domain_event(AssetUrlsChanged, self._on_domain_urls_changed)
        self._connect_domain_event(AssetRatingChanged, self._on_domain_rating_changed)

        # Qt-only signals (no domain equivalent)
        self._connect_bus(bus().sidebar_depth_changed, self._on_sidebar_depth_changed)
        self._connect_bus(bus().theme_changed, self._refresh_theme)
        self._connect_bus(bus().language_changed, self._refresh_language)
        self._connect_bus(bus().ui_scale_changed, self._refresh_theme)
        self._connect_bus(bus().ui_scale_changed, self.refresh_scaled_geometry)
        self._load_sidebar_depth_cfg()

    def _on_splitter_moved(self, _pos: int = 0, _index: int = 0) -> None:
        sizes = self._splitter.sizes()
        if len(sizes) == 2 and sizes[0] > 0 and sizes[1] > 0:
            self._saved_splitter_sizes = list(sizes)
        self._preview_rescale_timer.start()
        self._layout_save_timer.start()

    @staticmethod
    def _ghost_tool_style(sk, border_style: str) -> str:
        """Shared QSS for the four ghost tool buttons (audit P2-1)."""
        return (
            f"QPushButton {{ background: transparent; color: {sk.token('muted')}; "
            f"border: {scaled_px(1)}px {border_style} {sk.token('border')}; "
            f"border-radius: {sk.px(int(themes.prop('border_radius', 'sm')))}px; "
            f"padding: {sk.px(int(themes.prop('spacing', 'xs')))}px {sk.px(int(themes.prop('spacing', 'md')))}px; "
            f"font-size: {sk.pt(int(themes.prop('font_size', 'sm')))}px; }}"
            f"QPushButton:hover {{ background: {alpha(sk.token('hover_overlay'), themes.prop('opacity', 'hover'))}; }}"
            f"QPushButton:pressed {{ background: {alpha(sk.token('accent'), 0.28)}; }}")

    @staticmethod
    def _group_css(sk) -> str:
        """Single source for InfoPanel group-box QSS (build + theme refresh).

        Presents a modern, cohesive Linear-style card container with unbroken
        hairline border and translucent depth.
        """
        radius = sk.px(int(themes.prop('border_radius', 'md')))
        pad_x = sk.px(int(themes.prop('spacing', 'md')))
        pad_y = sk.px(int(themes.prop('spacing', 'sm')))
        hairline = sk.token('border_subtle')
        card_bg = alpha(sk.token('panel'), 0.45)
        return (
            f"QGroupBox {{"
            f"  color: {sk.token('heading')}; "
            f"  background: {card_bg}; "
            f"  border: {scaled_px(1)}px solid {hairline}; "
            f"  border-radius: {radius}px; "
            f"  margin-top: {pad_y}px; "
            f"  padding-top: {pad_y * 2 + scaled_px(8)}px; "
            f"  padding-left: {pad_x}px; "
            f"  padding-right: {pad_x}px; "
            f"  padding-bottom: {pad_y}px; "
            f"}} "
            f"QGroupBox::title {{"
            f"  subcontrol-origin: padding; "
            f"  subcontrol-position: top left; "
            f"  left: 0; "
            f"  top: {pad_y}px; "
            f"  font-weight: bold; "
            f"  color: {sk.token('heading')}; "
            f"  background: transparent; "
            f"  padding: 0; "
            f"}}"
        )

    def refresh_scaled_geometry(self, _scale: float | None = None):
        """Re-apply scale-dependent fixed geometry that QSS refresh cannot reach."""
        if hasattr(self, "_act_bar"):
            self._act_bar.setFixedHeight(scaled_px(28))
        if hasattr(self, "_preview"):
            self._preview.setMinimumHeight(scaled_px(60))
        if hasattr(self, "_tags_flow_layout"):
            self._tags_flow_layout.setSpacing(scaled_px(4))
        if hasattr(self, "_field_link"):
            for btn in self._field_link.findChildren(QPushButton):
                btn.setFixedSize(scaled_px(18), scaled_px(18))
                btn.setIconSize(QSize(scaled_px(themes.metrics("icon_sm")), scaled_px(themes.metrics("icon_sm"))))
        layout = self.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()

    def _refresh_theme(self, _name: str = ""):
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        self._preview_host.setStyleSheet(            "background: transparent;")
        if hasattr(self, '_details_scroll'):
            self._details_scroll.viewport().setStyleSheet(            "background: transparent;")
        for grp in (self._meta_grp, self._tags_grp, self._notes_grp):
            grp.setStyleSheet(self._group_css(sk))
        for btn, color, icon_name, dashed in [
            (self._add_tag_btn, "icon_muted", "tag", True),
            (self._manage_btn, "icon_muted", "settings", False),
            (self._browse_btn, "icon_muted", "tag", False),
            (self._ai_tag_btn, "icon_muted", "tag", False),
        ]:
            btn.setIcon(icons.icon(icon_name, color=color, size=scaled_px(14)))
            btn.setIconSize(QSize(scaled_px(14), scaled_px(14)))
            border_style = "dashed" if dashed else "solid"
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {themes.color('muted')}; "
                f"font-size: {sk.pt(int(themes.prop('font_size', 'sm')))}px; "
                f"border: {scaled_px(1)}px {border_style} {sk.token('border')}; "
                f"border-radius: {sk.px(int(themes.prop('border_radius', 'sm')))}px; "
                f"padding: {sk.px(int(themes.prop('spacing', 'xs')))}px {sk.px(int(themes.prop('spacing', 'md')))}px; }}"
                f"QPushButton:hover {{ background: {alpha(sk.token('hover_overlay'), themes.prop('opacity', 'hover'))}; }}"
                f"QPushButton:pressed {{ background: {alpha(sk.token('accent'), 0.28)}; }}")
        self._act_bar.setStyleSheet(
            f"background: transparent; border-top: {scaled_px(1)}px solid {sk.token('border')}; "
            f"padding: {sk.px(4)}px {sk.px(8)}px;")
        self._open_btn.setIcon(icons.icon("folder", color="icon_primary", size=scaled_px(themes.metrics("icon_sm"))))
        self._open_btn.setIconSize(QSize(scaled_px(themes.metrics("icon_sm")), scaled_px(themes.metrics("icon_sm"))))
        self._open_btn.setStyleSheet(sk.button_css(
            "primary", font_size_key="md",
            padding_y=sk.px(int(themes.prop("spacing", "xs"))),
            padding_x=sk.px(int(themes.prop("spacing", "md")))))
        self._copy_btn.setStyleSheet(sk.button_css(
            "secondary", font_size_key="sm",
            padding_y=sk.px(int(themes.prop("spacing", "xs"))),
            padding_x=sk.px(int(themes.prop("spacing", "md")))))
        self._copy_btn.setIcon(icons.icon("file", color="icon_secondary", size=scaled_px(themes.metrics("icon_sm"))))
        self._copy_btn.setIconSize(QSize(scaled_px(themes.metrics("icon_sm")), scaled_px(themes.metrics("icon_sm"))))
        self._refresh_empty_preview_state()
        if self._current_path:
            self._open_btn.setEnabled(True)
            self._open_btn.setToolTip(tr("info.open_tooltip"))
            self._copy_btn.setEnabled(True)
            self._copy_btn.setToolTip(tr("info.copy_tooltip"))
        self._name.setStyleSheet(
            sk.label_css("heading", size=16, bold=True)
            + f" QLabel {{ border: none; padding: {sk.px(2)}px 0; }}")
        # Update field labels and values
        self._refresh_field_styles()
        # Update link field
        self._refresh_link_field_style()
        # Update plugin fields
        self._refresh_plugin_fields_style()
        # Star rating re-tint: favorite/icon_muted and icon size both depend
        # on the active theme, so force a re-render even when the value is
        # unchanged (the lazy guard in _set_rating would skip it otherwise).
        if hasattr(self, "_rating_row"):
            self._set_rating(self._rating_value, force=True)
            rating_layout = self._rating_row.layout()
            rating_item = rating_layout.itemAt(0) if rating_layout is not None else None
            rating_label = rating_item.widget() if rating_item is not None else None
            if isinstance(rating_label, QLabel):
                rating_label.setStyleSheet(
                    sk.muted_css(11)
                    + f" QLabel {{ min-width: {sk.px(65)}px; }}")
        # Tag chips mix a light/dark polarity from the active theme
        # (tag_chip.py), so force a re-render — otherwise chips keep the
        # previous theme's polarity after a switch (audit B2②).
        if self._rendered_tags:
            forced_tags = list(self._rendered_tags)
            self._rendered_tags = ()
            self._render_tags(forced_tags)

    @staticmethod
    def _detect_reduce_motion() -> bool:
        try:
            return bool(AppSettings.instance().get("reduce_motion", False))
        except Exception:
            return False

    def _refresh_language(self, _code: str = ""):
        if hasattr(self, "_tab_bar"):
            self._tab_bar.set_tabs([
                tr("info.all"),
                tr("info.title"),
                tr("info.tags"),
                tr("info.notes"),
            ])
            # set_tabs() resets the selection to index 0 without emitting
            # current_changed; re-apply the filter so section visibility
            # cannot drift from the tab bar selection after a language switch.
            self._on_info_tab_changed(self._tab_bar.currentIndex())
        self._meta_grp.setTitle(tr("info.title"))
        self._tags_grp.setTitle(tr("info.tags"))
        self._notes_grp.setTitle(tr("info.notes"))
        self._add_tag_btn.setText(tr("info.add_tag"))
        self._add_tag_btn.setAccessibleName(tr("info.add_tag"))
        self._manage_btn.setText(tr("info.manage_tags"))
        self._manage_btn.setAccessibleName(tr("info.manage_tags"))
        self._browse_btn.setText(tr("info.browse_tags"))
        self._browse_btn.setAccessibleName(tr("info.browse_tags"))
        self._browse_btn.setToolTip(tr("info.browse_tags_tooltip"))
        self._ai_tag_btn.setText(tr("info.ai_tag"))
        self._ai_tag_btn.setAccessibleName(tr("info.ai_tag"))
        self._ai_tag_btn.setToolTip(tr("info.ai_tag_tooltip"))
        self._notes.setPlaceholderText(tr("info.notes_placeholder"))
        self._preview.setToolTip(tr("info.preview_dbl_click"))
        if hasattr(self, "_rating_row"):
            rating_layout = self._rating_row.layout()
            rating_item = rating_layout.itemAt(0) if rating_layout is not None else None
            rating_label = rating_item.widget() if rating_item is not None else None
            if isinstance(rating_label, QLabel):
                cast(QLabel, rating_label).setText(tr("info.rating"))
            for i, btn in enumerate(self._rating_stars, start=1):
                btn.setAccessibleName(tr("info.rating_star").format(n=i))
        self._open_btn.setText(tr("info.open"))
        self._open_btn.setAccessibleName(tr("info.open"))
        self._open_btn.setToolTip(
            tr("info.open_tooltip") if self._open_btn.isEnabled() else tr("info.select_file_first")
        )
        self._copy_btn.setText(tr("info.copy_path"))
        self._copy_btn.setAccessibleName(tr("info.copy_path"))
        self._copy_btn.setToolTip(
            tr("info.copy_tooltip") if self._copy_btn.isEnabled() else tr("info.select_file_first")
        )
        labels = ("info.field_type", "info.field_size", "info.field_contains", "info.field_modified", "info.field_path")
        for key, label_key in zip(("type", "size", "summary", "date", "path"), labels, strict=True):
            field = self._fields[key]
            layout = field.layout()
            item = layout.itemAt(0) if layout is not None else None
            label = item.widget() if item is not None else None
            if isinstance(label, QLabel):
                # PySide6 stubs type QLayoutItem.widget() as None, so the
                # isinstance check cannot narrow it for pyright.
                cast(QLabel, label).setText(tr(label_key))
        link_layout = self._field_link.layout()
        link_item = link_layout.itemAt(0) if link_layout is not None else None
        link_label = link_item.widget() if link_item is not None else None
        if isinstance(link_label, QLabel):
            cast(QLabel, link_label).setText(tr("info.field_link"))
        if not self._current_path:
            self._show_empty_state()
        # Language switching only retranslates text; it never changes colors,
        # so the per-control _refresh_theme() stylesheet sweep is skipped
        # (matching the setText-only _refresh_language precedent in
        # window.py / file_list). Theme refresh is wired separately via
        # theme_changed / ui_scale_changed above.

    def _refresh_field_styles(self):
        """Update all field label/value stylesheets for current theme."""
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        label_style = sk.muted_css(11) + f" QLabel {{ min-width: {sk.px(65)}px; }}"
        value_style = sk.label_css("body", size=12)
        for field in self._fields.values():
            layout = field.layout() if field else None
            if layout is None:
                continue
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item and item.widget():
                    w = item.widget()
                    if isinstance(w, QLabel):
                        if i == 0:  # label
                            w.setStyleSheet(label_style)
                        else:  # value
                            w.setStyleSheet(value_style)

    def _refresh_link_field_style(self):
        """Update link field label/value stylesheets for current theme."""
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        row = self._field_link
        layout = row.layout() if row else None
        if layout is None:
            return
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item and item.widget():
                w = item.widget()
                if isinstance(w, QLabel):
                    if i == 0:  # label
                        w.setStyleSheet(
                            sk.muted_css(11)
                            + f" QLabel {{ min-width: {sk.px(65)}px; }}")
                    else:  # value
                        w.setStyleSheet(sk.label_css("body", size=12))
                elif isinstance(w, _DragLabel):
                    if not w.text() or w.text() == "—":
                        w.setStyleSheet(sk.label_css("body", size=12))
        for button in row.findChildren(QPushButton):
            icon_name = button.property("semanticIcon")
            if not icon_name:
                continue
            button.setIcon(icons.icon(str(icon_name), color="icon_muted", size=scaled_px(themes.metrics("icon_sm"))))
            button.setIconSize(QSize(scaled_px(themes.metrics("icon_sm")), scaled_px(themes.metrics("icon_sm"))))
            button.setAccessibleName(button.toolTip())
        self._style_link_buttons()

    def _refresh_plugin_fields_style(self):
        """Update plugin field stylesheets for current theme."""
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        if not hasattr(self, '_plugin_fields_widget') or not self._plugin_fields_widget.isVisible():
            return
        for i in range(self._plugin_fields_layout.count()):
            item = self._plugin_fields_layout.itemAt(i)
            field = item.widget() if item is not None else None
            if field is not None:
                layout = field.layout()
                if layout is not None:
                    for j in range(layout.count()):
                        sub = layout.itemAt(j)
                        label = sub.widget() if sub is not None else None
                        if isinstance(label, QLabel):
                            qlabel = cast(QLabel, label)
                            if j == 0:
                                qlabel.setStyleSheet(
                                    sk.muted_css(11)
                                    + f" QLabel {{ min-width: {sk.px(65)}px; }}")
                            else:
                                qlabel.setStyleSheet(sk.label_css("body", size=12))

    def _make_rating_row(self) -> QWidget:
        """Build the star-rating row: muted label + 5 clickable stars."""
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 1, 0, 1)
        layout.setSpacing(scaled_px(2))
        lbl = QLabel(tr("info.rating"))
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl.setStyleSheet(
            sk.muted_css(11)
            + f" QLabel {{ min-width: {sk.px(65)}px; }}")
        layout.addWidget(lbl)
        self._rating_stars: list[QPushButton] = []
        for i in range(1, 6):
            star_btn = QPushButton()
            star_btn.setFixedSize(scaled_px(20), scaled_px(20))
            star_btn.setFlat(True)
            star_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            star_btn.setAccessibleName(tr("info.rating_star").format(n=i))
            star_btn.clicked.connect(
                lambda _checked=False, n=i: self._on_star_clicked(n))
            layout.addWidget(star_btn)
            self._rating_stars.append(star_btn)
        # -1 forces the first _set_rating render even for the unrated (0) state.
        self._rating_value = -1
        layout.addStretch()
        return row

    def _set_rating(self, rating: int | None, *, force: bool = False) -> None:
        """Render the current rating; None/0 shows all stars muted.

        ``force`` re-renders even when the value is unchanged — needed by
        theme/scale refreshes, where the star tint (favorite/icon_muted) and
        icon size both depend on the active theme.
        """
        value = 0
        if isinstance(rating, int) and not isinstance(rating, bool):
            value = max(0, min(5, rating))
        if (
            not force
            and value == self._rating_value
            and hasattr(self, "_rating_row_initialized")
        ):
            return
        self._rating_value = value
        self._rating_row_initialized = True
        star_size = scaled_px(16)
        btn_size = scaled_px(20)
        for i, btn in enumerate(self._rating_stars, start=1):
            tint = "favorite" if i <= value else "icon_muted"
            btn.setIcon(icons.icon("star", color=tint, size=star_size))
            btn.setIconSize(QSize(star_size, star_size))
            btn.setFixedSize(btn_size, btn_size)

    def _on_star_clicked(self, n: int) -> None:
        """Apply a rating; clicking the currently selected star clears it."""
        if not self._current_path or not self._controller:
            return
        try:
            target = None if n == self._rating_value else n
            self._controller.set_rating(self._current_path, target)
        except ValueError:
            _log.warning("Rating save rejected for path outside library: %s",
                         self._current_path)

    def _register_field(self, key: str, label: str, value: str = "") -> None:
        """Register a metadata field and add it to the layout."""
        field = self._make_field(label, value)
        self._fields[key] = field
        self._fields_layout.addWidget(field)

    def _set_field(self, key: str, value: str) -> None:
        """Update a registered field's value."""
        field = self._fields.get(key)
        if field:
            self._set_field_text(field, value)

    def _show_field(self, key: str, visible: bool = True) -> None:
        """Show or hide a registered field."""
        field = self._fields.get(key)
        if field:
            field.setVisible(visible)

    @staticmethod
    def _make_field(label: str, value: str) -> QWidget:
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 1, 0, 1)
        lbl = QLabel(label)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl.setStyleSheet(
            sk.muted_css(11)
            + f" QLabel {{ min-width: {sk.px(65)}px; }}")
        layout.addWidget(lbl)
        val = QLabel(value)
        val.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        val.setWordWrap(False)
        val.setMinimumSize(0, 0)
        val.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        val.setStyleSheet(sk.label_css("body", size=12))
        layout.addWidget(val, 1)
        return row

    @staticmethod
    def _set_field_text(row: QWidget, value: str):
        layout = row.layout()
        item = layout.itemAt(1) if layout is not None else None
        val_label = item.widget() if item is not None else None
        if isinstance(val_label, QLabel):
            qlabel = cast(QLabel, val_label)
            qlabel.setText(value)
            qlabel.setToolTip(value if value and value != "—" else "")

    def _make_link_field(self) -> QWidget:
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 1, 0, 1)
        lbl = QLabel(tr("info.field_link"))
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl.setStyleSheet(
            sk.muted_css(11)
            + f" QLabel {{ min-width: {sk.px(65)}px; }}")
        layout.addWidget(lbl)
        link = _DragLabel("—")
        link.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        link.setWordWrap(False)
        link.setMinimumSize(0, 0)
        link.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        link.setOpenExternalLinks(True)
        link.setStyleSheet(sk.label_css("body", size=12))
        layout.addWidget(link, 1)
        btn_holder = QWidget()
        btn_holder.setStyleSheet("background: transparent;")
        btn_holder_layout = QHBoxLayout(btn_holder)
        btn_holder_layout.setContentsMargins(0, 0, 0, 0)
        btn_holder_layout.setSpacing(2)
        layout.addWidget(btn_holder)

        # Reusable link action buttons. ``_set_link_field`` only toggles
        # visibility, avoiding a button create/destroy cycle per file switch.
        self._link_rm_btn = self._make_link_button(
            "close", "close", tr("info.link_remove"), lambda: self._remove_link(self._current_link_url))
        self._link_add_btn = self._make_link_button(
            "plus", "plus", tr("info.link_add"), self._add_link_dialog)
        self._link_scan_btn = self._make_link_button(
            "refresh", "refresh", tr("info.scanner.desc"), self._manual_scan_links)
        for btn in (self._link_rm_btn, self._link_add_btn, self._link_scan_btn):
            btn_holder_layout.addWidget(btn)
            btn.hide()
        self._current_link_url = ""
        return row

    @staticmethod
    def _make_link_button(property_icon, icon_name, tooltip, callback) -> QPushButton:
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        btn = QPushButton()
        btn.setIcon(icons.icon(icon_name, color="icon_muted", size=scaled_px(themes.metrics("icon_sm"))))
        btn.setIconSize(QSize(scaled_px(themes.metrics("icon_sm")), scaled_px(themes.metrics("icon_sm"))))
        btn.setProperty("semanticIcon", property_icon)
        btn.setToolTip(tooltip)
        btn.setAccessibleName(tooltip)
        btn.setFixedSize(scaled_px(18), scaled_px(18))
        btn.setFlat(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ color: {sk.token('muted')}; font-size: {sk.pt(sk.font_size('caption'))}px; padding: 0; "
            f"background: transparent; border: none; "
            f"border-radius: {sk.px(int(themes.prop('border_radius', 'sm')))}px; }}"
            f"QPushButton:hover {{ color: {sk.token('heading')}; background: {sk.token('accent')}; }}")
        btn.clicked.connect(callback)
        return btn

    def _style_link_buttons(self):
        """Re-tint the reusable link buttons after theme/scale changes."""
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        for btn in (self._link_rm_btn, self._link_add_btn, self._link_scan_btn):
            btn.setStyleSheet(
                f"QPushButton {{ color: {sk.token('muted')}; font-size: {sk.pt(sk.font_size('caption'))}px; padding: 0; "
                f"background: transparent; border: none; "
                f"border-radius: {sk.px(int(themes.prop('border_radius', 'sm')))}px; }}"
                f"QPushButton:hover {{ color: {sk.token('heading')}; background: {sk.token('accent')}; }}")

    def _set_link_field(self, url: str):
        row = self._field_link
        layout = row.layout()
        if layout is None:
            return
        link_item = layout.itemAt(1)
        link_label = link_item.widget() if link_item is not None else None
        if not isinstance(link_label, _DragLabel):
            return
        self._current_link_url = url
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        if url:
            short = url[:60] + "…" if len(url) > 60 else url
            link_label.setText(f"<a href='{url}'>{short}</a>")
            link_label.setToolTip(tr("info.drag_to_browser_hint").format(url=url))
            link_label.set_drag_url(url)
            link_label.setCursor(Qt.CursorShape.PointingHandCursor)
            link_label.setStyleSheet(
                sk.label_css("body", size=12)
                + " QLabel { text-decoration: underline; }")
        else:
            link_label.setText("—")
            link_label.setToolTip("")
            link_label.set_drag_url("")
            link_label.setCursor(Qt.CursorShape.ArrowCursor)
            link_label.setStyleSheet(sk.label_css("body", size=12))
        is_dir = bool(self._current_path and os.path.isdir(self._current_path))
        self._link_rm_btn.setVisible(bool(url))
        self._link_add_btn.setVisible(not url)
        self._link_scan_btn.setVisible(not url and is_dir)

    # ── Panel settings toggle ───────────────────────────────────

    def footer_bar(self):
        return self._act_bar

    def title_bar_buttons(self) -> list:
        """Return extra buttons for the dock title bar."""
        gear = QPushButton()
        gear.setIcon(icons.icon("settings", color="icon_primary", size=scaled_px(16)))
        gear.setIconSize(QSize(scaled_px(16), scaled_px(16)))
        gear.setToolTip(tr("panel.settings"))
        gear.setAccessibleName(tr("panel.settings"))
        gear.setFixedSize(scaled_px(20), scaled_px(20))
        gear.setFlat(True)
        gear.setProperty("semanticIcon", "settings")
        themes.set_button_variant(gear, "ghost")
        gear.setCursor(Qt.CursorShape.PointingHandCursor)
        gear.clicked.connect(self._show_panel_menu)
        return [gear]

    def _show_panel_menu(self):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        for key, label, widget in [
            ("preview", tr("info.preview"), self._preview_host),
            ("meta", tr("info.title"), self._meta_grp),
            ("tags", tr("info.tags"), self._tags_grp),
            ("notes", tr("info.notes"), self._notes_grp),
            ("actions", tr("info.actions"), self._act_bar),
        ]:
            a = menu.addAction(label)
            a.setCheckable(True)
            # Read the preference (not isHidden()) so the checkmark reflects
            # the persisted toggle even while a micro-tab filters the view.
            a.setChecked(self._section_preference.get(key, True))
            a.toggled.connect(lambda v, k=key, w=widget: self._set_section_visible(k, w, v))
        btn = self.sender()
        if isinstance(btn, QWidget):
            menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
        else:
            menu.exec(self.cursor().pos())

    def _section_widgets(self):
        return [
            ("preview", self._preview_host),
            ("meta", self._meta_grp),
            ("tags", self._tags_grp),
            ("notes", self._notes_grp),
            ("actions", self._act_bar),
        ]

    def _on_info_tab_changed(self, index: int) -> None:
        """Filter section visibility based on selected micro-tab."""
        self._apply_section_visibility()

    def _apply_section_visibility(self) -> None:
        """Single source of truth for section visibility.

        The micro-tab selects which sections are candidates; the persisted
        per-section preference (gear menu) gates each candidate. Tab switches
        and menu toggles are both just inputs that re-run this, so the two
        controls can never disagree about the final visible state.
        """
        index = self._tab_bar.currentIndex() if hasattr(self, "_tab_bar") else 0
        for key, widget in (
            ("meta", self._meta_grp),
            ("tags", self._tags_grp),
            ("notes", self._notes_grp),
        ):
            candidate = index == 0 or index == {"meta": 1, "tags": 2, "notes": 3}[key]
            widget.setVisible(candidate and self._section_preference.get(key, True))

        if hasattr(self, "_details_scroll"):
            widget = self._details_scroll.widget()
            if widget is not None and widget.layout() is not None:
                widget.layout().activate()
            self._details_scroll.verticalScrollBar().setValue(0)

    def _set_section_visible(self, key: str, widget: QWidget, visible: bool) -> None:
        if hasattr(self, "_section_preference"):
            self._section_preference[key] = visible
        self._apply_section_visibility()
        # preview/actions are not tab candidates, so make sure the direct
        # toggle still lands even when _apply_section_visibility skipped them.
        if key in ("preview", "actions"):
            widget.setVisible(visible)
        self._save_layout_state()

    def _restore_layout_state(self) -> None:
        """Restore saved section visibility and splitter sizes."""
        self.restore_panel_state()

    def save_state(self) -> dict:
        """Snapshot section visibility and splitter sizes for PanelState."""
        sizes = list(self._splitter.sizes())
        if len(sizes) == 2 and sizes[0] > 0 and sizes[1] > 0:
            self._saved_splitter_sizes = list(sizes)
        else:
            sizes = getattr(self, "_saved_splitter_sizes", [160, 400])
        return {
            # isHidden() reflects the explicit per-section preference even
            # before the panel itself has been shown (isVisible() would
            # report False for every section in that case).
            "sections": {key: not widget.isHidden() for key, widget in self._section_widgets()},
            "splitter": list(sizes),
        }

    def restore_state(self, state: dict) -> None:
        """Apply a saved layout snapshot."""
        if not isinstance(state, dict):
            return
        sections = state.get("sections")
        if isinstance(sections, dict):
            for key, widget in self._section_widgets():
                saved = sections.get(key)
                if isinstance(saved, bool):
                    if hasattr(self, "_section_preference"):
                        self._section_preference[key] = saved
                    widget.setVisible(saved)
        sizes = state.get("splitter")
        if isinstance(sizes, (list, tuple)) and len(sizes) == 2:
            try:
                top, bottom = int(sizes[0]), int(sizes[1])
                if top > 0 and bottom > 0:
                    self._saved_splitter_sizes = [top, bottom]
                    self._splitter.setSizes([top, bottom])
            except (TypeError, ValueError):
                pass

    def _save_layout_state(self) -> None:
        """Persist section visibility and splitter sizes via PanelState."""
        try:
            self.persist_panel_state()
        except Exception:
            _log.exception("Failed to save InfoPanel layout state")

    def _clear_preview(self):
        self._preview_pixmap = None
        self._preview_icon_name = ""
        self._preview_state = ""
        self._preview.clear()
        self._preview.setStyleSheet("")
        self._empty_preview_state.hide()
        self._preview.show()

    def _show_loading_state(self):
        """Explicit loading placeholder for the async preview window."""
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        self._preview_pixmap = None
        self._preview_icon_name = ""
        self._empty_preview_state.hide()
        self._preview.show()
        self._preview.setText("...")
        self._preview.setStyleSheet(sk.muted_css(24))
        self._preview_state = "loading"

    def _apply_scaled_preview(self):
        if self._preview_pixmap is None or self._preview_pixmap.isNull():
            return
        size = self._preview.size()
        current_size = (size.width(), size.height())

        # DE-DUPLICATE: skip when neither the target size nor the source
        # pixmap changed. Both resize paths land here debounced, and without
        # this guard every resize of the identical geometry would re-run the
        # SmoothTransformation scale + fade-in animation for no visible gain.
        if (
            current_size == self._last_scaled_size
            and self._preview_pixmap is self._last_scaled_pixmap
        ):
            return
        self._last_scaled_size = current_size
        self._last_scaled_pixmap = self._preview_pixmap

        pw, ph = current_size
        if pw < 40 or ph < 40:
            return
        scaled = self._preview_pixmap.scaled(
            pw, ph,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self._preview.setPixmap(scaled)
        self._preview.setStyleSheet("")
        # Fade in animation
        self._animate_preview_in()

    def _animate_preview_in(self):
        """Animate preview image fade-in."""
        if self._reduce_motion:
            self._preview.setWindowOpacity(1.0)
            return
        if hasattr(self, '_preview_anim') and self._preview_anim:
            self._preview_anim.stop()
        anim = QPropertyAnimation(self._preview, b"windowOpacity")
        anim.setDuration(themes.motion("normal"))
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        # Keep reference to prevent garbage collection
        self._preview_anim = anim

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Reuse the splitter-drag debounce timer for panel resizes too: a
        # single-shot restart per Resize collapses a resize storm (dock
        # dragging) into exactly one rescale 150ms after it settles, instead
        # of a 5-15ms SmoothTransformation scale on every event.
        timer = getattr(self, "_preview_rescale_timer", None)
        if timer is not None:
            timer.start()

    def eventFilter(self, obj, event):
        if hasattr(self, '_preview') and obj is self._preview and event.type() == event.Type.Resize:
            # Layout propagation of a panel resize fires a second Resize on the
            # preview label; feed it through the same debounce timer so both
            # triggers collapse into a single rescale per 150ms (the
            # pre-resize value of _last_scaled_pixmap also dedupes re-arms at
            # the settled size), instead of scaling twice per event.
            timer = getattr(self, "_preview_rescale_timer", None)
            if timer is not None:
                timer.start()
        if obj is self._preview_host and event.type() == event.Type.MouseButtonDblClick:
            _log.debug("Preview host double-click: path=%s", self._current_path)
            if self._current_path and os.path.exists(self._current_path):
                self.view_fullscreen.emit(self._current_path)
                return True
        return super().eventFilter(obj, event)

    def _on_preview_double_click(self):
        _log.debug("Preview double-click: path=%s", self._current_path)
        if not self._current_path:
            return
        # If it's a file, open directly; if a directory, open first image inside
        target = self._current_path
        if os.path.isdir(target):
            img = self._first_image_in_dir(target)
            if img:
                target = img
            else:
                return
        if os.path.isfile(target):
            self.view_fullscreen.emit(target)

    def _show_empty_state(self):
        self._current_path = ""
        # Persist pending notes and stop the debounce timer so a stale save
        # cannot overwrite the notes of a newly focused asset.
        self._flush_notes_save()
        if self._notes_timer:
            self._notes_timer.stop()
        self._clear_preview()
        self._preview.hide()
        self._refresh_empty_preview_state()
        self._empty_preview_state.show()
        self._preview_state = "empty"

    def _refresh_empty_preview_state(self):
        if not hasattr(self, "_empty_preview_state"):
            return
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        icon_size = scaled_px(48)
        self._empty_preview_icon.setPixmap(
            icons.icon("file", color="icon_muted", size=icon_size).pixmap(
                QSize(icon_size, icon_size)))
        self._empty_preview_label.setText(tr("info.no_file_selected"))
        self._empty_preview_label.setStyleSheet(
            sk.muted_css(int(themes.prop('font_size', 'sm'))) + " QLabel { border: none; }")
        if hasattr(self, "_palette_strip"):
            self._palette_strip.hide()
        if hasattr(self, "_open_btn"):
            self._open_btn.setEnabled(False)
            self._open_btn.setToolTip(tr("info.select_file_first"))
        if hasattr(self, "_copy_btn"):
            self._copy_btn.setEnabled(False)
            self._copy_btn.setToolTip(tr("info.select_file_first"))

    # ── Preview loader ─────────────────────────────────────────

    @staticmethod
    def _first_image_in_dir(dir_path: str) -> str | None:
        try:
            for i, entry in enumerate(os.scandir(dir_path)):
                if i > 500:
                    break
                if entry.is_file() and Path(entry.name).suffix.lower() in IMAGE_EXTS:
                    return entry.path
        except OSError:
            pass
        return None

    # ── Async directory size ──────────────────────────────────

    def _new_async_request(self, path: str) -> _AsyncRequest:
        scoped = self._scoped_services
        if scoped is None:
            raise RuntimeError("InfoPanel scoped services not injected")
        self._async_generation += 1
        # Retire the previous in-flight token: a superseded FileInfoTask
        # exits cooperatively at its next checkpoint (no join, no blocking)
        # instead of occupying one of the two pool workers with doomed work.
        self._info_token.cancel()
        self._info_token = CancellationToken()
        request = _AsyncRequest(
            self._async_generation,
            scoped.session,
            path,
        )
        self._async_request = request
        return request

    def _invalidate_async_requests(self):
        self._async_generation += 1
        self._async_request = None
        self._pending_task = None
        self._size_tasks.clear()
        self._info_token.cancel()
        self._info_token = CancellationToken()
        self._link_token.cancel()
        self._link_token = CancellationToken()
        self._size_token.cancel()
        self._size_token = CancellationToken()
        self._info_pool.cancel_all()
        self._info_pool.drain(3_000)
        self._size_pool.cancel_all()
        self._size_pool.drain(3_000)

    def _is_current_async_request(self, request: _AsyncRequest) -> bool:
        scoped = self._scoped_services
        return (
            request is self._async_request
            and request.generation == self._async_generation
            and scoped is not None
            and request.session is scoped.session
            and not request.session.is_closed
            and request.path == self._current_path
        )

    def _start_async_dir_size(self, request: _AsyncRequest):
        """Compute directory size using DB cache (ProjectData), fall back to scan."""
        from PySide6.QtCore import Signal, QObject
        class _SizeSignals(QObject):
            done = Signal(object, object)
        signals = _SizeSignals()
        signals.done.connect(self._on_async_dir_size_done)
        scoped = self._scoped_services
        session = request.session
        dir_path = request.path
        # Capture the panel's task registry before the class definition so the
        # worker can consult it (self inside run() is the _SizeTask, which has
        # no _size_tasks attribute).
        size_tasks = self._size_tasks
        metadata_port = self._metadata_port
        cancel_token = self._size_token
        class _SizeTask(CancellableRunnable):
            def __init__(self):
                super().__init__(cancel_token=cancel_token)
                # done is emitted inside run(); the panel keeps the signals
                # object alive until _on_async_dir_size_done consumes it.
                self.setAutoDelete(True)

            def run(self):
                # Bail out early when the request was invalidated while this
                # task was queued (the panel removed it from size_tasks), so
                # rapid folder switching does not pile up wasted scans.
                if self.is_cancelled() or request not in size_tasks:
                    return
                sz = 0
                try:
                    if scoped is not None and session and metadata_port is not None:
                        with session.operation():
                            if self.is_cancelled():
                                return
                            sz, _ = metadata_port.get_dir_size(
                                scoped.session.root, dir_path,
                                cancel_token=cancel_token.is_cancelled,
                            )
                    else:
                        return
                except Exception:
                    sz = 0
                if not self.is_cancelled():
                    signals.done.emit(request, sz)
        # Keep the signals object (and thus the queued delivery) alive until
        # the result is consumed on the UI thread.
        self._size_tasks[request] = signals
        self._size_pool.start(_SizeTask())

    def _on_async_dir_size_done(self, request: _AsyncRequest, size: int):
        self._size_tasks.pop(request, None)
        if not self._is_current_async_request(request):
            return
        self._set_field_text(self._fields["size"], format_info_size(size))


    @staticmethod
    def _load_preview_image(path: str, library_root: str | None = None) -> QImage | None:
        """Decode the preview image on the calling (worker) thread.

        Returns a plain ``QImage`` — QPixmap must only be constructed on the
        GUI thread, so the worker never touches QPixmap; the main-thread
        slot converts via ``QPixmap.fromImage`` (see ``_on_preview_ready``).
        """
        try:
            source = Path(path)
            root = Path(library_root) if library_root else source.parent
            body, _identity = read_snapshot(
                root, source, max_bytes=MAX_THUMBNAIL_SOURCE_BYTES,
            )
            from PySide6.QtGui import QImageReader
            buffer = QBuffer()
            buffer.setData(QByteArray(body))
            if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
                return None
            try:
                reader = QImageReader(buffer)
                reader.setAutoTransform(True)
                orig = reader.size()
                if not orig.isValid():
                    return None
                if orig.width() > PREVIEW_LOAD_MAX or orig.height() > PREVIEW_LOAD_MAX:
                    reader.setScaledSize(orig.scaled(
                        PREVIEW_LOAD_MAX, PREVIEW_LOAD_MAX,
                        Qt.AspectRatioMode.KeepAspectRatio))
                img = reader.read()
                if img.isNull():
                    return None
                return img
            finally:
                buffer.close()
        except Exception:
            _log.debug("Preview image snapshot failed: %s", path, exc_info=True)
            return None

    # ── Tags ───────────────────────────────────────────────────

    def _clear_tags(self):
        """Drop every chip (full teardown: library switch, shutdown)."""
        self._tag_render_generation = getattr(self, "_tag_render_generation", 0) + 1
        for w in self._tags_widgets:
            self._tags_flow_layout.removeWidget(w)
            w.deleteLater()
        self._tags_widgets.clear()
        for chip in self._tag_chip_pool.values():
            chip.deleteLater()
        self._tag_chip_pool.clear()
        self._rendered_tags = ()

    def _make_tag_chip(self, tag: str, color: str | None) -> QWidget:
        chip = create_tag_chip(
            tag,
            on_remove=self._remove_tag,
            color=color,
        )
        # Remember the color the chip was built for so a tag-color edit can
        # replace the pooled widget instead of leaving stale styling.
        chip.setProperty("tagColor", color or "")
        return chip

    def _discard_tag_chip(self, chip: QWidget) -> None:
        """Detach and schedule one pooled chip for deletion."""
        self._tags_flow_layout.removeWidget(chip)
        chip.hide()
        chip.setParent(None)
        chip.deleteLater()

    def _evict_tag_chip_pool(self, rendered: list[QWidget]) -> None:
        """Drop the least-recently-used hidden chips above the pool limit."""
        while len(self._tag_chip_pool) > _TAG_CHIP_POOL_LIMIT:
            _stale_tag, stale_chip = next(iter(self._tag_chip_pool.items()))
            if stale_chip in rendered:
                # Never evict a chip that is currently on screen, even if the
                # rendered tag set itself exceeds the pool limit.
                break
            del self._tag_chip_pool[_stale_tag]
            self._discard_tag_chip(stale_chip)

    def _render_tags(self, tags: list[str]):
        """Render the tag set, reusing pooled chips and diffing widget churn.

        Chips are kept in an LRU pool keyed by tag name: switching files with
        an overlapping tag vocabulary only hides/removes the difference, and a
        chip is rebuilt only when it is new or its tag color changed.
        """
        normalized = tuple(str(tag) for tag in tags)
        if normalized == self._rendered_tags and self._tags_widgets:
            return
        self._tag_render_generation = getattr(self, "_tag_render_generation", 0) + 1
        self._tags_flow.setUpdatesEnabled(False)
        try:
            for widget in self._tags_widgets:
                self._tags_flow_layout.removeWidget(widget)
                widget.hide()
            self._tags_widgets.clear()

            rendered: list[QWidget] = []
            fresh_chips: list[QWidget] = []
            for tag in normalized:
                color = tag_color_from(self._tags_port, tag)
                chip = self._tag_chip_pool.pop(tag, None)
                if chip is None or chip.property("tagColor") != (color or ""):
                    if chip is not None:
                        self._discard_tag_chip(chip)
                    chip = self._make_tag_chip(tag, color)
                    fresh_chips.append(chip)
                else:
                    # A pooled chip may have been hidden mid fade-in (opacity 0).
                    # Reuse is always shown fully opaque; only newly built chips
                    # go through the staggered entrance animation.
                    fade_anim = getattr(chip, "_fade_anim", None)
                    if fade_anim is not None:
                        fade_anim.stop()
                    chip.setWindowOpacity(1.0)
                chip.show()
                self._tags_flow_layout.addWidget(chip)
                self._tags_widgets.append(chip)
                rendered.append(chip)
                # Re-insertion at the end doubles as the pool's LRU recency.
                self._tag_chip_pool[tag] = chip
            self._evict_tag_chip_pool(rendered)
            self._rendered_tags = normalized
            for i, chip in enumerate(fresh_chips):
                if i < _MAX_ANIMATED_TAGS:
                    # Staggered fade-in animation for the first newly built chips.
                    self._animate_tag_in(chip, delay=i * 50)
                else:
                    chip.setWindowOpacity(1.0)
        finally:
            self._tags_flow.setUpdatesEnabled(True)
            self._tags_flow.update()

    def _animate_tag_in(self, chip, delay=0):
        """Animate tag chip entrance with fade-in."""
        if self._reduce_motion:
            chip.setWindowOpacity(1.0)
            return
        chip.setWindowOpacity(0.0)
        generation = self._tag_render_generation
        self._schedule_once(delay, lambda: self._do_fade_in(chip, generation))

    def _do_fade_in(self, chip, generation):
        if generation != self._tag_render_generation:
            return
        anim = QPropertyAnimation(chip, b"windowOpacity")
        anim.setDuration(themes.motion("fast"))
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        # Keep reference
        chip._fade_anim = anim

    def _add_tag(self):
        if not self._current_path or not os.path.exists(self._current_path) or not self._controller:
            return
        tag, ok = QInputDialog.getText(self, tr("info.dialog.add_tag"), tr("filelist.dialog.tag_label"))
        if ok and tag.strip():
            try:
                self._controller.add_tag(self._current_path, tag.strip())
            except ValueError:
                _log.warning("Tag add rejected for path outside library: %s", self._current_path)

    def _open_tag_editor(self):
        if not self._current_path or not os.path.exists(self._current_path) or not self._controller:
            return
        from AssetsManager.dialogs.tag_editor_dialog import TagEditorDialog
        tags_port = self._tags_port
        if tags_port is None:
            return
        dlg = TagEditorDialog(tags_port, self._current_path, self)
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.was_modified():
            new_tags = self._controller.get_tags(self._current_path)
            self._render_tags(new_tags)

    def _open_tag_browser(self):
        """Open the standalone tag browser and forward file clicks to navigation."""
        scoped = self._scoped_services
        if scoped is None:
            return
        from AssetsManager.dialogs.tag_browser_dialog import TagBrowserDialog
        dlg = TagBrowserDialog(scoped, self)
        dlg.directory_selected.connect(self.navigate_requested.emit)
        dlg.exec()

    # ── AI tagging (H2-c v1: manual trigger, single image) ──────

    def _update_ai_tag_visibility(self):
        """Show the AI button only when the user enabled AI tagging."""
        self._ai_tag_btn.setVisible(ai_tagging_enabled())

    def _ai_tag(self):
        """Run one manual AI-tagging pass over the focused asset.

        The vision call runs on a worker thread; the write stays inside
        ``TagService.add_tag_to_files`` (canonicalization, events and the
        batch ``tag_add`` activity row are inherited), so this panel adds
        no persistence code of its own.
        """
        if (
            not self._current_path
            or not os.path.exists(self._current_path)
            or self._scoped_services is None
        ):
            return
        # Belt-and-braces: the button is hidden when the feature is off.
        if not ai_tagging_enabled():
            return
        settings = AppSettings.instance()
        services = self._scoped_services
        tag_service = services.tag_service
        lib_root = self._library_root
        path = self._current_path
        endpoint = settings.get_ai_tagging_endpoint()
        model = settings.get_ai_tagging_model()
        max_tags = settings.get_ai_tagging_max_tags()
        force_existing = settings.get_ai_tagging_force_existing()
        self._ai_tag_btn.setEnabled(False)

        def _work():
            from AssetsManager.application.ai_tagging.service import tag_paths
            return tag_paths(
                tag_service, lib_root, [path],
                endpoint=endpoint, model=model, max_tags=max_tags,
                force_existing=force_existing,
            )

        def _done(result, exc):
            self._ai_tag_btn.setEnabled(True)
            if not self._same_path(path, self._current_path):
                return  # user moved on; domain events refresh the chips
            if exc is not None:
                _log.exception("AI tagging failed for %s", path)
                return
            outcome = result[0]
            if outcome.error_kind is not None:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    cast(QWidget, self), tr("info.ai_tag"),
                    ai_tag_error_text(outcome.error_kind))
                return
            if self._controller is not None:
                self._render_tags(self._controller.get_tags(path))
            if not outcome.added:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    cast(QWidget, self), tr("info.ai_tag"), tr("info.ai_no_tags"))

        from AssetsManager.panels.file_list._background import run_task
        run_task(_work, on_done=_done)

    def _remove_tag(self, tag: str):
        if not self._current_path or not self._controller:
            return
        try:
            self._controller.remove_tag(self._current_path, tag)
        except ValueError:
            _log.warning("Tag remove rejected for path outside library: %s", self._current_path)

    @staticmethod
    def _same_path(a: str, b: str) -> bool:
        """Compare two paths treating Windows junctions as identical."""
        try:
            return Path(a).resolve() == Path(b).resolve()
        except Exception:
            return str(a) == str(b)

    def _on_domain_tags_changed(self, event):
        """Handle a session-scoped tag update for the focused asset."""
        scoped = self._scoped_services
        if (
            not self._current_path
            or not self._controller
            or scoped is None
            or event.session_token != scoped.session.event_token
            or not self._same_path(event.file_path, self._current_path)
        ):
            return
        new_tags = self._controller.get_tags(self._current_path)
        self._render_tags(new_tags)

    def _on_domain_notes_changed(self, event):
        """Handle a session-scoped notes update for the focused asset."""
        scoped = self._scoped_services
        if not self._current_path or not self._controller or scoped is None:
            return
        if (event.session_token == scoped.session.event_token
                and self._same_path(event.file_path, self._current_path)):
            notes = self._controller.get_notes(self._current_path)
            if hasattr(self, '_notes') and self._notes:
                self._notes.blockSignals(True)
                self._notes.setPlainText(notes)
                self._notes.blockSignals(False)

    def _on_domain_urls_changed(self, event):
        """Handle a session-scoped URLs update for the focused asset."""
        scoped = self._scoped_services
        if not self._current_path or not self._controller or scoped is None:
            return
        if (event.session_token == scoped.session.event_token
                and self._same_path(event.file_path, self._current_path)):
            urls = self._controller.get_urls(self._current_path)
            self._set_link_field(urls[0] if urls else "")

    def _on_domain_rating_changed(self, event):
        """Handle a session-scoped rating update for the focused asset."""
        scoped = self._scoped_services
        if not self._current_path or not self._controller or scoped is None:
            return
        if (event.session_token == scoped.session.event_token
                and self._same_path(event.file_path, self._current_path)):
            self._set_rating(self._controller.get_rating(self._current_path))

    def set_scoped_services(self, services, *, runtime=None) -> None:
        """Bind library-scoped services resolved by MainWindow.

        ``runtime`` is part of the uniform ``ScopedServicesConsumer``
        signature; the info panel binds no runtime projection router, so the
        kwarg is accepted and ignored.
        """
        from AssetsManager.application.desktop_ports import RootBoundTagService
        from AssetsManager.controllers.info_controller import InfoController

        self._scoped_services = services
        self._library_root = services.session.root_str
        self._metadata_port = services.metadata_service
        self._tags_port = RootBoundTagService(self._library_root, services.tag_service)
        self._current_path = ""
        # Pooled chips carry styles/colors resolved against the old library's
        # tag service; rebuild them on the next selection.
        self._clear_tags()
        self._invalidate_async_requests()
        if hasattr(self, '_classify_cache'):
            self._classify_cache.clear()
        self._controller = InfoController(
            self._library_root,
            metadata_svc=services.metadata_service,
            tag_svc=services.tag_service,
            session=services.session,
        )

    def _on_sidebar_depth_changed(self, depth, branch_depths):
        self._sidebar_depth = depth
        self._branch_depths = dict(branch_depths or {})

    def _load_sidebar_depth_cfg(self):
        try:
            cfg = AppSettings.instance().get("sidebar_depth_cfg")
            if isinstance(cfg, dict):
                self._sidebar_depth = cfg.get("depth", 2)
                self._branch_depths = cfg.get("branch_depths", {}) or {}
        except Exception:
            pass

    def _is_deepest_folder(self, path: str) -> bool:
        """True if this folder is at the sidebar's deepest visible level."""
        from AssetsManager.controllers.info_controller import InfoController
        return InfoController.is_deepest_folder(
            path, self._library_root, self._sidebar_depth, self._branch_depths)

    # ── Link management ─────────────────────────────────────────

    def _add_link_dialog(self):
        if not self._current_path or not self._controller:
            return
        url, ok = QInputDialog.getText(self, tr("info.dialog.add_link"), tr("info.dialog.url_label"))
        if ok and url.strip():
            try:
                self._controller.add_url(self._current_path, url.strip())
            except ValueError as e:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, tr("info.dialog.invalid_url"), str(e))
                return

    def _remove_link(self, url: str):
        if not self._current_path or not self._controller:
            return
        try:
            self._controller.remove_url(self._current_path, url)
        except ValueError:
            _log.warning("Link remove rejected for path outside library: %s", self._current_path)

    def _manual_scan_links(self):
        if not self._current_path or not os.path.isdir(self._current_path) or not self._controller:
            return
        self._link_token.cancel()
        self._link_token = CancellationToken()
        task = _LinkScanTask(
            self._controller, self._current_path, cancel_token=self._link_token
        )
        task.signals.done.connect(self._on_manual_scan_done)
        self._link_scan_task = task
        self._info_pool.start(task)

    def _on_manual_scan_done(self, discovered, path):
        """Apply discovered URLs on the UI thread (queued delivery)."""
        self._link_scan_task = None
        if not self._controller:
            return
        for u in discovered:
            try:
                self._controller.add_url(path, u)
            except ValueError:
                pass
        if path == self._current_path:
            urls = self._controller.get_urls(path)
            self._set_link_field(urls[0] if urls else "")

    def _schedule_notes_save(self):
        from PySide6.QtCore import QTimer
        self._notes_save_path = self._current_path
        if self._notes_timer is None:
            self._notes_timer = QTimer(self)
            self._notes_timer.setSingleShot(True)
            self._notes_timer.timeout.connect(self._flush_notes_save)
        self._notes_timer.start(1000)

    def _flush_notes_save(self):
        """Persist pending notes.

        The debounce timer is single-shot and may fire after the focused
        asset changed; the scheduled path guard drops such stale saves so a
        previous file's timer cannot wipe out the new file's notes.
        """
        if self._notes_timer is not None:
            self._notes_timer.stop()
        try:
            if self._notes_save_path is not None and self._notes_save_path != self._current_path:
                # Timer belongs to a previously focused path; drop it.
                return
            path = self._current_path
            if path and os.path.exists(path) and self._controller:
                self._controller.save_notes(path, self._notes.toPlainText())
        except ValueError:
            _log.warning("Notes save rejected for path outside library: %s",
                         self._current_path)
        finally:
            self._notes_save_path = None

    # ── Main update ────────────────────────────────────────────

    def update_info(self, info):
        from PySide6.QtCore import QFileInfo
        if not info:
            self._current_path = ""
            self._show_empty_state()
            return
        if self._controller is None or self._scoped_services is None:
            _log.debug("update_info skipped: controller=%s lib_root=%s",
                       bool(self._controller), repr(self._library_root))
            return
        if isinstance(info, QFileInfo):
            fi = info
        else:
            fi = QFileInfo(str(info))

        self._flush_notes_save()
        if self._notes_timer:
            self._notes_timer.stop()

        # Same-focus short-circuit: one click reaches update_info twice
        # (click handler + selectionChanged both emit file_focused), so
        # re-focusing the already displayed path must not respawn an
        # identical FileInfoTask.  Domain events (AssetTags/Notes/UrlsChanged)
        # refresh without update_info — their handlers render straight from
        # the controller — and every controller/session rebinding resets
        # _current_path (set_scoped_services) or nulls it (controller=None on
        # prepare_library_switch), so a matching path here always means the
        # same binding; no force flag is needed.
        if fi.absoluteFilePath() == self._current_path:
            return

        self._current_path = fi.absoluteFilePath()
        self._update_ai_tag_visibility()
        request = self._new_async_request(self._current_path)
        is_dir = fi.isDir()

        # Favorites may point outside the library root; the controller rejects
        # those paths, so render a static fallback instead of a pending state.
        outside_library = False
        if self._library_root:
            try:
                outside_library = not Path(self._current_path).resolve().is_relative_to(
                    Path(self._library_root).resolve())
            except Exception:
                outside_library = False

        # URL discovery runs inside the async FileInfoTask; no state needed here.

        # Show placeholders immediately
        self._name.setText(fi.fileName())
        if is_dir:
            is_project = self._is_deepest_folder(self._current_path)
            self._set_field_text(self._fields["type"],
                                 tr("info.project") if is_project else tr("info.folder"))
            self._set_field_text(self._fields["size"],
                                 tr("info.calculating") if fi.exists() else "—")
        else:
            self._set_field_text(self._fields["type"],
                                 tr("info.file", ext=fi.suffix().upper()) if fi.suffix() else "—")
            size = fi.size()
            self._set_field_text(self._fields["size"], format_info_size(size) if size else "—")
        self._set_field_text(self._fields["date"],
                             fi.lastModified().toString("yyyy-MM-dd HH:mm:ss"))
        self._set_field_text(self._fields["path"], fi.absolutePath())
        self._fields["summary"].hide()
        self._set_link_field("")
        self._set_rating(0)
        self._render_tags([])
        self._notes.blockSignals(True)
        self._notes.setPlainText("")
        self._notes.blockSignals(False)
        self._show_loading_state()

        # Drop the reference to the previous task; the token that lets it exit
        # early was already cancelled by _new_async_request above, and stale
        # delivery is rejected by request identity in the callbacks.
        self._pending_task = None

        if not self._controller:
            return

        if outside_library:
            # Controller operations raise ValueError for paths outside the
            # library; show a static fallback instead of a pending "..." .
            self._show_preview_fallback()
            return

        # Start async load
        if not hasattr(self, '_classify_cache'):
            self._classify_cache = LRUCache(500)

        task = _FileInfoTask(
            request=request,
            controller=self._controller,
            library_root=self._library_root,
            sidebar_depth=self._sidebar_depth,
            branch_depths=self._branch_depths,
            classify_cache=self._classify_cache,
            generation=request.generation,
            cancel_token=self._info_token,
        )
        task.signals.result_ready.connect(self._on_file_info_ready)
        task.signals.preview_ready.connect(self._on_preview_ready)
        task.signals.urls_discovered.connect(self._on_task_urls_discovered)
        self._pending_task = task
        self._info_pool.start(task)

    def _on_task_urls_discovered(self, path, discovered):
        """Persist urls discovered by the worker on the UI thread.

        add_url publishes AssetUrlsChanged, so it must run on the GUI thread
        (queued delivery from the worker via the bridge).
        """
        if not self._controller:
            return
        for url in discovered:
            try:
                self._controller.add_url(path, url)
            except ValueError:
                pass
        if path == self._current_path:
            urls = self._controller.get_urls(path)
            self._set_link_field(urls[0] if urls else "")

    def _render_file_info(self, request, file_info):
        """Render FileInfo dataclass to widgets (no preview — handled async)."""
        self._name.setText(file_info.name)

        self._set_field_text(self._fields["type"], file_info.file_type)
        self._set_field_text(self._fields["size"], file_info.size_display)
        self._set_field_text(self._fields["date"], file_info.modified_display)
        self._set_field_text(self._fields["path"], file_info.parent_path)

        # Summary
        if file_info.is_dir and file_info.dir_summary:
            self._set_field_text(self._fields["summary"], file_info.dir_summary)
            self._fields["summary"].show()
        else:
            self._fields["summary"].hide()

        # Async dir size
        if file_info.is_dir and os.path.exists(self._current_path):
            self._start_async_dir_size(request)

        # Dominant color palette (if available)
        palette = getattr(file_info, "palette", None)
        if palette and hasattr(self, "_palette_strip"):
            self._palette_strip.set_colors(palette)
        elif hasattr(self, "_palette_strip"):
            self._palette_strip.hide()

        # Plugin fields
        self._render_plugin_fields(file_info.plugin_fields)

        # URLs
        self._set_link_field(file_info.urls[0] if file_info.urls else "")

        # Tags
        self._render_tags(list(file_info.tags))

        # Notes
        self._notes.blockSignals(True)
        self._notes.setPlainText(file_info.notes)
        self._notes.blockSignals(False)

        # Rating
        self._set_rating(file_info.rating)

        # Action buttons
        if hasattr(self, "_open_btn"):
            self._open_btn.setEnabled(True)
            self._open_btn.setToolTip(tr("info.open_tooltip"))
        if hasattr(self, "_copy_btn"):
            self._copy_btn.setEnabled(True)
            self._copy_btn.setToolTip(tr("info.copy_tooltip"))

    def _on_file_info_ready(self, request, file_info):
        """Called on main thread when async file-info load completes."""
        # _is_current_async_request already enforces identity, generation,
        # session and path equality. request.path comes from
        # QFileInfo.absoluteFilePath() while file_info.path is resolved by
        # the controller — these legitimately differ on Windows junctions
        # (e.g. OneDrive), so no extra path comparison is performed here.
        if not self._is_current_async_request(request):
            return
        self._render_file_info(request, file_info)

    def _on_preview_ready(self, request, image):
        """Called on main thread when async preview load completes.

        The worker emits a plain ``QImage``; QPixmap construction happens
        here on the GUI thread.
        """
        if not self._is_current_async_request(request):
            return
        if image:
            self._empty_preview_state.hide()
            self._preview.show()
            self._preview_icon_name = ""
            self._preview_pixmap = QPixmap.fromImage(image)
            self._preview_state = "image"
            self._apply_scaled_preview()
        else:
            self._show_preview_fallback()

    def _show_preview_fallback(self):
        """Show a theme-aware semantic icon when no preview image is available."""
        self._empty_preview_state.hide()
        self._preview.show()
        self._preview_state = "fallback"
        suffix = Path(self._current_path).suffix.lower().lstrip(".")
        is_dir = os.path.isdir(self._current_path)
        hints = {
            "png": "image", "jpg": "image", "jpeg": "image", "gif": "image", "bmp": "image",
            "webp": "image", "svg": "image",
            "blend": "cube", "fbx": "cube", "obj": "cube", "gltf": "cube", "glb": "cube",
            "mp4": "video", "mov": "video", "avi": "video", "mkv": "video", "webm": "video",
            "zip": "archive", "rar": "archive", "7z": "archive", "tar": "archive", "gz": "archive",
        }
        icon_name = hints.get(suffix, "folder" if is_dir else "file")
        self._preview_icon_name = icon_name
        self._preview.setText("")
        icon_size = scaled_px(64)
        self._preview.setPixmap(icons.icon(
            icon_name,
            color="icon_muted",
            size=icon_size,
            fallback="file",
        ).pixmap(QSize(icon_size, icon_size)))
        self._preview.setStyleSheet("background: transparent;")

    def _render_plugin_fields(self, plugin_fields):
        """Render plugin-contributed metadata fields from FileInfo."""
        self._plugin_fields_widget.setUpdatesEnabled(False)
        try:
            seen = set()
            for field in plugin_fields:
                key = field.key.capitalize()
                seen.add(key)
                row = self._plugin_field_rows.get(key)
                if row is None:
                    row = self._make_field(key, str(field.value))
                    self._plugin_field_rows[key] = row
                    self._plugin_fields_layout.addWidget(row)
                else:
                    self._set_field_text(row, str(field.value))
                row.setVisible(True)
            for key, row in list(self._plugin_field_rows.items()):
                if key not in seen:
                    row.setVisible(False)
            self._plugin_fields_widget.setVisible(bool(seen))
        except Exception:
            _log.exception("Plugin field rendering failed")
            self._plugin_fields_widget.setVisible(False)
        finally:
            self._plugin_fields_widget.setUpdatesEnabled(True)
            self._plugin_fields_widget.update()

    def clone(self):
        new = InfoPanel()
        new.restore_state(self.save_state())
        return new

    def flush_pending_changes(self):
        """Persist pending notes before switching libraries or opening a viewer."""
        self._flush_notes_save()

    def prepare_library_switch(self):
        """Flush local edits and stop debounce work for the old library."""
        self._tag_render_generation = getattr(self, "_tag_render_generation", 0) + 1
        self.flush_pending_changes()
        if self._notes_timer:
            self._notes_timer.stop()
        self._clear_pending_timers()
        self._invalidate_async_requests()
        # Do not retain a controller/repository backed by the old session while
        # the library is closing or a replacement session is being assembled.
        self._controller = None
        self._scoped_services = None

    def shutdown(self):
        if hasattr(self, "_layout_save_timer") and self._layout_save_timer is not None:
            if self._layout_save_timer.isActive():
                self._layout_save_timer.stop()
            self._save_layout_state()
        self.prepare_library_switch()
        self._invalidate_async_requests()
        super().shutdown()

    def closeEvent(self, event):
        if hasattr(self, "_layout_save_timer") and self._layout_save_timer is not None:
            if self._layout_save_timer.isActive():
                self._layout_save_timer.stop()
            self._save_layout_state()
        self.prepare_library_switch()
        super().closeEvent(event)
