import os
import warnings
from unittest.mock import Mock

import pytest
from shiboken6 import Shiboken

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QEnterEvent, QKeyEvent, QMouseEvent, QPainter, QPixmap, QPointingDevice
from PySide6.QtWidgets import QApplication

from AssetsManager.core.performance import PerformanceRecorder
from AssetsManager.panels.file_list._base import FileListPanel
from AssetsManager.panels.file_list._grid_widget import FileListGridWidget
from AssetsManager.panels.file_list._grid_layout import GridLayout
from AssetsManager.panels.file_list._model import FileSystemModel


_visible_grids: list[tuple[FileSystemModel, FileListGridWidget]] = []


@pytest.fixture(autouse=True)
def _shutdown_visible_grids():
    """Drain helper-owned workers before the shared QApplication pumps events."""
    yield
    for model, widget in _visible_grids:
        if Shiboken.isValid(widget):
            widget.stop_animations()
            widget.deleteLater()
        model.shutdown()
    _visible_grids.clear()


def _visible_grid(tmp_path):
    app = QApplication.instance() or QApplication([])
    (tmp_path / "asset.txt").write_text("asset", encoding="utf-8")
    model = FileSystemModel()
    model.set_directory(str(tmp_path))
    model._wait_for_scan()
    widget = FileListGridWidget()
    widget.set_model(model)
    widget.set_layout_ref(GridLayout())
    widget.resize(400, 300)
    widget.update_layout(model.rowCount(), widget.width())
    widget.show()
    app.processEvents()
    _visible_grids.append((model, widget))
    return app, model, widget


def test_grid_layout_uses_stable_left_aligned_column_tracks():
    layout = GridLayout()

    layout.compute(5, 320, item_size=88, spacing=12)

    assert layout.columns == 3
    assert [layout.rect_at(row).x() for row in range(3)] == [12, 112, 212]
    assert [layout.rect_at(row).x() for row in range(3, 5)] == [12, 112]


def test_grid_layout_hit_testing_keeps_blank_last_row_columns_empty():
    layout = GridLayout()
    layout.compute(5, 320, item_size=88, spacing=12)
    first = layout.rect_at(3)
    second = layout.rect_at(4)
    empty_column = layout.rect_at(2)

    assert layout.row_at(first.center().x(), first.center().y()) == 3
    assert layout.row_at(second.center().x(), second.center().y()) == 4
    assert layout.row_at(first.left() - 1, first.center().y()) == -1
    assert layout.row_at(empty_column.center().x(), first.center().y()) == -1


def test_grid_layout_recomputes_when_item_hint_changes_without_count_change():
    layout = GridLayout()
    assert layout.compute(20, 600, item_size=96, spacing=12, item_hint=QSize(120, 170))
    assert layout.item_hint == QSize(120, 170)

    assert layout.compute(20, 600, item_size=96, spacing=12, item_hint=QSize(180, 260))
    assert layout.item_hint == QSize(180, 260)


def test_grid_frame_records_scoped_counts_without_model_content(tmp_path):
    app, _model, widget = _visible_grid(tmp_path)
    recorder = PerformanceRecorder(enabled=True)
    widget.set_performance_context(recorder, "session-a", 7)

    widget.repaint()

    event = next(event for event in recorder.recent() if event.name == "grid.frame")
    assert event.session_token == "session-a"
    assert event.generation == 7
    assert event.path is None
    assert event.elapsed_ms >= 0
    assert set(event.attributes) == {
        "visible_item_count",
        "queued_entrance_count",
        "texture_cache_count",
        "texture_cache_bytes",
        "texture_build_count",
        "deferred_texture_count",
    }
    assert all(isinstance(value, int) and value >= 0 for value in event.attributes.values())
    assert event.attributes["texture_build_count"] == 0

    widget.invalidate_textures()
    widget.repaint()
    frame_event = [event for event in recorder.recent() if event.name == "grid.frame"][-1]
    assert frame_event.attributes["texture_build_count"] == 1
    assert frame_event.attributes["texture_cache_count"] >= frame_event.attributes["texture_build_count"]
    assert frame_event.attributes["texture_cache_bytes"] > 0
    texture_event = next(event for event in recorder.recent() if event.name == "grid.texture")
    assert (texture_event.session_token, texture_event.generation, texture_event.path) == ("session-a", 7, None)
    assert texture_event.elapsed_ms >= 0
    assert texture_event.attributes == {"row": 0}

    widget.deleteLater()
    app.processEvents()


