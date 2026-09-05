"""ImageViewerOverlay — GPU-accelerated image viewer with modern UX.

Features:
  - QGraphicsView + QOpenGLWidget viewport (GPU rendering)
  - Custom-painted chrome (header, footer, backdrop)
  - Smooth wheel zoom anchored under cursor
  - Fit-to-window / Actual-size shortcuts
  - Prev/Next image navigation with keyboard
  - Slideshow auto-advance (Space)
  - Frame-sequence navigation (, / .) and playback (Ctrl+P) when the
    opened image belongs to a detected frame sequence
  - Rotate 90° (R / Shift+R)
  - Copy to clipboard (Ctrl+C)
  - Save As (Ctrl+S)
  - EXIF overlay (I)
  - Thumbnail strip (T) — async prefetch, never decoded in paintEvent
  - Theme-aware styling
  - Cursor feedback (grab/grabbing via QGraphicsView default)

Decoding never runs on the UI thread: every QImageReader.read() happens on the
viewer's private, bounded worker pool, and the UI thread only converts the
delivered QImage to a QPixmap and drops stale deliveries by generation.
"""
import io
import logging
import os
from pathlib import Path

from PySide6.QtCore import (
    Qt, Signal, QRectF, QRect, QTimer, QSize, QObject,
    QByteArray, QBuffer, QIODevice,
)
from PySide6.QtGui import (
    QPixmap, QColor, QPainter, QPen, QFont,
    QImage, QImageReader, QTransform,
)
from PySide6.QtWidgets import (
    QFrame, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QApplication, QFileDialog,
)

from AssetsManager.core import icons, themes
from AssetsManager.core.constants import IMAGE_EXTS
from AssetsManager.application.thumbnail_service import MAX_THUMBNAIL_SOURCE_BYTES
from AssetsManager.application.media.decoders import decoder_for
from AssetsManager.application.sequence_service import SequenceNeighbors, find_neighbors
from AssetsManager.core.file_snapshot import read_snapshot
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.core.workers import BoundedPool, CancellationToken, CancellableRunnable
from AssetsManager.panels.file_list._loader import _suppress_libpng_warnings
from AssetsManager.panels.file_list._common import pil_image_to_qimage
from AssetsManager import i18n
tr = i18n.tr

_log = logging.getLogger(__name__)

# Downsampling cap for display-size decoding. Images larger than this are
# pre-scaled by QImageReader before the pixel decode runs (on the dedicated
# worker pool, never the UI thread), bounding the worst-case decode time and
# memory. 2048px comfortably exceeds typical viewer window sizes.
MAX_DIM = 2048

# Bounded drain for the viewer's private decode pool at close time. Decode
# tasks are cooperative-cancellable and size-capped at MAX_DIM, so the only
# work left after cancellation is at most one in-flight QImageReader.read().
_VIEWER_DRAIN_TIMEOUT_MS = 3000

# Default frame rate for in-sequence playback (Ctrl+P). Sequences rarely
# carry usable fps metadata; 12fps matches the flipbook convention.
_SEQUENCE_FPS = 12


class _ViewerBridge(QObject):
    """Cross-thread delivery bridge living on the UI thread.

    Worker tasks emit these signals; Qt queues the delivery back to the
    viewer's thread because the receiver lives there. Only QImage crosses the
    thread boundary — QPixmap and QWidget stay on the UI thread.
    """

    image_ready = Signal(int, str, QImage)       # (generation, path, image)
    strip_ready = Signal(int, int, str, QImage)  # (generation, index, path, thumb)
    exif_ready = Signal(int, str, object)       # (generation, path, metadata)


def _is_viewable_ext(ext: str) -> bool:
    """True when the viewer can decode *ext* (Pillow/Qt or media registry)."""
    return ext in IMAGE_EXTS or decoder_for(ext) is not None


