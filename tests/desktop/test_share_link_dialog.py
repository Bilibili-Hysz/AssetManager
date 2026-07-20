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


def test_share_link_dialog_normalizes_legacy_and_multi_path_inputs():
    legacy = ShareLinkDialog(path="asset.txt", server=Mock(_port=8080))
    multiple = ShareLinkDialog(paths=["one.txt", "two.txt"], server=Mock(_port=8080))
    try:
        assert legacy._paths == ["asset.txt"]
        assert multiple._paths == ["one.txt", "two.txt"]
    finally:
        legacy.close()
        multiple.close()
        legacy.deleteLater()
        multiple.deleteLater()


def test_share_link_dialog_disables_unscoped_creation():
    dialog = ShareLinkDialog(server=Mock(_port=8080))
    try:
        assert not dialog._create_btn.isEnabled()
        assert not dialog._selection_hint.isHidden()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_share_link_result_mode_requires_explicit_create_another():
    dialog = ShareLinkDialog(paths=["one.txt", "two.txt"], server=Mock(_port=8080))
    try:
        dialog._on_create_result(True, {"url": "http://share.test/s/1"})

        assert dialog.get_share_url() == "http://share.test/s/1"
        assert dialog._create_btn.isHidden()
        assert not dialog._create_another_btn.isHidden()

        dialog._create_another()

        assert dialog.get_share_url() is None
        assert not dialog._create_btn.isHidden()
        assert dialog._create_another_btn.isHidden()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_share_link_ignores_result_from_replaced_server():
    server = Mock(_port=8080)
    dialog = ShareLinkDialog(paths=["asset.txt"], server=server)
    try:
        dialog._creating = True
        dialog._server = Mock(_port=8081)
        dialog._on_create_result(True, {"url": "http://share.test/s/1"}, server)

        assert dialog.get_share_url() is None
        assert dialog._creating is True
    finally:
        dialog.close()
        dialog.deleteLater()