def test_grid_full_invalidation_paces_visible_texture_rebuilds(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    for row in range(30):
        (tmp_path / f"asset-{row}.txt").write_text("asset", encoding="utf-8")
    model = FileSystemModel()
    model.set_directory(str(tmp_path))
    model._wait_for_scan()
    widget = FileListGridWidget()
    widget.set_model(model)
    widget.set_layout_ref(GridLayout())
    widget.resize(1200, 720)
    widget.update_layout(model.rowCount(), widget.width())
    widget.show()
    app.processEvents()
    recorder = PerformanceRecorder(enabled=True)
    widget.set_performance_context(recorder, "session-a", 7)
    render_item = Mock(side_effect=widget._render_item)
    monkeypatch.setattr(widget, "_render_item", render_item)

    widget.invalidate_textures()
    widget.repaint()

    from AssetsManager.panels.file_list._grid_widget import _FULL_REBUILD_TEXTURE_BUDGET
    frame = [event for event in recorder.recent() if event.name == "grid.frame"][-1]
    assert render_item.call_count == _FULL_REBUILD_TEXTURE_BUDGET
    assert frame.attributes["texture_build_count"] == _FULL_REBUILD_TEXTURE_BUDGET
    assert frame.attributes["deferred_texture_count"] > 0
    assert widget._full_rebuild_pending is True

    for _ in range(10):
        app.processEvents()
        widget.repaint()
        if not widget._full_rebuild_pending:
            break

    assert widget._full_rebuild_pending is False
    assert len(widget._dirty.intersection(set(range(30)))) == 0
    widget.deleteLater()
    model.shutdown()
    app.processEvents()


def test_grid_invalidation_records_aggregate_reason(tmp_path):
    app, _model, widget = _visible_grid(tmp_path)
    recorder = PerformanceRecorder(enabled=True)
    widget.set_performance_context(recorder, "session-a", 7)
    widget._textures[0] = object()

    widget.invalidate_textures()

    event = next(event for event in recorder.recent() if event.name == "grid.invalidation")
    assert (event.session_token, event.generation, event.path, event.elapsed_ms) == ("session-a", 7, None, 0.0)
    assert event.attributes == {"reason": "explicit", "item_count": 1, "texture_cache_count": 1}
    widget.deleteLater()
    app.processEvents()


def test_grid_thumbnail_delivery_telemetry_is_pathless(tmp_path):
    app, _model, widget = _visible_grid(tmp_path)
    recorder = PerformanceRecorder(enabled=True)
    widget.set_performance_context(recorder, "session-a", 7)

    widget.record_thumbnail_pixmap(widget.start_thumbnail_delivery_measurement())
    widget.record_thumbnail_batch(3)

    events = [event for event in recorder.recent() if event.name.startswith("grid.thumbnail_")]
    assert [(event.name, event.path, event.attributes) for event in events] == [
        ("grid.thumbnail_pixmap", None, {"count": 1}),
        ("grid.thumbnail_batch", None, {"count": 3}),
    ]
    assert all(event.session_token == "session-a" and event.generation == 7 for event in events)
    widget.deleteLater()
    app.processEvents()


def test_grid_thumbnail_commit_invalidates_once_and_starts_each_fade_once():
    app = QApplication.instance() or QApplication([])
    widget = FileListGridWidget()
    widget._reduce_motion = False
    widget._textures[2] = object()

    widget.commit_thumbnail_rows([2, 4])
    widget.commit_thumbnail_rows([2, 4])

    assert widget._dirty == {2, 4}
    assert widget._textures[2] is not None
    assert widget._thumb_opacity == {4: 0.0}
    assert widget._thumbnail_rows == {2, 4}
    assert widget._anim_timer.isActive()
    widget.deleteLater()
    app.processEvents()


def test_grid_full_invalidation_keeps_previous_textures_visible():
    widget = FileListGridWidget()
    cached = object()
    widget._model_rows = 3
    widget._textures[1] = cached

    widget.invalidate_textures()

    assert widget._textures[1] is cached
    assert widget._dirty == {0, 1, 2}
    assert widget._full_rebuild_pending is True


def test_grid_failed_dirty_replacement_keeps_previous_texture(tmp_path, monkeypatch):
    app, _model, widget = _visible_grid(tmp_path)
    cached = QPixmap(10, 10)
    widget._textures[0] = cached
    widget._dirty = {0}
    widget._full_rebuild_pending = False
    monkeypatch.setattr(widget, "_render_item", Mock(return_value=None))

    widget.repaint()

    assert widget._textures[0] is cached
    assert widget._dirty == {0}
    widget.deleteLater()
    app.processEvents()


def test_grid_frame_scheduler_coalesces_row_invalidations(monkeypatch):
    from AssetsManager.panels.file_list import _grid_widget

    widget = FileListGridWidget()
    widget.set_layout_ref(GridLayout())
    widget._model_rows = 4
    widget.update_layout(4, 400)
    widget._cancel_frame()
    scheduled = []
    monkeypatch.setattr(_grid_widget.QTimer, "singleShot", lambda _delay, callback: scheduled.append(callback))
    update = Mock()
    widget.update = update

    widget._request_frame([0])
    widget._request_frame([1])

    assert len(scheduled) == 1
    scheduled.pop()()
    update.assert_called_once()
    assert update.call_args.args[0].contains(widget._layout.rect_at(0).translated(0, -widget._scroll_y).center())
    assert update.call_args.args[0].contains(widget._layout.rect_at(1).translated(0, -widget._scroll_y).center())


def test_grid_shutdown_discards_queued_frame_repaint(monkeypatch):
    from AssetsManager.panels.file_list import _grid_widget

    widget = FileListGridWidget()
    widget.set_layout_ref(GridLayout())
    widget._model_rows = 1
    widget.update_layout(1, 400)
    widget._cancel_frame()
    scheduled = []
    monkeypatch.setattr(_grid_widget.QTimer, "singleShot", lambda _delay, callback: scheduled.append(callback))
    update = Mock()
    widget.update = update

    widget._request_frame([0])
    widget.stop_animations()
    scheduled.pop()()

    update.assert_not_called()


def test_grid_shutdown_discards_queued_full_rebuild_update(monkeypatch):
    from AssetsManager.panels.file_list import _grid_widget

    widget = FileListGridWidget()
    scheduled = []
    monkeypatch.setattr(_grid_widget.QTimer, "singleShot", lambda _delay, callback: scheduled.append(callback))
    request_frame = Mock()
    widget._request_frame = request_frame
    widget._full_rebuild_pending = True

    widget._queue_full_rebuild_update()
    widget.stop_animations()
    scheduled.pop()()

    request_frame.assert_not_called()


def test_grid_deferred_frame_does_not_access_deleted_widget(monkeypatch):
    from AssetsManager.panels.file_list import _grid_widget

    app = QApplication.instance() or QApplication([])
    widget = FileListGridWidget()
    scheduled = []
    monkeypatch.setattr(_grid_widget.QTimer, "singleShot", lambda _delay, callback: scheduled.append(callback))

    widget._request_frame(full=True)
    widget.deleteLater()
    app.processEvents()
    scheduled.pop()()


def test_grid_frame_scheduler_records_pathless_coalescing(monkeypatch):
    from AssetsManager.panels.file_list import _grid_widget

    widget = FileListGridWidget()
    widget.set_layout_ref(GridLayout())
    widget._model_rows = 3
    widget.update_layout(3, 400)
    widget._cancel_frame()
    recorder = PerformanceRecorder(enabled=True)
    widget.set_performance_context(recorder, "session-a", 7)
    scheduled = []
    monkeypatch.setattr(_grid_widget.QTimer, "singleShot", lambda _delay, callback: scheduled.append(callback))
    widget.update = Mock()

    widget._request_frame([0])
    widget._request_frame([1])
    scheduled.pop()()

    event = next(event for event in recorder.recent() if event.name == "grid.frame_request")
    assert (event.session_token, event.generation, event.path) == ("session-a", 7, None)
    assert event.attributes["full"] is False
    assert event.attributes["coalesced_request_count"] == 2
    assert event.attributes["dirty_width"] > 0
    assert event.attributes["dirty_height"] > 0


def test_grid_animation_tick_requests_only_changed_card_regions(monkeypatch):
    widget = FileListGridWidget()
    widget.set_layout_ref(GridLayout())
    widget._model_rows = 3
    widget.update_layout(3, 400)
    requested = []
    monkeypatch.setattr(widget, "_request_frame", lambda rows=None, **kwargs: requested.append((set(rows or []), kwargs)))
    widget._thumb_opacity = {1: 0.0}

    widget._anim_tick()

    assert requested == [({1}, {"overlay": True})]


def test_grid_animation_tick_stays_local_after_scroll(monkeypatch):
    widget = FileListGridWidget()
    widget.set_layout_ref(GridLayout())
    widget._model_rows = 20
    widget.resize(400, 300)
    widget.update_layout(20, 400)
    widget._scroll_y = widget._layout.rect_at(4).y()
    requested = []
    monkeypatch.setattr(
        widget,
        "_request_frame",
        lambda rows=None, **kwargs: requested.append((set(rows or []), kwargs)),
    )
    widget._thumb_opacity = {4: 0.0}

    widget._anim_tick()

    assert requested == [({4}, {"overlay": True})]


def test_grid_selection_fade_completion_does_not_emit_selection_changed():
    app = QApplication.instance() or QApplication([])
    widget = FileListGridWidget()
    widget._selection_progress = {1: 0.005}
    changed = []
    widget.selection_changed.connect(lambda: changed.append(True))

    widget._anim_tick()

    assert changed == []
    assert widget._selection_progress == {}
    widget.deleteLater()
    app.processEvents()


def test_grid_model_reset_discards_prior_staged_rebuild_callback(monkeypatch):
    from AssetsManager.panels.file_list import _grid_widget

    widget = FileListGridWidget()
    widget._full_rebuild_pending = True
    scheduled = []
    monkeypatch.setattr(_grid_widget.QTimer, "singleShot", lambda _delay, callback: scheduled.append(callback))
    update = Mock()
    widget.update = update

    widget._queue_full_rebuild_update()
    stale_callback = scheduled.pop()
    widget._on_model_reset()
    widget._full_rebuild_pending = True
    stale_callback()

    update.assert_not_called()


def test_grid_stale_rebuild_callback_releases_scheduler_latch(monkeypatch):
    from AssetsManager.panels.file_list import _grid_widget

    widget = FileListGridWidget()
    widget._full_rebuild_pending = True
    scheduled = []
    monkeypatch.setattr(_grid_widget.QTimer, "singleShot", lambda _delay, callback: scheduled.append(callback))

    widget._queue_full_rebuild_update()
    stale_callback = scheduled.pop()
    widget.invalidate_textures()
    stale_callback()

    assert widget._full_rebuild_update_queued is False


def test_grid_newer_empty_commit_discards_hidden_presentation():
    widget = FileListGridWidget()
    widget._pending_presentation = (4, [0, 1], True)

    widget.discard_pending_presentation(5)

    assert widget._pending_presentation is None


def test_grid_texture_byte_accounting_cleans_evicted_and_cleared_entries():
    from PySide6.QtGui import QPixmap

    widget = FileListGridWidget()
    widget.set_performance_context(PerformanceRecorder(enabled=True), "session-a", 7)
    first = QPixmap(10, 20)
    second = QPixmap(20, 10)
    widget._store_texture_bytes(1, first)
    widget._store_texture_bytes(2, second)

    assert widget._texture_cache_bytes == 1600
    widget._textures[1] = first
    widget._textures[2] = second
    widget._textures.pop(1)
    widget._remove_texture_bytes(1)
    assert widget._texture_cache_bytes == 800

    widget._clear_textures()

    assert widget._texture_cache_bytes == 0
    assert widget._texture_bytes == {}


def test_grid_disabled_cache_accounting_avoids_pixmap_size_reads(monkeypatch):
    widget = FileListGridWidget()
    texture = Mock()
    monkeypatch.setattr(texture, "width", lambda: (_ for _ in ()).throw(AssertionError()))

    widget._store_texture_bytes(1, texture)

    assert widget._texture_cache_bytes == 0
    assert widget._texture_bytes == {}


def test_grid_texture_cache_evicts_lru_and_keeps_byte_accounting_scoped():
    from PySide6.QtGui import QPixmap

    app = QApplication.instance() or QApplication([])
    widget = FileListGridWidget()
    recorder = PerformanceRecorder(enabled=True)
    widget.set_performance_context(recorder, "session-a", 7)
    texture = QPixmap(10, 10)
    for row in range(200):
        widget._textures[row] = texture
        widget._store_texture_bytes(row, texture)

    widget._textures.move_to_end(0)
    widget._cache_texture(200, texture)

    assert 1 not in widget._textures
    assert 0 in widget._textures
    assert len(widget._textures) == 200
    assert widget._texture_cache_bytes == 200 * 400
    event = next(event for event in recorder.recent() if event.name == "grid.texture_eviction")
    assert (event.session_token, event.generation, event.path) == ("session-a", 7, None)
    assert event.attributes == {"texture_cache_count": 199, "texture_cache_bytes": 199 * 400}
    widget.deleteLater()
    app.processEvents()


def test_grid_animation_tick_records_scoped_counts_and_preserves_queue():
    app = QApplication.instance() or QApplication([])
    widget = FileListGridWidget()
    widget.set_layout_ref(GridLayout())
    widget.update_layout(4, 400)
    widget.resize(400, 300)
    widget._entrance_queue = [0, 1]
    recorder = PerformanceRecorder(enabled=True)
    widget.set_performance_context(recorder, "session-a", 7)

    widget._anim_tick()

    event = next(event for event in recorder.recent() if event.name == "grid.animation_tick")
    assert event.session_token == "session-a"
    assert event.generation == 7
    assert event.path is None
    assert set(event.attributes) == {"visible_item_count", "queued_entrance_count"}
    assert len(widget._entrance_queue) < 2

    widget.deleteLater()
    app.processEvents()


def test_grid_presentation_starts_entrance_once_per_generation():
    app = QApplication.instance() or QApplication([])
    widget = FileListGridWidget()
    widget._reduce_motion = False
    widget._model_rows = 3
    widget.show()
    app.processEvents()

    assert widget.begin_presentation(4, [0, 1]) is True
    assert widget._entrance_queue == [0, 1]
    assert widget.begin_presentation(4, [0, 1]) is False
    assert widget._entrance_queue == [0, 1]
    assert widget.begin_presentation(5, [1, 2]) is True
    assert widget._entrance_queue == [1, 2]

    widget.deleteLater()
    app.processEvents()


def test_grid_show_consumes_only_a_presentation_committed_while_hidden():
    app = QApplication.instance() or QApplication([])
    widget = FileListGridWidget()
    widget._model_rows = 2
    widget._reduce_motion = False

    assert widget.begin_presentation(4, [0, 1]) is True
    assert widget._pending_presentation == (4, [0, 1], True)

    widget.show()
    app.processEvents()

    assert widget._presented_generation == 4
    assert widget._entrance_queue == [0, 1]
    assert widget.begin_presentation(4, [0, 1]) is False
    widget.deleteLater()
    app.processEvents()


def test_grid_disabled_telemetry_does_not_read_clock(tmp_path, monkeypatch):
    from AssetsManager.panels.file_list import _grid_widget

    app, _model, widget = _visible_grid(tmp_path)
    monkeypatch.setattr(_grid_widget, "perf_counter", lambda: (_ for _ in ()).throw(AssertionError()))

    widget.repaint()
    widget._anim_tick()

    monkeypatch.undo()
    widget.deleteLater()
    app.processEvents()


def test_grid_recorder_failure_does_not_change_animation_state():
    app = QApplication.instance() or QApplication([])
    widget = FileListGridWidget()
    widget.set_layout_ref(GridLayout())
    widget.update_layout(4, 400)
    widget.resize(400, 300)
    widget._entrance_queue = [0, 1]
    class _FailingRecorder:
        enabled = True

        @staticmethod
        def record(*_args, **_kwargs):
            raise RuntimeError()

    recorder = _FailingRecorder()
    widget.set_performance_context(recorder, "session-a", 7)

    widget._anim_tick()

    assert len(widget._entrance_queue) < 2
    widget.deleteLater()
    app.processEvents()


def test_grid_performance_context_has_no_visual_side_effects():
    widget = FileListGridWidget()
    update = Mock()
    widget.update = update
    widget.set_performance_context(PerformanceRecorder(enabled=True), "session-a", 7)

    assert update.call_count == 0
    assert widget._anim_timer.isActive() is False


def test_grid_rebind_replaces_session_and_generation_attribution(tmp_path):
    app, _model, widget = _visible_grid(tmp_path)
    first = PerformanceRecorder(enabled=True)
    second = PerformanceRecorder(enabled=True)
    widget.set_performance_context(first, "session-a", 7)
    widget.repaint()
    widget.set_performance_context(second, "session-b", 9)
    widget.repaint()

    assert [event.session_token for event in first.recent() if event.name == "grid.frame"] == ["session-a"]
    event = next(event for event in second.recent() if event.name == "grid.frame")
    assert (event.session_token, event.generation) == ("session-b", 9)

    widget.deleteLater()
    app.processEvents()


def test_grid_model_reset_updates_presentation_generation(tmp_path):
    app, model, widget = _visible_grid(tmp_path)
    recorder = PerformanceRecorder(enabled=True)
    widget.set_performance_context(recorder, "session-a", model.scan_generation)
    model.set_directory(str(tmp_path))
    model._wait_for_scan()
    widget.update_layout(model.rowCount(), widget.width())
    widget.set_performance_generation(model.scan_generation)
    widget.repaint()

    event = next(event for event in recorder.recent() if event.name == "grid.frame")
    assert event.generation == model.scan_generation

    widget.deleteLater()
    app.processEvents()


def test_grid_frame_recorder_failure_does_not_escape(tmp_path):
    app, _model, widget = _visible_grid(tmp_path)
    recorder = PerformanceRecorder(enabled=True)
    recorder.record = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError())
    widget.set_performance_context(recorder, "session-a", 7)

    widget.repaint()

    widget.deleteLater()
    app.processEvents()


