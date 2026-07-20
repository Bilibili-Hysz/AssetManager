import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QAbstractAnimation
from PySide6.QtWidgets import QApplication
from unittest.mock import Mock

from AssetsManager.widgets.tab_container import TabContainer


def test_tab_title_updates_current_index_after_close(tmp_path):
    QApplication.instance() or QApplication([])
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    container = TabContainer()
    try:
        first_panel = container.current_file_list()
        assert first_panel is not None
        first_panel.navigate_to(str(first), set_root=True)

        container._add_tab(str(second))
        second_panel = container.current_file_list()
        assert second_panel is not None

        container._close_tab(0)
        second_panel.folder_entered.emit(str(second))

        assert container._tabs.tabText(0) == "second"
    finally:
        container.close()


def test_closing_tab_runs_full_panel_shutdown(tmp_path):
    QApplication.instance() or QApplication([])
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    container = TabContainer()
    try:
        first_panel = container.current_file_list()
        assert first_panel is not None
        container._add_tab(str(second))
        shutdown = Mock(wraps=first_panel.shutdown)
        first_panel.shutdown = shutdown

        container._close_tab(0)

        shutdown.assert_called_once()
    finally:
        container.close()


def test_panel_shutdown_stops_grid_animation_and_thumbnail_delivery_timers():
    QApplication.instance() or QApplication([])
    container = TabContainer()
    panel = container.current_file_list()
    assert panel is not None
    try:
        panel._grid_widget._anim_timer.start()
        panel._thumbnail_delivery._timer.start()
        panel._grid_widget._pending_presentation = (1, [0], True)
        panel._zoom_anim = Mock()
        panel._scroll_anim = Mock()

        panel.shutdown()

        assert not panel._grid_widget._anim_timer.isActive()
        assert not panel._thumbnail_delivery._timer.isActive()
        assert panel._grid_widget._pending_presentation is None
        panel._zoom_anim.stop.assert_called_once()
        panel._scroll_anim.stop.assert_called_once()
    finally:
        container.close()


def test_container_panel_entrance_animation_is_owned_and_stopped_on_shutdown():
    QApplication.instance() or QApplication([])
    container = TabContainer()
    panel = container.current_file_list()
    assert panel is not None
    try:
        panel._animate_in()

        assert panel._show_anim.parent() is panel
        panel.shutdown()

        assert panel._show_anim.state() == QAbstractAnimation.State.Stopped
    finally:
        container.close()


def test_container_panel_zoom_and_scroll_animations_are_panel_owned(monkeypatch):
    from AssetsManager.panels import file_list

    parents = []

    class Animation:
        class State:
            Running = object()

        def __init__(self, parent):
            parents.append(parent)
            self.valueChanged = Mock()
            self.finished = Mock()
            self.stop_calls = 0

        def state(self):
            return None

        def setDuration(self, _duration):
            pass

        def setEasingCurve(self, _curve):
            pass

        def setStartValue(self, _value):
            pass

        def setEndValue(self, _value):
            pass

        def start(self):
            pass

        def stop(self):
            self.stop_calls += 1

    monkeypatch.setattr(file_list, "QVariantAnimation", Animation)
    QApplication.instance() or QApplication([])
    container = TabContainer()
    panel = container.current_file_list()
    assert panel is not None
    zoom_event = type("_Event", (), {"angleDelta": lambda _self: type("_Delta", (), {"y": lambda _delta: 1})()})()
    try:
        panel._on_zoom_changed("128px")
        panel._smooth_scroll(zoom_event)

        assert parents == [panel, panel]
        panel.shutdown()

        assert panel._zoom_anim.stop_calls == 1
        assert panel._scroll_anim.stop_calls == 1
    finally:
        container.close()
