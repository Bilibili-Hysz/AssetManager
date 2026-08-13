import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget

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
