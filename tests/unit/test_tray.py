from PySide6.QtWidgets import QApplication

from AssetsManager.widgets.tray import SystemTrayManager


def test_tray_availability_tracks_qt_capability(monkeypatch):
    QApplication.instance() or QApplication([])  # QSystemTrayIcon needs an app
    monkeypatch.setattr(
        "AssetsManager.widgets.tray.QSystemTrayIcon.isSystemTrayAvailable", lambda: False
    )

    tray = SystemTrayManager()

    assert not tray.is_available
