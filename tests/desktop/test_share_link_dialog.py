import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit

from AssetsManager.dialogs.share_link_dialog import ShareLinkDialog


def test_share_link_dialog_keeps_password_input_as_line_edit():
    app = QApplication.instance() or QApplication([])
    dialog = ShareLinkDialog(path="asset.txt", server=Mock(_port=8080))
    try:
        assert isinstance(dialog._password_input, QLineEdit)
        assert dialog._password_input.echoMode() == QLineEdit.EchoMode.Password
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
