"""D4 dock chrome refresh tests — three signals, one rebuild per frame."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDockWidget, QWidget

from AssetsManager import dock_factory


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_schedule_dock_refresh_coalesces_three_signals_into_one_frame(monkeypatch):
    app = _app()
    dock = QDockWidget()
    dock.setWidget(QWidget())
    dock_factory._DOCK_TITLES[dock] = ("dock.sidebar", "Sidebar", [])

    monkeypatch.setattr(dock_factory, "_dock_refresh_pending", False)
    monkeypatch.setattr(dock_factory, "_dock_refresh_handle", None)

    calls: list[str] = []
    original_build = dock_factory._build_title_bar

    def fake_build(title: str, target_dock, buttons):
        calls.append(title)
        return original_build(title, target_dock, buttons)

    monkeypatch.setattr(dock_factory, "_build_title_bar", fake_build)

    try:
        # Theme + language + scale change in the same settings-apply burst.
        dock_factory._schedule_dock_refresh("Navy")
        dock_factory._schedule_dock_refresh("zh")
        dock_factory._schedule_dock_refresh(1.5)
        assert calls == []  # deferred to the next event-loop frame

        app.processEvents()
        assert len(calls) == 1  # one rebuild covers all three signals

        app.processEvents()
        assert len(calls) == 1  # no second rebuild without a new signal
        assert dock_factory._dock_refresh_pending is False
        assert dock_factory._dock_refresh_handle is None
    finally:
        dock_factory._DOCK_TITLES.pop(dock, None)
        dock_factory._dock_refresh_pending = False
        dock_factory._dock_refresh_handle = None
        dock.deleteLater()
        app.processEvents()
