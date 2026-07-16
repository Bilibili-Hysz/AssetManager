"""Info panel — splitter layout, dynamic preview, metadata, tags, notes.

Layout: QSplitter(preview / metadata scroll) + fixed Actions bar at bottom.
"""
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QRect, QSize, QPoint, QMimeData, QUrl, QPropertyAnimation, QEasingCurve, QRunnable, QThreadPool, QObject
from PySide6.QtWidgets import (
    QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QTextEdit,
    QGroupBox, QWidget, QInputDialog, QSplitter, QScrollArea, QFrame,
    QSizePolicy, QLayout, QLayoutItem,
)
from PySide6.QtGui import QPixmap, QDrag

from AssetsManager.panels.base import PanelContent
from AssetsManager.application.context import LibrarySession
from AssetsManager.core.cache import LRUCache
from AssetsManager.core.constants import IMAGE_EXTS
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.core import themes
from AssetsManager.widgets.tag_chip import create_tag_chip

from AssetsManager import i18n

_log = logging.getLogger(__name__)
tr = i18n.tr

PREVIEW_LOAD_MAX = 2000


class _DragLabel(QLabel):
    """Label that supports click-to-open and drag-to-browser."""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._drag_url = ""
        self._drag_start = None

    def set_drag_url(self, url: str):
        self._drag_url = url

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_url:
            self._drag_start = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start and self._drag_url:
            if (event.globalPosition().toPoint() - self._drag_start).manhattanLength() > 10:
                self._drag_start = None
                drag = QDrag(self)
                mime = QMimeData()
                mime.setUrls([QUrl(self._drag_url)])
                mime.setText(self._drag_url)
                drag.setMimeData(mime)
                drag.exec(Qt.DropAction.CopyAction)
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        super().mouseReleaseEvent(event)


class _PreviewLabel(QLabel):
    view_fullscreen = Signal(str)

    def mouseDoubleClickEvent(self, event):
        self.view_fullscreen.emit(self.toolTip())  # fallback, panel overrides handler
        super().mouseDoubleClickEvent(event)


class _FlowLayout(QLayout):
    """Wrapping flow layout for tag chips."""
    def __init__(self, parent=None, margin=0, spacing=4):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _do_layout(self, rect, test_only):
        x = rect.x()
        y = rect.y()
        line_height = 0
        spacing = self.spacing()
        for item in self._items:
            widget = item.widget()
            if widget and widget.isHidden():
                continue
            item_size = item.sizeHint()
            next_x = x + item_size.width() + spacing
            if next_x > rect.right() and line_height > 0:
                x = rect.x()
                y += line_height + spacing
                line_height = 0
                next_x = x + item_size.width() + spacing
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item_size))
            x = next_x
            line_height = max(line_height, item_size.height())
        return y + line_height - rect.y() + spacing


def format_info_size(size):
    try:
        size = float(size)
    except Exception:
        return "—"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


@dataclass(frozen=True)
class _AsyncRequest:
    generation: int
    session: LibrarySession
    path: str


class _FileInfoSignals(QObject):
    result_ready = Signal(object, object)
    preview_ready = Signal(object, object)


