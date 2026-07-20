"""On-demand QR output for a Share System URL."""
from io import BytesIO

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout

from AssetsManager import i18n
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.dialogs.tabbed_dialog import TabbedDialog

tr = i18n.tr


def qr_pixmap(url: str) -> QPixmap | None:
    """Return a scan-friendly QR image, or None when generation is unavailable."""
    try:
        import segno

        buffer = BytesIO()
        segno.make_qr(url, error="H").save(buffer, kind="png", scale=10, border=2)
        image = QImage()
        if not image.loadFromData(buffer.getvalue()) or image.isNull():
            return None
        return QPixmap.fromImage(image)
    except (ImportError, ValueError):
        return None


class ShareQrDialog(TabbedDialog):
    """Show a QR code only when the owner asks to share a known URL."""

    def __init__(self, parent=None, url: str = ""):
        self._url = url
        self._qr_pixmap = qr_pixmap(url) if url else None
        super().__init__(parent, title=tr("sharing.qr.title"), min_size=(400, 470))

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(scaled_px(16), scaled_px(16), scaled_px(16), scaled_px(16))
        layout.setSpacing(scaled_px(12))
        layout.addWidget(self.make_heading(tr("sharing.qr.title")))
        layout.addWidget(self.make_muted(tr("sharing.qr.hint")))

        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setAccessibleName(tr("sharing.qr.image"))
        if self._qr_pixmap is None:
            self._image_label.setText(tr("sharing.qr.unavailable"))
        else:
            self._image_label.setPixmap(self._qr_pixmap.scaled(
                scaled_px(240), scaled_px(240), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(self._image_label)

        self._url_label = self.make_label(self._url)
        self._url_label.setWordWrap(True)
        self._url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._url_label)

        actions = QHBoxLayout()
        self._copy_link_btn = self.make_primary_btn(tr("sharing.qr.copy_link"), self._copy_link)
        self._copy_image_btn = self.make_secondary_btn(tr("sharing.qr.copy_image"), self._copy_image)
        self._copy_image_btn.setEnabled(self._qr_pixmap is not None)
        self._close_btn = self.make_secondary_btn(tr("dialog.close"), self.accept)
        actions.addWidget(self._copy_link_btn)
        actions.addWidget(self._copy_image_btn)
        actions.addStretch()
        actions.addWidget(self._close_btn)
        layout.addLayout(actions)

    def _copy_link(self):
        QApplication.clipboard().setText(self._url)
        self._copy_link_btn.setText(tr("sharing.qr.copied"))
        QTimer.singleShot(1500, lambda: self._copy_link_btn.setText(tr("sharing.qr.copy_link")))

    def _copy_image(self):
        if self._qr_pixmap is None:
            return
        QApplication.clipboard().setPixmap(self._qr_pixmap)
        self._copy_image_btn.setText(tr("sharing.qr.copied"))
        QTimer.singleShot(1500, lambda: self._copy_image_btn.setText(tr("sharing.qr.copy_image")))
