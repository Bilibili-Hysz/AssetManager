"""Accessibility baseline tests for the self-drawn file grid canvas.

The grid paints every card itself, so assistive technology cannot see
individual files (unlike the Details QTableView). These tests pin the honest
baseline: an i18n accessible name, a live item/selection description, and one
debounced QAccessible.Alert per settled selection change.
"""
from unittest.mock import Mock

import pytest
from shiboken6 import Shiboken

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAccessible, QKeyEvent
from PySide6.QtWidgets import QApplication

from AssetsManager.i18n import tr
from AssetsManager.panels.file_list._grid_layout import GridLayout
from AssetsManager.panels.file_list._grid_widget import FileListGridWidget

_widgets: list[FileListGridWidget] = []


@pytest.fixture(autouse=True)
def _cleanup_widgets():
    yield
    for widget in _widgets:
        if Shiboken.isValid(widget):
            # stop_animations also cancels pending debounced announcements.
            widget.stop_animations()
            widget.deleteLater()
    if QApplication.instance() is not None:
        QApplication.processEvents()
    _widgets.clear()


def _grid() -> tuple[QApplication, FileListGridWidget]:
    app = QApplication.instance() or QApplication([])
    widget = FileListGridWidget()
    widget.set_layout_ref(GridLayout())
    _widgets.append(widget)
    return app, widget


def test_grid_accessible_name_and_description_track_items_and_selection():
    _app, widget = _grid()

    assert widget.accessibleName() == tr("filelist.grid.a11y.name")
    assert widget.accessibleDescription() == tr("filelist.grid.a11y.description", total=0)

    widget.update_layout(5, 400)
    assert widget.accessibleDescription() == tr("filelist.grid.a11y.description", total=5)

    widget.set_selection_rows({1, 3})
    assert widget.accessibleDescription() == tr(
        "filelist.grid.a11y.description_selected", total=5, selected=2)

    widget.update_layout(8, 400)
    assert widget.accessibleDescription() == tr(
        "filelist.grid.a11y.description_selected", total=8, selected=2)

    widget.clear_selection()
    assert widget.accessibleDescription() == tr("filelist.grid.a11y.description", total=8)


def test_grid_model_reset_clears_selection_from_accessible_description():
    _app, widget = _grid()
    widget._model_rows = 4
    widget._selection = {0}
    widget._update_a11y_description()
    assert widget.accessibleDescription() == tr(
        "filelist.grid.a11y.description_selected", total=4, selected=1)

    widget._on_model_reset()

    assert widget._selection == set()
    assert widget.accessibleDescription() == tr("filelist.grid.a11y.description", total=4)


def test_grid_selection_announce_emits_single_qaccessibility_alert(monkeypatch):
    app, widget = _grid()
    widget._model = Mock()
    widget._a11y_debounce_ms = 0
    calls: list[object] = []
    monkeypatch.setattr(QAccessible, "updateAccessibility", calls.append)

    widget.set_selection_rows({1})
    app.processEvents()

    assert len(calls) == 1
    assert calls[0].type() == QAccessible.Event.Alert


def test_grid_batch_selection_announces_one_summary(monkeypatch):
    app, widget = _grid()
    widget._model = Mock()
    widget._a11y_debounce_ms = 0
    calls: list[object] = []
    monkeypatch.setattr(QAccessible, "updateAccessibility", calls.append)

    # Rubber-band style: several rapid selection updates before the loop spins.
    widget.set_selection_rows({0})
    widget.set_selection_rows({0, 1})
    widget.set_selection_rows({0, 1, 2})
    app.processEvents()

    assert len(calls) == 1


def test_grid_clearing_selection_does_not_announce(monkeypatch):
    app, widget = _grid()
    widget._model = Mock()
    widget._a11y_debounce_ms = 0
    calls: list[object] = []
    monkeypatch.setattr(QAccessible, "updateAccessibility", calls.append)

    widget.clear_selection()
    app.processEvents()

    assert calls == []


def test_grid_announce_failure_does_not_propagate(monkeypatch):
    app, widget = _grid()
    widget._model = Mock()
    widget._a11y_debounce_ms = 0

    def _boom(_event):
        raise RuntimeError("no accessible backend")

    monkeypatch.setattr(QAccessible, "updateAccessibility", _boom)

    widget.set_selection_rows({0})
    app.processEvents()  # must not raise


def test_grid_keyboard_selection_updates_a11y_description():
    app, widget = _grid()
    widget._model_rows = 4
    widget.update_layout(4, 800)
    widget._selection = {0}
    widget._last_click_row = 0

    # Keyboard path (eventFilter/arrow keys) must keep working and stay in sync.
    widget.keyPressEvent(QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier))

    assert widget._selection == {1}
    assert widget.accessibleDescription() == tr(
        "filelist.grid.a11y.description_selected", total=4, selected=1)
    app.processEvents()
