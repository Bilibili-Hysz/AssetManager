"""ImageViewerOverlay — GPU-accelerated image viewer with modern UX.

Features:
  - QGraphicsView + QOpenGLWidget viewport (GPU rendering)
  - Custom-painted chrome (header, footer, backdrop)
  - Smooth wheel zoom anchored under cursor
  - Fit-to-window / Actual-size shortcuts
  - Prev/Next image navigation with keyboard
  - Slideshow auto-advance (Space)
  - Rotate 90° (R / Shift+R)
  - Copy to clipboard (Ctrl+C)
  - Save As (Ctrl+S)
  - EXIF overlay (I)
  - Thumbnail strip (T)
  - Theme-aware styling
  - Cursor feedback (grab/grabbing via QGraphicsView default)
"""
import logging
import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QRectF, QRect, QTimer, QSize
from PySide6.QtGui import (
    QPixmap, QColor, QPainter, QPen, QFont,
    QImageReader, QTransform,
)
from PySide6.QtWidgets import (
    QFrame, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QApplication, QFileDialog,
)

from AssetsManager.core import icons, themes
from AssetsManager.core.constants import IMAGE_EXTS
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager import i18n
tr = i18n.tr

_log = logging.getLogger(__name__)

# Downsampling cap for full-size decoding. Images larger than this are
# pre-scaled by QImageReader before the pixel decode runs on the UI thread,
# bounding the worst-case decode time. 2048px comfortably exceeds typical
# viewer window sizes while keeping memory and CPU cost small.
MAX_DIM = 2048


class _GraphicsView(QGraphicsView):
    """QGraphicsView with GPU viewport and wheel zoom."""

    zoom_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        try:
            from PySide6.QtOpenGLWidgets import QOpenGLWidget
            self.setViewport(QOpenGLWidget(self))
        except ImportError:
            # GL widget unavailable (headless / restricted environments):
            # fall back to the default raster viewport. Rendering stays
            # correct, only GPU acceleration is lost.
            _log.warning(
                "QOpenGLWidget unavailable; image viewer falls back to a raster viewport")

    def wheelEvent(self, event):
        d = event.angleDelta().y()
        factor = 1.12 if d > 0 else 1.0 / 1.12
        # Clamp the resulting scale factor to [0.05, 64.0] so repeated wheel
        # zooms cannot overflow/underflow the transform.
        cur = self.transform().m11()
        factor = min(max(factor, 0.05 / cur), 64.0 / cur)
        self.scale(factor, factor)
        self.zoom_changed.emit(self.transform().m11())

    def fit_in_view(self):
        if not self.scene() or self.scene().itemsBoundingRect().isEmpty():
            return
        super().fitInView(self.scene().itemsBoundingRect(),
                          Qt.AspectRatioMode.KeepAspectRatio)
        self.zoom_changed.emit(self.transform().m11())

    def reset_zoom(self):
        self.resetTransform()
        self.zoom_changed.emit(1.0)


