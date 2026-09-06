"""QuickTaggerOverlay — instant modal tagging overlay for selected assets.

Provides an instant, keyboard-driven tagging experience aligned with modern
creative DAMs (Eagle / Linear). Activated via 'T' key in file lists or explicitly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import Qt, QPoint, QSize, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCompleter, QWidget, QApplication, QLayoutItem,
)

from AssetsManager import i18n
from AssetsManager.core import themes, icons
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.widgets.elevation import apply_elevation, refresh_elevation
from AssetsManager.widgets.overlay_shell import OverlayShell
from AssetsManager.widgets.tag_chip import create_tag_chip

tr = i18n.tr


class QuickTaggerOverlay(OverlayShell):
    """Instant floating tagger dialog for one or more files.

    V05: shell-backed — the ``SCRIM_WORKSPACE`` backdrop (alpha unified from
    this overlay's historical 170), refresh-bus subscription, screen
    constraining, and focus return live in OverlayShell.
    """

    tags_changed = Signal()

    def __init__(
        self,
        paths: list[str],
        library_root: str,
        tag_service: Any = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setModal(True)

        self._paths = [str(p) for p in paths if p]
        self._library_root = str(library_root or "")
        self._tag_service = tag_service
        self._all_library_tags: list[str] = []
        self._current_tags: list[str] = []

        self._load_tags()
        self._setup_ui()
        self._reposition()

    def _load_tags(self) -> None:
        if not self._tag_service or not self._library_root:
            return
        try:
            self._all_library_tags = self._tag_service.get_all_tags(self._library_root) or []
        except Exception:
            self._all_library_tags = []

        # V15: TagService exposes the plural batch API (get_tags_for_files);
        # the historical singular get_tags_for_file never existed on the
        # production service and the AttributeError was swallowed below,
        # leaving the overlay permanently on "no tags" for real libraries.
        try:
            result = self._tag_service.get_tags_for_files(
                self._library_root, self._paths[:20]
            ) or {}
        except Exception:
            self._current_tags = []
            result = {}
        if len(self._paths) == 1:
            self._current_tags = next(iter(result.values()), [])
        else:
            common: set[str] | None = None
            for tags in result.values():
                t_set = set(tags or [])
                common = t_set if common is None else common & t_set
            self._current_tags = sorted(common or set())

    def _setup_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        self._root_layout = root_layout
        root_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Centered card
        self._card = QFrame(self)
        self._card.setObjectName("quickTaggerCard")
        self._apply_styles()
        apply_elevation(self._card, level=3)

        card_layout = QVBoxLayout(self._card)
        self._card_layout = card_layout
        card_layout.setSpacing(scaled_px(10))

        # ── Header ──────────────────────────────────────────
        self._header_layout = QHBoxLayout()
        header_layout = self._header_layout
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(scaled_px(8))

        icon_lbl = QLabel()
        icon_sz = scaled_px(themes.metrics("icon_sm"))
        icon_lbl.setPixmap(icons.icon("tag", color="icon_accent", size=icon_sz).pixmap(QSize(icon_sz, icon_sz)))
        header_layout.addWidget(icon_lbl)

        title_lbl = QLabel(tr("tagger.title", default="快速打标"))
        title_lbl.setObjectName("taggerTitle")
        self._title_label = title_lbl
        header_layout.addWidget(title_lbl)

        count_badge = QLabel(f"{len(self._paths)} " + tr("tagger.files_count", default="个资产"))
        count_badge.setObjectName("taggerCount")
        self._count_label = count_badge
        header_layout.addWidget(count_badge)
        header_layout.addStretch()

        self._close_btn = close_btn = QPushButton()
        # V06: same hit-area/icon tokens as QuickLookOverlay's close button
        # (metrics("hit_area")=24 / icon_sm=16) — was hand-written 22×22/12.
        hit_area = scaled_px(themes.metrics("hit_area"))
        icon_sm = scaled_px(themes.metrics("icon_sm"))
        close_btn.setFixedSize(hit_area, hit_area)
        close_btn.setIcon(icons.icon("close", color="icon_muted", size=icon_sm))
        close_btn.setIconSize(QSize(icon_sm, icon_sm))
        close_btn.setToolTip(tr("common.close", default="关闭 (Esc)"))
        themes.set_button_variant(close_btn, "ghost")
        close_btn.clicked.connect(self.reject)
        header_layout.addWidget(close_btn)
        card_layout.addLayout(header_layout)

        # ── Asset Target Description ─────────────────────────
        target_lbl = QLabel(self._target_text())
        target_lbl.setObjectName("taggerTarget")
        self._target_label = target_lbl
        card_layout.addWidget(target_lbl)

        # ── Existing Tags Flow ──────────────────────────────
        self._tags_container = QWidget()
        self._tags_layout = QHBoxLayout(self._tags_container)
        self._tags_layout.setContentsMargins(0, 0, 0, 0)
        self._tags_layout.setSpacing(scaled_px(4))
        self._render_chips()
        card_layout.addWidget(self._tags_container)

        # ── Tag Input with Autocomplete ──────────────────────
        self._input = QLineEdit()
        self._input.setFixedHeight(scaled_px(themes.metrics("control_height_md")))
        self._input.setPlaceholderText(tr("tagger.placeholder", default="输入标签名按 Enter 添加..."))

        if self._all_library_tags:
            completer = QCompleter(self._all_library_tags, self)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            self._input.setCompleter(completer)

        self._input.returnPressed.connect(self._add_current_tag)
        card_layout.addWidget(self._input)

        # ── Footer guide ─────────────────────────────────────
        footer_lbl = QLabel(tr("tagger.guide", default="Enter：添加标签  ·  Esc：完成退出"))
        footer_lbl.setObjectName("taggerFooter")
        self._footer_label = footer_lbl
        footer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(footer_lbl)

        root_layout.addWidget(self._card)
        self._apply_scaled_metrics()

    def _apply_styles(self) -> None:
        """Card QSS — extracted verbatim from _setup_ui for the V05 refresh
        hook (same tokens, same values)."""
        r_md = scaled_px(int(themes.prop("border_radius", "md")))
        input_r = scaled_px(int(themes.prop("border_radius", "sm")))
        border_clr = themes.color("border_subtle")
        panel_bg = themes.color("panel")
        self._card.setStyleSheet(
            f"#quickTaggerCard {{"
            f"  background: {panel_bg}; "
            f"  border: {scaled_px(1)}px solid {border_clr}; "
            f"  border-radius: {r_md}px; "
            f"}}"
            f"#quickTaggerCard QLabel#taggerTitle {{"
            f"  color: {themes.color('heading')}; font-size: {scaled_pt(themes.font_size('md'))}px; "
            f"  font-weight: bold; background: transparent; border: none;"
            f"}}"
            f"#quickTaggerCard QLabel#taggerCount {{"
            f"  color: {themes.color('muted')}; font-size: {scaled_pt(themes.font_size('xs'))}px; "
            f"  background: {themes.color('input_bg')}; border: {scaled_px(1)}px solid {border_clr}; "
            f"  border-radius: {scaled_px(4)}px; padding: {scaled_px(2)}px {scaled_px(6)}px;"
            f"}}"
            f"#quickTaggerCard QLabel#taggerTarget {{"
            f"  color: {themes.color('body')}; font-size: {scaled_pt(themes.font_size('sm'))}px; "
            f"  background: transparent; border: none;"
            f"}}"
            f"#quickTaggerCard QLineEdit {{"
            f"  background: {themes.color('input_bg')}; color: {themes.color('heading')}; "
            f"  border: {scaled_px(1)}px solid {themes.color('border')}; border-radius: {input_r}px; "
            f"  padding: 0 {scaled_px(10)}px; font-size: {scaled_pt(themes.font_size('sm'))}px; "
            f"}}"
            f"#quickTaggerCard QLineEdit:focus {{ border: {scaled_px(1)}px solid {themes.color('border_focus')}; }}"
            f"#quickTaggerCard QLabel#taggerFooter {{"
            f"  color: {themes.color('muted')}; font-size: {scaled_pt(themes.font_size('xxs'))}px; "
            f"  background: transparent; border: none;"
            f"}}"
        )

    def _apply_scaled_metrics(self) -> None:
        """Re-derive the fixed card width / control sizes / layout margins
        and spacing from the current ui_scale; also the ui_scale_changed half
        of the V05 refresh hook (stage E adds the spacing re-derivation)."""
        self._root_layout.setContentsMargins(scaled_px(16), scaled_px(16), scaled_px(16), scaled_px(16))
        self._card.setFixedWidth(scaled_px(440))
        self._card_layout.setContentsMargins(scaled_px(16), scaled_px(14), scaled_px(16), scaled_px(14))
        self._card_layout.setSpacing(scaled_px(10))
        self._header_layout.setSpacing(scaled_px(8))
        self._tags_layout.setSpacing(scaled_px(4))
        self._input.setFixedHeight(scaled_px(themes.metrics("control_height_md")))
        refresh_elevation(self._card, level=3)

    def _target_text(self) -> str:
        if len(self._paths) == 1:
            return Path(self._paths[0]).name
        return tr("tagger.multi_selection", default="已多选资产")

    def refresh_overlay_chrome(self) -> None:
        """OverlayShell hook (V05): restyle QSS, retranslate chrome text, and
        re-scale metrics without rebuilding the overlay."""
        self._apply_styles()
        self._apply_scaled_metrics()
        self._title_label.setText(tr("tagger.title", default="快速打标"))
        self._count_label.setText(
            f"{len(self._paths)} " + tr("tagger.files_count", default="个资产")
        )
        self._target_label.setText(self._target_text())
        self._input.setPlaceholderText(
            tr("tagger.placeholder", default="输入标签名按 Enter 添加...")
        )
        self._footer_label.setText(
            tr("tagger.guide", default="Enter：添加标签  ·  Esc：完成退出")
        )
        self._render_chips()
        self._reposition()

    def _render_chips(self) -> None:
        while self._tags_layout.count():
            # takeAt never yields None for a non-empty box layout; the guard
            # below keeps the drain loop a no-op-safe drain either way.
            item = cast("QLayoutItem", self._tags_layout.takeAt(0))
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not self._current_tags:
            empty_lbl = QLabel(tr("tagger.no_tags", default="暂无标签"))
            empty_lbl.setObjectName("taggerFooter")
            self._tags_layout.addWidget(empty_lbl)
        else:
            for tag in self._current_tags[:12]:
                chip = create_tag_chip(tag, on_remove=lambda t: self._remove_tag(t))
                self._tags_layout.addWidget(chip)
        self._tags_layout.addStretch()

    def _add_current_tag(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        if not self._tag_service or not self._library_root:
            self._input.clear()
            return
        try:
            self._tag_service.add_tag_to_files(self._library_root, self._paths, text)
            if text not in self._current_tags:
                self._current_tags.append(text)
                self._render_chips()
            if text not in self._all_library_tags:
                self._all_library_tags.append(text)
            self.tags_changed.emit()
        except Exception:
            pass
        self._input.clear()

    def _remove_tag(self, tag: str) -> None:
        if not self._tag_service or not self._library_root:
            return
        try:
            self._tag_service.remove_tag_from_files(self._library_root, self._paths, tag)
            if tag in self._current_tags:
                self._current_tags.remove(tag)
                self._render_chips()
            self.tags_changed.emit()
        except Exception:
            pass

    def _position_overlay(self) -> None:
        self._reposition()

    def _reposition(self) -> None:
        # QWidget's parent is always widget-shaped here (the dialog is only
        # ever parented to windows/file lists); Qt's binding types it as the
        # wider QObject.
        parent_widget = cast("QWidget | None", self.parent())
        if parent_widget is not None and hasattr(parent_widget, "geometry"):
            parent_geom = parent_widget.geometry()
            self.resize(parent_geom.size())
            self.move(parent_widget.mapToGlobal(QPoint(0, 0)))
        else:
            screen = QApplication.primaryScreen()
            if screen:
                # V05: constraint rule is availableGeometry (taskbar-free),
                # matching OverlayShell._constrain_to_screen; was screen
                # geometry() including the taskbar area.
                geom = screen.availableGeometry()
                self.resize(geom.size())
                self.move(geom.topLeft())

    # paintEvent (dimming backdrop) is inherited from OverlayShell: the
    # SCRIM_WORKSPACE variant paints theme base @ alpha 172 — unified from
    # this overlay's historical alpha 170 (expected V05 micro-change).

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.accept()
        else:
            super().keyPressEvent(event)