def _decode_image_bytes(body: bytes, max_dim: int, label: str = "<snapshot>") -> QImage | None:
    """Decode one captured image body without reopening its source path."""
    data = QByteArray(body)
    buffer = QBuffer()
    buffer.setData(data)
    if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
        return None
    try:
        reader = QImageReader(buffer)
        reader.setAutoTransform(True)
        orig = reader.size()
        if not orig.isValid():
            return None
        if orig.width() > max_dim or orig.height() > max_dim:
            reader.setScaledSize(orig.scaled(
                max_dim, max_dim, Qt.AspectRatioMode.KeepAspectRatio
            ))
        with _suppress_libpng_warnings():
            img = reader.read()
        return None if img.isNull() else img
    except Exception:
        _log.warning("Image decode failed: %s", label, exc_info=True)
        return None
    finally:
        buffer.close()


def _decode_image(path: str, max_dim: int) -> QImage | None:
    """Legacy path-based test/extension seam.

    Production viewer tasks call ``_decode_captured_image`` and never use this
    fallback. It remains for callers that explicitly use the historical helper.
    """
    try:
        with open(path, "rb") as stream:
            return _decode_image_bytes(stream.read(), max_dim, path)
    except OSError:
        return None


def _decode_captured_image(path: str, body: bytes, max_dim: int) -> QImage | None:
    """Decode captured bytes while preserving monkeypatch compatibility."""
    decoder = _decode_image
    if getattr(decoder, "__module__", None) == __name__ and getattr(
        decoder, "__name__", None
    ) == "_decode_image":
        return _decode_image_bytes(body, max_dim, path)
    return decoder(path, max_dim)


def _decode_media_image(path: str, media_decoder, max_dim: int) -> QImage | None:
    """Decode one professional-format source (RAW/PSD) via the registry.

    Worker-thread seam parallel to ``_decode_captured_image``; module-level so
    tests can monkeypatch it the same way. The decoder respects *max_dim*
    (the viewer's MAX_DIM pre-downsampling cap), so a 500-megapixel RAW never
    materializes beyond a display-size buffer.
    """
    try:
        pil = media_decoder.decode(Path(path), max_dim=max_dim)
    except Exception:
        _log.warning("Media decode failed: %s", path, exc_info=True)
        return None
    if pil is None:
        return None
    return pil_image_to_qimage(pil)


def _snapshot_path(path: str, library_root: str | None = None) -> bytes | None:
    source = Path(path)
    root = Path(library_root) if library_root else source.parent
    try:
        body, _identity = read_snapshot(
            root, source, max_bytes=MAX_THUMBNAIL_SOURCE_BYTES,
        )
        return body
    except (OSError, ValueError):
        _log.debug("Image snapshot failed: %s", path, exc_info=True)
        return None


class _FullImageTask(CancellableRunnable):
    """Display-size decode task run from one bounded source snapshot."""

    def __init__(self, bridge: _ViewerBridge, path: str, library_root: str | None,
                 max_dim: int, generation: int, token: CancellationToken):
        super().__init__(generation=generation, cancel_token=token)
        self._bridge = bridge
        self._path = path
        self._library_root = library_root
        self._max_dim = max_dim

    def run(self):
        if self.is_cancelled():
            return
        media_decoder = decoder_for(Path(self._path).suffix)
        if media_decoder is not None:
            img = (
                None if self.is_cancelled()
                else _decode_media_image(self._path, media_decoder, self._max_dim)
            )
        else:
            body = _snapshot_path(self._path, self._library_root)
            if body is None or self.is_cancelled():
                img = None
            else:
                img = _decode_captured_image(self._path, body, self._max_dim)
        if self.is_cancelled():
            return
        try:
            self._bridge.image_ready.emit(
                self.generation, self._path, img if img is not None else QImage())
        except RuntimeError:
            pass


class _ExifTask(CancellableRunnable):
    """Read EXIF from a captured source body off the UI thread."""

    def __init__(self, bridge: _ViewerBridge, path: str, library_root: str | None,
                 generation: int, token: CancellationToken):
        super().__init__(generation=generation, cancel_token=token)
        self._bridge = bridge
        self._path = path
        self._library_root = library_root

    def run(self):
        if self.is_cancelled():
            return
        body = _snapshot_path(self._path, self._library_root)
        metadata = {} if body is None else ImageViewerOverlay._read_exif_bytes(body)
        if self.is_cancelled():
            return
        try:
            self._bridge.exif_ready.emit(self.generation, self._path, metadata)
        except RuntimeError:
            pass


