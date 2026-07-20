import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from AssetsManager.domain.events import FileSystemChanged
from AssetsManager.panels.file_list import QWidgetFileListPanel


def test_file_list_ignores_foreign_session_file_events(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel._scoped_services = SimpleNamespace(session=SimpleNamespace(event_token="current"))
        starts = []
        monkeypatch.setattr(panel._file_op_timer, "start", lambda: starts.append("refresh"))

        panel._on_file_operation(FileSystemChanged(session_token="foreign"))
        panel._on_file_operation(FileSystemChanged(session_token="current"))

        assert starts == ["refresh"]
    finally:
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()


def test_file_list_shutdown_ignores_filesystem_watcher(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel._first_image_cache = Mock()
        panel._loader.clear_cache = Mock()
        panel._post_refresh = Mock()

        panel.shutdown()
        panel._fs_watcher.directoryChanged.emit("/library")

        panel._first_image_cache.clear.assert_not_called()
        panel._loader.clear_cache.assert_not_called()
        panel._post_refresh.assert_not_called()
    finally:
        panel.deleteLater()
        app.processEvents()