def test_grid_invalid_recorder_is_ignored_without_visual_side_effects():
    widget = FileListGridWidget()

    class _BrokenRecorder:
        @property
        def enabled(self):
            raise RuntimeError()

    widget.set_performance_context(_BrokenRecorder(), "session-a", 7)

    assert widget._performance_recorder is None


def test_grid_item_texture_uses_widget_device_pixel_ratio(tmp_path):
    (tmp_path / "folder").mkdir()
    app = QApplication.instance() or QApplication([])
    model = FileSystemModel()
    widget = FileListGridWidget()
    try:
        model.set_directory(str(tmp_path))
        model._wait_for_scan()
        widget.set_model(model)
        widget.devicePixelRatioF = lambda: 2.0

        texture = widget._render_item(0, QRect(0, 0, widget._item_w, widget._item_h))

        assert texture is not None
        assert texture.devicePixelRatio() == 2.0
    finally:
        widget.stop_animations()
        model.shutdown()
        widget.deleteLater()
        app.processEvents()


def test_grid_thumb_batch_marks_only_loaded_rows_dirty():
    widget = FileListGridWidget()
    widget._dirty.clear()

    widget.commit_thumbnail_rows([1, 9])

    assert widget._dirty == {1, 9}


def test_grid_static_data_change_preserves_interaction_and_thumbnail_fades():
    widget = FileListGridWidget()
    widget._textures[1] = object()
    widget._thumbnail_rows = {1}
    widget._thumb_opacity = {1: 0.4}
    widget._hover_progress = {1: 0.7}
    widget._selection_progress = {1: 0.8}
    widget._dirty.clear()

    index = type("_Index", (), {"row": lambda _self: 1})()
    widget._on_data_changed(index, index, [FileSystemModel.SUBTITLE_ROLE])

    assert widget._dirty == {1}
    assert widget._thumbnail_rows == {1}
    assert widget._thumb_opacity == {1: 0.4}
    assert widget._hover_progress == {1: 0.7}
    assert widget._selection_progress == {1: 0.8}


