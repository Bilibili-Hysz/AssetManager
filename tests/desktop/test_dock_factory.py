"""D4 dock chrome refresh tests — three signals, one rebuild per frame."""


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


def test_custom_widget_dock_keeps_title_on_refresh():
    app = _app()
    widget = QWidget()
    dock = dock_factory.create("Downloads", None, widget=widget)
    try:
        assert dock_factory._DOCK_TITLES[dock][0] == ""
        assert dock_factory._DOCK_TITLES[dock][1] == "Downloads"
        dock_factory._run_dock_refresh()
        assert dock_factory._DOCK_TITLES[dock][1] == "Downloads"
    finally:
        dock_factory._DOCK_TITLES.pop(dock, None)
        dock.deleteLater()
        app.processEvents()


def test_dock_title_bar_standardization():
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QLabel, QPushButton
    from AssetsManager.core import themes
    from AssetsManager.core.ui_scale import scaled_px

    app = _app()
    widget = QWidget()
    gear_btn = QPushButton()
    gear_btn.setProperty("semanticIcon", "settings")
    widget.title_bar_buttons = lambda: [gear_btn]

    dock = dock_factory.create("Inspector", None, widget=widget)
    try:
        title_bar = dock.titleBarWidget()
        assert title_bar is not None

        labels = title_bar.findChildren(QLabel)
        assert len(labels) >= 1
        title_label = labels[0]
        # 1. No hardcoded double space in dock title
        assert title_label.text() == "Inspector"
        assert not title_label.text().startswith("  ")

        # 2. Standardized buttons
        buttons = title_bar.findChildren(QPushButton)
        assert len(buttons) >= 3
        expected_btn_size = QSize(
            scaled_px(themes.metrics("hit_area")),
            scaled_px(themes.metrics("hit_area")),
        )
        expected_icon_size = QSize(
            scaled_px(themes.metrics("icon_sm")),
            scaled_px(themes.metrics("icon_sm")),
        )
        r_sm = scaled_px(int(themes.prop("border_radius", "sm")))
        for btn in buttons:
            assert btn.size() == expected_btn_size
            assert btn.iconSize() == expected_icon_size
            assert f"border-radius: {r_sm}px" in btn.styleSheet()
    finally:
        dock_factory._DOCK_TITLES.pop(dock, None)
        dock.deleteLater()
        app.processEvents()

