from AssetsManager.widgets.tray import SystemTrayManager


def test_tray_availability_tracks_qt_capability(monkeypatch):
    monkeypatch.setattr(
        "AssetsManager.widgets.tray.QSystemTrayIcon.isSystemTrayAvailable", lambda: False
    )

    tray = SystemTrayManager()

    assert not tray.is_available