def test_grid_nonvisual_data_change_does_not_invalidate_texture():
    widget = FileListGridWidget()
    widget._textures[1] = object()
    widget._dirty.clear()
    index = type("_Index", (), {"row": lambda _self: 1})()

    widget._on_data_changed(index, index, [FileSystemModel.DIR_SIZE_ROLE])

    assert widget._textures[1] is not None
    assert widget._dirty == set()


def test_grid_empty_role_data_change_invalidates_static_texture():
    widget = FileListGridWidget()
    widget._textures[1] = object()
    widget._dirty.clear()
    index = type("_Index", (), {"row": lambda _self: 1})()

    widget._on_data_changed(index, index, [])

    assert 1 not in widget._textures
    assert widget._dirty == {1}




def test_grid_selection_change_preserves_cached_textures():
    widget = FileListGridWidget()
    cached = object()
    widget._textures[3] = cached
    widget._selection = {3}
    widget._dirty.clear()

    widget._selection.clear()
    widget._apply_selection_progress({3})

    assert widget._textures[3] is cached
    assert widget._dirty == set()
    assert widget._selection_progress[3] == 1.0


def test_grid_hover_transition_preserves_cached_textures():
    app = QApplication.instance() or QApplication([])
    widget = FileListGridWidget()
    old_cached = object()
    new_cached = object()
    widget._textures[1] = old_cached
    widget._textures[2] = new_cached
    widget._hover_row = 1
    widget._dirty.clear()
    widget._layout = type("_Layout", (), {"row_at": lambda _self, _x, _y: 2})()

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        widget.mouseMoveEvent(QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(0, 0),
            QPointF(0, 0),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            QPointingDevice.primaryPointingDevice(),
        ))

    assert widget._textures[1] is old_cached
    assert widget._textures[2] is new_cached
    assert widget._dirty == set()
    assert widget._hover_progress == {1: 1.0, 2: 0.0}

    widget.deleteLater()
    app.processEvents()