class _FileInfoTask(QRunnable):
    """Background task for heavy file-info operations."""

    def __init__(self, request, controller, library_root,
                 sidebar_depth, branch_depths, classify_cache):
        super().__init__()
        self._request = request
        self._path = request.path
        self._controller = controller
        self._session = request.session
        self._library_root = library_root
        self._sidebar_depth = sidebar_depth
        self._branch_depths = branch_depths
        self._classify_cache = classify_cache
        self.signals = _FileInfoSignals()
        self.setAutoDelete(False)  # prevent QThreadPool from destroying before signal delivery

    def _load_preview(self, path, is_dir):
        if is_dir:
            img_path = InfoPanel._first_image_in_dir(path)
            if img_path:
                return InfoPanel._load_preview_pixmap(img_path)
            return None
        suffix = Path(path).suffix.lower()
        if suffix in IMAGE_EXTS:
            return InfoPanel._load_preview_pixmap(path)
        return None

    def run(self):
        try:
            with self._session.operation():
                self._run_scoped()
        except Exception:
            _log.exception("FileInfoTask failed for %s", self._path)

    def _run_scoped(self):
        from AssetsManager.controllers.info_controller import InfoController
        path = self._path
        is_dir = os.path.isdir(path)
        is_project = is_dir and InfoController.is_deepest_folder(
            path, self._library_root, self._sidebar_depth, self._branch_depths)

        if is_project and self._controller:
            existing = self._controller.get_urls(path)
            if not existing:
                discovered = self._controller.discover_urls_in_dir(path)
                for u in discovered:
                    try:
                        self._controller.add_url(path, u)
                    except ValueError:
                        pass

        dir_summary = self._controller.classify_dir(path, classify_cache=self._classify_cache) if is_dir else None

        if is_dir:
            display_type = tr("info.project") if is_project else tr("info.folder")
            display_size = tr("info.calculating") if os.path.exists(path) else "—"
        else:
            display_type = tr("info.file", ext=Path(path).suffix.lstrip('.').upper())
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            display_size = format_info_size(size) if size else "—"

        try:
            from datetime import datetime
            mtime = os.path.getmtime(path)
            modified_display = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        except OSError:
            modified_display = "—"

        parent_path = str(Path(path).parent)

        file_info = self._controller.get_file_info(
            path,
            is_dir=is_dir,
            file_type=display_type,
            size_display=display_size,
            modified_display=modified_display,
            parent_path=parent_path,
            dir_summary=dir_summary,
            is_project=is_project,
        )

        self.signals.result_ready.emit(self._request, file_info)

        preview = self._load_preview(path, is_dir)
        self.signals.preview_ready.emit(self._request, preview)


