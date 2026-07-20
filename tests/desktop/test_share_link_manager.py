import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from AssetsManager.dialogs.share_link_manager import ShareLinkManager


def test_share_actions_ignore_server_removed_after_load():
    app = QApplication.instance() or QApplication([])

    class _Server:
        _port = 8080

    manager = ShareLinkManager(server=_Server())
    try:
        manager._shares = [{"id": "share-id", "paths": ["asset.txt"]}]
        manager._server = None

        manager._copy_share_link(0)
        manager._delete_share(0)

        assert manager._status_label.text()
    finally:
        manager.close()
        manager.deleteLater()
        app.processEvents()