def test_grid_enter_respects_reduce_motion(monkeypatch):
    app = QApplication.instance() or QApplication([])
    widget = FileListGridWidget()
    widget._reduce_motion = True
    widget._layout = type("_Layout", (), {"row_at": lambda _self, _x, _y: 2})()
    monkeypatch.setattr(widget, "mapFromGlobal", lambda _pos: QPoint(0, 0))
    monkeypatch.setattr(widget, "cursor", lambda: type("_Cursor", (), {"pos": lambda _self: QPoint(0, 0)})())

    widget.enterEvent(QEnterEvent(QPointF(), QPointF(), QPointF()))

    assert widget._hover_row == 2
    assert widget._hover_progress == {}
    assert widget._anim_timer.isActive() is False
    widget.deleteLater()
    app.processEvents()


def test_grid_reduce_motion_keeps_hover_feedback_without_transition(monkeypatch):
    widget = FileListGridWidget()
    widget._reduce_motion = True
    widget._hover_row = 2
    widget._hover_progress = {1: 0.5}
    requested = []
    monkeypatch.setattr(
        widget,
        "_request_frame",
        lambda rows=None, **kwargs: requested.append((set(rows or []), kwargs)),
    )

    widget._anim_tick()

    assert widget._hover_progress == {}
    assert requested == [({1}, {"overlay": True})]


def test_grid_rounded_draws_enable_antialiasing_only_locally():
    widget = FileListGridWidget()
    painter = Mock()

    widget._draw_texture_placeholder(painter, QRect(0, 0, 100, 100))
    assert painter.setRenderHint.call_args_list == [
        ((QPainter.RenderHint.Antialiasing, True),),
    ]
    painter.reset_mock()

    widget._selection = {0}
    widget._draw_interaction_overlay(painter, 0, QRect(0, 0, 100, 100), 1.0)

    assert painter.setRenderHint.call_args_list == [
        ((QPainter.RenderHint.Antialiasing, True),),
    ]


def test_grid_light_relayout_preserves_cached_textures_and_dirty_rows():
    widget = FileListGridWidget()
    widget.set_layout_ref(GridLayout())
    widget._textures[0] = object()
    widget._dirty = {1}

    widget.update_layout(3, 400, relayout_only=True)

    assert widget._textures[0] is not None
    assert widget._dirty == {1}
    assert widget._zoom_relayout_active is True

    widget.update_layout(3, 400)

    assert widget._zoom_relayout_active is False


def test_grid_resize_relayout_preserves_existing_texture_content():
    widget = FileListGridWidget()
    widget.set_layout_ref(GridLayout())
    cached = object()
    widget._textures[0] = cached
    widget._model_rows = 3
    widget._dirty.clear()

    widget.update_layout(3, 800)

    assert widget._textures[0] is cached
    assert widget._dirty == set()


def test_grid_dirty_cached_texture_is_scaled_to_replacement_layout(tmp_path, monkeypatch):
    app, _model, widget = _visible_grid(tmp_path)
    widget._textures[0] = QPixmap(10, 10)
    widget._dirty = {0}
    widget._full_rebuild_pending = True
    monkeypatch.setattr(widget, "_render_item", Mock(return_value=None))
    draw_pixmap = Mock()
    from AssetsManager.panels.file_list import _grid_widget
    monkeypatch.setattr(_grid_widget.QPainter, "drawPixmap", draw_pixmap)

    widget.repaint()

    # A dirty row still carrying a stale texture is drawn scaled to the current
    # cell rect (QRect target) instead of at its native size.
    targets = [call.args[0] for call in draw_pixmap.call_args_list]
    assert any(isinstance(t, QRect) for t in targets)
    widget.deleteLater()
    app.processEvents()


