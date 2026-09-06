"""QuickLookOverlay — frameless, centered media and asset previewer.

Provides a seamless, desktop-native QuickLook preview overlay aligned with WebUI
QuickLookOverlay experience. Activated via Space bar in file lists or explicitly.
The dimmed backdrop is the shell's ``SCRIM_WORKSPACE`` variant — a translucent
fill of the theme ``base`` color at alpha 172 (unified from the historical 175;
see ``OverlayShell``; no blur sampling — see ``paintEvent``); the centered
preview card itself is opaque. Complies with Design System 2.0 (token-based
styling, scale-aware metrics).
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import (
    QGuiApplication,
    QImageReader,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from AssetsManager import i18n
from AssetsManager.core import icons, themes
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.constants import IMAGE_EXTS, VIDEO_EXTS
from AssetsManager.core.format_utils import format_size
from AssetsManager.core.ui_scale import scaled_pt, scaled_px
from AssetsManager.domain.asset import category_for_extension
from AssetsManager.widgets.elevation import apply_elevation, refresh_elevation
from AssetsManager.widgets.overlay_shell import OverlayShell

if TYPE_CHECKING:
    from PySide6.QtGui import QKeyEvent, QPaintEvent, QResizeEvent

tr = i18n.tr


class ImageCanvasWidget(QWidget):
    """High-quality antialiased smooth-scaling image preview canvas."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        if not self._pixmap or self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        canvas_rect = self.rect()
        if canvas_rect.isEmpty():
            return
        target_size = self._pixmap.size().scaled(
            canvas_rect.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        x = canvas_rect.x() + (canvas_rect.width() - target_size.width()) // 2
        y = canvas_rect.y() + (canvas_rect.height() - target_size.height()) // 2
        target_rect = QRect(x, y, target_size.width(), target_size.height())
        painter.drawPixmap(target_rect, self._pixmap)


class GenericFileWidget(QWidget):
    """Fallback canvas for non-image multimedia or generic files."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(
            scaled_px(24), scaled_px(24), scaled_px(24), scaled_px(24)
        )
        layout.setSpacing(scaled_px(10))

        self._icon_label = QLabel()
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon_label)

        self._name_label = QLabel()
        self._name_label.setObjectName("quickLookTitle")
        self._name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name_label.setWordWrap(True)
        layout.addWidget(self._name_label)

        self._path_label = QLabel()
        self._path_label.setObjectName("quickLookFooterText")
        self._path_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._path_label.setWordWrap(True)
        layout.addWidget(self._path_label)

        self._meta_label = QLabel()
        self._meta_label.setObjectName("quickLookIndex")
        self._meta_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._meta_label)

        self._hint_key = "quicklook.enter_hint"
        self._hint_default = "按 Enter 使用系统默认程序打开此文件"
        self._hint_label = QLabel(tr(self._hint_key, default=self._hint_default))
        self._hint_label.setObjectName("quickLookFooterText")
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._hint_label)

        self._layout = layout

    def retranslate(self) -> None:
        """Runtime language refresh for the static hint (stage E).  The hint
        key is stored at construction so refresh_overlay_chrome can reach it
        without rebuilding the canvas."""
        self._hint_label.setText(tr(self._hint_key, default=self._hint_default))

    def apply_scaled_metrics(self) -> None:
        """Re-derive the layout margins/spacing from the current ui_scale
        (stage E: the overlay-level rescale previously stopped at the card)."""
        self._layout.setContentsMargins(
            scaled_px(24), scaled_px(24), scaled_px(24), scaled_px(24)
        )
        self._layout.setSpacing(scaled_px(10))

    def set_file_info(
        self,
        name: str,
        path: str,
        icon_name: str,
        size_fmt: str,
        ext_badge: str,
    ) -> None:
        icon_size = scaled_px(48)
        pix = icons.icon(icon_name, color="accent", size=icon_size).pixmap(
            QSize(icon_size, icon_size)
        )
        self._icon_label.setPixmap(pix)
        self._name_label.setText(name)
        self._path_label.setText(path)
        meta_text = f"{ext_badge} · {size_fmt}" if size_fmt else ext_badge
        self._meta_label.setText(meta_text)


class CanvasContainer(QWidget):
    """Container widget for preview canvases with overlaid navigation buttons."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("quickLookCanvasArea")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.prev_btn: QPushButton | None = None
        self.next_btn: QPushButton | None = None

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        pad = scaled_px(16)
        if self.prev_btn:
            btn_w = self.prev_btn.width()
            btn_h = self.prev_btn.height()
            self.prev_btn.move(pad, (self.height() - btn_h) // 2)
            self.prev_btn.raise_()
        if self.next_btn:
            btn_w = self.next_btn.width()
            btn_h = self.next_btn.height()
            self.next_btn.move(self.width() - btn_w - pad, (self.height() - btn_h) // 2)
            self.next_btn.raise_()


class QuickLookOverlay(OverlayShell):
    """Frameless, centered modal dialog for instant file inspection.

    V05: shell-backed — the ``SCRIM_WORKSPACE`` backdrop, refresh-bus
    subscription, screen constraining, and focus return live in OverlayShell.
    """

    def __init__(
        self,
        file_paths: list[str],
        current_index: int = 0,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._file_paths: list[str] = [p for p in file_paths if p]
        self._current_index: int = 0
        if self._file_paths:
            self._current_index = max(0, min(current_index, len(self._file_paths) - 1))

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._build_ui()
        self._apply_styles()
        self._update_display()

    def closeEvent(self, event) -> None:
        # V16: the panel keeps a write-only reference to this overlay and
        # never clears it, so a dismissed QuickLook would otherwise hold its
        # decoded full-resolution pixmap (a 48 MP frame is ~190 MB) until the
        # next open replaces the canvas. Release the big state here; the
        # widget shell stays alive (tests and the panel touch it after
        # close), only the pixels go.
        self._image_canvas.set_pixmap(None)
        self._file_paths = []
        super().closeEvent(event)

    @property
    def current_index(self) -> int:
        """Current zero-based index of viewed file."""
        return self._current_index

    @property
    def total_count(self) -> int:
        """Total number of files in the current view set."""
        return len(self._file_paths)

    @property
    def current_path(self) -> str | None:
        """Path of the currently displayed file."""
        if 0 <= self._current_index < len(self._file_paths):
            return self._file_paths[self._current_index]
        return None

    def set_index(self, index: int) -> None:
        """Switch to viewing file at index."""
        if not self._file_paths:
            return
        new_index = max(0, min(index, len(self._file_paths) - 1))
        if new_index != self._current_index:
            self._current_index = new_index
            self._update_display()

    def next_item(self) -> None:
        """Advance to next file, wrapping around."""
        if self.total_count > 1:
            self.set_index((self._current_index + 1) % self.total_count)

    def prev_item(self) -> None:
        """Return to previous file, wrapping around."""
        if self.total_count > 1:
            self.set_index((self._current_index - 1 + self.total_count) % self.total_count)

    def _open_in_default_app(self) -> bool:
        """Open the current file using the system default application."""
        path = self.current_path
        if not path or not os.path.exists(path):
            return False
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        return QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _build_ui(self) -> None:
        self._card = QFrame(self)
        self._card.setObjectName("quickLookCard")
        apply_elevation(self._card, level=3)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # ── 1. Top Header Bar ─────────────────────────────────────
        self._header_widget = QWidget(self._card)
        self._header_widget.setObjectName("quickLookHeader")
        self._header_layout = QHBoxLayout(self._header_widget)
        header_layout = self._header_layout
        header_layout.setContentsMargins(
            scaled_px(16), scaled_px(10), scaled_px(16), scaled_px(10)
        )
        header_layout.setSpacing(scaled_px(10))

        self._header_icon = QLabel()
        self._header_icon.setFixedSize(
            scaled_px(themes.metrics("icon_sm")), scaled_px(themes.metrics("icon_sm"))
        )
        self._header_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self._header_icon)

        self._title_label = QLabel()
        self._title_label.setObjectName("quickLookTitle")
        self._title_label.setMaximumWidth(scaled_px(420))
        header_layout.addWidget(self._title_label)
        self._title_label_max_width = scaled_px(420)

        self._spec_pill = QLabel()
        self._spec_pill.setObjectName("quickLookSpecPill")
        header_layout.addWidget(self._spec_pill)

        header_layout.addStretch(1)

        self._index_label = QLabel()
        self._index_label.setObjectName("quickLookIndex")
        header_layout.addWidget(self._index_label)

        hit_area = scaled_px(themes.metrics("hit_area"))
        icon_sm = scaled_px(themes.metrics("icon_sm"))
        self._close_btn = QPushButton(self._header_widget)
        self._close_btn.setObjectName("quickLookCloseBtn")
        self._close_btn.setFixedSize(hit_area, hit_area)
        self._close_btn.setIcon(icons.icon("close", color="icon_primary", size=icon_sm))
        self._close_btn.setIconSize(QSize(icon_sm, icon_sm))
        themes.set_button_variant(self._close_btn, "ghost")
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setToolTip("Space / Esc")
        self._close_btn.clicked.connect(self.close)
        header_layout.addWidget(self._close_btn)

        card_layout.addWidget(self._header_widget, 0)

        # ── 2. Center Preview Canvas ──────────────────────────────
        self._canvas_container = CanvasContainer(self._card)
        container_layout = QVBoxLayout(self._canvas_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        self._stack = QStackedWidget(self._canvas_container)
        self._image_canvas = ImageCanvasWidget(self._stack)
        self._generic_canvas = GenericFileWidget(self._stack)
        self._stack.addWidget(self._image_canvas)
        self._stack.addWidget(self._generic_canvas)
        container_layout.addWidget(self._stack)

        # Floating Left / Right navigation buttons
        nav_btn_size = scaled_px(36)
        nav_icon_size = scaled_px(20)

        self._prev_btn = QPushButton(self._canvas_container)
        self._prev_btn.setObjectName("quickLookNavBtn")
        self._prev_btn.setFixedSize(nav_btn_size, nav_btn_size)
        self._prev_btn.setIcon(
            icons.icon("arrow_left", color="icon_primary", size=nav_icon_size)
        )
        self._prev_btn.setIconSize(QSize(nav_icon_size, nav_icon_size))
        self._prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prev_btn.setToolTip("←")
        self._prev_btn.clicked.connect(self.prev_item)

        self._next_btn = QPushButton(self._canvas_container)
        self._next_btn.setObjectName("quickLookNavBtn")
        self._next_btn.setFixedSize(nav_btn_size, nav_btn_size)
        self._next_btn.setIcon(
            icons.icon("arrow_right", color="icon_primary", size=nav_icon_size)
        )
        self._next_btn.setIconSize(QSize(nav_icon_size, nav_icon_size))
        self._next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next_btn.setToolTip("→")
        self._next_btn.clicked.connect(self.next_item)

        self._canvas_container.prev_btn = self._prev_btn
        self._canvas_container.next_btn = self._next_btn

        card_layout.addWidget(self._canvas_container, 1)

        # ── 3. Bottom Keyboard Shortcuts Guide Bar ────────────────
        self._footer_widget = QWidget(self._card)
        self._footer_widget.setObjectName("quickLookFooter")
        self._footer_layout = QHBoxLayout(self._footer_widget)
        footer_layout = self._footer_layout
        footer_layout.setContentsMargins(
            scaled_px(16), scaled_px(8), scaled_px(16), scaled_px(8)
        )
        footer_layout.setSpacing(scaled_px(8))
        footer_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        def _make_kbd(label: str) -> QLabel:
            k = QLabel(label)
            k.setObjectName("quickLookKbd")
            k.setAlignment(Qt.AlignmentFlag.AlignCenter)
            return k

        def _make_text(label: str) -> QLabel:
            t = QLabel(label)
            t.setObjectName("quickLookFooterText")
            return t

        footer_layout.addWidget(_make_kbd("Space"))
        footer_layout.addWidget(_make_text("/"))
        footer_layout.addWidget(_make_kbd("Esc"))
        # Refs kept for the V05 language refresh hook (label, i18n key, default).
        self._footer_texts: list[tuple[QLabel, str, str]] = []

        def _make_tr_text(key: str, default: str) -> QLabel:
            label = _make_text(tr(key, default=default))
            self._footer_texts.append((label, key, default))
            return label

        footer_layout.addWidget(_make_tr_text("quicklook.footer_close", "关闭"))
        footer_layout.addWidget(_make_text(" · "))
        footer_layout.addWidget(_make_kbd("←"))
        footer_layout.addWidget(_make_kbd("→"))
        footer_layout.addWidget(_make_tr_text("quicklook.footer_slice", "切片"))
        footer_layout.addWidget(_make_text(" · "))
        footer_layout.addWidget(_make_kbd("Enter"))
        footer_layout.addWidget(_make_tr_text("quicklook.footer_open", "系统默认打开"))

        card_layout.addWidget(self._footer_widget, 0)

    def _apply_styles(self) -> None:
        card_bg = alpha(themes.color("panel"), 0.96)
        header_bg = alpha(themes.color("panel"), 0.60)
        footer_bg = alpha(themes.color("panel"), 0.60)
        canvas_bg = alpha(themes.color("base"), 0.50)

        card_border = alpha(themes.color("on_accent"), 0.12)
        card_border_hover = alpha(themes.color("on_accent"), 0.28)
        border_width = scaled_px(1)

        radius_lg = scaled_px(int(themes.prop("border_radius", "lg")))
        radius_xs = scaled_px(int(themes.metrics("radius_xs")))

        pill_bg = alpha(themes.color("accent"), 0.15)
        pill_border = alpha(themes.color("accent"), 0.30)
        kbd_bg = alpha(themes.color("on_accent"), 0.10)

        color_heading = themes.color("heading")
        color_accent = themes.color("accent")
        color_muted = themes.color("muted")

        nav_btn_bg = alpha(themes.color("panel"), 0.80)
        nav_btn_hover_bg = alpha(themes.color("panel"), 0.95)
        nav_btn_radius = scaled_px(18)

        pad_y_xs = scaled_px(2)
        pad_x_xs = scaled_px(6)
        pad_y_xxs = scaled_px(1)

        fs_md = scaled_pt(int(themes.font_size("md")))
        fs_sm = scaled_pt(int(themes.font_size("sm")))
        fs_xs = scaled_pt(int(themes.font_size("xs")))

        self.setStyleSheet(
            f"""
            #quickLookCard {{
                background: {card_bg};
                border: {border_width}px solid {card_border};
                border-radius: {radius_lg}px;
            }}
            #quickLookHeader {{
                background: {header_bg};
                border-bottom: {border_width}px solid {card_border};
                border-top-left-radius: {radius_lg}px;
                border-top-right-radius: {radius_lg}px;
            }}
            #quickLookFooter {{
                background: {footer_bg};
                border-top: {border_width}px solid {card_border};
                border-bottom-left-radius: {radius_lg}px;
                border-bottom-right-radius: {radius_lg}px;
            }}
            #quickLookCanvasArea {{
                background: {canvas_bg};
            }}
            #quickLookTitle {{
                color: {color_heading};
                font-size: {fs_md}px;
                font-weight: bold;
            }}
            #quickLookSpecPill {{
                background: {pill_bg};
                color: {color_accent};
                border: {border_width}px solid {pill_border};
                border-radius: {radius_xs}px;
                padding: {pad_y_xs}px {pad_x_xs}px;
                font-size: {fs_xs}px;
                font-family: monospace;
                font-weight: bold;
            }}
            #quickLookIndex {{
                color: {color_muted};
                font-size: {fs_sm}px;
                font-family: monospace;
            }}
            #quickLookNavBtn {{
                background: {nav_btn_bg};
                border: {border_width}px solid {card_border};
                border-radius: {nav_btn_radius}px;
            }}
            #quickLookNavBtn:hover {{
                background: {nav_btn_hover_bg};
                border-color: {card_border_hover};
            }}
            #quickLookKbd {{
                background: {kbd_bg};
                color: {color_heading};
                border-radius: {radius_xs}px;
                padding: {pad_y_xxs}px {pad_x_xs}px;
                font-size: {fs_xs}px;
                font-family: monospace;
            }}
            #quickLookFooterText {{
                color: {color_muted};
                font-size: {fs_sm}px;
            }}
            """
        )

    def _update_display(self) -> None:
        path = self.current_path
        if not path:
            self._title_label.setText("")
            self._spec_pill.setText("")
            self._index_label.setText("0 / 0")
            self._prev_btn.setVisible(False)
            self._next_btn.setVisible(False)
            return

        name = os.path.basename(path)
        ext = os.path.splitext(path)[1].lower()
        ext_upper = ext.lstrip(".").upper() if ext else "FILE"

        size_fmt = ""
        try:
            size_fmt = format_size(os.path.getsize(path))
        except OSError:
            pass

        icon_sm = scaled_px(themes.metrics("icon_sm"))

        is_img = ext in IMAGE_EXTS
        image_loaded = False

        if is_img:
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            image = reader.read()
            if not image.isNull():
                image_loaded = True
                pix = QPixmap.fromImage(image)
                self._image_canvas.set_pixmap(pix)
                self._stack.setCurrentWidget(self._image_canvas)
                dim_str = f"{image.width()}×{image.height()}"
                spec_str = (
                    f"{dim_str} · {ext_upper} · {size_fmt}"
                    if size_fmt
                    else f"{dim_str} · {ext_upper}"
                )
                self._spec_pill.setText(spec_str)
                self._header_icon.setPixmap(
                    icons.icon("image", color="icon_primary", size=icon_sm).pixmap(
                        QSize(icon_sm, icon_sm)
                    )
                )

        if not image_loaded:
            cat = category_for_extension(ext)
            if cat == "videos" or ext in VIDEO_EXTS:
                icon_name = "video"
            elif cat == "3d":
                icon_name = "cube"
            elif cat == "archives":
                icon_name = "archive"
            elif cat == "documents":
                icon_name = (
                    "code"
                    if ext in {".py", ".json", ".js", ".ts", ".html", ".css", ".md"}
                    else "file"
                )
            else:
                icon_name = "file"

            self._generic_canvas.set_file_info(
                name=name,
                path=path,
                icon_name=icon_name,
                size_fmt=size_fmt,
                ext_badge=ext_upper,
            )
            self._stack.setCurrentWidget(self._generic_canvas)
            spec_str = f"{ext_upper} · {size_fmt}" if size_fmt else ext_upper
            self._spec_pill.setText(spec_str)
            self._header_icon.setPixmap(
                icons.icon(icon_name, color="icon_primary", size=icon_sm).pixmap(
                    QSize(icon_sm, icon_sm)
                )
            )

        self._title_label.setText(name)
        self._title_label.setToolTip(name)
        self._index_label.setText(f"{self._current_index + 1} / {self.total_count}")
        self.setAccessibleName(f"QuickLook: {name}")

        has_multiple = self.total_count > 1
        self._prev_btn.setVisible(has_multiple)
        self._next_btn.setVisible(has_multiple)

    # paintEvent (dimming backdrop) is inherited from OverlayShell: the
    # SCRIM_WORKSPACE variant paints theme base @ alpha 172 — unified from
    # this overlay's historical alpha 175 (expected V05 micro-change).

    def _apply_scaled_metrics(self) -> None:
        """Re-derive the fixed control sizes AND layout margins/spacing from
        the current ui_scale; also the ui_scale_changed half of the V05
        refresh hook (stage E adds the margin/spacing re-derivation)."""
        hit_area = scaled_px(themes.metrics("hit_area"))
        icon_sm = scaled_px(themes.metrics("icon_sm"))
        self._close_btn.setFixedSize(hit_area, hit_area)
        self._close_btn.setIconSize(QSize(icon_sm, icon_sm))
        # Header/footer bar margins + spacing (stage E: previously frozen at
        # the construction-time scale).
        self._header_layout.setContentsMargins(
            scaled_px(16), scaled_px(10), scaled_px(16), scaled_px(10)
        )
        self._header_layout.setSpacing(scaled_px(10))
        self._title_label_max_width = scaled_px(420)
        self._title_label.setMaximumWidth(self._title_label_max_width)
        self._footer_layout.setContentsMargins(
            scaled_px(16), scaled_px(8), scaled_px(16), scaled_px(8)
        )
        self._footer_layout.setSpacing(scaled_px(8))
        # Generic canvas margins follow the same rescale; the hint label is
        # retranslated separately (retranslate).
        self._generic_canvas.apply_scaled_metrics()
        nav_btn_size = scaled_px(36)
        nav_icon_size = scaled_px(20)
        for btn in (self._prev_btn, self._next_btn):
            btn.setFixedSize(nav_btn_size, nav_btn_size)
            btn.setIconSize(QSize(nav_icon_size, nav_icon_size))
        refresh_elevation(self._card, level=3)

    def refresh_overlay_chrome(self) -> None:
        """OverlayShell hook (V05/stage E): restyle QSS, retranslate footer
        text and the generic-file hint, and re-scale fixed sizes without
        rebuilding the overlay."""
        self._apply_styles()
        self._apply_scaled_metrics()
        for label, key, default in self._footer_texts:
            label.setText(tr(key, default=default))
        self._generic_canvas.retranslate()
        self._update_display()

    def mousePressEvent(self, event) -> None:
        if not self._card.geometry().contains(event.pos()):
            self.close()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Space, Qt.Key.Key_Escape):
            self.close()
            event.accept()
            return
        if key == Qt.Key.Key_Left:
            self.prev_item()
            event.accept()
            return
        if key == Qt.Key.Key_Right:
            self.next_item()
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._open_in_default_app()
            event.accept()
            return
        super().keyPressEvent(event)

    def _position_overlay(self) -> None:
        # Previous showEvent body: fill the parent window, or fall back to
        # the primary screen's availableGeometry; the shell constrains the
        # result to the screen afterwards.
        parent_widget = self.parentWidget()
        parent_win = parent_widget.window() if parent_widget else None
        if parent_win and parent_win.isVisible():
            top_left = parent_win.mapToGlobal(QPoint(0, 0))
            self.setGeometry(QRect(top_left, parent_win.size()))
        elif not self.geometry().isValid() or self.width() <= 100:
            screen = QGuiApplication.primaryScreen()
            if screen:
                self.setGeometry(screen.availableGeometry())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        pad = scaled_px(32)
        target_w = max(scaled_px(480), min(int(self.width() * 0.88), scaled_px(1100)))
        target_h = max(scaled_px(360), min(int(self.height() * 0.88), scaled_px(850)))
        card_w = min(target_w, max(scaled_px(200), self.width() - pad))
        card_h = min(target_h, max(scaled_px(150), self.height() - pad))
        self._card.resize(card_w, card_h)
        self._card.move((self.width() - card_w) // 2, (self.height() - card_h) // 2)