class ImageViewerOverlay(QFrame):
    """Frameless floating popup for viewing images at full size."""

    closed = Signal()

    def __init__(self, parent=None):
        owner = parent.window() if parent else None
        super().__init__(owner, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._host = parent
        self._host_window = owner
        self._pixmap: QPixmap | None = None
        self._base_pixmap: QPixmap | None = None
        self._rotation = 0
        self._current_path: str = ""
        self._image_list: list[str] = []
        self._image_idx = -1
        # Slideshow auto-advance timer (toggled with Space).
        self._slideshow_timer = QTimer(self)
        self._slideshow_timer.setInterval(3000)
        self._slideshow_timer.timeout.connect(lambda: self._nav(1))
        # Directory scan cache: parent dir -> (dir mtime, sorted image list).
        # Keyed by directory so paging through a folder rescans at most once
        # per change instead of once per image. Capacity is capped (simple
        # drop-oldest) to keep memory bounded.
        self._dir_list_cache: dict[str, tuple[float | None, list[str]]] = {}
        # EXIF overlay (toggled with I).
        self._show_exif = False
        self._exif: dict[str, str] = {}
        # Thumbnail strip (toggled with T); thumbnails are loaded lazily.
        self._show_strip = False
        self._strip_thumbs: dict[int, QPixmap] = {}
        self._strip_thumb_w = scaled_px(56)

        self._m = scaled_px(8)
        self._header_h = scaled_px(36)
        self._footer_h = scaled_px(28)

        # Image view (GPU-accelerated)
        self._view = _GraphicsView(self)
        self._view.zoom_changed.connect(self.update)
        self._view.viewport().installEventFilter(self)
        self._scene = QGraphicsScene(self._view)
        self._view.setScene(self._scene)
        self._pixmap_item: QGraphicsPixmapItem | None = None

        self._build_image_list()
        self.resize(scaled_px(900), scaled_px(650))

    # ── Public API ──────────────────────────────────────────────

    def load_image(self, path: str):
        if not os.path.isfile(path):
            return
        ext = Path(path).suffix.lower()
        if ext not in IMAGE_EXTS:
            return
        self._current_path = path
        self._build_image_list()
        self._exif = {}
        self._strip_thumbs = {}
        if self._show_exif:
            self._exif = self._read_exif(path)
        try:
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            orig = reader.size()
            if orig.width() > MAX_DIM or orig.height() > MAX_DIM:
                reader.setScaledSize(orig.scaled(MAX_DIM, MAX_DIM,
                                                 Qt.AspectRatioMode.KeepAspectRatio))
            qimg = reader.read()
            if qimg.isNull():
                _log.warning("Image decode failed (empty result): %s", path)
                self._pixmap = None
                return
            self._pixmap = QPixmap.fromImage(qimg)
            self._base_pixmap = self._pixmap
            self._rotation = 0
            self._update_scene()
            self.update()
        except Exception:
            _log.warning("Failed to load image %s", path, exc_info=True)
            self._pixmap = None

    def show_overlay(self):
        self._position_over_host()
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(10, self._view.fit_in_view)
        if self._host_window:
            try:
                self._host_window.installEventFilter(self)
            except RuntimeError:
                self._host_window = None

    # ── Layout ──────────────────────────────────────────────────

    def _position_over_host(self):
        if self._host_window is not None:
            try:
                g = self._host_window.geometry()
                self.setGeometry(g.adjusted(20, 20, -20, -20))
                return
            except RuntimeError:
                self._host_window = None
        screen = QApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen.adjusted(60, 60, -60, -60))

    def _container_rect(self) -> QRect:
        return self.rect().adjusted(self._m, self._m, -self._m, -self._m)

    def _header_rect(self) -> QRect:
        c = self._container_rect()
        return QRect(c.x(), c.y(), c.width(), self._header_h)

    def _footer_rect(self) -> QRect:
        c = self._container_rect()
        return QRect(c.x(), c.bottom() - self._footer_h, c.width(), self._footer_h)

    def _strip_h(self) -> int:
        """Height of the thumbnail strip (0 when hidden)."""
        return scaled_px(64) if self._show_strip else 0

    def _exif_w(self) -> int:
        """Width of the EXIF side panel (0 when hidden)."""
        return scaled_px(200) if self._show_exif else 0

    def _view_rect(self) -> QRect:
        c = self._container_rect()
        top = c.y() + self._header_h
        bottom = c.bottom() - self._footer_h - self._strip_h()
        left = c.x()
        right = c.right() - self._exif_w()
        return QRect(left, top, max(0, right - left + 1), max(0, bottom - top + 1))

    def _strip_rect(self) -> QRect:
        c = self._container_rect()
        return QRect(c.x(), c.bottom() - self._footer_h - self._strip_h(),
                     c.width(), self._strip_h())

    def _exif_rect(self) -> QRect:
        c = self._container_rect()
        top = c.y() + self._header_h
        bottom = c.bottom() - self._footer_h - self._strip_h()
        return QRect(c.right() - self._exif_w() + 1, top,
                     self._exif_w(), max(0, bottom - top + 1))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._view.setGeometry(self._view_rect())

    # ── Scene ───────────────────────────────────────────────────

    def _update_scene(self):
        t = themes.get()
        self._scene.clear()
        self._scene.setBackgroundBrush(QColor(t["base"]))
        if self._pixmap and not self._pixmap.isNull():
            self._pixmap_item = QGraphicsPixmapItem(self._pixmap)
            self._scene.addItem(self._pixmap_item)
            self._scene.setSceneRect(QRectF(self._pixmap.rect()))
        self._view.reset_zoom()

    # ── Image list ──────────────────────────────────────────────

    def _build_image_list(self):
        if not self._current_path:
            return
        parent = str(Path(self._current_path).parent)
        try:
            mtime = os.path.getmtime(parent)
        except OSError:
            mtime = None
        cached = None if mtime is None else self._dir_list_cache.get(parent)
        if cached is not None and cached[0] == mtime:
            self._image_list = cached[1]
        else:
            try:
                entries = sorted(
                    [e for e in os.scandir(parent)
                     if e.is_file() and Path(e.name).suffix.lower() in IMAGE_EXTS],
                    key=lambda e: e.name.lower())
                self._image_list = [e.path for e in entries]
                if len(self._dir_list_cache) >= 5:
                    # Drop the oldest cached directory (insertion order) to
                    # bound memory; paging typically reuses one directory.
                    self._dir_list_cache.pop(next(iter(self._dir_list_cache)))
                self._dir_list_cache[parent] = (mtime, list(self._image_list))
            except OSError:
                self._image_list = [self._current_path]
        try:
            self._image_idx = self._image_list.index(self._current_path)
        except ValueError:
            self._image_idx = 0

    def _nav(self, direction):
        if not self._image_list:
            return
        self._image_idx = (self._image_idx + direction) % len(self._image_list)
        target = self._image_list[self._image_idx]
        if target != self._current_path:
            self.load_image(target)
            QTimer.singleShot(10, self._view.fit_in_view)

    def _toggle_slideshow(self):
        """Start/stop auto-advance through the directory image list."""
        if self._slideshow_timer.isActive():
            self._slideshow_timer.stop()
        else:
            self._slideshow_timer.start()
        self.update()

    def _rotate(self, degrees: int):
        """Rotate the displayed image by *degrees* (multiples of 90)."""
        if self._base_pixmap is None or self._base_pixmap.isNull():
            return
        self._rotation = (self._rotation + degrees) % 360
        self._pixmap = self._base_pixmap.transformed(
            QTransform().rotate(self._rotation)
        )
        self._update_scene()
        self.update()

    def _slideshow_active(self) -> bool:
        return self._slideshow_timer.isActive()

    # ── Copy / Save ─────────────────────────────────────────────

    def _copy_to_clipboard(self):
        """Copy the current (possibly rotated) image to the clipboard."""
        if self._pixmap and not self._pixmap.isNull():
            QApplication.clipboard().setPixmap(self._pixmap)

    def _save_as(self):
        """Prompt for a destination and save the current image there."""
        if not self._pixmap or self._pixmap.isNull():
            return
        default = self._suggested_save_path()
        path, _ = QFileDialog.getSaveFileName(
            self, tr("viewer.save_title"), default, tr("viewer.save_filter"),
        )
        if path:
            self._save_pixmap_to(path)

    def _suggested_save_path(self) -> str:
        base = Path(self._current_path).stem if self._current_path else "image"
        if self._current_path:
            return str(Path(self._current_path).with_name(f"{base}_edited.png"))
        return f"{base}_edited.png"

    def _save_pixmap_to(self, destination: str) -> bool:
        """Write the current pixmap to *destination*. Returns success."""
        if not self._pixmap or self._pixmap.isNull():
            return False
        try:
            ok = self._pixmap.save(destination)
            if not ok:
                _log.warning("Pixmap save failed: %s", destination)
            return bool(ok)
        except Exception:
            _log.warning("Pixmap save failed: %s", destination, exc_info=True)
            return False

    # ── EXIF overlay ─────────────────────────────────────────────

    @staticmethod
    def _read_exif(path: str) -> dict[str, str]:
        """Read EXIF tags from *path* as an ordered ``{label: value}`` map.

        Returns an empty dict when the image has no EXIF, the library is
        unavailable, or decoding fails — EXIF is a best-effort viewer nicety.
        """
        try:
            from PIL import ExifTags, Image
        except ImportError:
            return {}
        try:
            with Image.open(path) as img:
                exif = img.getexif()
            if not exif:
                return {}
            result: dict[str, str] = {}
            for tag_id, value in exif.items():
                label = ExifTags.TAGS.get(tag_id)
                if label is None:
                    continue
                if isinstance(value, bytes):
                    value = value.decode("utf-8", "replace").rstrip("\x00")
                result[str(label)] = str(value)[:80]
            return result
        except Exception:
            _log.debug("EXIF read failed for %s", path, exc_info=True)
            return {}

    def _toggle_exif(self):
        """Show/hide the EXIF side panel."""
        self._show_exif = not self._show_exif
        if self._show_exif and self._current_path:
            self._exif = self._read_exif(self._current_path)
        self._view.setGeometry(self._view_rect())
        self.update()

    # ── Thumbnail strip ──────────────────────────────────────────

    def _strip_layout(self):
        """Return ``(strip_rect, gap, thumb_w, start_index, visible_count)``."""
        sr = self._strip_rect()
        gap = scaled_px(4)
        tw = self._strip_thumb_w
        visible = max(0, (sr.width() - 2 * gap) // (tw + gap))
        start = 0
        if self._image_list and visible < len(self._image_list):
            start = max(0, min(self._image_idx - visible // 2,
                               len(self._image_list) - visible))
        return sr, gap, tw, start, visible

    def _strip_start_index(self) -> int:
        return self._strip_layout()[3]

    def _strip_index_at(self, x: int) -> int:
        """Map an x coordinate in the strip to an image-list index (or -1)."""
        if not self._show_strip or not self._image_list:
            return -1
        sr, gap, tw, start, visible = self._strip_layout()
        if not sr.contains(x, sr.center().y()):
            return -1
        rel = (x - sr.x() - gap) // (tw + gap)
        if rel < 0 or rel >= visible:
            return -1
        idx = start + rel
        return idx if 0 <= idx < len(self._image_list) else -1

    def _ensure_strip_thumb(self, index: int) -> QPixmap | None:
        """Load (and cache) a downscaled thumbnail for ``_image_list[index]``."""
        if index in self._strip_thumbs:
            return self._strip_thumbs[index]
        if not (0 <= index < len(self._image_list)):
            return None
        path = self._image_list[index]
        try:
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            orig = reader.size()
            if not orig.isValid():
                return None
            reader.setScaledSize(orig.scaled(
                self._strip_thumb_w, self._strip_thumb_w,
                Qt.AspectRatioMode.KeepAspectRatio))
            qimg = reader.read()
            if qimg.isNull():
                return None
            pm = QPixmap.fromImage(qimg)
            self._strip_thumbs[index] = pm
            return pm
        except Exception:
            _log.debug("Strip thumbnail load failed for %s", path, exc_info=True)
            return None

    def _toggle_strip(self):
        """Show/hide the thumbnail navigation strip."""
        self._show_strip = not self._show_strip
        self._strip_thumbs.clear()
        self._view.setGeometry(self._view_rect())
        self.update()

    # ── Chrome painting ─────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = themes.get()
        rect = self.rect()
        container = self._container_rect()

        # Semi-transparent backdrop
        p.fillRect(rect, QColor(0, 0, 0, 180))

        # Container background
        p.setBrush(QColor(t["panel"]))
        p.setPen(QPen(QColor(t["border"]), 1))
        p.drawRoundedRect(container, 10, 10)

        # ── Header ──
        header = self._header_rect()
        p.setBrush(QColor(t["header"]))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(header, 10, 10)
        p.setBrush(QColor(t["panel"]))
        p.drawRect(QRect(header.x(), header.bottom() - 8, header.width(), 8))

        # Title: filename + counter
        name = Path(self._current_path).name if self._current_path else ""
        count = f"  {self._image_idx + 1} / {len(self._image_list)}" if self._image_list else ""
        p.setPen(QColor(t["heading"]))
        f = QFont()
        f.setPointSize(scaled_pt(11))
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRect(header.x() + 14, header.y(), header.width() - 60, header.height()),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    name + count)

        # Close button
        close_r = QRect(header.right() - 38, header.y() + 6, 28, 24)
        close_hover = close_r.contains(self.mapFromGlobal(self.cursor().pos()))
        if close_hover:
            p.setBrush(QColor(t["danger"]))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(close_r, 4, 4)
            p.setPen(QColor("white"))
        else:
            p.setPen(QColor(t["muted"]))
        close_color = QColor("white") if close_hover else QColor(t["muted"])
        close_icon = icons.icon("close", color=close_color.name(), size=scaled_px(16))
        close_pixmap = close_icon.pixmap(QSize(scaled_px(16), scaled_px(16)))
        p.drawPixmap(
            close_r.center().x() - close_pixmap.width() // 2,
            close_r.center().y() - close_pixmap.height() // 2,
            close_pixmap,
        )

        # ── Footer ──
        footer = self._footer_rect()
        p.setBrush(QColor(t["header"]))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(footer, 10, 10)
        p.setBrush(QColor(t["panel"]))
        p.drawRect(QRect(footer.x(), footer.y(), footer.width(), 8))

        # Hint text
        f3 = QFont()
        f3.setPointSize(scaled_pt(9))
        p.setFont(f3)
        p.setPen(QColor(t["muted"]))
        p.drawText(QRect(footer.x() + 14, footer.y(), footer.width() - 30, footer.height()),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    tr("viewer.footer"))

        # Zoom + dimensions
        if self._pixmap:
            zoom_pct = int(self._view.transform().m11() * 100)
            dims = f"{self._pixmap.width()}×{self._pixmap.height()}  {zoom_pct}%"
            p.drawText(QRect(footer.x() + 14, footer.y(), footer.width() - 30, footer.height()),
                        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, dims)

        # ── Thumbnail strip ──
        if self._show_strip:
            self._paint_strip(p, t)

        # ── EXIF side panel ──
        if self._show_exif:
            self._paint_exif(p, t)

        p.end()

    def _paint_strip(self, p, t):
        sr, gap, tw, start, visible = self._strip_layout()
        if sr.isNull() or visible <= 0:
            return
        p.setBrush(QColor(t["header"]))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(sr, 8, 8)
        for rel in range(visible):
            idx = start + rel
            if idx >= len(self._image_list):
                break
            cell = QRect(sr.x() + gap + rel * (tw + gap), sr.y() + gap,
                         tw, sr.height() - 2 * gap)
            thumb = self._ensure_strip_thumb(idx)
            if thumb is not None and not thumb.isNull():
                sw, sh = thumb.width(), thumb.height()
                scale = min(cell.width() / sw, cell.height() / sh)
                dw, dh = int(sw * scale), int(sh * scale)
                p.drawPixmap(QRect(cell.x() + (cell.width() - dw) // 2,
                                   cell.y() + (cell.height() - dh) // 2, dw, dh), thumb)
            else:
                p.setBrush(QColor(t["panel"]))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRect(cell)
            if idx == self._image_idx:
                p.setPen(QPen(QColor(t["accent"]), 2))
            else:
                p.setPen(QPen(QColor(t["border"]), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(cell)

    def _paint_exif(self, p, t):
        panel = self._exif_rect()
        if panel.isNull():
            return
        p.setBrush(QColor(t["panel"]))
        p.setPen(QPen(QColor(t["border"]), 1))
        p.drawRoundedRect(panel, 8, 8)

        title_font = QFont()
        title_font.setPointSize(scaled_pt(10))
        title_font.setBold(True)
        p.setFont(title_font)
        p.setPen(QColor(t["heading"]))
        p.drawText(QRect(panel.x() + 10, panel.y() + 6, panel.width() - 20, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   tr("viewer.exif_title"))

        body_font = QFont()
        body_font.setPointSize(scaled_pt(9))
        p.setFont(body_font)
        if not self._exif:
            p.setPen(QColor(t["muted"]))
            p.drawText(QRect(panel.x() + 10, panel.y() + 30, panel.width() - 20, 20),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       tr("viewer.exif_none"))
            return
        y = panel.y() + 30
        row_h = 18
        for label, value in self._exif.items():
            if y > panel.bottom() - row_h:
                break
            p.setPen(QColor(t["muted"]))
            p.drawText(QRect(panel.x() + 10, y, panel.width() - 20, row_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
            p.setPen(QColor(t["body"]))
            p.drawText(QRect(panel.x() + 10, y, panel.width() - 20, row_h),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, value)
            y += row_h

    # ── Input handling ──────────────────────────────────────────

    def eventFilter(self, obj, event):
        if obj is self._view.viewport():
            if event.type() == event.Type.Wheel:
                # Let QGraphicsView handle wheel → triggers _GraphicsView.wheelEvent
                return False
        if self._host_window is not None:
            try:
                if obj is self._host_window and event.type() in (event.Type.Move, event.Type.Resize):
                    self._position_over_host()
            except RuntimeError:
                self._host_window = None
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            close_r = QRect(self._header_rect().right() - 38,
                            self._header_rect().y() + 6, 28, 24)
            if close_r.contains(event.pos()):
                self.close()
                return
            if self._show_strip:
                idx = self._strip_index_at(event.pos().x())
                if idx >= 0 and idx != self._image_idx:
                    self._image_idx = idx
                    target = self._image_list[idx]
                    self.load_image(target)
                    QTimer.singleShot(10, self._view.fit_in_view)
                    return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        k = event.key()
        if k in (Qt.Key.Key_Escape, Qt.Key.Key_Q):
            self.close()
        elif k == Qt.Key.Key_Space:
            self._toggle_slideshow()
        elif k == Qt.Key.Key_Left:
            self._nav(-1)
        elif k == Qt.Key.Key_Right:
            self._nav(1)
        elif k == Qt.Key.Key_F:
            self._view.fit_in_view()
        elif k == Qt.Key.Key_R:
            self._rotate(-90 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 90)
        elif k == Qt.Key.Key_C and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._copy_to_clipboard()
        elif k == Qt.Key.Key_S and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._save_as()
        elif k == Qt.Key.Key_I:
            self._toggle_exif()
        elif k == Qt.Key.Key_T:
            self._toggle_strip()
        elif k in (Qt.Key.Key_1, Qt.Key.Key_0):
            self._view.reset_zoom()
        elif k == Qt.Key.Key_Plus or k == Qt.Key.Key_Equal:
            self._view.scale(1.25, 1.25)
            self._view.zoom_changed.emit(self._view.transform().m11())
        elif k == Qt.Key.Key_Minus:
            self._view.scale(0.8, 0.8)
            self._view.zoom_changed.emit(self._view.transform().m11())
        else:
            super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._view.fit_in_view()

    # ── Cleanup ─────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._host_window is not None:
            try:
                self._host_window.removeEventFilter(self)
            except RuntimeError:
                pass
            self._host_window = None
        self.closed.emit()
        super().closeEvent(event)


# ── Backward compatibility ─────────────────────────────────────

ImageViewer = ImageViewerOverlay


def open_image_viewer(parent, path: str):
    """Open an image in the floating viewer overlay."""
    viewer = ImageViewerOverlay(parent)
    viewer.load_image(path)
    viewer.show_overlay()
    return viewer
