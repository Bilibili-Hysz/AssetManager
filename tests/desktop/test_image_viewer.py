import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.panels.image_viewer import ImageViewerOverlay


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
