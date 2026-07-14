import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
