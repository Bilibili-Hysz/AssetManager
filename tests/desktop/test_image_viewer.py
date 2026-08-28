import threading
import time


from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.panels import image_viewer as viewer_module
from AssetsManager.panels.image_viewer import ImageViewerOverlay


def _wait_for(app, condition, timeout=5.0):
    """Pump the event loop until *condition* holds (queued decode delivery)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.005)
    app.processEvents()
    return condition()


def test_image_viewer_tracks_host_window_and_cleans_up():
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    host.resize(400, 300)
    viewer = ImageViewerOverlay(host)
    try:
        viewer.show_overlay()
        assert viewer._host_window is not None
        viewer.close()
        assert viewer._host_window is None
    finally:
        host.deleteLater()
        app.processEvents()


def _make_png(path, w, h):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(Qt.GlobalColor.white)
    assert img.save(str(path)), f"failed to save test image {path}"
    return path


def test_slideshow_toggle_starts_and_stops_timer(tmp_path):
    app = QApplication.instance() or QApplication([])
    _make_png(tmp_path / "a.png", 64, 64)
    host = QWidget()
    viewer = ImageViewerOverlay(host)
    try:
        viewer.load_image(str(tmp_path / "a.png"))
        assert not viewer._slideshow_active()
        viewer._toggle_slideshow()
        assert viewer._slideshow_active()
        viewer._toggle_slideshow()
        assert not viewer._slideshow_active()
    finally:
        viewer.close()
        host.deleteLater()
        app.processEvents()


def test_rotate_swaps_dimensions_and_tracks_rotation(tmp_path):
    app = QApplication.instance() or QApplication([])
    _make_png(tmp_path / "wide.png", 64, 32)
    host = QWidget()
    viewer = ImageViewerOverlay(host)
    try:
        viewer.load_image(str(tmp_path / "wide.png"))
        assert _wait_for(app, lambda: viewer._state == "ready")
        assert viewer._pixmap is not None
        assert (viewer._pixmap.width(), viewer._pixmap.height()) == (64, 32)

        viewer._rotate(90)
        assert viewer._rotation == 90
        assert (viewer._pixmap.width(), viewer._pixmap.height()) == (32, 64)

        viewer._rotate(-90)
        assert viewer._rotation == 0
        assert (viewer._pixmap.width(), viewer._pixmap.height()) == (64, 32)
    finally:
        viewer.close()
        host.deleteLater()
        app.processEvents()


def test_copy_to_clipboard_sets_current_pixmap(tmp_path):
    app = QApplication.instance() or QApplication([])
    _make_png(tmp_path / "copy.png", 64, 32)
    host = QWidget()
    viewer = ImageViewerOverlay(host)
    try:
        viewer.load_image(str(tmp_path / "copy.png"))
        assert _wait_for(app, lambda: viewer._state == "ready")
        viewer._copy_to_clipboard()
        cb = app.clipboard().pixmap()
        assert cb is not None and not cb.isNull()
        assert (cb.width(), cb.height()) == (64, 32)
    finally:
        viewer.close()
        host.deleteLater()
        app.processEvents()


def test_save_pixmap_to_writes_valid_image(tmp_path):
    app = QApplication.instance() or QApplication([])
    _make_png(tmp_path / "src.png", 32, 16)
    host = QWidget()
    viewer = ImageViewerOverlay(host)
    try:
        viewer.load_image(str(tmp_path / "src.png"))
        assert _wait_for(app, lambda: viewer._state == "ready")
        out = tmp_path / "out.png"
        assert viewer._save_pixmap_to(str(out))
        assert out.exists() and out.stat().st_size > 0
        reloaded = QImage(str(out))
        assert not reloaded.isNull()
        assert (reloaded.width(), reloaded.height()) == (32, 16)
    finally:
        viewer.close()
        host.deleteLater()
        app.processEvents()


def test_save_pixmap_to_returns_false_without_image(tmp_path):
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    viewer = ImageViewerOverlay(host)
    try:
        assert not viewer._save_pixmap_to(str(tmp_path / "none.png"))
        assert not (tmp_path / "none.png").exists()
    finally:
        viewer.close()
        host.deleteLater()
        app.processEvents()


def test_read_exif_extracts_make(tmp_path):
    from PIL import Image

    jpg = tmp_path / "with-exif.jpg"
    img = Image.new("RGB", (8, 8), "white")
    exif = Image.Exif()
    exif[271] = "TestCamera"  # Make
    img.save(str(jpg), exif=exif)

    result = ImageViewerOverlay._read_exif(str(jpg))
    assert result.get("Make") == "TestCamera"


def test_read_exif_returns_empty_for_plain_png(tmp_path):
    png = _make_png(tmp_path / "plain.png", 16, 16)
    assert ImageViewerOverlay._read_exif(str(png)) == {}


def test_toggle_exif_reads_current_image(tmp_path):
    app = QApplication.instance() or QApplication([])
    _make_png(tmp_path / "plain.png", 16, 16)
    host = QWidget()
    viewer = ImageViewerOverlay(host)
    try:
        viewer.load_image(str(tmp_path / "plain.png"))
        assert not viewer._show_exif
        viewer._toggle_exif()
        assert viewer._show_exif
        assert viewer._exif == {}  # plain PNG has no EXIF
        viewer._toggle_exif()
        assert not viewer._show_exif
    finally:
        viewer.close()
        host.deleteLater()
        app.processEvents()


def test_toggle_strip_and_index_mapping(tmp_path):
    app = QApplication.instance() or QApplication([])
    _make_png(tmp_path / "a.png", 16, 16)
    _make_png(tmp_path / "b.png", 16, 16)
    _make_png(tmp_path / "c.png", 16, 16)
    host = QWidget()
    viewer = ImageViewerOverlay(host)
    try:
        viewer.load_image(str(tmp_path / "a.png"))
        assert not viewer._show_strip
        assert viewer._strip_index_at(0) == -1  # hidden → no hit

        viewer._toggle_strip()
        assert viewer._show_strip
        sr = viewer._strip_rect()
        assert not sr.isNull()
        # Three images all fit: the window starts at index 0.
        assert viewer._strip_start_index() == 0
        first_center_x = sr.x() + scaled_px(4) + viewer._strip_thumb_w // 2
        assert viewer._strip_index_at(first_center_x) == 0
        assert viewer._strip_index_at(sr.right() + 100) == -1
        viewer._toggle_strip()
        assert not viewer._show_strip
    finally:
        viewer.close()
        host.deleteLater()
        app.processEvents()


def test_strip_and_exif_render_without_crash(tmp_path):
    app = QApplication.instance() or QApplication([])
    _make_png(tmp_path / "a.png", 16, 16)
    _make_png(tmp_path / "b.png", 16, 16)
    host = QWidget()
    viewer = ImageViewerOverlay(host)
    try:
        viewer.load_image(str(tmp_path / "a.png"))
        viewer._toggle_strip()
        viewer._toggle_exif()
        viewer.resize(800, 600)
        target = QPixmap(800, 600)
        viewer.render(target)  # exercises the strip + EXIF paint paths
    finally:
        viewer.close()
        host.deleteLater()
        app.processEvents()


# ── Async decode: no UI-thread blocking, stale-discard, failure paths ──

def test_large_image_open_is_async(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    png = _make_png(tmp_path / "big.png", 3000, 2000)
    started = threading.Event()
    release = threading.Event()
    real_decode = viewer_module._decode_image

    def slow_decode(path, max_dim):
        started.set()
        release.wait(5)
        return real_decode(path, max_dim)

    monkeypatch.setattr(viewer_module, "_decode_image", slow_decode)
    host = QWidget()
    viewer = ImageViewerOverlay(host)
    try:
        viewer.load_image(str(png))
        # load_image returned without blocking on the worker decode.
        assert started.wait(5), "decode task never reached the worker"
        assert viewer._state == "loading"
        release.set()
        assert _wait_for(app, lambda: viewer._state == "ready")
        assert viewer._pixmap is not None
        w, h = viewer._pixmap.width(), viewer._pixmap.height()
        assert w <= viewer_module.MAX_DIM and h <= viewer_module.MAX_DIM
        assert abs(w / h - 1.5) < 0.01  # 3000x2000 aspect preserved
    finally:
        viewer.close()
        host.deleteLater()
        app.processEvents()


def test_fast_paging_keeps_only_latest_image(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    a = _make_png(tmp_path / "a.png", 120, 40)
    b = _make_png(tmp_path / "b.png", 40, 120)
    gates: dict[str, threading.Event] = {}
    real_decode = viewer_module._decode_image

    def gated_decode(path, max_dim):
        gate = gates.setdefault(path, threading.Event())
        gate.wait(5)
        return real_decode(path, max_dim)

    monkeypatch.setattr(viewer_module, "_decode_image", gated_decode)
    host = QWidget()
    viewer = ImageViewerOverlay(host)
    try:
        viewer.load_image(str(a))
        viewer.load_image(str(b))  # supersedes a before a's decode finished
        assert viewer._current_path == str(b)
        assert viewer._state == "loading"
        # Wait until b's decode has reached the gated worker (a's task may have
        # been cancelled before it even started, leaving no gate behind).
        assert _wait_for(app, lambda: str(b) in gates)
        for gate in gates.values():
            gate.set()
        assert _wait_for(app, lambda: viewer._state == "ready")
        assert viewer._current_path == str(b)
        pm = viewer._pixmap
        assert pm is not None
        assert (pm.width(), pm.height()) == (40, 120)
        # The stale a decode finishing afterwards must not overwrite b.
        for gate in gates.values():
            gate.set()
        app.processEvents()
        time.sleep(0.05)
        app.processEvents()
        assert viewer._current_path == str(b)
        pm = viewer._pixmap
        assert pm is not None
        assert (pm.width(), pm.height()) == (40, 120)
    finally:
        viewer.close()
        host.deleteLater()
        app.processEvents()


def test_decode_failure_shows_error_state(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    _make_png(tmp_path / "bad.png", 16, 16)
    monkeypatch.setattr(viewer_module, "_decode_image", lambda path, max_dim: None)
    host = QWidget()
    viewer = ImageViewerOverlay(host)
    try:
        viewer.load_image(str(tmp_path / "bad.png"))
        assert _wait_for(app, lambda: viewer._state == "error")
        assert viewer._pixmap is None
    finally:
        viewer.close()
        host.deleteLater()
        app.processEvents()


def test_close_cancels_inflight_decode_and_drains_bounded(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(viewer_module, "_VIEWER_DRAIN_TIMEOUT_MS", 200)
    png = _make_png(tmp_path / "img.png", 64, 64)
    entered = threading.Event()
    release = threading.Event()
    real_decode = viewer_module._decode_image

    def blocking_decode(path, max_dim):
        entered.set()
        release.wait(10)
        return real_decode(path, max_dim)

    monkeypatch.setattr(viewer_module, "_decode_image", blocking_decode)
    host = QWidget()
    viewer = ImageViewerOverlay(host)
    viewer.load_image(str(png))
    assert entered.wait(5), "decode task never reached the worker"
    from AssetsManager.core.workers import retained_pool_count

    initial_retained = retained_pool_count()
    start = time.monotonic()
    viewer.close()  # cancel + bounded drain, then reaper ownership on timeout
    assert time.monotonic() - start < 2.0
    assert viewer._closed
    assert retained_pool_count() == initial_retained + 1
    # In-flight decode finishes after close: its cancelled token must suppress
    # delivery, so nothing gets applied to the (already closed) viewer.
    release.set()
    assert _wait_for(app, lambda: retained_pool_count() == initial_retained)
    assert viewer._state == "loading"
    assert viewer._pixmap is None
    host.deleteLater()
    app.processEvents()


def test_strip_paint_never_decodes_synchronously(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    _make_png(tmp_path / "a.png", 16, 16)
    _make_png(tmp_path / "b.png", 16, 16)
    _make_png(tmp_path / "c.png", 16, 16)
    real_decode = viewer_module._decode_image
    gate = threading.Event()
    calls: list[tuple[str, int]] = []

    def gated_decode(path, max_dim):
        calls.append((path, max_dim))
        gate.wait(5)
        return real_decode(path, max_dim)

    host = QWidget()
    viewer = ImageViewerOverlay(host)
    try:
        # Load the center image with the real decoder first.
        viewer.load_image(str(tmp_path / "a.png"))
        assert _wait_for(app, lambda: viewer._state == "ready")
        # From here on, every strip prefetch decode goes through the gate so we
        # can prove paintEvent neither performs nor waits for any decode.
        monkeypatch.setattr(viewer_module, "_decode_image", gated_decode)
        viewer._toggle_strip()
        viewer.resize(800, 600)
        target = QPixmap(800, 600)
        viewer.render(target)  # must NOT decode into _strip_thumbs
        assert viewer._strip_thumbs == {}
        assert len(viewer._strip_pending) > 0  # async prefetch was submitted
        # Deliver the prefetch: thumbnails arrive asynchronously via the pool.
        gate.set()
        assert _wait_for(app, lambda: len(viewer._strip_thumbs) >= 3)
        assert calls  # strip decodes ran on the worker using thumb size
        thumb_sizes = {max_dim for _path, max_dim in calls}
        assert thumb_sizes == {viewer._strip_thumb_w}
    finally:
        viewer.close()
        host.deleteLater()
        app.processEvents()


def test_zoom_and_scene_after_async_load(tmp_path):
    app = QApplication.instance() or QApplication([])
    _make_png(tmp_path / "z.png", 64, 32)
    host = QWidget()
    viewer = ImageViewerOverlay(host)
    try:
        viewer.load_image(str(tmp_path / "z.png"))
        assert _wait_for(app, lambda: viewer._state == "ready")
        assert viewer._pixmap_item is not None
        assert not viewer._scene.itemsBoundingRect().isEmpty()
        viewer._view.reset_zoom()
        viewer._view.scale(2.0, 2.0)
        assert abs(viewer._view.transform().m11() - 2.0) < 1e-6
        viewer._view.reset_zoom()
        viewer._view.fit_in_view()
        assert viewer._view.transform().m11() > 0
    finally:
        viewer.close()
        host.deleteLater()
        app.processEvents()