class InfoPanel(PanelContent):
    open_requested = Signal(str)
    copy_path_requested = Signal(str)
    view_fullscreen = Signal(str)  # request viewer panel

    def __init__(self, parent=None):
        super().__init__(parent)
        self._library_root = ""
        self._store = None
        self._project = None
        self._scoped_services = None
        self._controller = None
        self._current_path = ""
        self._preview_pixmap: QPixmap | None = None
        self._notes_timer = None
        self._sidebar_depth = 2
        self._branch_depths: dict[str, int] = {}
        self._urls_scanned: set[str] = set()  # avoid re-scanning URL discovery
        self._pending_task: _FileInfoTask | None = None
        self._async_generation = 0
        self._async_request: _AsyncRequest | None = None

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

        t = themes.get()
        meta = QGroupBox(tr("info.title"))
        meta.setStyleSheet(
            f"QGroupBox {{ border: 1px solid {t['border']}; border-radius: {scaled_px(4)}px; "
            f"margin-top: {scaled_px(4)}px; padding-top: {scaled_px(6)}px; color: {t['heading']}; }} "
            f"QGroupBox::title {{ subcontrol-origin: margin; left: {scaled_px(8)}px; padding: 0 {scaled_px(4)}px; }}")
        self._meta_grp = meta
        meta_layout = QVBoxLayout(meta)
        meta_layout.setSpacing(scaled_px(2))

        self._name = QLabel("—")
        self._name.setStyleSheet(f"font-size: {scaled_pt(14)}px; font-weight: bold; padding: {scaled_px(2)}px 0;")
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
        meta_layout.addWidget(self._plugin_fields_widget)

        details_layout.addWidget(meta)

        # Tags
        tags_grp = QGroupBox(tr("info.tags"))
        tags_grp.setStyleSheet(
            f"QGroupBox {{ border: 1px solid {t['border']}; border-radius: {scaled_px(4)}px; "
            f"margin-top: {scaled_px(4)}px; padding-top: {scaled_px(6)}px; color: {t['heading']}; }} "
            f"QGroupBox::title {{ subcontrol-origin: margin; left: {scaled_px(8)}px; padding: 0 {scaled_px(4)}px; }}")
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
        self._add_tag_btn.clicked.connect(self._add_tag)
        self._add_tag_btn.setStyleSheet(
            f"background: transparent; color: {t['muted']}; border: 1px dashed {t['border']}; "
            f"border-radius: {scaled_px(6)}px; padding: {scaled_px(2)}px {scaled_px(10)}px; font-size: {scaled_pt(11)}px;")
        self._add_tag_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_row.addWidget(self._add_tag_btn)
        self._manage_btn = QPushButton(tr("info.manage_tags"))
        self._manage_btn.clicked.connect(self._open_tag_editor)
        self._manage_btn.setStyleSheet(
            f"background: transparent; color: {t['muted']}; border: 1px solid {t['border']}; "
            f"border-radius: {scaled_px(6)}px; padding: {scaled_px(2)}px {scaled_px(10)}px; font-size: {scaled_pt(11)}px;")
        self._manage_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_row.addWidget(self._manage_btn)
        add_row.addStretch()
        tags_outer.addLayout(add_row)
        details_layout.addWidget(tags_grp)

        # Notes — fills space between Tags and Actions
        notes_grp = QGroupBox(tr("info.notes"))
        t = themes.get()
        notes_grp.setStyleSheet(
            f"QGroupBox {{ border: 1px solid {t['border']}; border-radius: {scaled_px(4)}px; "
            f"margin-top: {scaled_px(4)}px; padding-top: {scaled_px(6)}px; color: {t['heading']}; }} "
            f"QGroupBox::title {{ subcontrol-origin: margin; left: {scaled_px(8)}px; padding: 0 {scaled_px(4)}px; }}")
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
                              f"border-top: 1px solid {t['border']};")
        act_bar.setFixedHeight(scaled_px(28))
        act_layout = QHBoxLayout(act_bar)
        act_layout.setContentsMargins(scaled_px(10), scaled_px(4), scaled_px(10), scaled_px(4))
        act_layout.setSpacing(scaled_px(8))
        act_layout.addStretch()
        self._open_btn = QPushButton(tr("info.open"))
        self._open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_btn.setToolTip(tr("info.open_tooltip"))
        self._open_btn.setStyleSheet(
            f"background: {t['accent']}; color: {t['heading']}; "
            f"border: 1px solid {t['accent']}; border-radius: {scaled_px(4)}px; "
            f"padding: {scaled_px(2)}px {scaled_px(12)}px; font-size: {scaled_pt(12)}px;")
        self._open_btn.clicked.connect(lambda: self.open_requested.emit(self._current_path))
        self._copy_btn = QPushButton(tr("info.copy_path"))
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setToolTip(tr("info.copy_tooltip"))
        self._copy_btn.setStyleSheet(
            f"background: transparent; color: {t['body']}; "
            f"border: 1px solid {t['border']}; border-radius: {scaled_px(4)}px; "
            f"padding: 2px 10px; font-size: {scaled_pt(12)}px;")
        self._copy_btn.clicked.connect(lambda: self.copy_path_requested.emit(self._current_path))
        act_layout.addWidget(self._open_btn)
        act_layout.addWidget(self._copy_btn)
        act_layout.addStretch()

        # ── Initial ────────────────────────────────────────────

        self._splitter.setSizes([160, 400])
        self._splitter.splitterMoved.connect(self._apply_scaled_preview)
        self._show_empty_state()

        # Subscribe to domain events through a Qt bridge for UI-safe delivery.
        from AssetsManager.domain.events import TagsChanged, NotesChanged, UrlsChanged, LibraryOpened
        self._connect_domain_event(LibraryOpened, self._on_library_changed)
        self._connect_domain_event(TagsChanged, self._on_domain_tags_changed)
        self._connect_domain_event(NotesChanged, self._on_domain_notes_changed)
        self._connect_domain_event(UrlsChanged, self._on_domain_urls_changed)

        # Qt-only signals (no domain equivalent)
        self._connect_bus(bus().sidebar_depth_changed, self._on_sidebar_depth_changed)
        self._connect_bus(bus().theme_changed, self._refresh_theme)
        self._connect_bus(bus().language_changed, self._refresh_theme)
        self._connect_bus(bus().ui_scale_changed, self._refresh_theme)
        self._load_sidebar_depth_cfg()

    def _refresh_theme(self, _name: str = ""):
        t = themes.get()
        self._preview_host.setStyleSheet(            "background: transparent;")
        if hasattr(self, '_details_scroll'):
            self._details_scroll.viewport().setStyleSheet(            "background: transparent;")
        for grp, title in [(self._meta_grp, tr("info.title")), (self._tags_grp, tr("info.tags")),
                            (self._notes_grp, tr("info.notes"))]:
            grp.setStyleSheet(
                f"QGroupBox {{ color: {t['heading']}; border: 1px solid {t['border']}; "
                f"border-radius: {scaled_px(6)}px; margin-top: {scaled_px(8)}px; padding-top: {scaled_px(12)}px; }}"
                f"QGroupBox::title {{ subcontrol-origin: margin; left: {scaled_px(10)}px; padding: 0 {scaled_px(5)}px; }}")
        for btn, color in [(self._add_tag_btn, t['muted']), (self._manage_btn, t['muted'])]:
            btn.setStyleSheet(
                f"background: transparent; color: {color}; font-size: {scaled_pt(12)}px; "
                f"border: 1px solid {t['border']}; border-radius: {scaled_px(4)}px; padding: {scaled_px(2)}px {scaled_px(10)}px;")
        self._act_bar.setStyleSheet(
            f"background: transparent; border-top: 1px solid {t['border']}; "
            f"padding: {scaled_px(4)}px {scaled_px(8)}px;")
        self._open_btn.setStyleSheet(
            f"background: {t['accent']}; color: {t['heading']}; font-size: {scaled_pt(13)}px; "
            f"border: 1px solid {t['accent']}; border-radius: {scaled_px(4)}px; padding: {scaled_px(2)}px {scaled_px(12)}px;")
        self._copy_btn.setStyleSheet(
            f"background: transparent; color: {t['body']}; "
            f"border: 1px solid {t['border']}; border-radius: {scaled_px(4)}px; "
            f"padding: {scaled_px(2)}px {scaled_px(10)}px; font-size: {scaled_pt(12)}px;")
        self._name.setStyleSheet(f"color: {t['heading']}; font-size: {scaled_pt(16)}px; font-weight: bold; "
                                  f"background: transparent; border: none; padding: 2px 0;")
        # Update field labels and values
        self._refresh_field_styles()
        # Update link field
        self._refresh_link_field_style()
        # Update plugin fields
        self._refresh_plugin_fields_style()

    def _refresh_field_styles(self):
        """Update all field label/value stylesheets for current theme."""
        t = themes.get()
        label_style = f"color: {t['muted']}; font-size: {scaled_pt(11)}px; min-width: {scaled_px(65)}px;"
        value_style = f"color: {t['body']}; font-size: {scaled_pt(12)}px;"
        for field in self._fields.values():
            if not field or not field.layout():
                continue
            for i in range(field.layout().count()):
                item = field.layout().itemAt(i)
                if item and item.widget():
                    w = item.widget()
                    if isinstance(w, QLabel):
                        if i == 0:  # label
                            w.setStyleSheet(label_style)
                        else:  # value
                            w.setStyleSheet(value_style)

    def _refresh_link_field_style(self):
        """Update link field label/value stylesheets for current theme."""
        t = themes.get()
        row = self._field_link
        if not row or not row.layout():
            return
        for i in range(row.layout().count()):
            item = row.layout().itemAt(i)
            if item and item.widget():
                w = item.widget()
                if isinstance(w, QLabel):
                    if i == 0:  # label
                        w.setStyleSheet(f"color: {t['muted']}; font-size: {scaled_pt(11)}px; min-width: {scaled_px(65)}px;")
                    else:  # value
                        w.setStyleSheet(f"color: {t['body']}; font-size: {scaled_pt(12)}px;")
                elif isinstance(w, _DragLabel):
                    if not w.text() or w.text() == "—":
                        w.setStyleSheet(f"color: {t['body']}; font-size: {scaled_pt(12)}px;")

    def _refresh_plugin_fields_style(self):
        """Update plugin field stylesheets for current theme."""
        t = themes.get()
        if not hasattr(self, '_plugin_fields_widget') or not self._plugin_fields_widget.isVisible():
            return
        for i in range(self._plugin_fields_layout.count()):
            item = self._plugin_fields_layout.itemAt(i)
            if item and item.widget():
                field = item.widget()
                if field.layout():
                    for j in range(field.layout().count()):
                        sub = field.layout().itemAt(j)
                        if sub and sub.widget() and isinstance(sub.widget(), QLabel):
                            if j == 0:
                                sub.widget().setStyleSheet(f"color: {t['muted']}; font-size: {scaled_pt(11)}px; min-width: {scaled_px(65)}px;")
                            else:
                                sub.widget().setStyleSheet(f"color: {t['body']}; font-size: {scaled_pt(12)}px;")

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
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 1, 0, 1)
        lbl = QLabel(label)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl.setStyleSheet(f"color: {themes.get()['muted']}; font-size: {scaled_pt(11)}px; min-width: {scaled_px(65)}px;")
        layout.addWidget(lbl)
        val = QLabel(value)
        val.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        val.setWordWrap(False)
        val.setMinimumSize(0, 0)
        val.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        val.setStyleSheet(f"color: {themes.get()['body']}; font-size: {scaled_pt(12)}px;")
        layout.addWidget(val, 1)
        return row

    @staticmethod
    def _set_field_text(row: QWidget, value: str):
        val_label = row.layout().itemAt(1).widget()
        if isinstance(val_label, QLabel):
            val_label.setText(value)
            val_label.setToolTip(value if value and value != "—" else "")

    @staticmethod
    def _make_link_field() -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 1, 0, 1)
        lbl = QLabel(tr("info.field_link"))
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl.setStyleSheet(f"color: {themes.get()['muted']}; font-size: {scaled_pt(11)}px; min-width: {scaled_px(65)}px;")
        layout.addWidget(lbl)
        link = _DragLabel("—")
        link.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        link.setWordWrap(False)
        link.setMinimumSize(0, 0)
        link.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        link.setOpenExternalLinks(True)
        link.setStyleSheet(f"color: {themes.get()['body']}; font-size: {scaled_pt(12)}px;")
        layout.addWidget(link, 1)
        btn_holder = QWidget()
        btn_holder.setStyleSheet("background: transparent;")
        btn_holder_layout = QHBoxLayout(btn_holder)
        btn_holder_layout.setContentsMargins(0, 0, 0, 0)
        btn_holder_layout.setSpacing(2)
        layout.addWidget(btn_holder)
        return row

    def _set_link_field(self, url: str):
        row = self._field_link
        layout = row.layout()
        link_label = layout.itemAt(1).widget()
        btn_holder = layout.itemAt(2).widget()
        if not isinstance(link_label, _DragLabel) or btn_holder is None:
            return
        # Clear buttons
        while btn_holder.layout().count():
            item = btn_holder.layout().takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        t = themes.get()
        if url:
            short = url[:60] + "…" if len(url) > 60 else url
            link_label.setText(f"<a href='{url}'>{short}</a>")
            link_label.setToolTip(tr("info.drag_to_browser_hint").format(url=url))
            link_label.set_drag_url(url)
            link_label.setCursor(Qt.CursorShape.PointingHandCursor)
            link_label.setStyleSheet(
                f"color: {t['body']}; font-size: {scaled_pt(12)}px; text-decoration: underline;")
            rm_btn = QPushButton("×")
            rm_btn.setToolTip(tr("info.link_remove"))
            rm_btn.setFixedSize(scaled_px(18), scaled_px(18))
            rm_btn.setFlat(True)
            rm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            rm_btn.setStyleSheet(
                f"QPushButton {{ color: {t['muted']}; font-size: {scaled_pt(11)}px; padding: 0; "
                f"background: transparent; border: none; border-radius: {scaled_px(3)}px; }}"
                f"QPushButton:hover {{ color: {t['heading']}; background: {t['accent']}; }}")
            rm_btn.clicked.connect(lambda: self._remove_link(url))
            btn_holder.layout().addWidget(rm_btn)
        else:
            link_label.setText("—")
            link_label.setToolTip("")
            link_label.set_drag_url("")
            link_label.setCursor(Qt.CursorShape.ArrowCursor)
            link_label.setStyleSheet(
                f"color: {t['body']}; font-size: {scaled_pt(12)}px;")
            add_btn = QPushButton("+")
            add_btn.setToolTip(tr("info.link_add"))
            add_btn.setFixedSize(scaled_px(18), scaled_px(18))
            add_btn.setFlat(True)
            add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            add_btn.setStyleSheet(
                f"QPushButton {{ color: {t['muted']}; font-size: {scaled_pt(13)}px; padding: 0; "
                f"background: transparent; border: none; border-radius: {scaled_px(3)}px; }}"
                f"QPushButton:hover {{ color: {t['heading']}; background: {t['accent']}; }}")
            add_btn.clicked.connect(self._add_link_dialog)
            btn_holder.layout().addWidget(add_btn)
            scan_btn = QPushButton("↻")
            scan_btn.setToolTip(tr("info.scanner.desc"))
            scan_btn.setFixedSize(scaled_px(18), scaled_px(18))
            scan_btn.setFlat(True)
            scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            scan_btn.setStyleSheet(
                f"QPushButton {{ color: {t['muted']}; font-size: {scaled_pt(13)}px; padding: 0; "
                f"background: transparent; border: none; border-radius: {scaled_px(3)}px; }}"
                f"QPushButton:hover {{ color: {t['heading']}; background: {t['accent']}; }}")
            scan_btn.clicked.connect(self._manual_scan_links)
            btn_holder.layout().addWidget(scan_btn)

    # ── Panel settings toggle ───────────────────────────────────

    def footer_bar(self):
        return self._act_bar

    def title_bar_buttons(self) -> list:
        """Return extra buttons for the dock title bar."""
        t = themes.get()
        gear = QPushButton("⚙")
        gear.setToolTip(tr("panel.settings"))
        gear.setFixedSize(scaled_px(20), scaled_px(20))
        gear.setFlat(True)
        gear.setStyleSheet(
            f"color: {t['heading']}; font-size: {scaled_pt(13)}px; font-weight: bold; "
            f"padding: 0; background: transparent; border: none; border-radius: {scaled_px(3)}px;")
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
        if btn and hasattr(btn, 'rect'):
            menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
        else:
            menu.exec(self.cursor().pos())

    def _clear_preview(self):
        self._preview_pixmap = None
        self._preview.clear()
        self._preview.setStyleSheet("")

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
        self._clear_preview()
        self._preview.setText(tr("info.no_file_selected"))
        self._preview.setStyleSheet(f"color: {themes.get()['muted']}; font-size: {scaled_pt(32)}px;")

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

    def _classify_dir(self, dir_path: str) -> str:
        if self._controller is not None:
            if not hasattr(self, '_classify_cache'):
                self._classify_cache = LRUCache(500)
            return self._controller.classify_dir(dir_path, classify_cache=self._classify_cache)
        return ""

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
        from PySide6.QtCore import QRunnable, QThreadPool, Signal, QObject
        class _SizeSignals(QObject):
            done = Signal(object, object)
        signals = _SizeSignals()
        signals.done.connect(self._on_async_dir_size_done)
        project = self._project
        session = request.session
        dir_path = request.path
        class _SizeTask(QRunnable):
            def __init__(task_self):
                super().__init__()
                task_self.setAutoDelete(False)
            def run(task_self):
                sz = 0
                try:
                    if project and session:
                        with session.operation():
                            sz, _ = project.get_dir_size(dir_path)
                    else:
                        from AssetsManager.core.project_data import ProjectData
                        sz = ProjectData.compute_dir_size(dir_path)
                except Exception:
                    sz = 0
                signals.done.emit(request, sz)
        pool = QThreadPool.globalInstance()
        pool.start(_SizeTask())

    def _on_async_dir_size_done(self, request: _AsyncRequest, size: int):
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
        for w in self._tags_widgets:
            self._tags_flow_layout.removeWidget(w)
            w.deleteLater()
        self._tags_widgets.clear()

    def _make_tag_chip(self, tag: str) -> QWidget:
        return create_tag_chip(tag, on_remove=self._remove_tag)

    def _render_tags(self, tags: list[str]):
        self._clear_tags()
        for i, tag in enumerate(tags):
            chip = self._make_tag_chip(tag)
            self._tags_widgets.append(chip)
            self._tags_flow_layout.addWidget(chip)
            # Staggered fade-in animation
            self._animate_tag_in(chip, delay=i * 50)

    def _animate_tag_in(self, chip, delay=0):
        """Animate tag chip entrance with fade-in."""
        chip.setWindowOpacity(0.0)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(delay, lambda: self._do_fade_in(chip))

    def _do_fade_in(self, chip):
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
            new_tags = self._controller.add_tag(self._current_path, tag.strip())
            self._render_tags(new_tags)

    def _open_tag_editor(self):
        if not self._current_path or not os.path.exists(self._current_path) or not self._controller:
            return
        from AssetsManager.application.tag_service import TagServiceAdapter
        from AssetsManager.dialogs.tag_editor_dialog import TagEditorDialog
        scoped = self._scoped_services
        if scoped is None:
            return
        adapter = TagServiceAdapter(self._library_root, scoped.tag_service)
        dlg = TagEditorDialog(adapter, self._current_path, self)
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.was_modified():
            new_tags = self._controller.get_tags(self._current_path)
            self._render_tags(new_tags)

    def _remove_tag(self, tag: str):
        if not self._current_path or not self._controller:
            return
        new_tags = self._controller.remove_tag(self._current_path, tag)
        self._render_tags(new_tags)

    def _on_domain_tags_changed(self, event):
        """Handle TagsChanged from EventBus (application layer)."""
        if not self._current_path or not self._controller:
            return
        new_tags = self._controller.get_tags(self._current_path)
        self._render_tags(new_tags)

    def _on_domain_notes_changed(self, event):
        """Handle NotesChanged from EventBus."""
        if not self._current_path or not self._controller:
            return
        if hasattr(event, 'file_path') and event.file_path == self._current_path:
            notes = self._controller.get_notes(self._current_path)
            if hasattr(self, '_notes') and self._notes:
                self._notes.blockSignals(True)
                self._notes.setPlainText(notes)
                self._notes.blockSignals(False)

    def _on_domain_urls_changed(self, event):
        """Handle UrlsChanged from EventBus."""
        if not self._current_path or not self._controller:
            return
        if hasattr(event, 'file_path') and event.file_path == self._current_path:
            urls = self._controller.get_urls(self._current_path)
            self._set_link_field(urls[0] if urls else "")

    def _on_library_changed(self, event):
        """Handle LibraryOpened domain event — reset state; services already injected."""
        path = event.library_root
        self._library_root = os.path.normpath(path)
        self._current_path = ""
        self._urls_scanned.clear()
        self._invalidate_async_requests()
        if hasattr(self, '_classify_cache'):
            self._classify_cache.clear()
        scoped = self._scoped_services
        if (
            scoped is not None
            and not scoped.session.is_closed
            and scoped.session.root_str == self._library_root
        ):
            session = self._scoped_services.session
            self._store = session.tag_store
            self._project = session.project_data
            if self._controller is None:
                from AssetsManager.controllers.info_controller import InfoController
                self._controller = InfoController(
                    self._library_root,
                    session.db_conn,
                    metadata_svc=self._scoped_services.metadata_service,
                    tag_svc=self._scoped_services.tag_service,
                )
        else:
            self._store = None
            self._project = None
            self._controller = None
        _log.debug("Library changed: root=%s store=%s project=%s",
                   self._library_root, bool(self._store), bool(self._project))

    def set_scoped_services(self, services):
        """Bind library-scoped services resolved by MainWindow."""
        from AssetsManager.controllers.info_controller import InfoController

        self._scoped_services = services
        self._library_root = services.session.root_str
        self._current_path = ""
        self._urls_scanned.clear()
        self._invalidate_async_requests()
        if hasattr(self, '_classify_cache'):
            self._classify_cache.clear()
        self._store = services.session.tag_store
        self._project = services.session.project_data
        self._controller = InfoController(
            self._library_root,
            services.session.db_conn,
            metadata_svc=services.metadata_service,
            tag_svc=services.tag_service,
        )

    def _resolve_store(self):
        if self._scoped_services is not None:
            return self._scoped_services.session.tag_store
        return None

    def _resolve_project(self):
        if self._scoped_services is not None:
            return self._scoped_services.session.project_data
        return None

    def _ensure_store(self):
        if self._store is None and self._library_root:
            self._store = self._resolve_store()

    def _ensure_project(self):
        if self._project is None and self._library_root:
            self._project = self._resolve_project()

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
            urls = self._controller.get_urls(self._current_path)
            self._set_link_field(urls[0] if urls else "")

    def _remove_link(self, url: str):
        if not self._current_path or not self._controller:
            return
        self._controller.remove_url(self._current_path, url)
        urls = self._controller.get_urls(self._current_path)
        self._set_link_field(urls[0] if urls else "")

    def _manual_scan_links(self):
        if not self._current_path or not os.path.isdir(self._current_path) or not self._controller:
            return
        discovered = self._controller.discover_urls_in_dir(self._current_path)

        from PySide6.QtWidgets import QMessageBox
        info_lines = [
            f"Path: {self._current_path}",
            f"Library root: {self._library_root}",
            f"Sidebar depth: {self._sidebar_depth}, branch_depths: {self._branch_depths}",
            f"is_deepest: {self._is_deepest_folder(self._current_path)}",
            f"URLs in DB: {self._controller.get_urls(self._current_path)}",
            "",
            f"Scan found {len(discovered)} URL(s):",
        ]
        for u in discovered[:20]:
            info_lines.append(f"  {u}")
        if len(discovered) > 20:
            info_lines.append(f"  ... ({len(discovered)} total)")
        QMessageBox.information(self, tr("info.scanner.title"), "\n".join(info_lines))
        if discovered:
            for u in discovered:
                try:
                    self._controller.add_url(self._current_path, u)
                except ValueError:
                    pass
            urls = self._controller.get_urls(self._current_path)
            self._set_link_field(urls[0] if urls else "")

    def _schedule_notes_save(self):
        from PySide6.QtCore import QTimer
        if self._notes_timer is None:
            self._notes_timer = QTimer(self)
            self._notes_timer.setSingleShot(True)
            self._notes_timer.timeout.connect(self._flush_notes_save)
        self._notes_timer.start(1000)

    def _flush_notes_save(self):
        if self._current_path and os.path.exists(self._current_path) and self._controller:
            self._controller.save_notes(self._current_path, self._notes.toPlainText())

    # ── Main update ────────────────────────────────────────────

    def update_info(self, info):
        from PySide6.QtCore import QFileInfo
        self._ensure_store()
        self._ensure_project()
        if not self._store or not self._project:
            _log.debug("update_info skipped: store=%s project=%s lib_root=%s",
                       bool(self._store), bool(self._project), repr(self._library_root))
            return
        if isinstance(info, QFileInfo):
            fi = info
        else:
            fi = QFileInfo(str(info))

        self._flush_notes_save()

        self._current_path = fi.absoluteFilePath()
        request = self._new_async_request(self._current_path)
        is_dir = fi.isDir()

        # Mark as scanned for URL discovery (async task does the actual work)
        if is_dir and self._controller and self._is_deepest_folder(self._current_path):
            self._urls_scanned.add(self._current_path)

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
        self._clear_preview()
        self._preview.setText("...")
        self._preview.setStyleSheet(f"color: {themes.get()['muted']}; font-size: {scaled_pt(24)}px;")

        # Cancel previous pending task (stale detection handles in-flight results)
        self._pending_task = None

        if not self._controller:
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
        self._pending_task = task
        QThreadPool.globalInstance().start(task)

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
        if not self._is_current_async_request(request) or file_info.path != request.path:
            return
        self._render_file_info(request, file_info)

    def _on_preview_ready(self, request, pixmap):
        """Called on main thread when async preview load completes."""
        if not self._is_current_async_request(request):
            return
        if pixmap:
            self._preview_pixmap = pixmap
            self._apply_scaled_preview()
        else:
            self._show_preview_fallback()

    def _show_preview_fallback(self):
        """Show emoji hint when no preview image is available."""
        suffix = Path(self._current_path).suffix.lower()
        is_dir = os.path.isdir(self._current_path)
        hints = {
            "png": "🖼", "jpg": "🖼", "jpeg": "🖼", "gif": "🖼", "bmp": "🖼",
            "webp": "🖼", "svg": "🖼",
            "blend": "🧊", "fbx": "🧊", "obj": "🧊", "gltf": "🧊", "glb": "🧊",
            "mp4": "🎬", "mov": "🎬", "avi": "🎬", "mkv": "🎬", "webm": "🎬",
            "txt": "📄", "json": "📄", "py": "📄", "md": "📄", "xml": "📄",
            "zip": "🗜", "rar": "🗜", "7z": "🗜", "tar": "🗜", "gz": "🗜",
        }
        muted = themes.get()['muted']
        self._preview.setText(hints.get(suffix, "📄" if not is_dir else "📁"))
        self._preview.setStyleSheet(f"color: {muted}; font-size: {scaled_pt(40)}px;")

    def _render_plugin_fields(self, plugin_fields):
        """Render plugin-contributed metadata fields from FileInfo."""
        while self._plugin_fields_layout.count():
            item = self._plugin_fields_layout.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.deleteLater()

        try:
            for field in plugin_fields:
                self._plugin_fields_layout.addWidget(
                    self._make_field(field.key.capitalize(), str(field.value))
                )
            self._plugin_fields_widget.setVisible(self._plugin_fields_layout.count() > 0)
        except Exception:
            _log.exception("Plugin field rendering failed")
            self._plugin_fields_widget.setVisible(False)

    def clone(self):
        return InfoPanel()

    def shutdown(self):
        self._flush_notes_save()
        if self._notes_timer:
            self._notes_timer.stop()
        self._invalidate_async_requests()
        super().shutdown()

    def closeEvent(self, event):
        self._flush_notes_save()
        if self._notes_timer:
            self._notes_timer.stop()
        super().closeEvent(event)
