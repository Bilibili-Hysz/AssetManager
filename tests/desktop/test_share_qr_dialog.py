import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from AssetsManager.dialogs.share_qr_dialog import ShareQrDialog, qr_pixmap


def test_qr_pixmap_generates_for_share_url():
    _app = QApplication.instance() or QApplication([])
    pixmap = qr_pixmap("http://share.test/s/1")

    assert pixmap is not None
    assert not pixmap.isNull()


def test_qr_dialog_exposes_copy_actions():
    app = QApplication.instance() or QApplication([])
    dialog = ShareQrDialog(url="http://share.test/s/1")
    try:
        assert dialog._url_label.text() == "http://share.test/s/1"
        assert dialog._copy_link_btn.isEnabled()
        assert dialog._copy_image_btn.isEnabled() == (dialog._qr_pixmap is not None)
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