def test_grid_scroll_always_requests_full_repaint(monkeypatch):
    # Scrolling shifts the whole visible content, so the full viewport must be
    # repainted every frame (each card re-drawn at its new offset). A strip-only
    # repaint would leave stale pixels in the region that received no new cell.
    widget = FileListGridWidget()
    widget.set_layout_ref(GridLayout())
    widget._model_rows = 10
    widget.resize(300, 200)
    widget.update_layout(10, 300)
    widget._scroll_y = 0
    requested = []
    monkeypatch.setattr(widget, "_request_frame", lambda **kwargs: requested.append(kwargs))

    widget._on_scroll(50)

    assert requested == [{"full": True}]


def test_grid_mark_scan_settled_clears_reset_guard():
    widget = FileListGridWidget()
    widget._on_scan_started(1)
    assert widget._scan_reset_pending is True

    widget.mark_scan_settled()

    assert widget._scan_reset_pending is False


def test_grid_layout_marks_only_new_rows_dirty_when_cache_exists():
    widget = FileListGridWidget()
    widget.set_layout_ref(GridLayout())
    widget._textures[0] = object()
    widget._model_rows = 2
    widget._dirty.clear()

    widget.update_layout(4, 400)

    assert widget._dirty == {2, 3}


def test_zoom_frame_scales_grid_without_reflowing_columns():
    panel = type("_Panel", (), {})()
    panel._thumb_size = 96
    panel._model = type("_Model", (), {"rowCount": lambda _self: 5})()
    panel._grid_widget = Mock()
    panel._grid_widget.width.return_value = 400

    FileListPanel._on_zoom_frame(panel, 128)

    panel._grid_widget.set_zoom_thumb_size.assert_called_once_with(128)
    panel._grid_widget.update_layout.assert_not_called()


def test_zoom_start_captures_target_layout_before_animation():
    panel = QObject()
    panel._thumb_size = 96
    panel._zoom_anim = None
    panel._zoom_generation = 0
    panel._grid_widget = Mock()
    panel._on_zoom_frame = Mock()
    panel._on_zoom_done = Mock()

    FileListPanel._on_zoom_changed(panel, "128px")

    panel._grid_widget.begin_zoom.assert_called_once_with(128, None)
    assert panel._zoom_anim.duration() == 185
    assert panel._zoom_anim.easingCurve().type() == QEasingCurve.Type.OutCubic
    panel._zoom_anim.stop()


def test_zoom_start_forwards_a_pending_pointer_anchor():
    panel = QObject()
    panel._thumb_size = 96
    panel._zoom_anim = None
    panel._zoom_generation = 0
    panel._pending_zoom_anchor = QPoint(84, 126)
    panel._grid_widget = Mock()
    panel._on_zoom_frame = Mock()
    panel._on_zoom_done = Mock()

    FileListPanel._on_zoom_changed(panel, "128px")

    panel._grid_widget.begin_zoom.assert_called_once_with(128, QPoint(84, 126))
    assert panel._pending_zoom_anchor is None
    panel._zoom_anim.stop()


def test_zoom_reduce_motion_commits_without_starting_an_animation():
    panel = type("_Panel", (), {})()
    panel._thumb_size = 96
    panel._zoom_anim = None
    panel._zoom_generation = 0
    panel._grid_widget = Mock()
    panel._grid_widget._zoom_relayout_active = False
    panel._grid_widget._reduce_motion = True
    panel._on_zoom_done = Mock()

    FileListPanel._on_zoom_changed(panel, "128px")

    assert panel._thumb_size == 128
    panel._grid_widget.begin_zoom.assert_called_once_with(128, None)
    panel._grid_widget.set_zoom_thumb_size.assert_called_once_with(128)
    panel._on_zoom_done.assert_called_once_with(1, 128)
    assert panel._zoom_anim is None


def test_wheel_zoom_captures_the_pointer_as_the_zoom_anchor():
    panel = type("_Panel", (), {})()
    panel._grid_widget = Mock()
    panel._grid_widget.rect.return_value = QRect(0, 0, 400, 300)
    panel._zoom_combo = Mock()
    panel._zoom_combo.currentIndex.return_value = 1
    captured = []
    panel._zoom_combo.setCurrentIndex.side_effect = (
        lambda index: captured.append((index, panel._pending_zoom_anchor))
    )
    event = Mock()
    event.modifiers.return_value = Qt.KeyboardModifier.ControlModifier
    event.angleDelta.return_value = QPoint(0, 120)
    event.position.return_value = QPointF(90, 70)

    FileListPanel._wheel_zoom_evt(panel, event, panel._grid_widget)

    assert captured == [(2, QPoint(90, 70))]
    assert panel._pending_zoom_anchor is None


def test_zoom_same_interpolated_size_commits_active_layout():
    panel = type("_Panel", (), {})()
    panel._thumb_size = 128
    panel._zoom_anim = None
    panel._zoom_generation = 0
    panel._grid_widget = Mock()
    panel._grid_widget._zoom_relayout_active = True
    panel._on_zoom_frame = Mock()
    panel._on_zoom_done = Mock()

    FileListPanel._on_zoom_changed(panel, "128px")

    panel._grid_widget.begin_zoom.assert_called_once_with(128, None)
    panel._on_zoom_done.assert_called_once_with(1)


def test_zoom_done_commits_generation_target_not_last_frame_size():
    panel = type("_Panel", (), {})()
    panel._zoom_generation = 2
    panel._thumb_size = 117
    panel._loader = Mock()
    panel._grid_widget = Mock()
    panel._model = type("_Model", (), {"rowCount": lambda _self: 5})()
    panel._grid_widget.width.return_value = 400
    panel._load_visible = Mock()

    FileListPanel._on_zoom_done(panel, 2, 128)

    assert panel._thumb_size == 128
    panel._loader.set_size.assert_called_once_with(128)
    panel._grid_widget.set_thumb_size.assert_called_once_with(128)


def test_grid_does_not_cache_intermediate_zoom_texture(tmp_path, monkeypatch):
    app, _model, widget = _visible_grid(tmp_path)
    widget._textures.clear()
    widget._dirty = {0}
    widget._zoom_relayout_active = True
    render_item = Mock(side_effect=widget._render_item)
    monkeypatch.setattr(widget, "_render_item", render_item)

    widget.repaint()

    assert render_item.call_count == 0
    assert widget._dirty == {0}
    widget.deleteLater()
    app.processEvents()