class _StripThumbTask(CancellableRunnable):
    """Async downscaled strip-thumbnail decode from one source snapshot."""

    def __init__(self, bridge: _ViewerBridge, index: int, path: str,
                 library_root: str | None, size: int, generation: int,
                 token: CancellationToken):
        super().__init__(generation=generation, cancel_token=token)
        self._bridge = bridge
        self._index = index
        self._path = path
        self._library_root = library_root
        self._size = size

    def run(self):
        if self.is_cancelled():
            return
        media_decoder = decoder_for(Path(self._path).suffix)
        if media_decoder is not None:
            img = (
                None if self.is_cancelled()
                else _decode_media_image(self._path, media_decoder, self._size)
            )
        else:
            body = _snapshot_path(self._path, self._library_root)
            if body is None or self.is_cancelled():
                img = None
            else:
                img = _decode_captured_image(self._path, body, self._size)
        if self.is_cancelled():
            return
        try:
            self._bridge.strip_ready.emit(
                self.generation, self._index, self._path,
                img if img is not None else QImage())
        except RuntimeError:
            pass


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
        # NOTE: 本视图宿主于 WA_TranslucentBackground 的 frameless Tool 顶层窗口。
        # Qt 不支持在半透明顶层窗口上使用 QOpenGLWidget——真实 GPU 环境下
        # setViewport(QOpenGLWidget) 直接 access violation（事件日志 16:30/16:31
        # 两次 c0000005，faulthandler 栈钉在本文件 :284）。因此这里保持默认的
        # 光栅视口：单图缩放查看的光栅路径完全够用，且无 GL 上下文创建失败面。
        # app.py 的 QOpenGLWidget 探针保留，仅为打包锚点（G2 要求 QtOpenGLWidgets
        # 随包），与此视口无关。

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
        self._library_root: str | None = None
        self._pixmap: QPixmap | None = None
        self._base_pixmap: QPixmap | None = None
        self._rotation = 0
        self._current_path: str = ""
        self._image_list: list[str] = []
        self._image_idx = -1
        # Async decode state: all QImageReader work runs on the private,
        # bounded pool below. ``_state`` tracks the display lifecycle; stale
        # deliveries are rejected by generation + current-path equality.
        self._decode_pool = BoundedPool(max_thread_count=2)
        self._bridge = _ViewerBridge(self)
        self._bridge.image_ready.connect(self._on_image_ready)
        self._bridge.strip_ready.connect(self._on_strip_ready)
        self._bridge.exif_ready.connect(self._on_exif_ready)
        self._decoder_generation = 0
        self._closed = False
        self._state = "empty"  # one of "empty" | "loading" | "ready" | "error"
        # Slideshow auto-advance timer (toggled with Space).
        self._slideshow_timer = QTimer(self)
        self._slideshow_timer.setInterval(3000)
        self._slideshow_timer.timeout.connect(lambda: self._nav(1))
        # Frame-sequence playback timer (toggled with Ctrl+P). Stepping goes
        # through the same load_image path as manual navigation; detection
        # state lives in _sequence and is refreshed on every load_image.
        self._sequence: SequenceNeighbors | None = None
        self._sequence_timer = QTimer(self)
        self._sequence_timer.setInterval(int(1000 / _SEQUENCE_FPS))
        self._sequence_timer.timeout.connect(self._sequence_auto_step)
        self._fit_timers: list = []
        # Directory scan cache: parent dir -> (dir mtime, sorted image list).
        # Keyed by directory so paging through a folder rescans at most once
        # per change instead of once per image. Capacity is capped (simple
        # drop-oldest) to keep memory bounded.
        self._dir_list_cache: dict[str, tuple[float | None, list[str]]] = {}
        # EXIF overlay (toggled with I).
        self._show_exif = False
        self._exif: dict[str, str] = {}
        # Thumbnail strip (toggled with T); thumbnails are loaded lazily and
        # asynchronously (never decoded inside paintEvent).
        self._show_strip = False
        self._strip_thumbs: dict[int, QPixmap] = {}
        self._strip_pending: set[int] = set()
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

    def load_image(self, path: str, library_root: str | None = None):
        """Request async decode of *path*; returns immediately.

        The UI thread only submits the request — QImageReader work runs on the
        viewer's private pool and the result is applied on the UI thread when
        it finishes (and is still current). The previously shown image stays
        visible while the new one decodes.
        """
        if self._closed:
            return
        if not os.path.isfile(path):
            return
        ext = Path(path).suffix.lower()
        # Professional formats (RAW/PSD) are viewable when the media decoder
        # registry can route them; without the extras this stays closed and
        # only Pillow/QImageReader-readable extensions load.
        if ext not in IMAGE_EXTS and decoder_for(ext) is None:
            return
        self._cancel_pending_decode()
        self._library_root = str(Path(library_root).resolve()) if library_root else None
        self._current_path = path
        self._sequence = self._detect_sequence(path)
        if self._sequence is None:
            self._stop_sequence_playback()
        self._build_image_list()
        self._exif = {}
        self._strip_thumbs = {}
        self._strip_pending = set()
        self._state = "loading"
        self.update()
        token = CancellationToken()
        task = _FullImageTask(
            self._bridge, path, self._library_root, MAX_DIM,
            self._decoder_generation, token,
        )
        self._decode_pool.start(task)
        if self._show_exif:
            exif_task = _ExifTask(
                self._bridge, path, self._library_root,
                self._decoder_generation, CancellationToken(),
            )
            self._decode_pool.start(exif_task)

    def _cancel_pending_decode(self) -> None:
        """Bump the generation and cooperatively cancel all in-flight work."""
        self._decoder_generation += 1
        self._decode_pool.cancel_all()
        self._strip_pending.clear()

    def _on_image_ready(self, generation: int, path: str, qimg: QImage) -> None:
        """Apply a delivered display image on the UI thread (queued slot)."""
        if self._closed or generation != self._decoder_generation or path != self._current_path:
            return  # stale decode or viewer already closed — never overwrite current
        if qimg.isNull():
            self._state = "error"
            self._pixmap = None
            self._base_pixmap = None
            self._rotation = 0
            self._update_scene()
            self.update()
            return
        pm = QPixmap.fromImage(qimg)
        self._pixmap = pm
        self._base_pixmap = pm
        self._rotation = 0
        self._state = "ready"
        self._update_scene()
        self.update()
        self._schedule_fit()
        if self._show_strip:
            self._prefetch_strip()

    def _prefetch_strip(self, margin: int = 4) -> None:
        """Submit async thumbnail decodes for the visible strip window."""
        if self._closed or not self._show_strip or not self._image_list:
            return
        _, _gap, _tw, start, visible = self._strip_layout()
        lo = max(0, start - margin)
        hi = min(len(self._image_list), start + visible + margin)
        for idx in range(lo, hi):
            if idx in self._strip_thumbs or idx in self._strip_pending:
                continue
            path = self._image_list[idx]
            self._strip_pending.add(idx)
            token = CancellationToken()
            task = _StripThumbTask(
                self._bridge, idx, path, self._library_root, self._strip_thumb_w,
                self._decoder_generation, token,
            )
            self._decode_pool.start(task)

    def _on_strip_ready(self, generation: int, index: int, path: str, qimg: QImage) -> None:
        """Cache a delivered strip thumbnail on the UI thread (queued slot)."""
        if self._closed or generation != self._decoder_generation:
            return
        if not (0 <= index < len(self._image_list)) or self._image_list[index] != path:
            return
        self._strip_pending.discard(index)
        if qimg.isNull():
            return
        self._strip_thumbs[index] = QPixmap.fromImage(qimg)
        self.update()

    def show_overlay(self):
        self._position_over_host()
        self.show()
        self.raise_()
        self.activateWindow()
        self._schedule_fit()
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
                     if e.is_file() and _is_viewable_ext(Path(e.name).suffix.lower())],
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
        self._stop_sequence_playback()  # manual navigation always pauses playback
        if not self._image_list:
            return
        self._image_idx = (self._image_idx + direction) % len(self._image_list)
        target = self._image_list[self._image_idx]
        if target != self._current_path:
            self.load_image(target)
            self._schedule_fit()

    def _toggle_slideshow(self):
        """Start/stop auto-advance through the directory image list."""
        if self._slideshow_timer.isActive():
            self._slideshow_timer.stop()
        else:
            # The two auto-advance timers are mutually exclusive: a running
            # sequence playback would fight the directory-wide slideshow.
            self._stop_sequence_playback()
            self._slideshow_timer.start()
        self.update()

    def _rotate(self, degrees: int):
        """Rotate the displayed image by *degrees* (multiples of 90)."""
        if self._base_pixmap is None or self._base_pixmap.isNull():
            return
        if self._state == "loading":
            # A new image is still decoding; the old base pixmap would be
            # replaced on delivery and the rotation reset — avoid rotating a
            # soon-to-be-discarded image.
            return
        self._rotation = (self._rotation + degrees) % 360
        self._pixmap = self._base_pixmap.transformed(
            QTransform().rotate(self._rotation)
        )
        self._update_scene()
        self.update()

    def _slideshow_active(self) -> bool:
        return self._slideshow_timer.isActive()

    # ── Frame-sequence navigation / playback ────────────────────

    def _detect_sequence(self, path: str) -> SequenceNeighbors | None:
        """Detect the frame sequence *path* belongs to (None when standalone)."""
        source = Path(path)
        return find_neighbors(source.parent, source.name)

    def _sequence_step(self, direction: int, manual: bool = True) -> None:
        """Move to the previous/next frame of the detected sequence.

        Manual steps clamp at the sequence ends; playback ticks wrap around
        so a playing sequence loops. Both go through load_image, so decode
        stays on the worker pool and stale deliveries are discarded.
        """
        if self._sequence is None:
            return
        if manual:
            self._stop_sequence_playback()
        frames = self._sequence.frames
        if not frames:
            return
        if manual:
            target_index = self._sequence.index + direction
            if not 0 <= target_index < len(frames):
                return
        else:
            target_index = (self._sequence.index + direction) % len(frames)
        target = frames[target_index]
        if target != self._current_path:
            self.load_image(target)
            self._schedule_fit()

    def _sequence_auto_step(self):
        """Timer tick: advance one frame, looping at the sequence ends."""
        if self._sequence is None:
            self._stop_sequence_playback()
            return
        self._sequence_step(1, manual=False)

    def _toggle_sequence_playback(self):
        """Start/pause in-place playback of the detected sequence (Ctrl+P)."""
        if self._sequence_timer.isActive():
            self._sequence_timer.stop()
        elif self._sequence is not None and self._sequence.count > 1:
            self._slideshow_timer.stop()  # keep the auto-advance timers exclusive
            self._sequence_timer.start()
        self.update()

    def _stop_sequence_playback(self):
        if self._sequence_timer.isActive():
            self._sequence_timer.stop()
            self.update()

    def _sequence_playing(self) -> bool:
        return self._sequence_timer.isActive()

    def _sequence_status_suffix(self) -> str:
        """Footer suffix 'Sequence i/N' plus the playback key hint."""
        if self._sequence is None:
            return ""
        label = tr(
            "viewer.sequence_label",
            index=self._sequence.index + 1,
            count=self._sequence.count,
        )
        return f"  ·  {label}  ·  {tr('viewer.sequence_hint')}"

    def _sequence_status_text(self) -> str:
        """Full footer status text including the sequence suffix (test seam)."""
        return tr("viewer.footer") + self._sequence_status_suffix()

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
    def _read_exif_bytes(body: bytes) -> dict[str, str]:
        """Read EXIF tags from one captured image body."""
        try:
            from PIL import ExifTags, Image
        except ImportError:
            return {}
        try:
            with Image.open(io.BytesIO(body)) as img:
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
            return {}

    @staticmethod
    def _read_exif(path: str) -> dict[str, str]:
        """Legacy helper retained for direct callers and tests."""
        try:
            with open(path, "rb") as stream:
                return ImageViewerOverlay._read_exif_bytes(stream.read())
        except OSError:
            return {}

    def _on_exif_ready(self, generation: int, path: str, metadata: object) -> None:
        if self._closed or generation != self._decoder_generation or path != self._current_path:
            return
        self._exif = dict(metadata) if isinstance(metadata, dict) else {}
        self.update()

    def _toggle_exif(self):
        """Show/hide the EXIF side panel."""
        self._show_exif = not self._show_exif
        if self._show_exif and self._current_path:
            self._exif = {}
            task = _ExifTask(
                self._bridge, self._current_path, self._library_root,
                self._decoder_generation, CancellationToken(),
            )
            self._decode_pool.start(task)
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

    def _toggle_strip(self):
        """Show/hide the thumbnail navigation strip."""
        self._show_strip = not self._show_strip
        self._strip_thumbs.clear()
        self._strip_pending.clear()
        self._view.setGeometry(self._view_rect())
        self.update()
        if self._show_strip:
            self._prefetch_strip()

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
        r_md = scaled_px(int(themes.prop("border_radius", "md")))
        p.drawRoundedRect(container, r_md, r_md)

        # ── Header ──
        header = self._header_rect()
        p.setBrush(QColor(t["header"]))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(header, r_md, r_md)
        p.setBrush(QColor(t["panel"]))
        p.drawRect(QRect(header.x(), header.bottom() - 8, header.width(), 8))

        # Title: filename + counter
        name = Path(self._current_path).name if self._current_path else ""
        count = f"  {self._image_idx + 1} / {len(self._image_list)}" if self._image_list else ""
        p.setPen(QColor(t["heading"]))
        f = QFont()
        f.setPointSize(scaled_pt(int(themes.font_size("caption"))))
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
            r_xs = scaled_px(int(themes.metrics("radius_xs")))
            p.drawRoundedRect(close_r, r_xs, r_xs)
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
        p.drawRoundedRect(footer, r_md, r_md)
        p.setBrush(QColor(t["panel"]))
        p.drawRect(QRect(footer.x(), footer.y(), footer.width(), 8))

        # Hint text (plus the "Sequence i/N · keys" suffix while a detected
        # frame sequence is displayed)
        f3 = QFont()
        f3.setPointSize(scaled_pt(int(themes.font_size("xxs"))))
        p.setFont(f3)
        p.setPen(QColor(t["muted"]))
        p.drawText(QRect(footer.x() + 14, footer.y(), footer.width() - 30, footer.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._sequence_status_text())

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

        # ── Loading / error hint ──
        if self._state in ("loading", "error"):
            self._paint_status_hint(p, t)

        p.end()

    def _paint_status_hint(self, p, t):
        if self._pixmap is not None and not self._pixmap.isNull():
            return  # an image is already displayed — keep it while loading
        text = tr("viewer.loading") if self._state == "loading" else tr("viewer.load_failed")
        f = QFont()
        f.setPointSize(scaled_pt(int(themes.font_size("sm"))))
        p.setFont(f)
        p.setPen(QColor(t["muted"]))
        p.drawText(self._view_rect(), Qt.AlignmentFlag.AlignCenter, text)

    def _paint_strip(self, p, t):
        sr, gap, tw, start, visible = self._strip_layout()
        if sr.isNull() or visible <= 0:
            return
        p.setBrush(QColor(t["header"]))
        p.setPen(Qt.PenStyle.NoPen)
        r_sm = scaled_px(int(themes.prop("border_radius", "sm")))
        p.drawRoundedRect(sr, r_sm, r_sm)
        any_missing = False
        for rel in range(visible):
            idx = start + rel
            if idx >= len(self._image_list):
                break
            cell = QRect(sr.x() + gap + rel * (tw + gap), sr.y() + gap,
                         tw, sr.height() - 2 * gap)
            # Only already-delivered pixmaps are painted here; missing cells
            # draw a placeholder and an async prefetch is requested below.
            thumb = self._strip_thumbs.get(idx)
            if thumb is not None and not thumb.isNull():
                sw, sh = thumb.width(), thumb.height()
                scale = min(cell.width() / sw, cell.height() / sh)
                dw, dh = int(sw * scale), int(sh * scale)
                p.drawPixmap(QRect(cell.x() + (cell.width() - dw) // 2,
                                   cell.y() + (cell.height() - dh) // 2, dw, dh), thumb)
            else:
                any_missing = True
                p.setBrush(QColor(t["panel"]))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRect(cell)
            if idx == self._image_idx:
                p.setPen(QPen(QColor(t["accent"]), 2))
            else:
                p.setPen(QPen(QColor(t["border"]), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(cell)
        # Submitting async decode requests from paintEvent is fine; only the
        # decode itself must never happen here.
        if any_missing:
            self._prefetch_strip()

    def _paint_exif(self, p, t):
        panel = self._exif_rect()
        if panel.isNull():
            return
        p.setBrush(QColor(t["panel"]))
        p.setPen(QPen(QColor(t["border"]), 1))
        r_sm = scaled_px(int(themes.prop("border_radius", "sm")))
        p.drawRoundedRect(panel, r_sm, r_sm)

        title_font = QFont()
        title_font.setPointSize(scaled_pt(int(themes.font_size("xs"))))
        title_font.setBold(True)
        p.setFont(title_font)
        p.setPen(QColor(t["heading"]))
        p.drawText(QRect(panel.x() + 10, panel.y() + 6, panel.width() - 20, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   tr("viewer.exif_title"))

        body_font = QFont()
        body_font.setPointSize(scaled_pt(int(themes.font_size("xxs"))))
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
                    self._stop_sequence_playback()
                    target = self._image_list[idx]
                    self.load_image(target)
                    self._schedule_fit()
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
        elif k == Qt.Key.Key_P and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._toggle_sequence_playback()
        elif k == Qt.Key.Key_Comma or event.text() == "，":
            # Sequence frame navigation: previous frame (full-width comma
            # included for CJK keyboards). Left/Right stay on their existing
            # directory-wide navigation.
            self._sequence_step(-1)
        elif k == Qt.Key.Key_Period or event.text() == "。":
            self._sequence_step(1)
        else:
            super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._view.fit_in_view()

    # ── Cleanup ─────────────────────────────────────────────────

    def _schedule_fit(self, interval_ms: int = 10) -> None:
        """Schedule a cancellable fit-in-view pass after layout settles."""
        from AssetsManager.core.timers import TimerHandle

        self._fit_timers = [timer for timer in self._fit_timers if timer.is_active()]
        self._fit_timers.append(
            TimerHandle.schedule(self, interval_ms, self._view.fit_in_view)
        )

    def _cancel_fit_timers(self) -> None:
        for timer in self._fit_timers:
            timer.cancel()
        self._fit_timers.clear()

    def closeEvent(self, event):
        self._closed = True
        # Cooperative-cancel every in-flight decode and drain the private pool
        # (bounded) so no background callback can touch the overlay while it
        # is being destroyed. Cancelled tasks observe their token and never
        # emit; delivery slots additionally reject by generation / _closed.
        self._cancel_pending_decode()
        self._decode_pool.close(
            _VIEWER_DRAIN_TIMEOUT_MS,
            owner_label="ImageViewer decode",
        )
        self._slideshow_timer.stop()
        self._sequence_timer.stop()
        self._cancel_fit_timers()
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


def open_image_viewer(parent, path: str, *, library_root: str | None = None):
    """Open an image in the floating viewer overlay."""
    viewer = ImageViewerOverlay(parent)
    viewer.load_image(path, library_root=library_root)
    viewer.show_overlay()
    return viewer
