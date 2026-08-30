"""UndoPanelDialog — offscreen panel behavior (H1-b E-C2).

The dialog is a view over ``UndoService.history_snapshot`` plus a thin
launcher for ``perform_undo``/``perform_redo``; both services are mocked, so
these tests cover the panel wiring (rows, buttons, refresh event, failure
hint) rather than undo semantics (covered in tests/unit/test_undo_service.py
and test_undo_history_snapshot.py).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from AssetsManager import i18n
from AssetsManager.application.undo_service import UndoHistoryItem
from AssetsManager.dialogs.undo_panel import UndoPanelDialog


@pytest.fixture(autouse=True)
def _chinese_ui():
    """Pin the UI language so the translated-label assertions are stable."""
    original = i18n.current_language()
    i18n.set_language("zh")
    yield
    i18n.set_language(original)


def _item(**overrides) -> UndoHistoryItem:
    defaults = dict(
        entry_type="delete",
        target="/lib/hero.png",
        recorded_at=1700000000.0,
        degraded=False,
        failed=False,
        is_batch=False,
        child_count=0,
        has_backup=True,
        origin="undo",
    )
    defaults.update(overrides)
    return UndoHistoryItem(**defaults)


def _mock_runtime(snapshot):
    undo_service = MagicMock()
    undo_service.history_snapshot.return_value = list(snapshot)
    undo_service.perform_undo.return_value = True
    undo_service.perform_redo.return_value = True
    file_operations = MagicMock()
    session = SimpleNamespace(root_str="/lib", event_token="token-1")
    services = SimpleNamespace(
        undo_service=undo_service, file_operation_service=file_operations)
    return SimpleNamespace(services=services, session=session), undo_service


def test_panel_lists_snapshot_rows_with_retention_hint():
    app = QApplication.instance() or QApplication([])
    runtime, _undo = _mock_runtime([
        _item(),
        _item(entry_type="rename", target="/lib/a.png -> /lib/b.png",
              has_backup=False),
    ])
    dialog = UndoPanelDialog(runtime)

    try:
        dialog.show()
        app.processEvents()

        assert dialog.windowTitle() == "撤销历史"
        assert dialog._table.rowCount() == 2
        # Newest (first snapshot item) on top; translated labels resolved.
        assert dialog._table.item(0, 1).text() == "/lib/hero.png"
        assert "90" in dialog._table.item(0, 4).text()
        assert dialog._table.item(1, 4).text() == "—"
        assert dialog._undo_btn.isEnabled()
        assert not dialog._redo_btn.isEnabled()
        assert dialog._status_label.text() == ""
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_undo_button_calls_perform_undo_and_publishes_refresh(monkeypatch):
    app = QApplication.instance() or QApplication([])
    runtime, undo = _mock_runtime([_item()])
    publish = MagicMock()
    monkeypatch.setattr(
        "AssetsManager.dialogs.undo_panel.get_event_bus",
        lambda: SimpleNamespace(publish=publish),
    )
    dialog = UndoPanelDialog(runtime)

    try:
        dialog._undo_btn.click()
        app.processEvents()

        undo.perform_undo.assert_called_once_with(
            runtime.services.file_operation_service, "/lib")
        # One session-scoped refresh event after a successful step.
        assert publish.call_count == 1
        event = publish.call_args[0][0]
        assert event.library_root == "/lib"
        assert event.session_token == "token-1"
        assert event.kind == "undo"
        assert dialog._status_label.text() == ""
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_failed_undo_keeps_entry_and_shows_inline_hint(monkeypatch):
    app = QApplication.instance() or QApplication([])
    runtime, undo = _mock_runtime([_item()])
    undo.perform_undo.return_value = False
    publish = MagicMock()
    monkeypatch.setattr(
        "AssetsManager.dialogs.undo_panel.get_event_bus",
        lambda: SimpleNamespace(publish=publish),
    )
    dialog = UndoPanelDialog(runtime)

    try:
        dialog._undo_btn.click()
        app.processEvents()

        assert dialog._status_label.text() == "上一步撤销/重做未能执行，该条目仍保留在列表中。"
        assert publish.call_count == 0  # no refresh event on failure
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_redo_button_calls_perform_redo():
    app = QApplication.instance() or QApplication([])
    runtime, undo = _mock_runtime([_item(origin="redo")])
    dialog = UndoPanelDialog(runtime)

    try:
        assert dialog._redo_btn.isEnabled()
        dialog._redo_btn.click()
        app.processEvents()

        undo.perform_redo.assert_called_once_with(
            runtime.services.file_operation_service, "/lib")
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_empty_history_shows_empty_state_and_disables_buttons():
    app = QApplication.instance() or QApplication([])
    runtime, _undo = _mock_runtime([])
    dialog = UndoPanelDialog(runtime)

    try:
        dialog.show()
        app.processEvents()

        assert dialog._table.rowCount() == 0
        assert not dialog._undo_btn.isEnabled()
        assert not dialog._redo_btn.isEnabled()
        assert dialog._status_label.text() == "本会话还没有撤销历史。"
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_snapshot_failure_degrades_to_empty_state():
    app = QApplication.instance() or QApplication([])
    runtime, undo = _mock_runtime([])
    undo.history_snapshot.side_effect = RuntimeError("session closed")
    dialog = UndoPanelDialog(runtime)

    try:
        dialog._refresh()  # must not raise

        assert dialog._table.rowCount() == 0
        assert dialog._status_label.text() == "本会话还没有撤销历史。"
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


@pytest.mark.parametrize(
    ("overrides", "expected_fragment"),
    [
        ({"degraded": True}, "恢复不完整"),
        ({"failed": True}, "上次执行失败"),
        ({"is_batch": True, "child_count": 4, "has_backup": True}, "4 项"),
    ],
)
def test_row_state_annotations(overrides, expected_fragment):
    app = QApplication.instance() or QApplication([])
    runtime, _undo = _mock_runtime([_item(**overrides)])
    dialog = UndoPanelDialog(runtime)

    try:
        row_text = " | ".join(
            dialog._table.item(0, column).text() or ""
            for column in range(dialog._table.columnCount())
        )
        assert expected_fragment in row_text
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