def test_grid_zoom_cancels_card_fades_and_entrance_stagger():
    widget = FileListGridWidget()
    widget.set_layout_ref(GridLayout())
    widget.resize(800, 600)
    widget.update_layout(8, 800)
    widget._thumb_opacity = {0: 0.4, 3: 0.8}
    widget._entrance_queue = [0, 1, 2]
    widget._entrance_visible = {4}

    widget.begin_zoom(128)

    assert widget._thumb_opacity == {}
    assert widget._entrance_queue == []
    assert widget._entrance_visible == set()


def test_grid_zoom_interpolates_dirty_texture_position(tmp_path, monkeypatch):
    app, _model, widget = _visible_grid(tmp_path)
    widget._textures[0] = QPixmap(10, 10)
    widget._dirty = {0}
    widget.begin_zoom(180)
    widget.set_zoom_thumb_size(128)
    monkeypatch.setattr(widget, "_render_item", Mock(return_value=None))
    draw_pixmap = Mock()
    from AssetsManager.panels.file_list import _grid_widget
    monkeypatch.setattr(_grid_widget.QPainter, "drawPixmap", draw_pixmap)

    widget.repaint()

    assert isinstance(draw_pixmap.call_args_list[-1].args[0], QRect)
    widget.deleteLater()
    app.processEvents()


def test_grid_thumbnail_commit_during_zoom_does_not_start_fade():
    widget = FileListGridWidget()
    widget._zoom_relayout_active = True
    widget._reduce_motion = False

    widget.commit_thumbnail_rows([3])

    assert widget._thumb_opacity == {}


def test_grid_zoom_renders_temporary_fallback_without_caching(tmp_path, monkeypatch):
    app, _model, widget = _visible_grid(tmp_path)
    widget._textures.clear()
    widget.begin_zoom(180)
    widget.set_zoom_thumb_size(128)
    render_item = Mock(side_effect=widget._render_item)
    monkeypatch.setattr(widget, "_render_item", render_item)

    widget.repaint()

    assert render_item.call_count <= 2
    assert widget._zoom_fallback_textures
    assert widget._textures == {}
    widget.deleteLater()
    app.processEvents()


def test_grid_zoom_fallback_is_cleared_at_commit():
    widget = FileListGridWidget()
    widget._zoom_relayout_active = True
    widget._zoom_fallback_textures = {1: QPixmap(10, 10)}
    widget._scrollbar.setRange(0, 100)

    widget.finish_zoom()

    assert widget._zoom_fallback_textures == {}


def test_grid_zoom_interpolates_toward_target_layout():
    widget = FileListGridWidget()
    widget.set_layout_ref(GridLayout())
    widget.resize(800, 600)
    widget.update_layout(8, 800)
    before_columns = widget._layout.columns

    widget.begin_zoom(180)
    start = widget._zoom_texture_rect(widget._layout.rect_at(4), 4)
    widget.set_zoom_thumb_size(128)
    middle = widget._zoom_texture_rect(widget._layout.rect_at(4), 4)

    assert widget._layout.columns == before_columns
    assert widget._zoom_relayout_active is True
    assert middle != start
    assert middle.x() != widget._layout.rect_at(4).x()


def test_grid_zoom_retargets_from_the_current_visual_geometry():
    widget = FileListGridWidget()
    widget.set_layout_ref(GridLayout())
    widget.resize(800, 600)
    widget.update_layout(40, 800)
    widget._scroll_y = 240
    widget.begin_zoom(180)
    widget.set_zoom_thumb_size(128)
    visual_rects = [
        widget._zoom_texture_rect(rect, row)
        for row, rect in enumerate(widget._layout._rects)
    ]

    widget.begin_zoom(48)

    assert widget._zoom_source_rects == visual_rects
    assert widget._zoom_start_size == 128
    assert widget._zoom_target_size == 48


def test_grid_zoom_keeps_the_pointer_position_inside_its_card():
    widget = FileListGridWidget()
    widget.set_layout_ref(GridLayout())
    widget.resize(800, 600)
    widget.update_layout(100, 800)
    widget._scroll_y = 300
    visible = widget._layout.visible_rows(widget._scroll_y, widget.height())
    row = next(
        row for row in visible
        if widget._layout.rect_at(row).top() >= widget._scroll_y
        and widget._layout.rect_at(row).bottom() <= widget._scroll_y + widget.height()
    )
    source = widget._layout.rect_at(row)
    anchor_pos = QPoint(
        source.center().x(),
        source.top() - widget._scroll_y + source.height() // 3,
    )
    relative_y = (widget._scroll_y + anchor_pos.y() - source.top()) / source.height()

    widget.begin_zoom(48, anchor_pos)
    widget.set_zoom_thumb_size(48)
    target = widget._zoom_texture_rect(widget._layout.rect_at(row), row)
    target_focus_y = target.top() + target.height() * relative_y

    assert abs(target_focus_y - (widget._scroll_y + anchor_pos.y())) <= 1


def test_grid_zoom_keeps_center_anchor_and_includes_target_visible_rows():
    widget = FileListGridWidget()
    widget.set_layout_ref(GridLayout())
    widget.resize(800, 600)
    widget.update_layout(100, 800)
    widget._scroll_y = 300

    widget.begin_zoom(48)

    assert widget._zoom_anchor_y_offset != 0
    assert widget._zoom_visible_rows
    assert any(row not in widget._layout.visible_rows(widget._scroll_y, widget.height()) for row in widget._zoom_visible_rows)


def test_grid_finish_zoom_adjusts_scrollbar_for_anchor():
    widget = FileListGridWidget()
    widget._zoom_relayout_active = True
    widget._zoom_anchor_y_offset = 40
    widget._scroll_y = 100
    widget._scrollbar.setRange(0, 500)
    widget._scrollbar.setValue(100)

    widget.finish_zoom()

    assert widget._scrollbar.value() == 60
    assert widget._zoom_relayout_active is False


