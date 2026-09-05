"""UI construction and chrome styling for the file list panel.

``LayoutMixin`` builds every widget the panel renders — header, toolbar,
breadcrumb, status bar, grid canvas and the details QTreeView — and owns
their styling (chrome CSS, detail theme, state icons, translations), the
status-bar rendering, and the context-menu construction with its command
definitions.

Business logic lives in ``_base_logic.py``; signal wiring and interaction
handling live in ``_base_events.py``; ``_base.py`` composes the three.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import Qt, QSize, QPoint
from PySide6.QtWidgets import (
    QHBoxLayout, QComboBox, QLabel, QWidget, QMenu,
    QSizePolicy, QTreeView, QAbstractItemView, QHeaderView,
    QLineEdit, QPushButton,
)

from AssetsManager.core import icons
from AssetsManager.core import themes
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager import i18n

from AssetsManager.application.asset_filters import category_labels
from AssetsManager.panels._ai_tag_common import ai_tagging_enabled
from AssetsManager.panels.file_list._common import ZOOM_PRESETS
from AssetsManager.panels.file_list._grid_layout import GridLayout
from AssetsManager.panels.file_list._grid_widget import FileListGridWidget
from AssetsManager.panels.file_list._thumbnail_delivery import ThumbnailDeliveryCoordinator
from AssetsManager.panels.file_list._detail_model import DetailModel
from AssetsManager.panels.file_list._commands import FileListCommand, FileListCommandContext
from AssetsManager.panels.file_list._ui_helpers import (
    _add_command_group,
    _always,
    _DetailsItemDelegate,
    _make_nav_button,
)
from AssetsManager.panels.file_list._status_helpers import (
    compute_total_size,
    status_text,
)
from AssetsManager.widgets.toast import Toast

if TYPE_CHECKING:
    from pathlib import Path

    from AssetsManager.controllers.file_list_controller import FileListController
    from AssetsManager.panels.file_list._model import FileSystemModel

tr = i18n.tr


class LayoutMixin:
    """Widget creation, layout management and chrome styling."""

    if TYPE_CHECKING:
        # Host surface owned by FileListPanel / sibling mixins.
        _model: FileSystemModel
        _controller: FileListController
        _current: Path
        _cached_total_sz: int
        _undo_svc: Any
        content_layout: Any

        def setFocusProxy(self, w: Any) -> None: ...
        def _go_back(self) -> None: ...
        def _go_forward(self) -> None: ...
        def _go_up(self) -> None: ...
        def _toggle_sort_dir(self) -> None: ...
        def _toggle_hidden(self) -> None: ...
        def _do_refresh(self) -> None: ...
        def _on_sort_changed(self) -> None: ...
        def _on_filter_changed(self) -> None: ...
        def _on_view_changed(self, index: int) -> None: ...
        def _on_zoom_changed(self, val: str) -> None: ...
        def _on_search_changed(self, text: str) -> None: ...
        def _toggle_advanced_filter(self) -> None: ...
        def _apply_advanced_filter(self) -> None: ...
        def _clear_advanced_filter(self) -> None: ...
        def _invoke_command(
            self,
            command_id: str,
            context: FileListCommandContext | None = None,
            global_pos: QPoint | None = None,
            *,
            shortcut: bool = False,
        ) -> None: ...
        def _navigate_or_open(self, path: str) -> None: ...
        def _add_plugin_context_items(self, menu: QMenu, file_path: str) -> None: ...
        def _can_paste(self) -> bool: ...
        def _get_scoped_services(self) -> Any: ...
        def _apply_tag_dialog(self, paths: list[str]) -> None: ...
        def _remove_tag_dialog(self, paths: list[str]) -> None: ...
        def _manage_tags_dialog(self, paths: list[str]) -> None: ...
        def _ai_tag_batch(self, paths: list[str]) -> None: ...
        def _populate_details(self) -> None: ...
        def _load_visible(self) -> None: ...
        def _render_bc(self) -> None: ...
        def window(self) -> QWidget: ...

    def _build_ui(self) -> None:
        """Build header, toolbar, breadcrumb, status bar, grid and detail views."""
        # ── Tier-1: Address & Navigation Band (36px Horizon) ─────

        self._header = QWidget()
        self._header.setFixedHeight(scaled_px(36))
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(scaled_px(8), 0, scaled_px(8), 0)
        header_layout.setSpacing(scaled_px(8))

        self._header_title = QLabel(tr("filelist.header"))
        self._header_title.hide()  # Title integrated with breadcrumbs
        header_layout.addWidget(self._header_title)

        # 1. Zone 1: Navigation Cluster [←] [→] [↑]
        self._nav_buttons = []
        self._nav_tooltip_keys = ("filelist.back", "filelist.forward", "filelist.up")
        self._nav_buttons.append(self._make_nav_button("arrow_left", tr("filelist.back"), self._go_back))
        self._nav_buttons.append(self._make_nav_button("arrow_right", tr("filelist.forward"), self._go_forward))
        self._nav_buttons.append(self._make_nav_button("arrow_up", tr("filelist.up"), self._go_up))
        for b in self._nav_buttons:
            header_layout.addWidget(b)

        # 2. Zone 2: Enclosed Address Bar Capsule [📁 Breadcrumbs... ↻]
        self._address_container = QWidget()
        self._address_container.setObjectName("addressBarCapsule")
        self._address_container.setFixedHeight(scaled_px(28))
        addr_layout = QHBoxLayout(self._address_container)
        addr_layout.setContentsMargins(scaled_px(6), 0, scaled_px(4), 0)
        addr_layout.setSpacing(scaled_px(4))

        self._addr_icon = QLabel()
        self._addr_icon.setPixmap(icons.icon("folder", color="icon_secondary", size=scaled_px(14)).pixmap(QSize(scaled_px(14), scaled_px(14))))
        addr_layout.addWidget(self._addr_icon)

        self._breadcrumb = QWidget()
        self._breadcrumb.setStyleSheet("background: transparent;")
        self._bc_layout = QHBoxLayout(self._breadcrumb)
        self._bc_layout.setContentsMargins(0, 0, 0, 0)
        self._bc_layout.setSpacing(0)
        addr_layout.addWidget(self._breadcrumb, 1)

        self._refresh_btn = self._make_nav_button("refresh", tr("filelist.refresh"), self._do_refresh)
        # hit_area (24) is the a11y floor for square icon-button hot zones (audit F-5).
        self._refresh_btn.setFixedSize(
            scaled_px(themes.metrics("hit_area")), scaled_px(themes.metrics("hit_area"))
        )
        addr_layout.addWidget(self._refresh_btn)

        header_layout.addWidget(self._address_container, 1)

        # 3. Zone 3: Scoped Search Box [🔍 Search...]
        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("filelist.filter_placeholder"))
        self._search.setClearButtonEnabled(True)
        self._search.installEventFilter(cast(QWidget, self))
        self._setup_search_history(self._search)
        self._search.setFixedHeight(scaled_px(28))
        self._search.setFixedWidth(scaled_px(200))
        header_layout.addWidget(self._search)

        # Tier-2 disclosure toggle (chrome 退让: collapsible command band)
        self._toolbar_toggle_btn = self._make_nav_button(
            "chevron_down", tr("filelist.toolbar.collapse"), self._toggle_toolbar)
        header_layout.addWidget(self._toolbar_toggle_btn)

        self.content_layout.addWidget(self._header)

        # ── Tier-2: View & Command Band (32px Horizon) ───────────

        self._toolbar_widget = QWidget()
        self._toolbar_widget.setFixedHeight(scaled_px(32))
        tb = QHBoxLayout(self._toolbar_widget)
        tb.setContentsMargins(scaled_px(6), 0, scaled_px(6), 0)
        tb.setSpacing(scaled_px(6))

        # Group 1: Filter
        self._filter_combo = QComboBox()
        self._filter_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._populate_filter_combo()
        self._filter_combo.setToolTip(tr("filelist.filter_tooltip"))
        self._filter_combo.setAccessibleName(tr("filelist.filter_tooltip"))
        tb.addWidget(self._filter_combo)

        # Group 2: Sort
        sort_layout = QHBoxLayout()
        sort_layout.setContentsMargins(0, 0, 0, 0)
        sort_layout.setSpacing(scaled_px(2))

        self._sort_combo = QComboBox()
        self._sort_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for key, label in (
            ("name", tr("filelist.sort.name")),
            ("date", tr("filelist.sort.date")),
            ("size", tr("filelist.sort.size")),
            ("type", tr("filelist.sort.type")),
        ):
            self._sort_combo.addItem(label, key)
        self._sort_combo.setToolTip(tr("filelist.sort_tooltip"))
        self._sort_combo.setAccessibleName(tr("filelist.sort_tooltip"))
        sort_layout.addWidget(self._sort_combo)

        self._sort_btn = self._make_nav_button("arrow_up_down", tr("filelist.sort_dir"), self._toggle_sort_dir)
        sort_layout.addWidget(self._sort_btn)
        tb.addLayout(sort_layout)

        # Group 3: View & Zoom
        view_layout = QHBoxLayout()
        view_layout.setContentsMargins(0, 0, 0, 0)
        view_layout.setSpacing(scaled_px(2))

        self._view_combo = QComboBox()
        self._view_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._view_combo.addItem(tr("filelist.view.grid"), userData="Grid")
        self._view_combo.addItem(tr("filelist.view.details"), userData="Details")
        self._view_combo.setToolTip(tr("filelist.view_tooltip"))
        self._view_combo.setAccessibleName(tr("filelist.view_tooltip"))
        view_layout.addWidget(self._view_combo)

        self._zoom_combo = QComboBox()
        self._zoom_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for sz in ZOOM_PRESETS:
            self._zoom_combo.addItem(f"{sz}px")
        self._zoom_combo.setCurrentIndex(2)
        self._zoom_combo.setToolTip(tr("filelist.zoom_tooltip"))
        self._zoom_combo.setAccessibleName(tr("filelist.zoom_tooltip"))
        view_layout.addWidget(self._zoom_combo)
        tb.addLayout(view_layout)

        tb.addStretch()

        # Group 4: Utilities (Hidden toggle & Advanced filter)
        utils_layout = QHBoxLayout()
        utils_layout.setContentsMargins(0, 0, 0, 0)
        utils_layout.setSpacing(scaled_px(2))

        self._hidden_btn = self._make_nav_button("eye", tr("filelist.hidden"), self._toggle_hidden)
        utils_layout.addWidget(self._hidden_btn)

        self._advanced_btn = self._make_nav_button(
            "settings", tr("filelist.advanced.tooltip"), self._toggle_advanced_filter)
        utils_layout.addWidget(self._advanced_btn)
        tb.addLayout(utils_layout)

        self.content_layout.addWidget(self._toolbar_widget)
        self._build_advanced_filter_popup()
        self._refresh_state_icons()
        self._apply_chrome_style()

        self.setFocusProxy(self._search)

        # ── Status bar ──────────────────────────────────────────

        self._status_bar = QWidget()
        self._status_bar.setFixedHeight(scaled_px(28))
        sl = QHBoxLayout(self._status_bar)
        sl.setContentsMargins(scaled_px(10), scaled_px(4), scaled_px(10), scaled_px(4))
        sl.setSpacing(scaled_px(8))
        self._status = QLabel("")
        sl.addWidget(self._status)
        sl.addStretch()
        self._operation_feedback = QLabel("")
        self._operation_feedback.hide()
        sl.addWidget(self._operation_feedback)

        self._footer_right = QWidget()
        fr_layout = QHBoxLayout(self._footer_right)
        fr_layout.setContentsMargins(0, 0, 0, 0)
        fr_layout.setSpacing(scaled_px(4))

        self._cmd_palette_btn = QPushButton("Ctrl+K")
        self._cmd_palette_btn.setFixedHeight(scaled_px(20))
        self._cmd_palette_btn.setToolTip(tr("shortcuts.command_palette", default="打开全局命令面板 (Ctrl+K)"))
        self._cmd_palette_btn.setIcon(icons.icon("search", color="icon_muted", size=scaled_px(12)))
        self._cmd_palette_btn.setIconSize(QSize(scaled_px(12), scaled_px(12)))
        themes.set_button_variant(self._cmd_palette_btn, "ghost")
        self._cmd_palette_btn.clicked.connect(self._trigger_command_palette)
        fr_layout.addWidget(self._cmd_palette_btn)

        self._view_grid_btn = QPushButton()
        self._view_grid_btn.setFixedSize(scaled_px(22), scaled_px(20))
        self._view_grid_btn.setToolTip(tr("filelist.view.grid"))
        self._view_grid_btn.setIcon(icons.icon("grid", color="icon_secondary", size=scaled_px(12)))
        self._view_grid_btn.setIconSize(QSize(scaled_px(12), scaled_px(12)))
        themes.set_button_variant(self._view_grid_btn, "ghost")
        self._view_grid_btn.clicked.connect(lambda: self._set_view_mode_by_name("Grid"))
        fr_layout.addWidget(self._view_grid_btn)

        self._view_details_btn = QPushButton()
        self._view_details_btn.setFixedSize(scaled_px(22), scaled_px(20))
        self._view_details_btn.setToolTip(tr("filelist.view.details"))
        self._view_details_btn.setIcon(icons.icon("file", color="icon_secondary", size=scaled_px(12)))
        self._view_details_btn.setIconSize(QSize(scaled_px(12), scaled_px(12)))
        themes.set_button_variant(self._view_details_btn, "ghost")
        self._view_details_btn.clicked.connect(lambda: self._set_view_mode_by_name("Details"))
        fr_layout.addWidget(self._view_details_btn)

        sl.addWidget(self._footer_right)
        self._fst_status_style()
        self.content_layout.addWidget(self._status_bar)

        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        self._header.setProperty("central", True)

        self._grid_widget = FileListGridWidget()
        self._grid_widget.set_model(self._model)
        self._grid_layout = GridLayout()
        self._grid_widget.set_layout_ref(self._grid_layout)
        self._thumbnail_delivery = ThumbnailDeliveryCoordinator(self._model, self._grid_widget)

        self.content_layout.insertWidget(
            self.content_layout.indexOf(self._status_bar), self._grid_widget)
        self._grid_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._grid_widget.installEventFilter(cast(QWidget, self))
        self._grid_widget.setAcceptDrops(True)

        # ── Detail view (QTreeView + DetailModel) ─────────────
        self._detail_view = QTreeView()
        self._detail_model = DetailModel()
        self._detail_view.setModel(self._detail_model)
        self._detail_view.setRootIsDecorated(False)
        self._detail_view.setItemsExpandable(False)
        self._detail_view.setIndentation(0)
        self._detail_view.setItemDelegate(_DetailsItemDelegate(self._detail_view))
        self._detail_view.setUniformRowHeights(True)
        self._detail_view.setAlternatingRowColors(True)
        self._detail_view.setIconSize(QSize(scaled_px(18), scaled_px(18)))
        self._detail_view.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._detail_view.setAllColumnsShowFocus(False)
        detail_header = self._detail_view.header()
        detail_header.setStretchLastSection(True)
        detail_header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        detail_header.setMinimumHeight(scaled_px(30))
        detail_header.setMinimumSectionSize(scaled_px(72))
        detail_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        detail_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        detail_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        detail_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        detail_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        detail_header.setSortIndicatorShown(True)
        self._detail_view.setSortingEnabled(True)
        self._detail_view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._detail_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._detail_view.setEditTriggers(QTreeView.EditTrigger.EditKeyPressed)
        self._detail_view.setDragEnabled(True)
        self._detail_view.setAcceptDrops(True)
        self._detail_view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self._detail_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._detail_view.installEventFilter(cast(QWidget, self))
        self._detail_view.viewport().installEventFilter(cast(QWidget, self))
        self._detail_view.hide()
        self._apply_detail_theme()
        self.content_layout.insertWidget(
            self.content_layout.indexOf(self._status_bar), self._detail_view)

        from AssetsManager.widgets.empty_state import EmptyStateWidget

        self._empty_state = EmptyStateWidget(cast(QWidget, self), kind="directory")
        self.content_layout.insertWidget(
            self.content_layout.indexOf(self._status_bar), self._empty_state)
        self._empty_state.hide()





    def _fst_status_style(self):
        self._status_bar.setStyleSheet(
            f"background: transparent; "
            f"border-top: {scaled_px(1)}px solid {themes.color('border_subtle')};")
        self._status.setStyleSheet(
            f"color: {themes.color('muted')}; font-size: {scaled_pt(themes.font_size('sm'))}px; "
            f"background: transparent; "
            f"padding: {scaled_px(int(themes.prop('spacing', 'xs')))}px 0;")
        self._operation_feedback.setStyleSheet(
            f"color: {themes.color('muted')}; font-size: {scaled_pt(themes.font_size('sm'))}px; "
            f"background: transparent; "
            f"padding: {scaled_px(int(themes.prop('spacing', 'xs')))}px 0;")

    @staticmethod
    def _header_css(t: dict) -> str:
        r_sm = scaled_px(int(themes.prop("border_radius", "sm")))
        hover = alpha(t["hover_overlay"], themes.prop("opacity", "hover"))
        return (
            f"background: {themes.header_for_dock()}; "
            f"border-bottom: {scaled_px(1)}px solid {t['border_subtle']}; "
            f"border-top: none; border-left: none; border-right: none; "
            f"#addressBarCapsule {{"
            f"  background: {t['input_bg']}; "
            f"  border: {scaled_px(1)}px solid {t['border_subtle']}; "
            f"  border-radius: {r_sm}px; "
            f"}}"
            f"#addressBarCapsule:hover {{"
            f"  border-color: {t['accent']}; "
            f"}}"
            f"#addressBarCapsule QLabel {{ background: transparent; border: none; }}"
            f"#addressBarCapsule QPushButton {{"
            f"  background: transparent; color: {t['muted']}; border: none; "
            f"  font-size: {scaled_pt(themes.font_size('sm'))}px; "
            f"  padding: {scaled_px(2)}px {scaled_px(6)}px; border-radius: {r_sm}px; "
            f"}}"
            f"#addressBarCapsule QPushButton:hover {{"
            f"  background: {hover}; color: {t['heading']}; "
            f"}}"
            f"#addressBarCapsule QPushButton[isCurrent='true'] {{"
            f"  color: {t['heading']}; font-weight: bold; "
            f"}}"
        )

    @staticmethod
    def _header_title_css(t: dict) -> str:
        return (
            f"color: {t['heading']}; font-size: {scaled_pt(int(themes.prop('font_size', 'sm')))}px; "
            f"font-weight: bold; "
            f"background: transparent; border: none; "
            f"padding: {scaled_px(int(themes.prop('spacing', 'xs')))}px {scaled_px(int(themes.prop('spacing', 'sm')))}px;"
        )

    @staticmethod
    def _nav_button_css(t: dict) -> str:
        return (
            f"QPushButton {{ background: transparent; color: {t['body']}; "
            f"border: none; padding: 0; min-width: {scaled_px(26)}px; }} "
            f"QPushButton:hover {{ background: {alpha(t['hover_overlay'], themes.prop('opacity', 'hover'))}; "
            f"border-radius: {scaled_px(int(themes.prop('border_radius', 'sm')))}px; "
            f"color: {t['heading']}; }}"
            f"QPushButton:pressed {{ background: {alpha(t['hover_overlay'], themes.prop('opacity', 'hover'))}; "
            f"border-radius: {scaled_px(int(themes.prop('border_radius', 'sm')))}px; "
            f"color: {t['heading']}; }}"
        )

    def _apply_chrome_style(self):
        """Single source for header/title/nav/status chrome styling."""
        t = themes.get()
        if hasattr(self, "_header"):
            self._header.setStyleSheet(self._header_css(t))
        if hasattr(self, "_header_title"):
            self._header_title.setStyleSheet(self._header_title_css(t))
        if hasattr(self, "_nav_buttons"):
            for btn in self._nav_buttons:
                btn.setStyleSheet(self._nav_button_css(t))
        if hasattr(self, "_addr_icon"):
            self._addr_icon.setPixmap(
                icons.icon("folder", color="icon_secondary", size=scaled_px(14)).pixmap(
                    QSize(scaled_px(14), scaled_px(14))
                )
            )
        if hasattr(self, "_status_bar"):
            self._fst_status_style()
        if hasattr(self, "_bc_layout"):
            # The breadcrumb re-renders from current navigation state; without
            # this its buttons keep the previous theme's colors (audit B2③).
            self._render_bc()
        self._style_advanced_popup()

    def refresh_header(self):
        """Re-apply header bar styling (called on bg opacity changes)."""
        self._apply_chrome_style()

    @property
    def _view_mode(self):
        return self._view_combo.currentData() or self._view_combo.currentText()

    def _apply_list_theme(self):
        pass

    def _sync_selection_anim(self):
        pass

    @staticmethod
    def _filter_category_text(key: str, label: str) -> str:
        if key in {"all", "images", "models", "videos", "documents", "archives"}:
            return tr(f"filelist.filter.{key}")
        return label

    def _populate_filter_combo(self, selected_key: str | None = None) -> str:
        """Rebuild category choices and return the surviving canonical key."""
        categories = category_labels()
        available_keys = {key for key, _label in categories}
        key = selected_key if selected_key in available_keys else "all"
        self._filter_combo.blockSignals(True)
        try:
            self._filter_combo.clear()
            for category_key, label in categories:
                self._filter_combo.addItem(
                    self._filter_category_text(category_key, label), category_key,
                )
            self._filter_combo.setCurrentIndex(
                max(0, self._filter_combo.findData(key))
            )
        finally:
            self._filter_combo.blockSignals(False)
        return key

    def _on_category_registry_changed(self) -> None:
        """Refresh an open panel after plugin categories are rebuilt."""
        if getattr(self, "_category_registry_disconnected", False) or self._model.is_shutdown:
            return
        selected_key = self._filter_combo.currentData()
        surviving_key = self._populate_filter_combo(selected_key)
        # A surviving key may have a different extension set after a plugin
        # update, so every registry generation must reapply the model filter.
        self._model.set_filter(
            text=self._search.text().lower(), category=surviving_key,
        )
        self._refresh_state_icons()
        self._update_status()
        if self._view_mode == "Details":
            self._populate_details()
        self._load_visible()

    def _retranslate_controls(self):
        self._header_title.setText(tr("filelist.header"))
        for button, key in zip(self._nav_buttons, self._nav_tooltip_keys, strict=True):
            button.setToolTip(tr(key))
        self._sort_btn.setToolTip(tr("filelist.sort_dir"))
        self._hidden_btn.setToolTip(tr("filelist.hidden"))
        self._refresh_btn.setToolTip(tr("filelist.refresh"))
        self._search.setPlaceholderText(tr("filelist.filter_placeholder"))
        self._advanced_btn.setToolTip(tr("filelist.advanced.tooltip"))
        self._advanced_btn.setAccessibleName(tr("filelist.advanced.tooltip"))
        self._set_toolbar_visible(not self._toolbar_widget.isHidden())
        if hasattr(self, "_advanced_popup"):
            self._adv_title.setText(tr("filelist.advanced.title"))
            self._adv_mtime_after_label.setText(tr("filelist.advanced.modified_after"))
            self._adv_mtime_before_label.setText(tr("filelist.advanced.modified_before"))
            self._adv_size_min_label.setText(tr("filelist.advanced.size_min"))
            self._adv_size_max_label.setText(tr("filelist.advanced.size_max"))
            self._adv_rating_min_label.setText(tr("filelist.advanced.rating_min"))
            self._adv_rating_max_label.setText(tr("filelist.advanced.rating_max"))
            self._adv_rating_min.setToolTip(tr("filelist.advanced.rating_hint"))
            self._adv_rating_max.setToolTip(tr("filelist.advanced.rating_hint"))
            self._adv_extensions_label.setText(tr("filelist.advanced.extensions"))
            self._adv_extensions.setPlaceholderText(tr("filelist.advanced.extensions_hint"))
            self._adv_mtime_after.setSpecialValueText(tr("filelist.advanced.any"))
            self._adv_mtime_before.setSpecialValueText(tr("filelist.advanced.any"))
            self._adv_size_min.setSpecialValueText(tr("filelist.advanced.any"))
            self._adv_size_max.setSpecialValueText(tr("filelist.advanced.any"))
            self._adv_rating_min.setSpecialValueText(tr("filelist.advanced.any"))
            self._adv_rating_max.setSpecialValueText(tr("filelist.advanced.any"))
            self._adv_apply_btn.setText(tr("filelist.advanced.apply"))
            self._adv_clear_btn.setText(tr("filelist.advanced.clear"))

        sort_key = self._sort_combo.currentData()
        self._sort_combo.blockSignals(True)
        self._sort_combo.clear()
        for key, label in (("name", tr("filelist.sort.name")), ("date", tr("filelist.sort.date")),
                           ("size", tr("filelist.sort.size")), ("type", tr("filelist.sort.type"))):
            self._sort_combo.addItem(label, key)
        self._sort_combo.setCurrentIndex(max(0, self._sort_combo.findData(sort_key)))
        self._sort_combo.blockSignals(False)

        filter_key = self._filter_combo.currentData()
        self._populate_filter_combo(filter_key)

        view_mode = self._view_combo.currentData()
        self._view_combo.blockSignals(True)
        self._view_combo.setItemText(0, tr("filelist.view.grid"))
        self._view_combo.setItemText(1, tr("filelist.view.details"))
        self._view_combo.setCurrentIndex(max(0, self._view_combo.findData(view_mode)))
        self._view_combo.blockSignals(False)

    def _toast(self, text: str):
        Toast.info(self._grid_widget, text, duration=2000)

    def _sort_key(self):
        return self._sort_combo.currentData() or self._sort_combo.currentText()

    def _filter_key(self):
        return self._filter_combo.currentData() or self._filter_combo.currentText()

    def _setup_search_history(self, line_edit):
        from PySide6.QtWidgets import QCompleter
        from AssetsManager.controllers.file_list_controller import FileListController
        history = FileListController.get_search_history()
        if history:
            completer = QCompleter(history, line_edit)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            line_edit.setCompleter(completer)

    def _build_advanced_filter_popup(self) -> None:
        """Build the compact advanced-filter popup (hidden by default).

        Lives next to the existing search input — this is a refinement of
        the one FileList search entry, not a second search surface.
        """
        from PySide6.QtCore import QDate
        from PySide6.QtWidgets import (
            QDialog, QDateEdit, QGridLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
        )

        self._advanced_popup = QDialog(cast(QWidget, self), Qt.WindowType.Popup)
        popup = self._advanced_popup
        grid = QGridLayout(popup)
        grid.setContentsMargins(scaled_px(12), scaled_px(10), scaled_px(12), scaled_px(10))
        grid.setHorizontalSpacing(scaled_px(8))
        grid.setVerticalSpacing(scaled_px(6))

        self._adv_title = QLabel(tr("filelist.advanced.title"))
        grid.addWidget(self._adv_title, 0, 0, 1, 2)

        self._adv_mtime_after_label = QLabel(tr("filelist.advanced.modified_after"))
        self._adv_mtime_after = QDateEdit()
        self._adv_mtime_before = QDateEdit()
        for date_edit in (self._adv_mtime_after, self._adv_mtime_before):
            date_edit.setCalendarPopup(True)
            date_edit.setDisplayFormat("yyyy-MM-dd")
            date_edit.setMinimumDate(QDate(2000, 1, 1))
            date_edit.setDate(date_edit.minimumDate())
            date_edit.setSpecialValueText(tr("filelist.advanced.any"))
        self._adv_mtime_before_label = QLabel(tr("filelist.advanced.modified_before"))
        self._adv_size_min_label = QLabel(tr("filelist.advanced.size_min"))
        self._adv_size_max_label = QLabel(tr("filelist.advanced.size_max"))
        self._adv_size_min = QSpinBox()
        self._adv_size_max = QSpinBox()
        for spin in (self._adv_size_min, self._adv_size_max):
            spin.setRange(0, 2097151)
            spin.setSuffix(" MiB")
            spin.setSpecialValueText(tr("filelist.advanced.any"))
        self._adv_rating_min_label = QLabel(tr("filelist.advanced.rating_min"))
        self._adv_rating_max_label = QLabel(tr("filelist.advanced.rating_max"))
        self._adv_rating_min = QSpinBox()
        self._adv_rating_max = QSpinBox()
        # 0 is the "any" sentinel (unrated rows are excluded by any real
        # rating bound in the shared structured query anyway).
        for spin in (self._adv_rating_min, self._adv_rating_max):
            spin.setRange(0, 5)
            spin.setToolTip(tr("filelist.advanced.rating_hint"))
            spin.setSpecialValueText(tr("filelist.advanced.any"))
        self._adv_extensions_label = QLabel(tr("filelist.advanced.extensions"))
        self._adv_extensions = QLineEdit()
        self._adv_extensions.setPlaceholderText(tr("filelist.advanced.extensions_hint"))
        self._adv_extensions.setClearButtonEnabled(True)

        rows = (
            (self._adv_mtime_after_label, self._adv_mtime_after, 1),
            (self._adv_mtime_before_label, self._adv_mtime_before, 2),
            (self._adv_size_min_label, self._adv_size_min, 3),
            (self._adv_size_max_label, self._adv_size_max, 4),
            (self._adv_rating_min_label, self._adv_rating_min, 5),
            (self._adv_rating_max_label, self._adv_rating_max, 6),
            (self._adv_extensions_label, self._adv_extensions, 7),
        )
        for label, editor, row in rows:
            grid.addWidget(label, row, 0)
            grid.addWidget(editor, row, 1)
        for editor in (self._adv_mtime_after, self._adv_mtime_before,
                       self._adv_size_min, self._adv_size_max,
                       self._adv_rating_min, self._adv_rating_max,
                       self._adv_extensions):
            editor.setMinimumWidth(scaled_px(150))
            editor.setAccessibleName(editor.toolTip() or "")

        self._adv_clear_btn = QPushButton(tr("filelist.advanced.clear"))
        self._adv_clear_btn.clicked.connect(self._clear_advanced_filter)
        self._adv_apply_btn = QPushButton(tr("filelist.advanced.apply"))
        self._adv_apply_btn.clicked.connect(self._apply_advanced_filter)
        themes.set_button_variant(self._adv_clear_btn, "ghost")
        themes.set_button_variant(self._adv_apply_btn, "primary")
        grid.addWidget(self._adv_clear_btn, 8, 0)
        grid.addWidget(self._adv_apply_btn, 8, 1)

        self._style_advanced_popup()

    def _style_advanced_popup(self) -> None:
        """Apply theme tokens to the advanced-filter popup chrome."""
        if not hasattr(self, "_advanced_popup"):
            return
        t = themes.get()
        label_color = t["muted"]
        label_font = f"font-size: {scaled_pt(int(themes.prop('font_size', 'sm')))}px;"
        for label in (
            self._adv_title, self._adv_mtime_after_label, self._adv_mtime_before_label,
            self._adv_size_min_label, self._adv_size_max_label,
            self._adv_rating_min_label, self._adv_rating_max_label,
            self._adv_extensions_label,
        ):
            label.setStyleSheet(f"color: {label_color}; background: transparent; {label_font}")
        self._adv_title.setStyleSheet(
            f"color: {themes.color('heading')}; background: transparent; {label_font} font-weight: bold;"
        )
        self._advanced_popup.setStyleSheet(
            f"QDialog {{ background: {themes.color('panel')}; "
            f"border: {scaled_px(1)}px solid {themes.color('border')}; "
            f"border-radius: {scaled_px(int(themes.prop('border_radius', 'md')))}px; }}"
            f"QLineEdit, QSpinBox, QDateEdit {{ background: {themes.color('input_bg')}; "
            f"color: {themes.color('input_text')}; border: {scaled_px(1)}px solid {themes.color('border')}; "
            f"border-radius: {scaled_px(int(themes.prop('border_radius', 'sm')))}px; "
            f"padding: {scaled_px(2)}px {scaled_px(6)}px; }}"
        )

    def _on_detail_header_clicked(self, col: int):
        """Tweak column widths after sort for better readability."""
        detail_view = self._detail_view
        if detail_view is not None:
            detail_view.resizeColumnToContents(col)

    def _invalidate_size_cache(self):
        if self._model.rowCount():
            self._compute_total_sz()
        self._update_status()

    def _compute_total_sz(self):
        self._cached_total_sz = compute_total_size(self._model)

    def _update_status(self):
        state = getattr(self._model, "list_state", None)
        if state is not None and state == getattr(self._model, "STATE_LOADING", None):
            self._status.setText(status_text(state=state, view_mode=self._view_mode, total=0, selected=0, size_str=""))
            return
        if state is not None and state == getattr(self._model, "STATE_SCAN_ERROR", None):
            self._status.setText(status_text(state=state, view_mode=self._view_mode, total=0, selected=0, size_str=""))
            return
        if state is not None and state == getattr(self._model, "STATE_EMPTY_FOLDER", None):
            self._status.setText(status_text(state=state, view_mode=self._view_mode, total=0, selected=0, size_str=""))
            return
        if state is not None and state == getattr(self._model, "STATE_EMPTY_FILTERED", None):
            self._status.setText(status_text(state=state, view_mode=self._view_mode, total=0, selected=0, size_str=""))
            return
        total = self._model.rowCount()
        mode = self._view_mode
        if self._view_mode == "Details":
            sel = len(self._detail_view.selectionModel().selectedRows())
            self._status.setText(status_text(state=state, view_mode=mode, total=total, selected=sel, size_str=""))
        elif hasattr(self, '_grid_widget') and self._grid_widget is not None:
            if self._cached_total_sz < 0:
                self._compute_total_sz()
            sz_str = self._controller.format_total_size_suffix(self._cached_total_sz)
            sel = len(self._grid_widget.selection_model_rows())
            self._status.setText(status_text(state=state, view_mode=mode, total=total, selected=sel, size_str=sz_str))
        else:
            self._status.setText(status_text(state=state, view_mode=mode, total=total, selected=0, size_str=""))
        if hasattr(self, "_show_empty_if_needed"):
            self._show_empty_if_needed()

    def _show_empty_if_needed(self):
        if self._model.rowCount() == 0:
            self._status.setText(tr("filelist.empty"))
            if hasattr(self, "_empty_state"):
                query = self._search.text().strip() if hasattr(self, "_search") else ""
                if query:
                    self._empty_state.set_state(
                        kind="search",
                        title=tr("filelist.search_no_results"),
                        subtitle=tr("sidebar.empty_hint"),
                    )
                else:
                    self._empty_state.set_state(
                        kind="directory",
                        title=tr("filelist.empty"),
                        subtitle=tr("panel.empty.hint", default=""),
                    )
                self._empty_state.show()
                self._grid_widget.hide()
                self._detail_view.hide()
        else:
            if hasattr(self, "_empty_state"):
                self._empty_state.hide()
                if self._view_mode == "Details":
                    self._detail_view.show()
                    self._grid_widget.hide()
                else:
                    self._grid_widget.show()
                    self._detail_view.hide()
            self._apply_list_theme()

    def _trigger_command_palette(self) -> None:
        win = self.window() if callable(getattr(self, "window", None)) else None
        open_palette = getattr(win, "_open_command_palette", None)
        if callable(open_palette):
            open_palette()
        else:
            try:
                from AssetsManager.widgets.command_palette import CommandPalette
                dlg = CommandPalette(cast(QWidget, self))
                dlg.exec()
            except Exception:
                pass

    def _set_view_mode_by_name(self, mode: str) -> None:
        if hasattr(self, "_view_combo"):
            idx = self._view_combo.findData(mode)
            if idx >= 0:
                self._view_combo.setCurrentIndex(idx)

    def _refresh_state_icons(self) -> None:
        """Keep stateful toolbar controls icon-only across every refresh path."""
        sort_icon = "arrow_up" if self._model.sort_ascending else "arrow_down"
        hidden_icon = "eye" if self._model.show_hidden else "eye_off"
        chevron = "chevron_down" if not self._toolbar_widget.isHidden() else "chevron_right"
        for button, icon_name in (
            (self._sort_btn, sort_icon),
            (self._hidden_btn, hidden_icon),
            (self._toolbar_toggle_btn, chevron),
        ):
            button.setIcon(icons.icon(icon_name, color="icon_secondary", size=scaled_px(16)))
            button.setIconSize(QSize(scaled_px(16), scaled_px(16)))
            button.setProperty("semanticIcon", icon_name)
            button.setText("")

    def _toggle_toolbar(self) -> None:
        """Expand/collapse the Tier-2 command band (sort/filter/view/zoom)."""
        self._set_toolbar_visible(self._toolbar_widget.isHidden())

    def _set_toolbar_visible(self, visible: bool) -> None:
        self._toolbar_widget.setVisible(visible)
        chevron = "chevron_down" if visible else "chevron_right"
        self._toolbar_toggle_btn.setIcon(
            icons.icon(chevron, color="icon_secondary", size=scaled_px(16)))
        self._toolbar_toggle_btn.setProperty("semanticIcon", chevron)
        tip = tr("filelist.toolbar.collapse" if visible else "filelist.toolbar.expand")
        self._toolbar_toggle_btn.setToolTip(tip)
        self._toolbar_toggle_btn.setAccessibleName(tip)

    @staticmethod
    def _make_nav_button(icon_name, tooltip, callback):
        return _make_nav_button(icon_name, tooltip, callback)

    @staticmethod
    def _add_command_group(
        menu: QMenu,
        commands: tuple[FileListCommand, ...],
        context: FileListCommandContext,
        group: str,
    ) -> None:
        _add_command_group(menu, commands, context, group)

    @staticmethod
    def _always(_context: FileListCommandContext) -> bool:
        return _always(_context)

    def _apply_detail_theme(self):
        """Apply theme styling to the detail view (QTreeView).

        The header is styled by the central ``QHeaderView::section`` rule
        (themes.py, audit B1/I4) — the per-widget copy was removed.
        """
        self._detail_view.setStyleSheet(
            f"QTreeView {{"
            f"  background: {themes.color('base')}; color: {themes.color('body')}; "
            f"  alternate-background-color: {alpha(themes.color('header'), 0.12)}; "
            f"  selection-background-color: {alpha(themes.color('accent'), 0.20)}; "
            f"  selection-color: {themes.color('heading')}; "
            f"  border: none; outline: none; font-size: {scaled_pt(int(themes.prop('font_size', 'sm')))}px; "
            f"}}"
            f"QTreeView::item {{"
            f"  padding: {scaled_px(int(themes.prop('spacing', 'xs')))}px {scaled_px(int(themes.prop('spacing', 'sm')))}px; "
            f"  border: none; border-bottom: {scaled_px(1)}px solid {themes.color('border_subtle')}; "
            f"}}"
            f"QTreeView::item:alternate {{"
            f"  background: {alpha(themes.color('header'), 0.24)}; "
            f"}}"
            f"QTreeView::item:hover {{"
            f"  background: {alpha(themes.color('hover_overlay'), themes.prop('opacity', 'hover'))}; "
            f"}}"
            f"QTreeView::item:selected {{"
            f"  background: {alpha(themes.color('accent'), 0.28)}; color: {themes.color('heading')}; "
            f"  border-left: {scaled_px(2)}px solid {themes.color('accent')}; "
            f"}}")

    def _build_context_menu(self, paths: list[str], global_pos: QPoint) -> QMenu:
        """Build the shared Grid and Details context menu without displaying it."""
        menu = QMenu(cast(QWidget, self))
        context = self._command_context(paths)
        if paths:
            p = paths[0]
            commands = self._selected_commands(context, global_pos, p)
            self._add_command_group(menu, commands, context, "open")
            if not os.path.isdir(p):
                open_with = menu.addMenu(tr("filelist.menu.open_with"))
                open_with.addAction(tr("filelist.menu.default"), lambda p=p: self._navigate_or_open(p))
                from AssetsManager.core.tool_scheduler import list_tools, run_tool
                for tool in list_tools():
                    if "{file}" in str(tool.get("args", [])):
                        action = open_with.addAction(
                            tool.get("name", "Tool"),
                            lambda checked, t=tool, fp=p: run_tool(t, file_path=fp),
                        )
                        action.setIcon(icons.icon(tool.get("icon_name") or tool.get("icon"), color="icon_primary", size=scaled_px(16), fallback="wrench"))
            self._add_command_group(menu, commands, context, "clipboard")
            self._add_command_group(menu, commands, context, "mutate")
            self._add_command_group(menu, commands, context, "history")
            tag_menu = menu.addMenu(tr("filelist.menu.tags"))
            tag_menu.addAction(tr("filelist.menu.apply_tag"), lambda: self._apply_tag_dialog(paths))
            tag_menu.addAction(tr("filelist.menu.remove_tag"), lambda: self._remove_tag_dialog(paths))
            # H2-c: batch AI tagging — the item exists only while the user
            # has explicitly enabled AI tagging in settings (zero menu churn
            # and zero behavior change when the feature is off).
            if ai_tagging_enabled():
                tag_menu.addAction(tr("filelist.menu.ai_tag"), lambda: self._ai_tag_batch(paths))
            tag_menu.addSeparator()
            tag_menu.addAction(tr("filelist.menu.manage_tags"), lambda: self._manage_tags_dialog(paths))
            tag_menu.setEnabled(context.can_mutate)
            menu.addSeparator()
            self._add_command_group(menu, commands, context, "organize")
            self._add_plugin_context_items(menu, p)
        else:
            commands = self._empty_commands(context)
            self._add_command_group(menu, commands, context, "clipboard")
            self._add_command_group(menu, commands, context, "browse")
            self._add_command_group(menu, commands, context, "history")
            self._add_command_group(menu, commands, context, "organize")
        return menu

    def _command_context(self, paths: list[str]) -> FileListCommandContext:
        can_mutate = self._get_scoped_services() is not None
        undo_service = self._undo_svc if can_mutate else None
        return FileListCommandContext(
            paths=tuple(paths),
            current_dir=self._current,
            view_mode=self._view_mode,
            clipboard_has_local_files=self._can_paste(),
            can_mutate=can_mutate,
            undo_available=undo_service is not None and undo_service.can_undo(),
            redo_available=undo_service is not None and undo_service.can_redo(),
        )

    def _empty_commands(self, _context: FileListCommandContext) -> tuple[FileListCommand, ...]:
        return (
            FileListCommand("paste", "filelist.menu.paste", "Ctrl+V", "clipboard", self._always,
                            lambda value: value.can_mutate and value.clipboard_has_local_files,
                            lambda: self._invoke_command("paste", _context)),
            FileListCommand("new_folder", "filelist.menu.new_folder", "Ctrl+Shift+N", "clipboard", self._always,
                            lambda value: value.can_mutate, lambda: self._invoke_command("new_folder", _context)),
            FileListCommand("select_all", "filelist.menu.select_all", "Ctrl+A", "browse", self._always,
                            self._always, lambda: self._invoke_command("select_all", _context)),
            FileListCommand("refresh", "filelist.menu.refresh", "F5", "browse", self._always,
                            self._always, lambda: self._invoke_command("refresh", _context)),
            FileListCommand("toggle_hidden", "filelist.menu.toggle_hidden", "Ctrl+H", "browse", self._always,
                            self._always, lambda: self._invoke_command("toggle_hidden", _context)),
            FileListCommand("undo", "filelist.menu.undo", "Ctrl+Z", "history", self._always,
                            lambda value: value.undo_available, lambda: self._invoke_command("undo", _context)),
            FileListCommand("redo", "filelist.menu.redo", "Ctrl+Y", "history", self._always,
                            lambda value: value.redo_available, lambda: self._invoke_command("redo", _context)),
            FileListCommand("reveal", "filelist.menu.open_explorer", None, "organize", self._always,
                            self._always, lambda: self._invoke_command("reveal", _context)),
            FileListCommand("help", "filelist.menu.keyboard_help", "F4", "organize", self._always,
                            self._always, lambda: self._invoke_command("help", _context)),
        )

    def _selected_commands(
        self, context: FileListCommandContext, global_pos: QPoint, path: str,
    ) -> tuple[FileListCommand, ...]:
        return (
            FileListCommand("open", "filelist.menu.open", "Enter", "open", self._always, self._always,
                            lambda: self._invoke_command("open", context)),
            FileListCommand("copy", "filelist.menu.copy", "Ctrl+C", "clipboard", self._always, self._always,
                            lambda: self._invoke_command("copy", context)),
            FileListCommand("cut", "filelist.menu.cut", "Ctrl+X", "clipboard", self._always, self._always,
                            lambda: self._invoke_command("cut", context)),
            FileListCommand("copy_path", "filelist.menu.copy_path", None, "clipboard", self._always, self._always,
                            lambda: self._invoke_command("copy_path", context)),
            FileListCommand("rename", "filelist.menu.rename", "F2", "mutate", self._always,
                            lambda value: value.can_mutate and len(value.paths) == 1,
                            lambda: self._invoke_command("rename", context)),
            FileListCommand("duplicate", "filelist.menu.duplicate", "Ctrl+D", "mutate", self._always,
                            lambda value: value.can_mutate, lambda: self._invoke_command("duplicate", context)),
            FileListCommand("trash", "filelist.menu.delete", "Delete", "mutate", self._always,
                            lambda value: value.can_mutate, lambda: self._invoke_command("trash", context)),
            FileListCommand("permanent_delete", "filelist.menu.delete_permanent", "Shift+Delete", "mutate",
                            self._always, lambda value: value.can_mutate,
                            lambda: self._invoke_command("permanent_delete", context)),
            FileListCommand("undo", "filelist.menu.undo", "Ctrl+Z", "history", self._always,
                            lambda value: value.undo_available, lambda: self._invoke_command("undo", context)),
            FileListCommand("redo", "filelist.menu.redo", "Ctrl+Y", "history", self._always,
                            lambda value: value.redo_available, lambda: self._invoke_command("redo", context)),
            FileListCommand("properties", "filelist.properties", "Alt+Enter", "organize", self._always,
                            self._always, lambda: self._invoke_command("properties", context)),
            FileListCommand("reveal", "filelist.menu.open_explorer", None, "organize", self._always,
                            self._always, lambda: self._invoke_command("reveal", context)),
            FileListCommand("quick_share", "sharing.quick_share", None, "organize", self._always,
                            self._always, lambda: self._invoke_command("quick_share", context, global_pos)),
            FileListCommand("help", "filelist.menu.keyboard_help", "F4", "organize", self._always,
                            self._always, lambda: self._invoke_command("help", context)),
        )

    def _show_context_menu(self, paths: list[str], global_pos: QPoint):
        self._build_context_menu(paths, global_pos).exec(global_pos)

    def _show_filelist_shortcuts(self) -> None:
        """Show FileList's stable shortcuts without depending on its host window."""
        from AssetsManager.core.settings import AppSettings
        from PySide6.QtWidgets import QMessageBox

        settings = AppSettings.instance()
        if not settings.get("filelist_shortcut_hints_seen", False):
            settings.set("filelist_shortcut_hints_seen", True)
            settings.save()
        lines = [
            f"F4 - {tr('filelist.help.keyboard_help')}",
            f"Ctrl+F - {tr('shortcuts.filelist_filter')}",
            f"Enter - {tr('filelist.menu.open')}",
            f"Alt+Enter - {tr('filelist.properties')}",
            f"Backspace - {tr('filelist.help.up')}",
            f"Ctrl+C / Ctrl+X / Ctrl+V - {tr('filelist.help.clipboard')}",
            f"Ctrl+D - {tr('filelist.menu.duplicate')}",
            f"F2 - {tr('filelist.menu.rename')}",
            f"Delete / Shift+Delete - {tr('filelist.help.delete')}",
            f"Ctrl+Z / Ctrl+Y - {tr('filelist.help.history')}",
            tr("filelist.help.history_retention"),
            f"Ctrl+Shift+N - {tr('filelist.menu.new_folder')}",
            f"Ctrl+A - {tr('filelist.menu.select_all')}",
            f"F5 - {tr('filelist.menu.refresh')}",
            f"Ctrl+H - {tr('filelist.menu.toggle_hidden')}",
            f"Escape - {tr('filelist.help.clear')}",
        ]
        QMessageBox.information(cast(QWidget, self), tr("filelist.help.title"), "\n".join(lines))
