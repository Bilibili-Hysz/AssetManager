"""Info panel — splitter layout, dynamic preview, metadata, tags, notes.

Layout: QSplitter(preview / metadata scroll) + fixed Actions bar at bottom.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import cast

from PySide6.QtCore import Qt, Signal, QSize, QPropertyAnimation, QEasingCurve, QRunnable, QThreadPool, QObject, QTimer
from PySide6.QtWidgets import (
    QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QTextEdit,
    QGroupBox, QWidget, QInputDialog, QSplitter, QScrollArea, QFrame,
    QSizePolicy,
)
from PySide6.QtGui import QPixmap

from AssetsManager.panels.base import PanelContent
from AssetsManager.application.desktop_ports import TagsViewPort
from AssetsManager.core.cache import LRUCache
from AssetsManager.core.constants import IMAGE_EXTS
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.core import themes, icons
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


class InfoPanel(PanelContent):
    open_requested = Signal(str)
    copy_path_requested = Signal(str)
    view_fullscreen = Signal(str)  # request viewer panel
    navigate_requested = Signal(str)  # request file-list navigation

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

        # ── Metadata area (bottom pane, scrollable) ───────────

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
        tags_outer.addWidget(self._tags_flow)

        add_row = QHBoxLayout()
        self._add_tag_btn = QPushButton(tr("info.add_tag"))
        self._add_tag_btn.setIcon(icons.icon("tag", color="icon_muted", size=scaled_px(14)))
        self._add_tag_btn.setIconSize(QSize(scaled_px(14), scaled_px(14)))
        self._add_tag_btn.setAccessibleName(tr("info.add_tag"))
        self._add_tag_btn.clicked.connect(self._add_tag)
        self._add_tag_btn.setStyleSheet(
            f"background: transparent; color: {sk.token('muted')}; border: 1px dashed {sk.token('border')}; "
            f"border-radius: {sk.px(6)}px; padding: {sk.px(2)}px {sk.px(10)}px; font-size: {sk.pt(11)}px;")
        self._add_tag_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_row.addWidget(self._add_tag_btn)
        self._manage_btn = QPushButton(tr("info.manage_tags"))
        self._manage_btn.setIcon(icons.icon("settings", color="icon_muted", size=scaled_px(14)))
        self._manage_btn.setIconSize(QSize(scaled_px(14), scaled_px(14)))
        self._manage_btn.setAccessibleName(tr("info.manage_tags"))
        self._manage_btn.clicked.connect(self._open_tag_editor)
        self._manage_btn.setStyleSheet(
            f"background: transparent; color: {sk.token('muted')}; border: 1px solid {sk.token('border')}; "
            f"border-radius: {sk.px(6)}px; padding: {sk.px(2)}px {sk.px(10)}px; font-size: {sk.pt(11)}px;")
        self._manage_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_row.addWidget(self._manage_btn)
        self._browse_btn = QPushButton(tr("info.browse_tags"))
        self._browse_btn.setIcon(icons.icon("tag", color="icon_muted", size=scaled_px(14)))
        self._browse_btn.setIconSize(QSize(scaled_px(14), scaled_px(14)))
        self._browse_btn.setAccessibleName(tr("info.browse_tags"))
        self._browse_btn.setToolTip(tr("info.browse_tags_tooltip"))
        self._browse_btn.clicked.connect(self._open_tag_browser)
        self._browse_btn.setStyleSheet(
            f"background: transparent; color: {sk.token('muted')}; border: 1px solid {sk.token('border')}; "
            f"border-radius: {sk.px(6)}px; padding: {sk.px(2)}px {sk.px(10)}px; font-size: {sk.pt(11)}px;")
        self._browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_row.addWidget(self._browse_btn)
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
        self._splitter.addWidget(self._details_scroll)

        # ── Actions (fixed at bottom, outside scroll) ──────────

        act_bar = QWidget()
        self._act_bar = act_bar
        act_bar.setStyleSheet(f"background: transparent; "
                              f"border-top: 1px solid {sk.token('border')};")
        act_bar.setFixedHeight(scaled_px(28))
        act_layout = QHBoxLayout(act_bar)
        act_layout.setContentsMargins(scaled_px(10), scaled_px(4), scaled_px(10), scaled_px(4))
        act_layout.setSpacing(scaled_px(8))
        act_layout.addStretch()
        self._open_btn = QPushButton(tr("info.open"))
        self._open_btn.setIcon(icons.icon("folder", color="icon_primary", size=scaled_px(15)))
        self._open_btn.setIconSize(QSize(scaled_px(15), scaled_px(15)))
        self._open_btn.setAccessibleName(tr("info.open"))
        self._open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_btn.setToolTip(tr("info.open_tooltip"))
        self._open_btn.setStyleSheet(
            f"background: {sk.token('accent')}; color: {sk.token('heading')}; "
            f"border: 1px solid {sk.token('accent')}; border-radius: {sk.px(4)}px; "
            f"padding: {sk.px(2)}px {sk.px(12)}px; font-size: {sk.pt(12)}px;")
        self._open_btn.clicked.connect(lambda: self.open_requested.emit(self._current_path))
        self._copy_btn = QPushButton(tr("info.copy_path"))
        self._copy_btn.setIcon(icons.icon("file", color="icon_secondary", size=scaled_px(15)))
        self._copy_btn.setIconSize(QSize(scaled_px(15), scaled_px(15)))
        self._copy_btn.setAccessibleName(tr("info.copy_path"))
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setToolTip(tr("info.copy_tooltip"))
        self._copy_btn.setStyleSheet(
            f"background: transparent; color: {sk.token('body')}; "
            f"border: 1px solid {sk.token('border')}; border-radius: {sk.px(4)}px; "
            f"padding: {sk.px(2)}px {sk.px(10)}px; font-size: {sk.pt(12)}px;")
        self._copy_btn.clicked.connect(lambda: self.copy_path_requested.emit(self._current_path))
        act_layout.addWidget(self._open_btn)
        act_layout.addWidget(self._copy_btn)
        act_layout.addStretch()

        # ── Initial ────────────────────────────────────────────

        self._splitter.setSizes([160, 400])
        # Debounce splitter drags: each move event would otherwise trigger a
        # full SmoothTransformation rescale of the preview on the UI thread.
        self._preview_rescale_timer = QTimer(self)
        self._preview_rescale_timer.setSingleShot(True)
        self._preview_rescale_timer.setInterval(150)
        self._preview_rescale_timer.timeout.connect(self._apply_scaled_preview)
        self._splitter.splitterMoved.connect(lambda *_args: self._preview_rescale_timer.start())
        self._show_empty_state()

        # Subscribe to domain events through a Qt bridge for UI-safe delivery.
        from AssetsManager.domain.events import (
            AssetNotesChanged, AssetTagsChanged, AssetUrlsChanged,
        )
        self._connect_domain_event(AssetTagsChanged, self._on_domain_tags_changed)
        self._connect_domain_event(AssetNotesChanged, self._on_domain_notes_changed)
        self._connect_domain_event(AssetUrlsChanged, self._on_domain_urls_changed)

        # Qt-only signals (no domain equivalent)
        self._connect_bus(bus().sidebar_depth_changed, self._on_sidebar_depth_changed)
        self._connect_bus(bus().theme_changed, self._refresh_theme)
        self._connect_bus(bus().language_changed, self._refresh_language)
        self._connect_bus(bus().ui_scale_changed, self._refresh_theme)
        self._connect_bus(bus().ui_scale_changed, self.refresh_scaled_geometry)
        self._load_sidebar_depth_cfg()

    @staticmethod
    def _group_css(sk) -> str:
        """Single source for InfoPanel group-box QSS (build + theme refresh).

        Uses the global hairline token instead of a full-strength border so
        the metadata/tags/notes sections read as layers, not boxed-in cards.
        """
        return (
            f"QGroupBox {{ color: {sk.token('heading')}; border: 1px solid {sk.token('border_subtle')}; "
            f"border-radius: {sk.px(6)}px; margin-top: {sk.px(8)}px; padding-top: {sk.px(12)}px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: {sk.px(10)}px; padding: 0 {sk.px(5)}px; }}"
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
                btn.setIconSize(QSize(scaled_px(15), scaled_px(15)))
        layout = self.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()

    def _refresh_theme(self, _name: str = ""):
        t = themes.get()
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        self._preview_host.setStyleSheet(            "background: transparent;")
        if hasattr(self, '_details_scroll'):
            self._details_scroll.viewport().setStyleSheet(            "background: transparent;")
        for grp in (self._meta_grp, self._tags_grp, self._notes_grp):
            grp.setStyleSheet(self._group_css(sk))
        for btn, color, icon_name in [
            (self._add_tag_btn, "icon_muted", "tag"),
            (self._manage_btn, "icon_muted", "settings"),
            (self._browse_btn, "icon_muted", "tag"),
        ]:
            btn.setIcon(icons.icon(icon_name, color=color, size=scaled_px(14)))
            btn.setIconSize(QSize(scaled_px(14), scaled_px(14)))
            btn.setStyleSheet(
                f"background: transparent; color: {t['muted']}; font-size: {sk.pt(12)}px; "
                f"border: 1px solid {sk.token('border')}; border-radius: {sk.px(4)}px; padding: {sk.px(2)}px {sk.px(10)}px;")
        self._act_bar.setStyleSheet(
            f"background: transparent; border-top: 1px solid {sk.token('border')}; "
            f"padding: {sk.px(4)}px {sk.px(8)}px;")
        self._open_btn.setIcon(icons.icon("folder", color="icon_primary", size=scaled_px(15)))
        self._open_btn.setIconSize(QSize(scaled_px(15), scaled_px(15)))
        self._open_btn.setStyleSheet(
            f"background: {sk.token('accent')}; color: {sk.token('heading')}; font-size: {sk.pt(13)}px; "
            f"border: 1px solid {sk.token('accent')}; border-radius: {sk.px(4)}px; padding: {sk.px(2)}px {sk.px(12)}px;")
        self._copy_btn.setStyleSheet(
            f"background: transparent; color: {sk.token('body')}; "
            f"border: 1px solid {sk.token('border')}; border-radius: {sk.px(4)}px; "
            f"padding: {sk.px(2)}px {sk.px(10)}px; font-size: {sk.pt(12)}px;")
        self._copy_btn.setIcon(icons.icon("file", color="icon_secondary", size=scaled_px(15)))
        self._copy_btn.setIconSize(QSize(scaled_px(15), scaled_px(15)))
        self._refresh_empty_preview_state()
        self._name.setStyleSheet(
            sk.label_css("heading", size=16, bold=True)
            + f" QLabel {{ border: none; padding: {sk.px(2)}px 0; }}")
        # Update field labels and values
        self._refresh_field_styles()
        # Update link field
        self._refresh_link_field_style()
        # Update plugin fields
        self._refresh_plugin_fields_style()

    @staticmethod
    def _detect_reduce_motion() -> bool:
        try:
            from AssetsManager.core.settings import AppSettings
            return bool(AppSettings.instance().get("reduce_motion", False))
        except Exception:
            return False

    def _refresh_language(self, _code: str = ""):
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
        self._notes.setPlaceholderText(tr("info.notes_placeholder"))
        self._preview.setToolTip(tr("info.preview_dbl_click"))
        self._open_btn.setText(tr("info.open"))
        self._open_btn.setAccessibleName(tr("info.open"))
        self._open_btn.setToolTip(tr("info.open_tooltip"))
        self._copy_btn.setText(tr("info.copy_path"))
        self._copy_btn.setAccessibleName(tr("info.copy_path"))
        self._copy_btn.setToolTip(tr("info.copy_tooltip"))
        labels = ("info.field_type", "info.field_size", "info.field_contains", "info.field_modified", "info.field_path")
        for key, label_key in zip(("type", "size", "summary", "date", "path"), labels):
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
        self._refresh_theme()

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
            button.setIcon(icons.icon(str(icon_name), color="icon_muted", size=scaled_px(15)))
            button.setIconSize(QSize(scaled_px(15), scaled_px(15)))
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
        btn.setIcon(icons.icon(icon_name, color="icon_muted", size=scaled_px(15)))
        btn.setIconSize(QSize(scaled_px(15), scaled_px(15)))
        btn.setProperty("semanticIcon", property_icon)
        btn.setToolTip(tooltip)
        btn.setAccessibleName(tooltip)
        btn.setFixedSize(scaled_px(18), scaled_px(18))
        btn.setFlat(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ color: {sk.token('muted')}; font-size: {sk.pt(11)}px; padding: 0; "
            f"background: transparent; border: none; border-radius: {sk.px(3)}px; }}"
            f"QPushButton:hover {{ color: {sk.token('heading')}; background: {sk.token('accent')}; }}")
        btn.clicked.connect(callback)
        return btn

    def _style_link_buttons(self):
        """Re-tint the reusable link buttons after theme/scale changes."""
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        for btn in (self._link_rm_btn, self._link_add_btn, self._link_scan_btn):
            btn.setStyleSheet(
                f"QPushButton {{ color: {sk.token('muted')}; font-size: {sk.pt(11)}px; padding: 0; "
                f"background: transparent; border: none; border-radius: {sk.px(3)}px; }}"
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
        for label, widget in [
            (tr("info.preview"), self._preview_host),
            (tr("info.title"), self._meta_grp),
            (tr("info.tags"), self._tags_grp),
            (tr("info.notes"), self._notes_grp),
            (tr("info.actions"), self._act_bar),
        ]:
            a = menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(widget.isVisible())
            a.toggled.connect(lambda v, w=widget: w.setVisible(v))
        btn = self.sender()
        if isinstance(btn, QWidget):
            menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
        else:
            menu.exec(self.cursor().pos())

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
        pw = self._preview.width()
        ph = self._preview.height()
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
        anim.setDuration(200)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        # Keep reference to prevent garbage collection
        self._preview_anim = anim

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_scaled_preview()

    def eventFilter(self, obj, event):
        if hasattr(self, '_preview') and obj is self._preview and event.type() == event.Type.Resize:
            self._apply_scaled_preview()
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
            sk.muted_css(12) + " QLabel { border: none; }")

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
        from PySide6.QtCore import QThreadPool, Signal, QObject
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
        class _SizeTask(QRunnable):
            def __init__(self):
                super().__init__()
                # done is emitted inside run(); the panel keeps the signals
                # object alive until _on_async_dir_size_done consumes it.
                self.setAutoDelete(True)

            def run(self):
                # Bail out early when the request was invalidated while this
                # task was queued (the panel removed it from size_tasks), so
                # rapid folder switching does not pile up wasted scans.
                if request not in size_tasks:
                    return
                sz = 0
                try:
                    if scoped is not None and session and metadata_port is not None:
                        with session.operation():
                            sz, _ = metadata_port.get_dir_size(
                                scoped.session.root, dir_path
                            )
                    else:
                        return
                except Exception:
                    sz = 0
                signals.done.emit(request, sz)
        # Keep the signals object (and thus the queued delivery) alive until
        # the result is consumed on the UI thread.
        self._size_tasks[request] = signals
        pool = QThreadPool.globalInstance()
        pool.start(_SizeTask())

    def _on_async_dir_size_done(self, request: _AsyncRequest, size: int):
        self._size_tasks.pop(request, None)
        if not self._is_current_async_request(request):
            return
        self._set_field_text(self._fields["size"], format_info_size(size))


    @staticmethod
    def _load_preview_pixmap(path: str) -> QPixmap | None:
        try:
            if not os.path.isfile(path):
                return None
            from PySide6.QtGui import QImageReader
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            orig = reader.size()
            if orig.width() > PREVIEW_LOAD_MAX or orig.height() > PREVIEW_LOAD_MAX:
                reader.setScaledSize(orig.scaled(
                    PREVIEW_LOAD_MAX, PREVIEW_LOAD_MAX,
                    Qt.AspectRatioMode.KeepAspectRatio))
            img = reader.read()
            if img.isNull():
                return None
            return QPixmap.fromImage(img)
        except Exception:
            _log.exception("Preview image load failed")
            return None

    # ── Tags ───────────────────────────────────────────────────

    def _clear_tags(self):
        self._tag_render_generation = getattr(self, "_tag_render_generation", 0) + 1
        for w in self._tags_widgets:
            self._tags_flow_layout.removeWidget(w)
            w.deleteLater()
        self._tags_widgets.clear()
        self._rendered_tags = ()

    def _make_tag_chip(self, tag: str) -> QWidget:
        return create_tag_chip(
            tag,
            on_remove=self._remove_tag,
            color=tag_color_from(self._tags_port, tag),
        )

    def _render_tags(self, tags: list[str]):
        normalized = tuple(str(tag) for tag in tags)
        if normalized == self._rendered_tags and self._tags_widgets:
            return
        self._tags_flow.setUpdatesEnabled(False)
        try:
            self._clear_tags()
            self._rendered_tags = normalized
            for i, tag in enumerate(normalized):
                chip = self._make_tag_chip(tag)
                self._tags_widgets.append(chip)
                self._tags_flow_layout.addWidget(chip)
                if i < _MAX_ANIMATED_TAGS:
                    # Staggered fade-in animation for the first visible chips.
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
        from PySide6.QtCore import QTimer
        generation = self._tag_render_generation
        QTimer.singleShot(delay, lambda: self._do_fade_in(chip, generation))

    def _do_fade_in(self, chip, generation):
        if generation != self._tag_render_generation:
            return
        anim = QPropertyAnimation(chip, b"windowOpacity")
        anim.setDuration(150)
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

    def set_scoped_services(self, services):
        """Bind library-scoped services resolved by MainWindow."""
        from AssetsManager.application.desktop_ports import RootBoundTagService
        from AssetsManager.controllers.info_controller import InfoController

        self._scoped_services = services
        self._library_root = services.session.root_str
        self._metadata_port = services.metadata_service
        self._tags_port = RootBoundTagService(self._library_root, services.tag_service)
        self._current_path = ""
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
        from AssetsManager.core.settings import AppSettings
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
        task = _LinkScanTask(self._controller, self._current_path)
        task.signals.done.connect(self._on_manual_scan_done)
        self._link_scan_task = task
        QThreadPool.globalInstance().start(task)

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

        self._current_path = fi.absoluteFilePath()
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
        self._clear_tags()
        self._notes.blockSignals(True)
        self._notes.setPlainText("")
        self._notes.blockSignals(False)
        self._show_loading_state()

        # Cancel previous pending task (stale detection handles in-flight results)
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
        )
        task.signals.result_ready.connect(self._on_file_info_ready)
        task.signals.preview_ready.connect(self._on_preview_ready)
        task.signals.urls_discovered.connect(self._on_task_urls_discovered)
        self._pending_task = task
        QThreadPool.globalInstance().start(task)

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

    def _on_preview_ready(self, request, pixmap):
        """Called on main thread when async preview load completes."""
        if not self._is_current_async_request(request):
            return
        if pixmap:
            self._empty_preview_state.hide()
            self._preview.show()
            self._preview_icon_name = ""
            self._preview_pixmap = pixmap
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
        return InfoPanel()

    def flush_pending_changes(self):
        """Persist pending notes before switching libraries or opening a viewer."""
        self._flush_notes_save()

    def prepare_library_switch(self):
        """Flush local edits and stop debounce work for the old library."""
        self._tag_render_generation = getattr(self, "_tag_render_generation", 0) + 1
        self.flush_pending_changes()
        if self._notes_timer:
            self._notes_timer.stop()
        # Do not retain a controller/repository backed by the old session while
        # the library is closing or a replacement session is being assembled.
        self._controller = None
        self._scoped_services = None

    def shutdown(self):
        self.prepare_library_switch()
        self._invalidate_async_requests()
        super().shutdown()

    def closeEvent(self, event):
        self.prepare_library_switch()
        super().closeEvent(event)