def test_stale_zoom_completion_does_not_invalidate_grid_textures():
    panel = type("_Panel", (), {})()
    panel._zoom_generation = 2
    panel._thumb_size = 96
    panel._loader = Mock()
    panel._grid_widget = Mock()
    panel._model = type("_Model", (), {"rowCount": lambda _self: 5})()
    panel._grid_widget.width.return_value = 400

    FileListPanel._on_zoom_done(panel, 1)

    panel._loader.set_size.assert_not_called()
    panel._grid_widget.invalidate_textures.assert_not_called()


def test_current_zoom_completion_invalidates_grid_textures_once():
    panel = type("_Panel", (), {})()
    panel._zoom_generation = 2
    panel._thumb_size = 128
    panel._loader = Mock()
    panel._grid_widget = Mock()
    panel._model = type("_Model", (), {"rowCount": lambda _self: 5})()
    panel._grid_widget.width.return_value = 400
    panel._load_visible = Mock()

    FileListPanel._on_zoom_done(panel, 2)

    panel._loader.set_size.assert_called_once_with(128)
    panel._grid_widget.invalidate_textures.assert_called_once_with()
    panel._grid_widget.update_layout.assert_called_once_with(5, 400)
    panel._load_visible.assert_called_once_with()


def test_scroll_discards_queued_full_rebuild_repaint(monkeypatch):
    from AssetsManager.panels.file_list import _grid_widget

    widget = FileListGridWidget()
    widget._full_rebuild_pending = True
    scheduled = []
    monkeypatch.setattr(_grid_widget.QTimer, "singleShot", lambda _delay, callback: scheduled.append(callback))
    update = Mock()
    widget.update = update

    widget._queue_full_rebuild_update()
    widget.set_scrolling()
    scheduled.pop()()

    assert update.call_count == 0
    assert widget._full_rebuild_update_queued is False


def test_view_mode_uses_stable_id_when_display_text_is_localized():
    app = QApplication.instance() or QApplication([])
    panel = FileListPanel()
    panel._view_combo.setItemText(0, "网格")
    panel._view_combo.setCurrentIndex(0)

    assert panel._view_combo.itemData(0) == "Grid"
    assert panel._view_mode == "Grid"

    details_index = panel._view_combo.findData("Details")
    panel._view_combo.setCurrentIndex(details_index)
    assert panel._view_mode == "Details"

    panel.deleteLater()
    app.processEvents()


def test_restore_view_mode_uses_saved_stable_id():
    app = QApplication.instance() or QApplication([])
    panel = FileListPanel()
    panel._view_combo.setItemText(1, "详情")
    panel._view_memory["library/subfolder"] = "Details"

    panel._restore_view_mode("library/subfolder")

    assert panel._view_mode == "Details"

    panel.deleteLater()
    app.processEvents()


def test_populated_model_reset_repopulates_details_view(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    panel = FileListPanel()
    panel._view_combo.setCurrentIndex(panel._view_combo.findData("Details"))
    (tmp_path / "asset.txt").write_text("asset")
    panel._model._raw_entries = list(__import__("os").scandir(tmp_path))
    panel._model._apply_sort()
    populated = []
    monkeypatch.setattr(panel, "_populate_details", lambda: populated.append(True))

    panel._on_grid_model_reset()

    assert populated == [True]

    panel.deleteLater()
    app.processEvents()


def test_grid_shift_arrow_without_prior_click_keeps_rows_valid():
    app = QApplication.instance() or QApplication([])
    widget = FileListGridWidget()
    try:
        widget._model_rows = 5
        widget._last_click_row = -1
        widget._selection = {0}
        widget._step_mod_arrow(1, Qt.KeyboardModifier.ShiftModifier)
        assert widget._selection == {0, 1}
        assert widget._last_click_row == 1
        # Stepping back from the anchored range keeps every row valid.
        widget._step_mod_arrow(-2, Qt.KeyboardModifier.ShiftModifier)
        assert widget._selection == {0, 1}
        assert widget._last_click_row == 0
    finally:
        widget.deleteLater()
        app.processEvents()


def test_grid_shift_arrow_without_prior_click_upward_anchors_at_zero():
    app = QApplication.instance() or QApplication([])
    widget = FileListGridWidget()
    try:
        widget._model_rows = 5
        widget._last_click_row = -1
        widget._selection = {4}
        widget._step_mod_arrow(-1, Qt.KeyboardModifier.ShiftModifier)
        # The never-clicked anchor (-1) clamps to row 0, so the range cannot
        # include an invalid -1 row.
        assert widget._selection == {0}
        assert widget._last_click_row == 0
    finally:
        widget.deleteLater()
        app.processEvents()


def test_grid_inline_rename_escape_cancels_and_closes_editor(tmp_path):
    app, model, widget = _visible_grid(tmp_path)
    renamed = []
    widget.rename_requested.connect(lambda row, name: renamed.append((row, name)))
    widget._start_rename(0)
    editor = widget._rename_editor
    assert editor is not None
    editor.setText("renamed.txt")

    pressed = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
    )
    assert widget.eventFilter(editor, pressed) is True
    app.processEvents()

    assert widget._rename_editor is None
    assert renamed == []


def test_grid_inline_rename_enter_still_commits(tmp_path):
    app, model, widget = _visible_grid(tmp_path)
    renamed = []
    widget.rename_requested.connect(lambda row, name: renamed.append((row, name)))
    widget._start_rename(0)
    editor = widget._rename_editor
    assert editor is not None
    editor.setText("renamed.txt")

    editor.editingFinished.emit()
    app.processEvents()

    assert widget._rename_editor is None
    assert renamed == [(0, "renamed.txt")]


def test_grid_release_on_multi_selection_collapses_to_clicked_row():
    app = QApplication.instance() or QApplication([])
    widget = FileListGridWidget()
    try:
        widget._model_rows = 3
        widget._click_pending_row = 1
        widget._selection = {0, 1, 2}
        clicked = []
        widget.clicked.connect(clicked.append)
        widget.mouseReleaseEvent(QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPointingDevice.primaryPointingDevice(),
        ))
        assert widget._selection == {1}
        assert widget._click_pending_row == -1
        assert clicked == [1]
    finally:
        widget.deleteLater()
        app.processEvents()
