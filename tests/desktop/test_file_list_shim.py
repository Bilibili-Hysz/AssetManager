import os
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from aiohttp import ClientSession

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelectionModel, QMimeData, QPoint, QUrl, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.i18n import tr
from AssetsManager.panels.file_list import QWidgetFileListPanel
from AssetsManager.panels.file_list._base import FileListPanel
from AssetsManager.panels.file_list._shortcuts import handle_key


def test_grid_visible_thumbnails_are_requested_before_prefetch_rows():
    from AssetsManager.panels.file_list import QWidgetFileListPanel
    from AssetsManager.panels.file_list._common import IMAGE_EXTS

    class Entry:
        def __init__(self, row):
            self.path = f"/library/{row}.png"
            self.name = f"{row}.png"

        def is_dir(self):
            return False

        def is_file(self):
            return True

    panel = type("_Panel", (), {})()
    panel._model = type("_Model", (), {
        "rowCount": lambda _self: 10,
        "entry_at": lambda _self, row: Entry(row),
    })()
    panel._view_mode = "Grid"
    panel._grid_widget = type("_Grid", (), {"height": lambda _self: 300, "_scroll_y": 0})()
    panel._grid_layout = type("_Layout", (), {
        "visible_rows": lambda _self, _scroll, _height: [3, 4],
        "columns": 2,
    })()
    panel._loader = Mock()

    QWidgetFileListPanel._load_visible(panel)

    assert IMAGE_EXTS
    panel._loader.retain_deferred.assert_called_once_with({f"/library/{row}.png" for row in range(10)})
    assert [(call.args[0], call.kwargs["priority"]) for call in panel._loader.request.call_args_list] == [
        (3, 0), (4, 0), (0, 1), (1, 1), (2, 1), (5, 1), (6, 1), (7, 1), (8, 1), (9, 1),
    ]


def test_file_list_state_controls_keep_semantic_icons_after_state_changes():
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel._model._sort_asc = True
        panel._model._show_hidden = False
        panel._refresh_state_icons()
        assert panel._sort_btn.text() == ""
        assert panel._hidden_btn.text() == ""
        assert panel._sort_btn.property("semanticIcon") == "arrow_up"
        assert panel._hidden_btn.property("semanticIcon") == "eye_off"
        assert not panel._sort_btn.icon().isNull()
        assert not panel._hidden_btn.icon().isNull()

        panel._model._sort_asc = False
        panel._model._show_hidden = True
        panel._refresh_state_icons()
        assert panel._sort_btn.property("semanticIcon") == "arrow_down"
        assert panel._hidden_btn.property("semanticIcon") == "eye"
    finally:
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()


def test_lan_mutation_event_refreshes_desktop_file_list_for_same_session(tmp_path):
    """A LAN-originated filesystem event reaches the active Desktop panel."""
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path)
    panel = QWidgetFileListPanel()
    panel.set_scoped_services(bootstrap.runtime_for(session).services)
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()
    app.processEvents()
    panel._post_refresh = Mock()

    from AssetsManager.domain.events import FileSystemChanged
    from AssetsManager.domain.event_bus import get_event_bus

    target = tmp_path / "lan-created.txt"
    target.write_text("created by LAN")
    get_event_bus().publish(FileSystemChanged(
        library_root=session.root_str,
        session_token=session.event_token,
        paths=(str(target),),
    ))
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not panel._post_refresh.called:
        app.processEvents()
        time.sleep(0.01)

    try:
        panel._post_refresh.assert_called_once_with()
    finally:
        panel.shutdown()
        bootstrap.library_service.close_session(session)


def test_file_list_captures_thumbnail_service_from_runtime_snapshot_and_clears_on_shutdown(tmp_path):
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path)
    runtime = bootstrap.runtime_for(session)
    panel = QWidgetFileListPanel()

    try:
        panel.set_runtime(runtime)
        assert panel._scoped_services is runtime.services_snapshot
        assert panel._thumbnail_service is runtime.services_snapshot.thumbnail_service

        replacement_session = bootstrap.library_service.open_session(tmp_path / "other")
        replacement_runtime = bootstrap.runtime_for(replacement_session)
        panel.set_runtime(replacement_runtime)
        assert panel._thumbnail_service is replacement_runtime.services_snapshot.thumbnail_service
        assert panel._scoped_services is replacement_runtime.services_snapshot
        assert panel._thumbnail_service is not runtime.services_snapshot.thumbnail_service

        panel.shutdown()
        assert panel._thumbnail_service is None
    finally:
        if getattr(panel, "_thumbnail_service", None) is not None:
            panel.shutdown()
        bootstrap.library_service.close_session(session)
        if not replacement_session.is_closed:
            bootstrap.library_service.close_session(replacement_session)
        app.processEvents()


def test_real_lan_tag_mutation_refreshes_desktop_tag_tree(tmp_path):
    """A real LAN tag mutation reaches the Desktop tag projection."""
    import asyncio

    from AssetsManager.domain.events import TagCatalogChanged
    from AssetsManager.domain.event_bus import get_event_bus
    from AssetsManager.lan.server import _LanServerImpl
    from AssetsManager.panels.tag_tree import TagTreePanel

    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path)
    runtime = bootstrap.runtime_for(session)
    asset = tmp_path / "lan-tagged.txt"
    asset.write_text("created by LAN")
    server = _LanServerImpl(runtime=runtime, password="TaskE-Password!")
    event_bus = get_event_bus()
    baseline_catalog_handlers = event_bus.handler_count(TagCatalogChanged)
    tag_tree = TagTreePanel()
    tag_tree.set_runtime(runtime)
    catalog_events = []
    catalog_subscription = event_bus.subscribe(TagCatalogChanged, catalog_events.append)

    async def mutate_over_lan():
        from AssetsManager.application.security_preflight import SecurityPreflight
        preflight = SecurityPreflight()
        preflight.confirm_authenticated_lan()
        server.start(port=0, bind="127.0.0.1", preflight=preflight)
        try:
            async with ClientSession() as client:
                response = await client.post(
                    f"http://127.0.0.1:{server._port}/api/tags",
                    json={"file_path": "lan-tagged.txt", "tag": "from-lan"},
                    headers={"Authorization": f"Bearer {server._auth_service.generate_token(server.password_hash)}"},
                )
                assert response.status == 200
        finally:
            server.stop()

    try:
        asyncio.run(mutate_over_lan())
        assert catalog_events
        assert catalog_events[-1].library_root == session.root_str
        assert catalog_events[-1].session_token == session.event_token
        assert event_bus.handler_count(TagCatalogChanged) >= 2
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            app.processEvents()
            if any("from-lan" in tag_tree._tree.topLevelItem(i).text(0)
                   for i in range(tag_tree._tree.topLevelItemCount())):
                break
            time.sleep(0.01)
        assert any("from-lan" in tag_tree._tree.topLevelItem(i).text(0)
                   for i in range(tag_tree._tree.topLevelItemCount()))
    finally:
        catalog_subscription.close()
        tag_tree.shutdown()
        app.processEvents()
        assert event_bus.handler_count(TagCatalogChanged) == baseline_catalog_handlers
        tag_tree.deleteLater()
        app.processEvents()
        bootstrap.library_service.close_session(session)
        assert not runtime._lifecycle_adapters
        assert not runtime.event_router._subscribers
        assert not runtime.event_router._event_subscriptions


def test_grid_scan_commit_starts_one_presentation_after_loading_reset(tmp_path):
    (tmp_path / "asset.txt").write_text("asset")
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        begin_presentation = Mock(wraps=panel._grid_widget.begin_presentation)
        panel._grid_widget.begin_presentation = begin_presentation
        update_layout = Mock(wraps=panel._grid_widget.update_layout)
        panel._grid_widget.update_layout = update_layout

        panel.navigate_to(str(tmp_path))
        panel._model._wait_for_scan()
        app.processEvents()

        assert begin_presentation.call_count == 1
        assert begin_presentation.call_args.args[0] == panel._model.scan_generation
        assert [call.args[0] for call in update_layout.call_args_list] == [0, 1]
    finally:
        panel.shutdown()
        app.processEvents()


def test_empty_grid_scan_does_not_start_presentation_or_thumbnail_load(tmp_path):
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel._grid_widget.begin_presentation = Mock()
        panel._load_visible = Mock()

        panel.navigate_to(str(tmp_path), set_root=True)
        panel._model._wait_for_scan()
        app.processEvents()

        panel._grid_widget.begin_presentation.assert_not_called()
        panel._load_visible.assert_not_called()
    finally:
        panel.shutdown()
        app.processEvents()


def test_grid_visibility_toggle_does_not_replay_presentation(tmp_path):
    (tmp_path / "asset.txt").write_text("asset")
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel.navigate_to(str(tmp_path), set_root=True)
        panel._model._wait_for_scan()
        app.processEvents()
        begin_presentation = Mock(wraps=panel._grid_widget.begin_presentation)
        panel._grid_widget.begin_presentation = begin_presentation

        details = panel._view_combo.findData("Details")
        grid = panel._view_combo.findData("Grid")
        panel._view_combo.setCurrentIndex(details)
        panel._view_combo.setCurrentIndex(grid)

        begin_presentation.assert_not_called()
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_scan_commits_latest_grid_presentation_before_switching_back(tmp_path):
    (tmp_path / "asset.txt").write_text("asset")
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        details = panel._view_combo.findData("Details")
        grid = panel._view_combo.findData("Grid")
        panel._view_combo.setCurrentIndex(details)
        begin_presentation = Mock(wraps=panel._grid_widget.begin_presentation)
        panel._grid_widget.begin_presentation = begin_presentation

        panel.navigate_to(str(tmp_path), set_root=True)
        panel._model._wait_for_scan()
        app.processEvents()

        assert begin_presentation.call_args.args[0] == panel._model.scan_generation
        panel._view_combo.setCurrentIndex(grid)
        app.processEvents()
        assert panel._grid_widget._pending_presentation is not None
        assert panel._grid_widget._pending_presentation[0] == panel._model.scan_generation
    finally:
        panel.shutdown()
        app.processEvents()


def test_grid_reset_discards_pending_thumbnail_batch(tmp_path):
    (tmp_path / "asset.txt").write_text("asset")
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel._thumbnail_delivery._batch = {0: str(tmp_path / "asset.txt")}
        panel._thumbnail_delivery._timer.start()

        panel._model.set_directory(str(tmp_path))

        assert panel._thumbnail_delivery._batch == {}
        assert panel._thumbnail_delivery._timer.isActive() is False
    finally:
        panel.shutdown()
        app.processEvents()


def test_grid_thumbnail_delivery_batches_only_current_model_rows(tmp_path):
    (tmp_path / "asset.png").write_bytes(b"not decoded by this test")
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel.navigate_to(str(tmp_path), set_root=True)
        panel._model._wait_for_scan()
        row = panel._model._path_index[str(tmp_path / "asset.png")]
        committed = Mock()
        panel._grid_widget.commit_thumbnail_rows = committed
        image = QImage(1, 1, QImage.Format.Format_RGB32)

        panel._on_thumbnail_ready(row, str(tmp_path / "missing.png"), image)
        panel._on_thumbnail_ready(row, str(tmp_path / "asset.png"), image)
        panel._flush_thumb_batch()

        committed.assert_called_once_with([row])
    finally:
        panel.shutdown()
        app.processEvents()


def test_thumbnail_result_is_ignored_after_panel_shutdown():
    panel = type("_Panel", (), {})()
    panel._model = type("_Model", (), {"_is_shutdown": True})()

    FileListPanel._on_thumbnail_ready(panel, 0, "/library/asset.png", Mock())


def test_grid_thumbnail_delivery_is_ignored_after_panel_shutdown():
    panel = type("_Panel", (), {})()
    panel._model = type("_Model", (), {"_is_shutdown": True})()
    panel._thumbnail_delivery = Mock()

    QWidgetFileListPanel._on_thumbnail_ready(panel, 0, "/library/asset.png", Mock())

    panel._thumbnail_delivery.handle_ready.assert_not_called()


def test_delayed_grid_load_is_ignored_after_panel_shutdown():
    panel = type("_Panel", (), {})()
    panel._model = type("_Model", (), {"_is_shutdown": True})()
    panel._loader = Mock()

    QWidgetFileListPanel._load_visible(panel)

    panel._loader.request.assert_not_called()




def test_file_operation_is_ignored_after_panel_shutdown():
    panel = type("_Panel", (), {})()
    panel._model = type("_Model", (), {"_is_shutdown": True})()
    panel._file_op_timer = Mock()

    QWidgetFileListPanel._on_file_operation(panel, Mock())

    panel._file_op_timer.start.assert_not_called()


def test_grid_status_uses_cached_total_size_without_recomputing():
    panel = type("_Panel", (), {})()
    panel._model = type("_Model", (), {"rowCount": lambda _self: 20})()
    panel._view_mode = "Grid"
    panel._grid_widget = type("_Grid", (), {"selection_model_rows": lambda _self: set()})()
    panel._cached_total_sz = 1024
    panel._compute_total_sz = Mock()
    panel._controller = Mock()
    panel._controller.format_total_size_suffix.return_value = "  |  1.0 KB"
    panel._status = Mock()

    QWidgetFileListPanel._update_status(panel)

    panel._compute_total_sz.assert_not_called()
    panel._controller.format_total_size_suffix.assert_called_once_with(1024)


def test_grid_status_computes_total_size_when_cache_is_invalid():
    panel = type("_Panel", (), {})()
    panel._model = type("_Model", (), {"rowCount": lambda _self: 20})()
    panel._view_mode = "Grid"
    panel._grid_widget = type("_Grid", (), {"selection_model_rows": lambda _self: set()})()
    panel._cached_total_sz = -1
    panel._compute_total_sz = Mock(side_effect=lambda: setattr(panel, "_cached_total_sz", 1024))
    panel._controller = Mock()
    panel._controller.format_total_size_suffix.return_value = "  |  1.0 KB"
    panel._status = Mock()

    QWidgetFileListPanel._update_status(panel)

    panel._compute_total_sz.assert_called_once_with()
    panel._controller.format_total_size_suffix.assert_called_once_with(1024)


def test_grid_status_projects_explicit_file_list_states(tmp_path):
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel.navigate_to(str(tmp_path), set_root=True)
        assert "Loading" in panel._status.text()
        panel._model._wait_for_scan()
        assert panel._status.text() == tr("filelist.empty")

        (tmp_path / "asset.txt").write_text("asset")
        panel._model.refresh()
        panel._model._wait_for_scan()
        app.processEvents()
        panel._model._wait_for_scan()
        panel._model.set_filter(text="missing")
        assert panel._status.text() == tr("filelist.state.empty_filtered")
    finally:
        panel.shutdown()
        app.processEvents()


def test_operation_feedback_projects_running_success_and_partial_states(tmp_path):
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    panel = QWidgetFileListPanel()
    session = bootstrap.library_service.open_session(tmp_path)
    panel.set_scoped_services(bootstrap.runtime_for(session).services)
    try:
        panel._show_operation_feedback(session, "copy", running=True)
        assert panel._operation_feedback.isHidden() is False
        assert "progress" in panel._operation_feedback.text().lower()

        panel._show_operation_feedback(session, "copy", changed_count=2)
        assert "2" in panel._operation_feedback.text()
        assert panel._operation_feedback_timer.isActive()

        panel._show_operation_feedback(session, "copy", changed_count=1, errors=("blocked",))
        assert "1" in panel._operation_feedback.text()
        assert "failed" in panel._operation_feedback.text().lower()

        panel._show_operation_feedback(
            session,
            "copy",
            changed_count=1,
            warnings=(object(),),
        )
        assert panel._operation_feedback.text() == tr(
            "filelist.feedback.degraded",
            operation=tr("filelist.feedback.operation.copy"),
            count=1,
            warnings=1,
        )
    finally:
        panel.shutdown()
        app.processEvents()


def test_stale_operation_completion_does_not_refresh_or_update_feedback(tmp_path):
    from AssetsManager.application.file_operation_service import FileOperationResult

    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    source = first / "asset.txt"
    source.write_text("asset")
    panel = QWidgetFileListPanel()
    first_session = bootstrap.library_service.open_session(first)
    panel.set_scoped_services(bootstrap.runtime_for(first_session).services)
    callbacks = []
    try:
        panel.navigate_to(str(first), set_root=True)
        panel._clipboard_source = [str(source)]
        panel._clipboard_cut = False
        panel._run_in_background = lambda func, *args, on_done=None: callbacks.append((func, on_done))
        panel._post_refresh = Mock()
        panel._show_operation_feedback = Mock()
        bootstrap.runtime_for(first_session).services.file_operation_service.copy_to_directory = Mock(
            return_value=FileOperationResult((first / "copy.txt",), ())
        )

        panel._paste()
        second_session = bootstrap.library_service.open_session(second)
        panel.set_scoped_services(bootstrap.runtime_for(second_session).services)
        func, on_done = callbacks.pop()
        func()
        on_done()

        panel._post_refresh.assert_not_called()
        panel._show_operation_feedback.assert_called_once_with(first_session, "copy", running=True)
    finally:
        panel.shutdown()
        app.processEvents()


def test_duplicate_feedback_reports_partial_failures(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first")
    second.write_text("second")
    panel = QWidgetFileListPanel()
    session = bootstrap.library_service.open_session(tmp_path)
    scoped = bootstrap.runtime_for(session).services
    panel.set_scoped_services(scoped)
    try:
        panel._selected_paths = lambda: [str(first), str(second)]
        panel._run_in_background = lambda func, *args, on_done=None: (func(), on_done())
        panel._post_refresh = Mock()
        duplicated = tmp_path / "first - Copy.txt"

        def duplicate(path, *, copy_label):
            if path == str(second):
                raise OSError("target is locked")
            assert copy_label == " - Copy"
            return duplicated

        monkeypatch.setattr(scoped.file_operation_service, "duplicate", duplicate)

        panel._duplicate_selected()

        assert "1" in panel._operation_feedback.text()
        assert "failed" in panel._operation_feedback.text().lower()
        panel._post_refresh.assert_called_once()
    finally:
        panel.shutdown()
        app.processEvents()


def test_grid_selects_requested_operation_result_after_refresh(tmp_path):
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    panel = QWidgetFileListPanel()
    session = bootstrap.library_service.open_session(tmp_path)
    panel.set_scoped_services(bootstrap.runtime_for(session).services)
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()
    target = tmp_path / "created.txt"
    target.write_text("created")

    try:
        panel._request_operation_selection(session, [target])
        panel._post_refresh()
        panel._model._wait_for_scan()
        app.processEvents()
        panel._model._wait_for_scan()
        panel._model._wait_for_scan()

        assert panel._grid_widget.selection_model_rows() == {panel._model._path_index[str(target)]}
    finally:
        panel.shutdown()
        app.processEvents()


def test_operation_selection_is_discarded_after_directory_or_session_change(tmp_path):
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    target = first / "created.txt"
    target.write_text("created")
    panel = QWidgetFileListPanel()
    first_session = bootstrap.library_service.open_session(first)
    panel.set_scoped_services(bootstrap.runtime_for(first_session).services)
    panel.navigate_to(str(first), set_root=True)
    panel._model._wait_for_scan()

    try:
        panel._request_operation_selection(first_session, [target])
        second_session = bootstrap.library_service.open_session(second)
        panel.set_scoped_services(bootstrap.runtime_for(second_session).services)
        panel.navigate_to(str(second), set_root=True)
        panel._model._wait_for_scan()

        assert panel._grid_widget.selection_model_rows() == set()
    finally:
        panel.shutdown()
        app.processEvents()


def test_grid_deletion_candidates_prefer_next_visible_item(tmp_path):
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text(name)
    panel = QWidgetFileListPanel()
    session = bootstrap.library_service.open_session(tmp_path)
    panel.set_scoped_services(bootstrap.runtime_for(session).services)
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()
    deleted = tmp_path / "b.txt"

    try:
        candidates = panel._deletion_selection_candidates([deleted])
        deleted.unlink()
        panel._request_operation_selection(session, candidates)
        panel._post_refresh()
        panel._model._wait_for_scan()
        app.processEvents()
        panel._model._wait_for_scan()

        assert panel._grid_widget.selection_model_rows() == {panel._model._path_index[str(tmp_path / "c.txt")]}
    finally:
        panel.shutdown()
        app.processEvents()


def test_grid_deletion_candidates_fall_back_to_previous_visible_item(tmp_path):
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text(name)
    panel = QWidgetFileListPanel()
    session = bootstrap.library_service.open_session(tmp_path)
    panel.set_scoped_services(bootstrap.runtime_for(session).services)
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()
    deleted = tmp_path / "b.txt"

    try:
        candidates = panel._deletion_selection_candidates([deleted])
        deleted.unlink()
        panel._request_operation_selection(session, candidates)
        panel._post_refresh()
        panel._model._wait_for_scan()
        app.processEvents()
        panel._model._wait_for_scan()

        assert panel._grid_widget.selection_model_rows() == {panel._model._path_index[str(tmp_path / "a.txt")]}
    finally:
        panel.shutdown()
        app.processEvents()


def test_grid_undo_rename_selects_restored_path_after_refresh(tmp_path):
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    old = tmp_path / "old.txt"
    new = tmp_path / "new.txt"
    old.write_text("asset")
    panel = QWidgetFileListPanel()
    session = bootstrap.library_service.open_session(tmp_path)
    scoped = bootstrap.runtime_for(session).services
    panel.set_scoped_services(scoped)
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()
    scoped.undo_service.record_rename(str(old), str(new))
    scoped.file_operation_service.move(old, new)
    panel._run_in_background = lambda func, *args, on_done=None: (func(), on_done and on_done())

    try:
        panel._undo()
        panel._model._wait_for_scan()
        app.processEvents()
        panel._model._wait_for_scan()

        assert panel._grid_widget.selection_model_rows() == {panel._model._path_index[str(old)]}

        panel._redo()
        panel._model._wait_for_scan()
        app.processEvents()
        panel._model._wait_for_scan()

        assert panel._grid_widget.selection_model_rows() == {panel._model._path_index[str(new)]}
    finally:
        panel.shutdown()
        app.processEvents()


class _ScrollTimer:
    def __init__(self):
        self.start_calls = 0
        self.stop_calls = 0

    def start(self):
        self.start_calls += 1

    def stop(self):
        self.stop_calls += 1


def _bare_scroll_panel():
    panel = type("_Panel", (), {})()
    panel._scroll_debounce = _ScrollTimer()
    panel._scroll_animating = False
    panel._scroll_animation_generation = 0
    panel._scroll_animation_setting_value = False
    return panel


def test_manual_scroll_value_change_starts_thumbnail_debounce():
    panel = _bare_scroll_panel()

    FileListPanel._on_scroll_value_changed(panel)

    assert panel._scroll_debounce.start_calls == 1


def test_scroll_value_changes_during_smooth_animation_do_not_start_thumbnail_debounce():
    panel = _bare_scroll_panel()
    panel._scroll_animating = True
    panel._scroll_animation_setting_value = True

    FileListPanel._on_scroll_value_changed(panel)

    assert panel._scroll_debounce.start_calls == 0


def test_only_latest_smooth_scroll_completion_starts_thumbnail_debounce():
    panel = _bare_scroll_panel()

    first = FileListPanel._begin_smooth_scroll(panel)
    second = FileListPanel._begin_smooth_scroll(panel)
    FileListPanel._finish_smooth_scroll(panel, first)

    assert panel._scroll_debounce.start_calls == 0
    FileListPanel._finish_smooth_scroll(panel, second)

    assert panel._scroll_debounce.start_calls == 1


def test_user_scroll_during_smooth_animation_stops_animation_and_starts_debounce():
    panel = _bare_scroll_panel()
    animation = Mock()
    panel._scroll_anim = animation
    FileListPanel._begin_smooth_scroll(panel)

    FileListPanel._on_scroll_value_changed(panel)

    animation.stop.assert_called_once_with()
    assert panel._scroll_animating is False
    assert panel._scroll_debounce.start_calls == 1


def test_animation_scroll_value_change_does_not_cancel_its_own_animation():
    panel = _bare_scroll_panel()
    animation = Mock()
    panel._scroll_anim = animation
    FileListPanel._begin_smooth_scroll(panel)
    panel._scroll_animation_setting_value = True

    FileListPanel._on_scroll_value_changed(panel)

    animation.stop.assert_not_called()
    assert panel._scroll_debounce.start_calls == 0


def test_grid_scrollbar_uses_shared_animation_gate():
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        timer = _ScrollTimer()
        panel._scroll_debounce = timer
        scrollbar = panel._grid_widget._scrollbar
        scrollbar.setRange(0, 100)

        scrollbar.setValue(10)
        assert timer.start_calls == 1

        panel._scroll_animating = True
        panel._scroll_animation_setting_value = True
        scrollbar.setValue(20)
        assert timer.start_calls == 1
    finally:
        panel.shutdown()
        app.processEvents()


def test_grid_selection_shim_supports_actions_api(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel.navigate_to(str(tmp_path), set_root=True)
        panel._model._wait_for_scan()
        panel._grid_widget.update_layout(panel._model.rowCount(), 400)

        selection = panel._list_view.selectionModel()
        first = panel._model.index(0, 0)
        selection.select(first, QItemSelectionModel.SelectionFlag.Select)

        assert selection.currentIndex().isValid()
        assert [idx.row() for idx in selection.selectedRows()] == [0]

        selection.clear()

        assert selection.selectedRows() == []
    finally:
        panel.shutdown()
        app.processEvents()


def test_grid_selection_shim_emits_selection_changed(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel.navigate_to(str(tmp_path), set_root=True)
        panel._model._wait_for_scan()
        panel._grid_widget.update_layout(panel._model.rowCount(), 400)

        selection = panel._list_view.selectionModel()
        seen = []
        selection.selectionChanged.connect(lambda: seen.append(True))

        selection.select(panel._model.index(0, 0), QItemSelectionModel.SelectionFlag.Select)

        assert seen == [True]
    finally:
        panel.shutdown()
        app.processEvents()


def test_grid_selection_survives_sort_by_path(tmp_path):
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "a.txt").write_text("a")
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel.navigate_to(str(tmp_path), set_root=True)
        panel._model._wait_for_scan()
        panel._grid_widget.update_layout(panel._model.rowCount(), 400)
        target = str(tmp_path / "b.txt")
        row = panel._model._path_index[target]
        panel._grid_widget._selection = {row}

        panel._model.set_sort("name", asc=True)

        selected = [panel._model.path_at(r) for r in panel._grid_widget.selection_model_rows()]
        assert selected == [target]
    finally:
        panel.shutdown()
        app.processEvents()


def test_grid_selection_drops_filtered_paths(tmp_path):
    (tmp_path / "image.png").write_text("image")
    (tmp_path / "readme.txt").write_text("readme")
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel.navigate_to(str(tmp_path), set_root=True)
        panel._model._wait_for_scan()
        panel._grid_widget.update_layout(panel._model.rowCount(), 400)
        panel._grid_widget._selection = {panel._model._path_index[str(tmp_path / "readme.txt")]}

        panel._model.set_filter(category="images")

        assert panel._grid_widget.selection_model_rows() == set()
    finally:
        panel.shutdown()
        app.processEvents()


def test_set_root_uses_injected_scoped_library_runtime(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        session = bootstrap.library_service.open_session(tmp_path)
        services = bootstrap.runtime_for(session).services
        panel.set_scoped_services(services)

        panel.navigate_to(str(tmp_path), set_root=True)

        assert panel._model._metadata_service is not None
        conn = session.connection_for(tmp_path)
        assert panel._model._metadata_service._connection(tmp_path) is conn
        assert panel._loader._thumbnail_service is services.thumbnail_service
        assert not hasattr(panel._loader, "_db_conn")
        assert panel._loader._cache_dir == session.thumb_dir_str
        assert panel._loader._lib_root == session.root_str
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_uninjected_runtime_does_not_resolve_qapplication_bootstrap(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        bootstrap.library_service.open_session(tmp_path)
        runtime_for = Mock(wraps=bootstrap.runtime_for)
        monkeypatch.setattr(bootstrap, "runtime_for", runtime_for)

        with pytest.raises(RuntimeError, match="scoped services not injected"):
            panel._configure_library_runtime(str(tmp_path))

        runtime_for.assert_not_called()
        assert panel._scoped_services is None
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_root_refresh_retains_injected_session_and_closed_worker_skips_write(tmp_path, monkeypatch):
    """Queued work after close exits quietly without accessing the closed store."""
    class CapturingPool:
        def __init__(self):
            self.tasks = []

        def setMaxThreadCount(self, _count):
            pass

        def start(self, task):
            self.tasks.append(task)

        def waitForDone(self):
            pass

    library = tmp_path / "library"
    folder = library / "folder"
    folder.mkdir(parents=True)
    (folder / "asset.bin").write_bytes(b"abc")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    pool = CapturingPool()
    panel = QWidgetFileListPanel()
    try:
        session = bootstrap.library_service.open_session(library)
        scoped = bootstrap.runtime_for(session).services
        get_dir_size = Mock(wraps=scoped.metadata_service.get_dir_size)
        monkeypatch.setattr(scoped.metadata_service, "get_dir_size", get_dir_size)
        panel.set_scoped_services(scoped)
        panel._model._size_pool = pool

        panel.navigate_to(str(library), set_root=True)
        panel.navigate_to(str(folder))
        panel.navigate_to(str(library), set_root=True)

        assert panel._model._session is session
        panel._model._start_async_dir_size(str(folder))
        bootstrap.library_service.close_session(session)
        pool.tasks.pop().run()
        get_dir_size.assert_not_called()
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_prepare_library_switch_drains_thumbnails_before_directory_size_work():
    panel = type("_Panel", (), {})()
    calls = []
    panel._loader = type("_Loader", (), {
        "invalidate_tasks": lambda _self: calls.append("invalidate") or 3,
        "wait_for_runtime": lambda _self, generation: calls.append(("thumbnails", generation)),
    })()
    panel._model = type("_Model", (), {
        "prepare_library_switch": lambda _self: calls.append("directory-sizes"),
    })()

    FileListPanel.prepare_library_switch(panel)

    assert calls == ["invalidate", ("thumbnails", 3), "directory-sizes"]


def test_directory_size_result_is_ignored_after_panel_shutdown():
    panel = type("_Panel", (), {})()
    panel._model = type("_Model", (), {
        "_is_shutdown": True,
        "_pending_dir_sizes": {"/library/folder"},
    })()

    FileListPanel._on_dir_size_ready(panel, "/library/folder", "1.0 KB", 1)

    assert panel._model._pending_dir_sizes == {"/library/folder"}


def test_external_drop_uses_scoped_file_operation_service(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from AssetsManager.panels.file_list._base import FileListPanel

    library = tmp_path / "library"
    library.mkdir()
    external = tmp_path / "external.txt"
    external.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
        panel.set_scoped_services(scoped)
        panel.navigate_to(str(library), set_root=True)
        panel._post_refresh = Mock()
        panel._load_visible = Mock()

        class DropEvent:
            def __init__(self, *paths):
                self.paths = paths

            def mimeData(self):
                class MimeData:
                    def urls(self):
                        class Url:
                            def toLocalFile(self):
                                return str(external)
                        return [Url()]
                return MimeData()

        copied = Mock(return_value=type("Result", (), {"errors": ()})())
        monkeypatch.setattr(scoped.file_operation_service, "copy_to_directory", copied)

        assert panel._on_drop(DropEvent()) is True
        copied.assert_called_once_with(
            [str(external)], str(library), library_root=str(library),
        )

        copied.reset_mock()
        assert FileListPanel._on_drop(panel, DropEvent()) is True
        copied.assert_called_once_with(
            [str(external)], str(library), library_root=str(library),
        )
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_in_library_drop_moves_and_records_only_successful_undo_entries(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from AssetsManager.application.file_operation_service import (
        FileOperationResult,
        FileOperationWarning,
    )
    from AssetsManager.panels.file_list._base import FileListPanel

    library = tmp_path / "library"
    source = library / "asset.txt"
    failed_source = library / "failed.txt"
    destination = library / "destination"
    library.mkdir()
    destination.mkdir()
    source.write_text("asset")
    failed_source.write_text("failed")
    moved = destination / "asset-renamed.txt"
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
        panel.set_scoped_services(scoped)
        panel._current = destination
        panel._post_refresh = Mock()
        panel._load_visible = Mock()
        panel._undo_svc = Mock()

        class DropEvent:
            def __init__(self, *paths):
                self.paths = paths

            def mimeData(self):
                class MimeData:
                    def __init__(self, paths):
                        self.paths = paths

                    def urls(self):
                        class Url:
                            def __init__(self, path):
                                self.path = path

                            def toLocalFile(self):
                                return str(self.path)
                        return [Url(path) for path in self.paths]
                return MimeData(self.paths)

        move = Mock(side_effect=[
            FileOperationResult(
                (moved,),
                (),
                (
                    FileOperationWarning(
                        "asset_index_refresh_busy",
                        "parent",
                        str(destination),
                        "busy",
                    ),
                ),
            ),
            FileOperationResult((), ("move failed",)),
        ])
        copy = Mock()
        monkeypatch.setattr(scoped.file_operation_service, "move_to_directory", move)
        monkeypatch.setattr(scoped.file_operation_service, "copy_to_directory", copy)

        assert panel._on_drop(DropEvent(source, failed_source)) is True

        assert move.call_args_list == [
            (([str(source)], str(destination)), {"library_root": str(library)}),
            (([str(failed_source)], str(destination)), {"library_root": str(library)}),
        ]
        copy.assert_not_called()
        panel._undo_svc.record_rename.assert_called_once_with(str(source), str(moved))
        assert panel._operation_feedback.text() == tr(
            "filelist.feedback.partial_degraded",
            operation=tr("filelist.feedback.operation.drop"),
            count=1,
            failed=1,
            warnings=1,
        )

        panel._undo_svc.reset_mock()
        move.reset_mock()
        move.side_effect = None
        move.return_value = FileOperationResult((moved,), ())
        assert FileListPanel._on_drop(panel, DropEvent(source)) is True
        panel._undo_svc.record_rename.assert_called_once_with(str(source), str(moved))

    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_external_drop_without_scoped_services_refuses_copy(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from AssetsManager.panels.file_list._base import FileListPanel

    library = tmp_path / "library"
    external = tmp_path / "external.txt"
    library.mkdir()
    external.write_text("asset")
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel._current = library
        copy_service = Mock()
        monkeypatch.setattr(panel, "_get_file_operation_service", copy_service)

        class DropEvent:
            def mimeData(self):
                class MimeData:
                    def urls(self):
                        class Url:
                            def toLocalFile(self):
                                return str(external)
                        return [Url()]
                return MimeData()

        assert panel._on_drop(DropEvent()) is False
        assert FileListPanel._on_drop(panel, DropEvent()) is False
        copy_service.assert_not_called()
    finally:
        panel.shutdown()
        app.processEvents()


def test_paste_uses_scoped_service_for_local_system_clipboard_urls(tmp_path, monkeypatch):
    from unittest.mock import Mock

    library = tmp_path / "library"
    library.mkdir()
    external = tmp_path / "external.txt"
    external.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
        panel.set_scoped_services(scoped)
        panel.navigate_to(str(library), set_root=True)
        panel._run_in_background = lambda func, *args, on_done=None: (func(), on_done and on_done())
        panel._post_refresh = Mock()
        copied = Mock(return_value=type("Result", (), {"ok": True, "errors": ()})())
        monkeypatch.setattr(scoped.file_operation_service, "copy_to_directory", copied)

        mime = QMimeData()
        local_url = QUrl.fromLocalFile(str(external))
        mime.setUrls([local_url])
        QApplication.clipboard().setMimeData(mime)

        panel._paste()

        copied.assert_called_once_with([local_url.toLocalFile()], str(library))
        panel._post_refresh.assert_called_once()

        copied.reset_mock()
        panel._post_refresh.reset_mock()
        mime = QMimeData()
        mime.setUrls([QUrl("https://example.com/asset"), QUrl()])
        QApplication.clipboard().setMimeData(mime)

        panel._paste()

        copied.assert_not_called()
        panel._post_refresh.assert_not_called()
    finally:
        QApplication.clipboard().clear()
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_paste_passes_index_warnings_to_operation_feedback(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from AssetsManager.application.file_operation_service import (
        FileOperationResult,
        FileOperationWarning,
    )

    library = tmp_path / "library"
    library.mkdir()
    external = tmp_path / "external.txt"
    external.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
        panel.set_scoped_services(scoped)
        panel.navigate_to(str(library), set_root=True)
        panel._run_in_background = lambda func, *args, on_done=None: (func(), on_done and on_done())
        panel._post_refresh = Mock()
        panel._show_operation_feedback = Mock()
        monkeypatch.setattr(
            scoped.file_operation_service,
            "copy_to_directory",
            Mock(
                return_value=FileOperationResult(
                    (library / "external.txt",),
                    (),
                    (
                        FileOperationWarning(
                            "asset_index_refresh_busy",
                            "parent",
                            str(library),
                            "busy",
                        ),
                    ),
                )
            ),
        )

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(external))])
        QApplication.clipboard().setMimeData(mime)
        panel._paste()

        done_calls = [
            call
            for call in panel._show_operation_feedback.call_args_list
            if call.kwargs.get("warnings")
        ]
        assert len(done_calls) == 1
        assert len(done_calls[0].kwargs["warnings"]) == 1
    finally:
        QApplication.clipboard().clear()
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_paste_without_scoped_services_refuses_external_and_internal_clipboards(tmp_path, monkeypatch):
    from unittest.mock import Mock

    library = tmp_path / "library"
    library.mkdir()
    external = tmp_path / "external.txt"
    external.write_text("asset")
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel._current = library
        panel._post_refresh = Mock()
        service = Mock()
        monkeypatch.setattr(panel, "_get_file_operation_service", service)

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(external))])
        QApplication.clipboard().setMimeData(mime)

        panel._paste()

        service.assert_not_called()
        panel._post_refresh.assert_not_called()

        panel._clipboard_source = [str(external)]
        panel._clipboard_cut = True
        panel._paste()

        service.assert_not_called()
        panel._post_refresh.assert_not_called()
        assert panel._clipboard_source == [str(external)]
        assert panel._clipboard_cut is True
    finally:
        QApplication.clipboard().clear()
        panel.shutdown()
        app.processEvents()


def test_cut_paste_records_undo_only_after_successful_move(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from AssetsManager.application.file_operation_service import FileOperationResult

    library = tmp_path / "library"
    library.mkdir()
    source = library / "asset.txt"
    source.write_text("asset")
    second_source = library / "second.txt"
    second_source.write_text("second")
    destination = library / "destination"
    destination.mkdir()
    moved = destination / source.name
    second_moved = destination / second_source.name
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
        panel.set_scoped_services(scoped)
        panel._current = destination

        def run_inline(func, *args, on_done=None):
            func()
            if on_done:
                on_done()

        panel._run_in_background = run_inline
        panel._post_refresh = Mock()
        panel._undo_svc = Mock()
        move = Mock(return_value=FileOperationResult((moved, second_moved), ()))
        monkeypatch.setattr(scoped.file_operation_service, "move_to_directory", move)
        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QMessageBox.warning",
            Mock(),
        )

        panel._clipboard_source = [str(source), str(second_source)]
        panel._clipboard_cut = True
        panel._paste()

        move.assert_called_once_with(
            [str(source), str(second_source)], str(destination), library_root=str(library),
        )
        assert panel._undo_svc.record_rename.call_args_list == [
            ((str(source), str(moved)),),
            ((str(second_source), str(second_moved)),),
        ]

        panel._undo_svc.reset_mock()
        move.reset_mock()
        panel._clipboard_source = [str(source), str(second_source)]
        panel._clipboard_cut = True
        move.return_value = FileOperationResult((moved, second_moved), ("move failed",))

        panel._paste()

        panel._undo_svc.record_rename.assert_not_called()
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_cut_paste_outside_library_reports_error_and_keeps_clipboard(tmp_path, monkeypatch):
    from unittest.mock import Mock

    library = tmp_path / "library"
    library.mkdir()
    external = tmp_path / "external.txt"
    external.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
        panel.set_scoped_services(scoped)
        panel.navigate_to(str(library), set_root=True)
        panel._run_in_background = lambda func, *args, on_done=None: (func(), on_done and on_done())
        panel._post_refresh = Mock()
        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QMessageBox.warning",
            Mock(),
        )

        panel._clipboard_source = [str(external)]
        panel._clipboard_cut = True
        panel._paste()

        # The out-of-library move refusal surfaces through the operation
        # feedback path instead of dying silently inside the worker thread…
        assert "failed" in panel._operation_feedback.text().lower()
        # …and the cut markers are restored so the user can retry elsewhere.
        assert panel._clipboard_source == [str(external)]
        assert panel._clipboard_cut is True
        panel._post_refresh.assert_called_once()
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_delete_to_trash_skips_undo_backup_and_scopes_service(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from PySide6.QtWidgets import QMessageBox

    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    target = tmp_path / "asset.txt"
    target.write_text("asset")
    try:
        panel.navigate_to(str(tmp_path), set_root=True)
        panel.set_scoped_services(bootstrap.runtime_for(bootstrap.library_service.open_session(tmp_path)).services)
        panel._undo_svc = Mock()
        panel._post_refresh = Mock()
        service = Mock()
        service.delete_to_trash.return_value = type("Result", (), {"errors": ()})()
        monkeypatch.setattr(panel, "_get_file_operation_service", lambda: service)
        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QMessageBox.question",
            lambda *args: QMessageBox.StandardButton.Yes,
        )
        def run_inline(func, *args, on_done=None):
            func()
            if on_done:
                on_done()

        panel._run_in_background = run_inline

        panel._delete([str(target)])

        panel._undo_svc.record_delete.assert_not_called()
        service.delete_to_trash.assert_called_once_with([str(target)], library_root=str(tmp_path))
        panel._post_refresh.assert_called_once()
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_permanent_delete_records_undo_only_after_scoped_delete_succeeds(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from AssetsManager.application.file_operation_service import FileOperationResult
    from PySide6.QtWidgets import QMessageBox

    library = tmp_path / "library"
    target = library / "asset.txt"
    library.mkdir()
    target.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
        panel.set_scoped_services(scoped)
        panel._run_in_background = lambda func, *args, on_done=None: (func(), on_done and on_done())
        panel._post_refresh = Mock()
        service = Mock()
        service.delete_permanent.return_value = FileOperationResult((target,), ())
        monkeypatch.setattr(panel, "_get_file_operation_service", lambda: service)
        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QMessageBox.warning",
            lambda *args: QMessageBox.StandardButton.Yes,
        )

        panel._delete_permanent([str(target)])

        service.delete_permanent.assert_called_once_with([str(target)], library_root=str(library))
        assert panel._undo_svc.can_undo()
        assert panel._undo_svc.peek_undo().path == str(target)
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_failed_permanent_delete_discards_backup_without_undo_history(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from AssetsManager.application.file_operation_service import FileOperationResult
    from PySide6.QtWidgets import QMessageBox

    library = tmp_path / "library"
    target = library / "asset.txt"
    library.mkdir()
    target.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
        panel.set_scoped_services(scoped)
        panel._run_in_background = lambda func, *args, on_done=None: (func(), on_done and on_done())
        panel._post_refresh = Mock()
        service = Mock()
        service.delete_permanent.return_value = FileOperationResult((), ("blocked",))
        monkeypatch.setattr(panel, "_get_file_operation_service", lambda: service)
        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QMessageBox.warning",
            lambda *args: QMessageBox.StandardButton.Yes,
        )

        panel._delete_permanent([str(target)])

        service.delete_permanent.assert_called_once_with([str(target)], library_root=str(library))
        assert not panel._undo_svc.can_undo()
        assert list(Path(panel._undo_svc._undo_dir).iterdir()) == []
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_partial_permanent_delete_commits_only_changed_path_backups(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from AssetsManager.application.file_operation_service import FileOperationResult
    from PySide6.QtWidgets import QMessageBox

    library = tmp_path / "library"
    first_target = library / "first.txt"
    second_target = library / "second.txt"
    library.mkdir()
    first_target.write_text("first")
    second_target.write_text("second")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
        panel.set_scoped_services(scoped)
        panel._run_in_background = lambda func, *args, on_done=None: (func(), on_done and on_done())
        panel._post_refresh = Mock()
        service = Mock()
        service.delete_permanent.return_value = FileOperationResult(
            (first_target,), ("second delete failed",),
        )
        monkeypatch.setattr(panel, "_get_file_operation_service", lambda: service)
        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QMessageBox.warning",
            lambda *args: QMessageBox.StandardButton.Yes,
        )

        panel._delete_permanent([str(first_target), str(second_target)])

        assert panel._undo_svc.can_undo()
        assert panel._undo_svc.peek_undo().path == str(first_target)
        entries = list(Path(panel._undo_svc._undo_dir).iterdir())
        # The backup file plus its projection snapshot file.
        assert len(entries) == 2
        assert sum(1 for entry in entries if entry.name.endswith(".projection.json")) == 1
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_partial_delete_selects_neighbor_of_successfully_deleted_path(tmp_path, monkeypatch):
    from AssetsManager.application.file_operation_service import FileOperationResult
    from PySide6.QtWidgets import QMessageBox

    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text(name)
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    panel = QWidgetFileListPanel()
    session = bootstrap.library_service.open_session(tmp_path)
    panel.set_scoped_services(bootstrap.runtime_for(session).services)
    monkeypatch.setattr(
        "AssetsManager.panels.file_list._actions.QMessageBox.question",
        lambda *args: QMessageBox.StandardButton.Yes,
    )
    try:
        panel.navigate_to(str(tmp_path), set_root=True)
        panel._model._wait_for_scan()
        panel._run_in_background = lambda func, *args, on_done=None: (func(), on_done and on_done())
        panel._post_refresh = Mock()
        panel._request_operation_selection = Mock()
        service = Mock(return_value=None)
        service.delete_to_trash.return_value = FileOperationResult((tmp_path / "a.txt",), ("b failed",))
        monkeypatch.setattr(panel, "_get_file_operation_service", lambda: service)

        panel._delete([str(tmp_path / "a.txt"), str(tmp_path / "b.txt")])

        panel._request_operation_selection.assert_called_once_with(session, (str(tmp_path / "b.txt"), str(tmp_path / "c.txt")))
    finally:
        panel.shutdown()
        app.processEvents()


def test_operation_request_without_current_directory_target_clears_prior_intent(tmp_path):
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    panel = QWidgetFileListPanel()
    session = bootstrap.library_service.open_session(tmp_path)
    panel.set_scoped_services(bootstrap.runtime_for(session).services)
    target = tmp_path / "target.txt"
    outside = tmp_path.parent / "outside.txt"
    try:
        panel.navigate_to(str(tmp_path), set_root=True)
        panel._request_operation_selection(session, [target])

        panel._request_operation_selection(session, [outside])

        assert panel._pending_operation_selection is None
    finally:
        panel.shutdown()
        app.processEvents()


def test_panel_undo_redo_use_perform_methods(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from AssetsManager.application.file_operation_service import FileOperationWarning

    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel._run_in_background = lambda func, *args, on_done=None: (func(), on_done and on_done())
        panel._post_refresh = Mock()
        panel._undo_svc = Mock()
        panel._undo_svc.can_undo.return_value = True
        panel._undo_svc.can_redo.return_value = True
        service = Mock()
        service.last_operation_id = None
        service.drain_refresh_diagnostics.side_effect = [
            (
                (
                    "undo-op",
                    (
                        FileOperationWarning(
                            "asset_index_refresh_busy", "parent", str(tmp_path), "busy"
                        ),
                    ),
                ),
            ),
            (
                (
                    "redo-op",
                    (
                        FileOperationWarning(
                            "asset_index_refresh_stale", "parent", str(tmp_path), "stale"
                        ),
                    ),
                ),
            ),
        ]
        panel._undo_svc.perform_undo.return_value = True
        panel._undo_svc.perform_redo.return_value = True
        panel._show_operation_feedback = Mock()
        monkeypatch.setattr(panel, "_get_scoped_services", lambda: Mock())
        monkeypatch.setattr(panel, "_get_file_operation_service", lambda: service)
        monkeypatch.setattr(panel, "_is_current_operation_session", lambda _session: True)

        panel._undo()
        panel._redo()

        panel._undo_svc.perform_undo.assert_called_once_with(service, panel._lib_root)
        panel._undo_svc.perform_redo.assert_called_once_with(service, panel._lib_root)
        warning_calls = [
            call
            for call in panel._show_operation_feedback.call_args_list
            if call.kwargs.get("warnings")
        ]
        assert len(warning_calls) == 2
    finally:
        panel.shutdown()
        app.processEvents()


def test_failed_grid_rename_does_not_record_undo(tmp_path, monkeypatch):
    from unittest.mock import Mock

    source = tmp_path / "asset.txt"
    source.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        panel.set_scoped_services(bootstrap.runtime_for(bootstrap.library_service.open_session(tmp_path)).services)
        panel._undo_svc = Mock()
        service = Mock()
        service.move.side_effect = OSError("rename failed")
        monkeypatch.setattr(panel, "_get_file_operation_service", lambda: service)

        import pytest

        with pytest.raises(OSError, match="rename failed"):
            panel._rename_file_path(str(source), "renamed.txt")

        service.move.assert_called_once()
        panel._undo_svc.record_rename.assert_not_called()
        assert source.exists()
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_covered_mutations_refuse_without_scoped_services(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from PySide6.QtWidgets import QMessageBox

    source = tmp_path / "asset.txt"
    destination = tmp_path / "renamed.txt"
    source.write_text("asset")
    QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        service = Mock()
        panel._post_refresh = Mock()
        panel._undo_svc = Mock()
        panel._undo_svc.can_undo.return_value = True
        panel._undo_svc.can_redo.return_value = True
        run_in_background = Mock()
        panel._run_in_background = run_in_background
        monkeypatch.setattr(panel, "_get_file_operation_service", lambda: service)
        question = Mock(return_value=QMessageBox.StandardButton.Yes)
        warning = Mock(return_value=QMessageBox.StandardButton.Yes)
        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QMessageBox.question", question,
        )
        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QMessageBox.warning", warning,
        )

        assert panel._rename_absolute(str(source), str(destination)) == str(source.resolve())
        panel._delete([str(source)])
        panel._delete_permanent([str(source)])
        panel._undo()
        panel._redo()

        service.assert_not_called()
        question.assert_not_called()
        warning.assert_not_called()
        panel._undo_svc.perform_undo.assert_not_called()
        panel._undo_svc.perform_redo.assert_not_called()
        run_in_background.assert_not_called()
        panel._post_refresh.assert_not_called()
        assert source.exists()
    finally:
        panel.shutdown()


def test_unscoped_mutations_never_construct_unbound_services(tmp_path, monkeypatch):
    """Mutation paths must fail closed before reaching fallback constructors."""
    from unittest.mock import Mock

    from AssetsManager.panels.file_list._base import FileListPanel

    source = tmp_path / "asset.txt"
    destination = tmp_path / "renamed.txt"
    source.write_text("asset")
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel._clipboard_source = [str(source)]
        panel._clipboard_cut = False
        panel._post_refresh = Mock()
        panel._run_in_background = Mock()
        panel._undo_svc = Mock()
        panel._undo_svc.can_undo.return_value = True
        panel._undo_svc.can_redo.return_value = True
        monkeypatch.setattr(
            "AssetsManager.application.FileOperationService",
            lambda: (_ for _ in ()).throw(AssertionError("unbound FileOperationService constructed")),
        )
        monkeypatch.setattr(
            "AssetsManager.application.UndoService",
            lambda: (_ for _ in ()).throw(AssertionError("unbound UndoService constructed")),
        )

        assert panel._rename_absolute(str(source), str(destination)) == str(source.resolve())
        panel._paste()
        assert FileListPanel._on_drop(panel, type("Drop", (), {"mimeData": lambda self: type("Mime", (), {"urls": lambda self: [type("Url", (), {"toLocalFile": lambda self: str(source)})()]})()})()) is False
        panel._delete([str(source)])
        panel._delete_permanent([str(source)])
        panel._new_folder()
        panel._duplicate_selected()
        panel._undo()
        panel._redo()

        panel._run_in_background.assert_not_called()
        panel._post_refresh.assert_not_called()
    finally:
        panel.shutdown()
        app.processEvents()


def test_duplicate_captures_originating_service_and_closed_session_refuses(tmp_path, monkeypatch):
    """Queued duplicates stay bound to the service injected when requested."""
    from unittest.mock import Mock

    import pytest

    library_a = tmp_path / "library-a"
    library_b = tmp_path / "library-b"
    source = library_a / "asset.txt"
    library_a.mkdir()
    library_b.mkdir()
    source.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    queued = []
    try:
        scoped_a = bootstrap.runtime_for(bootstrap.library_service.open_session(library_a)).services
        scoped_b = bootstrap.runtime_for(bootstrap.library_service.open_session(library_b)).services
        duplicate_a = Mock(wraps=scoped_a.file_operation_service.duplicate)
        duplicate_b = Mock(wraps=scoped_b.file_operation_service.duplicate)
        monkeypatch.setattr(scoped_a.file_operation_service, "duplicate", duplicate_a)
        monkeypatch.setattr(scoped_b.file_operation_service, "duplicate", duplicate_b)
        panel.set_scoped_services(scoped_a)
        monkeypatch.setattr(panel, "_selected_paths", lambda: [str(source)])
        monkeypatch.setattr(
            panel, "_run_in_background", lambda operation, *args, on_done=None: queued.append(operation),
        )
        panel._post_refresh = Mock()

        panel._duplicate_selected()
        panel.set_scoped_services(scoped_b)

        queued.pop()()
        assert (library_a / "asset - Copy.txt").read_text() == "asset"
        assert not (library_b / "asset - Copy.txt").exists()
        duplicate_a.assert_called_once_with(str(source), copy_label=" - Copy")
        duplicate_b.assert_not_called()

        panel.set_scoped_services(scoped_a)
        panel._duplicate_selected()
        panel.set_scoped_services(scoped_b)
        bootstrap.library_service.close_session(scoped_a.session)

        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            queued.pop()()
        assert duplicate_a.call_count == 1
        duplicate_b.assert_not_called()
        assert not (library_a / "asset - Copy_1.txt").exists()
        assert not (library_b / "asset - Copy.txt").exists()
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_queued_mutations_capture_originating_scoped_dependencies(tmp_path, monkeypatch):
    """Switching panels cannot redirect queued mutations to another library."""
    from types import SimpleNamespace
    from unittest.mock import Mock

    import pytest
    from PySide6.QtWidgets import QMessageBox

    library_a = tmp_path / "library-a"
    library_b = tmp_path / "library-b"
    library_a.mkdir()
    library_b.mkdir()
    source = library_a / "asset.txt"
    source.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    queued = []
    try:
        scoped_a = bootstrap.runtime_for(bootstrap.library_service.open_session(library_a)).services
        scoped_b = bootstrap.runtime_for(bootstrap.library_service.open_session(library_b)).services
        for scoped in (scoped_a, scoped_b):
            scoped.file_operation_service.copy_to_directory = Mock(
                return_value=SimpleNamespace(ok=True, changed_paths=(), errors=()),
            )
            scoped.file_operation_service.move_to_directory = Mock(
                return_value=SimpleNamespace(ok=True, changed_paths=(), errors=()),
            )
            scoped.file_operation_service.delete_to_trash = Mock(
                return_value=SimpleNamespace(errors=()),
            )
            scoped.file_operation_service.delete_permanent = Mock(
                return_value=SimpleNamespace(changed_paths=(), errors=()),
            )
            scoped.undo_service.prepare_delete = Mock(return_value=None)
            scoped.undo_service.commit_delete = Mock()
            scoped.undo_service.discard_delete = Mock()
            scoped.undo_service.perform_undo = Mock()
            scoped.undo_service.perform_redo = Mock()
            scoped.undo_service.can_undo = Mock(return_value=True)
            scoped.undo_service.can_redo = Mock(return_value=True)
        panel._run_in_background = lambda operation, *args, on_done=None: queued.append(operation)
        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QMessageBox.question",
            Mock(return_value=QMessageBox.StandardButton.Yes),
        )
        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QMessageBox.warning",
            Mock(return_value=QMessageBox.StandardButton.Yes),
        )

        actions = [
            lambda: (setattr(panel, "_clipboard_source", [str(source)]), setattr(panel, "_clipboard_cut", False), panel._paste()),
            lambda: panel._delete([str(source)]),
            lambda: panel._delete_permanent([str(source)]),
            panel._undo,
            panel._redo,
        ]
        for action in actions:
            panel.set_scoped_services(scoped_a)
            action()
            panel.set_scoped_services(scoped_b)
            queued.pop()()

        assert scoped_a.file_operation_service.copy_to_directory.called
        assert scoped_a.file_operation_service.delete_to_trash.called
        assert scoped_a.file_operation_service.delete_permanent.called
        scoped_a.undo_service.perform_undo.assert_called_once_with(
            scoped_a.file_operation_service, str(library_a.resolve()),
        )
        scoped_a.undo_service.perform_redo.assert_called_once_with(
            scoped_a.file_operation_service, str(library_a.resolve()),
        )
        assert not scoped_b.file_operation_service.copy_to_directory.called
        assert not scoped_b.file_operation_service.delete_to_trash.called
        assert not scoped_b.file_operation_service.delete_permanent.called
        assert not scoped_b.undo_service.perform_undo.called
        assert not scoped_b.undo_service.perform_redo.called

        for action in actions:
            session_a = bootstrap.library_service.open_session(library_a)
            scoped_a = bootstrap.runtime_for(session_a).services
            scoped_a.undo_service.can_undo = Mock(return_value=True)
            scoped_a.undo_service.can_redo = Mock(return_value=True)
            panel.set_scoped_services(scoped_a)
            panel._clipboard_source = [str(source)]
            panel._clipboard_cut = False
            panel._run_in_background = lambda operation, *args, on_done=None: queued.append(operation)
            action()
            panel.set_scoped_services(scoped_b)
            bootstrap.library_service.close_session(session_a)
            with pytest.raises(RuntimeError, match="closed LibrarySession"):
                queued.pop()()
        assert not scoped_b.file_operation_service.move_to_directory.called
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_panel_shutdown_does_not_cleanup_bootstrap_owned_undo_service(tmp_path, monkeypatch):
    from unittest.mock import Mock

    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(tmp_path)).services
    panel.set_scoped_services(scoped)
    cleanup = Mock()
    monkeypatch.setattr(scoped.undo_service, "cleanup", cleanup)

    try:
        panel.shutdown()
        cleanup.assert_not_called()
    finally:
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_panel_shutdown_releases_scoped_service_references(tmp_path):
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    panel = QWidgetFileListPanel()
    scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(tmp_path)).services
    panel.set_scoped_services(scoped)

    try:
        panel.shutdown()

        assert panel._scoped_services is None
        assert panel._undo_svc is None
        assert panel._model._session is None
        assert panel._model._metadata_service is None
        assert panel._controller._file_ops is None
        assert panel._controller._undo_svc is None
    finally:
        app.processEvents()


def test_file_list_does_not_construct_unbound_undo_service(monkeypatch):
    """The panel receives its undo service only through scoped injection."""
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        "AssetsManager.application.UndoService",
        lambda: (_ for _ in ()).throw(AssertionError("unbound UndoService constructed")),
    )

    panel = QWidgetFileListPanel()
    try:
        assert panel._undo_svc is None
    finally:
        panel.shutdown()
        app.processEvents()


def test_grid_selection_survives_post_refresh_by_path(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    target = tmp_path / "b.txt"
    target.write_text("b")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    panel = QWidgetFileListPanel()
    session = bootstrap.library_service.open_session(tmp_path)
    panel.set_scoped_services(bootstrap.runtime_for(session).services)
    try:
        panel.navigate_to(str(tmp_path), set_root=True)
        panel._model._wait_for_scan()
        panel._grid_widget._selection = {panel._model._path_index[str(target)]}

        panel._post_refresh()
        panel._model._wait_for_scan()
        app.processEvents()
        panel._model._wait_for_scan()
        panel._model._wait_for_scan()

        selected = [panel._model.path_at(row) for row in panel._grid_widget.selection_model_rows()]
        assert selected == [str(target)]
    finally:
        panel.shutdown()
        app.processEvents()


def test_grid_batch_rename_selects_first_renamed_result(tmp_path, monkeypatch):
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text(name)
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    panel = QWidgetFileListPanel()
    session = bootstrap.library_service.open_session(tmp_path)
    panel.set_scoped_services(bootstrap.runtime_for(session).services)
    from AssetsManager.panels.file_list._batch_rename import plan_batch_rename

    class AcceptedDialog:
        DialogCode = type("DialogCode", (), {"Accepted": 1})

        def __init__(self, paths, _parent):
            self.plan = plan_batch_rename(
                paths, "{name}_renamed", occupied_paths=paths, windows_rules=True,
            )

        def exec(self):
            return self.DialogCode.Accepted

    monkeypatch.setattr("AssetsManager.panels.file_list._batch_rename_dialog.BatchRenameDialog", AcceptedDialog)
    try:
        panel.navigate_to(str(tmp_path), set_root=True)
        panel._model._wait_for_scan()
        panel._grid_widget._selection = {
            panel._model._path_index[str(tmp_path / name)] for name in ("a.txt", "b.txt")
        }

        panel._batch_rename([str(tmp_path / "a.txt"), str(tmp_path / "b.txt")])
        panel._model._wait_for_scan()
        app.processEvents()
        panel._model._wait_for_scan()
        app.processEvents()

        selected = [panel._model.path_at(row) for row in panel._grid_widget.selection_model_rows()]
        assert selected == [str(tmp_path / "a_renamed.txt")]
    finally:
        panel.shutdown()
        app.processEvents()


def test_grid_selection_survives_filter_when_path_remains_visible(tmp_path):
    (tmp_path / "alpha.txt").write_text("a")
    target = tmp_path / "beta.txt"
    target.write_text("b")
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel.navigate_to(str(tmp_path), set_root=True)
        panel._model._wait_for_scan()
        panel._grid_widget._selection = {panel._model._path_index[str(target)]}

        panel._model.set_filter(text="beta")

        selected = [panel._model.path_at(row) for row in panel._grid_widget.selection_model_rows()]
        assert selected == [str(target)]
    finally:
        panel.shutdown()
        app.processEvents()


def test_grid_clear_selection_during_refresh_overrides_path_restore(tmp_path):
    target = tmp_path / "asset.txt"
    target.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    panel = QWidgetFileListPanel()
    session = bootstrap.library_service.open_session(tmp_path)
    panel.set_scoped_services(bootstrap.runtime_for(session).services)
    try:
        panel.navigate_to(str(tmp_path), set_root=True)
        panel._model._wait_for_scan()
        panel._grid_widget._selection = {panel._model._path_index[str(target)]}

        panel._post_refresh()
        panel._grid_widget.clear_selection()
        panel._model._wait_for_scan()
        app.processEvents()

        assert panel._grid_widget.selection_model_rows() == set()
    finally:
        panel.shutdown()
        app.processEvents()


def test_grid_selection_drops_when_navigating_to_another_directory(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    selected = first / "selected.txt"
    selected.write_text("asset")
    (second / "other.txt").write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    panel = QWidgetFileListPanel()
    session = bootstrap.library_service.open_session(tmp_path)
    panel.set_scoped_services(bootstrap.runtime_for(session).services)
    try:
        panel.navigate_to(str(first), set_root=True)
        panel._model._wait_for_scan()
        panel._grid_widget._selection = {panel._model._path_index[str(selected)]}

        panel.navigate_to(str(second))
        panel._model._wait_for_scan()
        app.processEvents()

        assert panel.current_path == str(second.resolve())
        assert panel._grid_widget.selection_model_rows() == set()
    finally:
        panel.shutdown()
        app.processEvents()


def test_grid_refresh_drops_externally_removed_selection(tmp_path):
    target = tmp_path / "removed.txt"
    target.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    panel = QWidgetFileListPanel()
    session = bootstrap.library_service.open_session(tmp_path)
    panel.set_scoped_services(bootstrap.runtime_for(session).services)
    try:
        panel.navigate_to(str(tmp_path), set_root=True)
        panel._model._wait_for_scan()
        panel._grid_widget._selection = {panel._model._path_index[str(target)]}
        target.unlink()

        panel._post_refresh()
        panel._model._wait_for_scan()
        app.processEvents()
        panel._model._wait_for_scan()
        panel._model._wait_for_scan()

        assert panel._grid_widget.selection_model_rows() == set()
    finally:
        panel.shutdown()
        app.processEvents()


def test_context_menu_exposes_same_operation_actions_for_file_and_directory(tmp_path):
    """The shared builder keeps Grid and Details operation menus aligned."""
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    file_path = tmp_path / "asset.txt"
    folder_path = tmp_path / "folder"
    file_path.write_text("asset")
    folder_path.mkdir()

    try:
        expected_keys = {
            "filelist.menu.open",
            "filelist.menu.copy",
            "filelist.menu.cut",
            "filelist.menu.copy_path",
            "filelist.menu.rename",
            "filelist.menu.delete",
            "filelist.menu.delete_permanent",
            "filelist.menu.duplicate",
            "filelist.menu.undo",
            "filelist.menu.redo",
        }
        expected = {tr(key) for key in expected_keys}
        for path in (file_path, folder_path):
            menu = panel._build_context_menu([str(path)], QPoint())
            labels = {action.text() for action in menu.actions() if not action.isSeparator()}
            assert expected <= labels
            menu.deleteLater()
    finally:
        panel.shutdown()
        app.processEvents()


def test_context_menu_open_uses_the_same_internal_open_behavior_as_enter(tmp_path):
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    file_path = tmp_path / "asset.txt"
    file_path.write_text("asset")
    opened = Mock()
    panel.file_double_clicked.connect(opened)

    try:
        menu = panel._build_context_menu([str(file_path)], QPoint())
        menu.actions()[0].trigger()

        opened.assert_called_once_with(str(file_path))
        menu.deleteLater()
    finally:
        panel.shutdown()
        app.processEvents()


def test_context_menu_disables_mutations_without_scoped_services(tmp_path):
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    path = tmp_path / "asset.txt"
    path.write_text("asset")

    try:
        menu = panel._build_context_menu([str(path)], QPoint())
        actions = {action.text(): action for action in menu.actions() if not action.isSeparator()}
        for key in (
            "filelist.menu.rename",
            "filelist.menu.duplicate",
            "filelist.menu.delete",
            "filelist.menu.delete_permanent",
            "filelist.menu.undo",
            "filelist.menu.redo",
        ):
            assert actions[tr(key)].isEnabled() is False
        assert actions[tr("filelist.menu.copy")].isEnabled() is True
        assert actions[tr("filelist.menu.cut")].isEnabled() is True
        menu.deleteLater()
    finally:
        panel.shutdown()
        app.processEvents()


def test_context_menu_projects_scoped_undo_redo_availability(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    path = tmp_path / "asset.txt"
    path.write_text("asset")
    panel._undo_svc = Mock()
    panel._undo_svc.can_undo.return_value = True
    panel._undo_svc.can_redo.return_value = False
    monkeypatch.setattr(panel, "_get_scoped_services", lambda: Mock())

    try:
        menu = panel._build_context_menu([str(path)], QPoint())
        actions = {action.text(): action for action in menu.actions() if not action.isSeparator()}
        assert actions[tr("filelist.menu.rename")].isEnabled() is True
        assert actions[tr("filelist.menu.duplicate")].isEnabled() is True
        assert actions[tr("filelist.menu.delete")].isEnabled() is True
        assert actions[tr("filelist.menu.delete_permanent")].isEnabled() is True
        assert actions[tr("filelist.menu.undo")].isEnabled() is True
        assert actions[tr("filelist.menu.redo")].isEnabled() is False
        menu.deleteLater()
    finally:
        panel.shutdown()
        app.processEvents()


def test_context_menu_keeps_rename_visible_but_disabled_for_multi_selection(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    paths = [tmp_path / "first.txt", tmp_path / "second.txt"]
    for path in paths:
        path.write_text("asset")
    panel._undo_svc = Mock()
    panel._undo_svc.can_undo.return_value = False
    panel._undo_svc.can_redo.return_value = False
    monkeypatch.setattr(panel, "_get_scoped_services", lambda: Mock())

    try:
        menu = panel._build_context_menu([str(path) for path in paths], QPoint())
        actions = {action.text(): action for action in menu.actions() if not action.isSeparator()}
        assert tr("filelist.menu.rename") in actions
        assert actions[tr("filelist.menu.rename")].isEnabled() is False
        assert actions[tr("filelist.menu.duplicate")].isEnabled() is True
        menu.deleteLater()
    finally:
        panel.shutdown()
        app.processEvents()


def test_empty_context_menu_exposes_common_view_and_history_actions():
    app = QApplication.instance() or QApplication([])
    QApplication.clipboard().clear()
    panel = QWidgetFileListPanel()

    try:
        menu = panel._build_context_menu([], QPoint())
        actions = {action.text(): action for action in menu.actions() if not action.isSeparator()}
        expected_keys = {
            "filelist.menu.paste",
            "filelist.menu.new_folder",
            "filelist.menu.select_all",
            "filelist.menu.refresh",
            "filelist.menu.toggle_hidden",
            "filelist.menu.undo",
            "filelist.menu.redo",
        }
        assert {tr(key) for key in expected_keys} <= actions.keys()
        assert actions[tr("filelist.menu.paste")].isEnabled() is False
        menu.deleteLater()
    finally:
        panel.shutdown()
        app.processEvents()


def test_empty_context_menu_enables_paste_when_file_list_owns_clipboard(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    panel._clipboard_source = ["/library/asset.txt"]
    panel._undo_svc = Mock()
    panel._undo_svc.can_undo.return_value = False
    panel._undo_svc.can_redo.return_value = False
    monkeypatch.setattr(panel, "_get_scoped_services", lambda: Mock())

    try:
        menu = panel._build_context_menu([], QPoint())
        paste = next(action for action in menu.actions() if action.text() == tr("filelist.menu.paste"))
        assert paste.isEnabled() is True
        menu.deleteLater()
    finally:
        panel.shutdown()
        app.processEvents()


def test_empty_context_menu_enables_paste_for_external_local_file_clipboard(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "asset.txt"
    source.write_text("asset")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(source))])
    QApplication.clipboard().setMimeData(mime)
    panel = QWidgetFileListPanel()
    panel._undo_svc = Mock()
    panel._undo_svc.can_undo.return_value = False
    panel._undo_svc.can_redo.return_value = False
    monkeypatch.setattr(panel, "_get_scoped_services", lambda: Mock())

    try:
        menu = panel._build_context_menu([], QPoint())
        paste = next(action for action in menu.actions() if action.text() == tr("filelist.menu.paste"))
        assert paste.isEnabled() is True
        menu.deleteLater()
    finally:
        panel.shutdown()
        QApplication.clipboard().clear()
        app.processEvents()


def test_context_menu_projects_stable_shortcuts_from_file_list_commands(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    path = tmp_path / "asset.txt"
    path.write_text("asset")
    panel._undo_svc = Mock()
    panel._undo_svc.can_undo.return_value = False
    panel._undo_svc.can_redo.return_value = False
    monkeypatch.setattr(panel, "_get_scoped_services", lambda: Mock())

    try:
        selected_menu = panel._build_context_menu([str(path)], QPoint())
        selected = {action.text(): action for action in selected_menu.actions() if not action.isSeparator()}
        assert selected[tr("filelist.menu.open")].shortcut().toString() == "Enter"
        assert selected[tr("filelist.menu.copy")].shortcut().toString() == "Ctrl+C"
        assert selected[tr("filelist.menu.rename")].shortcut().toString() == "F2"
        assert selected[tr("filelist.menu.delete_permanent")].shortcut().toString() == "Shift+Del"

        empty_menu = panel._build_context_menu([], QPoint())
        empty = {action.text(): action for action in empty_menu.actions() if not action.isSeparator()}
        assert empty[tr("filelist.menu.paste")].shortcut().toString() == "Ctrl+V"
        assert empty[tr("filelist.menu.new_folder")].shortcut().toString() == "Ctrl+Shift+N"
        assert empty[tr("filelist.menu.refresh")].shortcut().toString() == "F5"
        assert empty[tr("filelist.menu.keyboard_help")].shortcut().toString() == "F4"
        selected_menu.deleteLater()
        empty_menu.deleteLater()
    finally:
        panel.shutdown()
        app.processEvents()


@pytest.mark.parametrize(
    ("key", "modifiers", "command_id"),
    [
        (Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier, "copy"),
        (Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier, "cut"),
        (Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier, "paste"),
        (Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier, "duplicate"),
        (Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier, "undo"),
        (Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier, "redo"),
        (Qt.Key.Key_F5, Qt.KeyboardModifier.NoModifier, "refresh"),
        (Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier, "select_all"),
        (Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier, "toggle_hidden"),
        (Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier, "trash"),
        (Qt.Key.Key_Delete, Qt.KeyboardModifier.ShiftModifier, "permanent_delete"),
        (Qt.Key.Key_F2, Qt.KeyboardModifier.NoModifier, "rename"),
        (Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier, "new_folder"),
        (Qt.Key.Key_F4, Qt.KeyboardModifier.NoModifier, "help"),
    ],
)
def test_common_shortcuts_dispatch_to_file_list_command_ids(key, modifiers, command_id):
    panel = type("_Panel", (), {"_view_mode": "Grid"})()
    panel._invoke_command = Mock()
    event = type("_Event", (), {
        "key": lambda _self: key,
        "modifiers": lambda _self: modifiers,
    })()

    assert handle_key(panel, event) is True
    panel._invoke_command.assert_called_once_with(command_id, shortcut=True)


def test_filelist_help_persists_seen_hint_and_uses_local_presentation(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    settings = Mock()
    settings.get.return_value = False
    information = Mock()
    monkeypatch.setattr("AssetsManager.core.settings.AppSettings.instance", lambda: settings)
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.information", information)
    try:
        panel._invoke_command("help")

        settings.set.assert_called_once_with("filelist_shortcut_hints_seen", True)
        settings.save.assert_called_once_with()
        information.assert_called_once()
        assert "F4" in information.call_args.args[2]
    finally:
        panel.shutdown()
        app.processEvents()


def test_apply_tag_dialog_uses_catalog_picker_for_all_selected_paths(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    panel = QWidgetFileListPanel()
    session = bootstrap.library_service.open_session(tmp_path)
    panel.set_scoped_services(bootstrap.runtime_for(session).services)
    service = Mock()
    service.get_all_tags.return_value = ["character", "hero"]
    monkeypatch.setattr(panel, "_get_tag_service", lambda: service)
    picker = Mock(return_value=("hero", True))
    monkeypatch.setattr("AssetsManager.panels.file_list._actions.QInputDialog.getItem", picker)
    panel._post_refresh = Mock()
    paths = [str(tmp_path / "a.txt"), str(tmp_path / "b.txt")]
    try:
        panel._apply_tag_dialog(paths)

        picker.assert_called_once_with(
            panel, tr("filelist.dialog.apply_tag"), tr("filelist.dialog.tag_label"),
            ["character", "hero"], 0, True,
        )
        assert service.add_tag.call_args_list == [
            ((str(tmp_path), path, "hero"),) for path in paths
        ]
        panel._post_refresh.assert_called_once_with()
    finally:
        panel.shutdown()
        app.processEvents()


def test_backspace_remains_a_navigation_shortcut_outside_the_command_registry():
    panel = type("_Panel", (), {"_view_mode": "Grid"})()
    panel._go_up = Mock()
    panel._invoke_command = Mock()
    event = type("_Event", (), {
        "key": lambda _self: Qt.Key.Key_Backspace,
        "modifiers": lambda _self: Qt.KeyboardModifier.NoModifier,
    })()

    assert handle_key(panel, event) is True
    panel._go_up.assert_called_once_with()
    panel._invoke_command.assert_not_called()


def test_enter_in_grid_dispatches_the_shared_open_command():
    panel = type("_Panel", (), {"_view_mode": "Grid"})()
    panel._invoke_command = Mock()
    event = type("_Event", (), {
        "key": lambda _self: Qt.Key.Key_Return,
        "modifiers": lambda _self: Qt.KeyboardModifier.NoModifier,
    })()

    assert handle_key(panel, event) is True
    panel._invoke_command.assert_called_once_with("open", shortcut=True)


def test_enter_in_details_dispatches_the_shared_open_command():
    panel = type("_Panel", (), {"_view_mode": "Details"})()
    panel._invoke_command = Mock()
    event = type("_Event", (), {
        "key": lambda _self: Qt.Key.Key_Enter,
        "modifiers": lambda _self: Qt.KeyboardModifier.NoModifier,
    })()

    assert handle_key(panel, event) is True
    panel._invoke_command.assert_called_once_with("open", shortcut=True)


@pytest.mark.parametrize("view_mode", ["Grid", "Details"])
def test_escape_clears_current_view_selection_search_and_status(view_mode):
    panel = type("_Panel", (), {"_view_mode": view_mode})()
    panel._grid_widget = Mock()
    panel._detail_view = Mock()
    panel._search = Mock()
    panel._update_status = Mock()
    event = type("_Event", (), {
        "key": lambda _self: Qt.Key.Key_Escape,
        "modifiers": lambda _self: Qt.KeyboardModifier.NoModifier,
    })()

    assert handle_key(panel, event) is True
    if view_mode == "Grid":
        panel._grid_widget.clear_selection.assert_called_once_with()
        panel._detail_view.clearSelection.assert_not_called()
    else:
        panel._detail_view.clearSelection.assert_called_once_with()
        panel._grid_widget.clear_selection.assert_not_called()
    panel._search.clear.assert_called_once_with()
    panel._update_status.assert_called_once_with()


def test_alt_enter_opens_properties_for_first_selected_path():
    panel = type("_Panel", (), {"_view_mode": "Grid"})()
    panel._invoke_command = Mock()
    event = type("_Event", (), {
        "key": lambda _self: Qt.Key.Key_Return,
        "modifiers": lambda _self: Qt.KeyboardModifier.AltModifier,
    })()

    assert handle_key(panel, event) is True
    panel._invoke_command.assert_called_once_with("properties", shortcut=True)


def test_ctrl_f_focuses_and_selects_the_search_field():
    panel = type("_Panel", (), {"_view_mode": "Grid"})()
    panel._search = Mock()
    event = type("_Event", (), {
        "key": lambda _self: Qt.Key.Key_F,
        "modifiers": lambda _self: Qt.KeyboardModifier.ControlModifier,
    })()

    assert handle_key(panel, event) is True
    panel._search.setFocus.assert_called_once_with()
    panel._search.selectAll.assert_called_once_with()


@pytest.mark.parametrize("view_mode", ["Grid", "Details"])
def test_enter_with_no_selection_is_a_safe_noop(view_mode):
    panel = type("_Panel", (), {"_view_mode": view_mode})()
    panel._invoke_command = Mock()
    event = type("_Event", (), {
        "key": lambda _self: Qt.Key.Key_Return,
        "modifiers": lambda _self: Qt.KeyboardModifier.NoModifier,
    })()

    assert handle_key(panel, event) is True
    panel._invoke_command.assert_called_once_with("open", shortcut=True)


@pytest.mark.parametrize("is_dir", [True, False])
def test_shared_open_command_navigates_directories_and_opens_files(tmp_path, is_dir):
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    path = tmp_path / ("folder" if is_dir else "asset.txt")
    if is_dir:
        path.mkdir()
    else:
        path.write_text("asset")
    panel.navigate_to = Mock()
    opened = Mock()
    panel.file_double_clicked.connect(opened)

    try:
        panel._invoke_command("open", panel._command_context([str(path)]), shortcut=True)

        if is_dir:
            panel.navigate_to.assert_called_once_with(str(path))
            opened.assert_not_called()
        else:
            opened.assert_called_once_with(str(path))
            panel.navigate_to.assert_not_called()
    finally:
        panel.shutdown()
        app.processEvents()


def test_reused_scan_after_sort_during_refresh_repopulates_grid(tmp_path):
    """M3: sort reset during a preserved refresh zeroes the grid; the reused
    scan must repopulate it instead of leaving the canvas blank."""
    for name in ("b.txt", "a.txt", "c.txt"):
        (tmp_path / name).write_text(name)
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel.navigate_to(str(tmp_path), set_root=True)
        panel._model._wait_for_scan()
        app.processEvents()
        assert panel._grid_widget._model_rows == 3

        panel._model.refresh()
        panel._model.set_sort("name", asc=False)
        panel._model._wait_for_scan()
        app.processEvents()

        assert panel._grid_widget._model_rows == panel._model.rowCount() == 3
        assert panel._model._last_scan_reused is False  # flag consumed by the panel
    finally:
        panel.shutdown()
        app.processEvents()


def test_go_up_cannot_escape_library_root_via_prefix_collision(tmp_path):
    """M4: root C:\\lib must not allow _go_up to reach sibling C:\\library."""
    root = tmp_path / "lib"
    child = root / "sub"
    sibling = tmp_path / "library"
    root.mkdir()
    child.mkdir()
    sibling.mkdir()
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel.navigate_to(str(root), set_root=True)
        panel._model._wait_for_scan()
        app.processEvents()

        panel.navigate_to(str(child))
        panel._model._wait_for_scan()
        app.processEvents()
        panel._go_up()
        app.processEvents()
        assert panel._current == root

        panel.navigate_to(str(sibling))
        panel._model._wait_for_scan()
        app.processEvents()
        before = panel._current
        panel._go_up()
        app.processEvents()
        assert panel._current == before
    finally:
        panel.shutdown()
        app.processEvents()


# ── P2: drag-drop path resolution / keyboard focus / animation reuse ─────────


def test_same_directory_drop_is_filtered_before_any_service_call(tmp_path, monkeypatch):
    """Dropping a file onto its own directory must be a no-op even when the
    QUrl path uses forward slashes while the panel destination uses backslashes."""
    from unittest.mock import Mock

    library = tmp_path / "library"
    library.mkdir()
    asset = library / "asset.txt"
    asset.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
        panel.set_scoped_services(scoped)
        panel.navigate_to(str(library), set_root=True)
        panel._post_refresh = Mock()
        move = Mock()
        copy = Mock()
        monkeypatch.setattr(scoped.file_operation_service, "move_to_directory", move)
        monkeypatch.setattr(scoped.file_operation_service, "copy_to_directory", copy)

        url_path = str(asset).replace("\\", "/")

        class DropEvent:
            def mimeData(self):
                class MimeData:
                    def urls(self):
                        class Url:
                            def toLocalFile(self):
                                return url_path
                        return [Url()]
                return MimeData()

        assert panel._on_drop(DropEvent()) is False
        move.assert_not_called()
        copy.assert_not_called()
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_drop_classifies_library_and_external_sources_by_resolved_path(tmp_path, monkeypatch):
    """A mixed drop must move in-library sources once and copy external sources
    once, even when the drop URLs use the forward-slash QUrl spelling."""
    from unittest.mock import Mock

    from AssetsManager.application.file_operation_service import FileOperationResult

    library = tmp_path / "library"
    source_dir = library / "source"
    source_dir.mkdir(parents=True)
    asset = source_dir / "asset.txt"
    asset.write_text("asset")
    external = tmp_path / "external.txt"
    external.write_text("external")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
        panel.set_scoped_services(scoped)
        panel.navigate_to(str(library), set_root=True)
        panel._post_refresh = Mock()
        panel._load_visible = Mock()
        move = Mock(return_value=FileOperationResult(()))
        copy = Mock(return_value=FileOperationResult(()))
        monkeypatch.setattr(scoped.file_operation_service, "move_to_directory", move)
        monkeypatch.setattr(scoped.file_operation_service, "copy_to_directory", copy)

        url_paths = [str(asset).replace("\\", "/"), str(external).replace("\\", "/")]

        class DropEvent:
            def mimeData(self):
                class MimeData:
                    def urls(self):
                        class Url:
                            def __init__(self, path):
                                self.path = path

                            def toLocalFile(self):
                                return self.path
                        return [Url(path) for path in url_paths]
                return MimeData()

        assert panel._on_drop(DropEvent()) is True
        assert move.call_args_list == [
            (([str(asset)], str(library)), {"library_root": str(library)}),
        ]
        assert copy.call_args_list == [
            (([str(external)], str(library)), {"library_root": str(library)}),
        ]
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_drop_service_value_error_is_reported_through_feedback(tmp_path, monkeypatch):
    """Root-scope violations surface as ValueError; the drop handler must
    report them instead of letting the exception escape."""
    from unittest.mock import Mock

    library = tmp_path / "library"
    source_dir = library / "source"
    source_dir.mkdir(parents=True)
    source = source_dir / "asset.txt"
    source.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
        panel.set_scoped_services(scoped)
        panel.navigate_to(str(library), set_root=True)
        panel._post_refresh = Mock()
        panel._load_visible = Mock()
        move = Mock(side_effect=ValueError("Path is outside library root"))
        monkeypatch.setattr(scoped.file_operation_service, "move_to_directory", move)

        class DropEvent:
            def mimeData(self):
                class MimeData:
                    def urls(self):
                        class Url:
                            def toLocalFile(self):
                                return str(source)
                        return [Url()]
                return MimeData()

        assert panel._on_drop(DropEvent()) is True
        assert "failed" in panel._operation_feedback.text().lower()
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_search_focused_handle_key_passes_typing_through():
    """Backspace/Delete typed into the search box must not trigger navigation
    or deletion commands."""
    panel = type("_Panel", (), {"_view_mode": "Grid"})()
    panel._search = Mock()
    panel._search.hasFocus.return_value = True
    panel._go_up = Mock()
    panel._invoke_command = Mock()
    backspace = type("_Event", (), {
        "key": lambda _self: Qt.Key.Key_Backspace,
        "modifiers": lambda _self: Qt.KeyboardModifier.NoModifier,
    })()
    delete = type("_Event", (), {
        "key": lambda _self: Qt.Key.Key_Delete,
        "modifiers": lambda _self: Qt.KeyboardModifier.NoModifier,
    })()

    assert handle_key(panel, backspace) is False
    assert handle_key(panel, delete) is False
    panel._go_up.assert_not_called()
    panel._invoke_command.assert_not_called()


def test_search_focused_escape_still_clears_search_and_selection():
    panel = type("_Panel", (), {"_view_mode": "Grid"})()
    panel._grid_widget = Mock()
    panel._detail_view = Mock()
    panel._search = Mock()
    panel._search.hasFocus.return_value = True
    panel._update_status = Mock()
    event = type("_Event", (), {
        "key": lambda _self: Qt.Key.Key_Escape,
        "modifiers": lambda _self: Qt.KeyboardModifier.NoModifier,
    })()

    assert handle_key(panel, event) is True
    panel._grid_widget.clear_selection.assert_called_once_with()
    panel._search.clear.assert_called_once_with()
    panel._update_status.assert_called_once_with()


def test_search_focused_ctrl_f_still_refocuses_the_search_field():
    panel = type("_Panel", (), {"_view_mode": "Grid"})()
    panel._search = Mock()
    panel._search.hasFocus.return_value = True
    event = type("_Event", (), {
        "key": lambda _self: Qt.Key.Key_F,
        "modifiers": lambda _self: Qt.KeyboardModifier.ControlModifier,
    })()

    assert handle_key(panel, event) is True
    panel._search.setFocus.assert_called_once_with()
    panel._search.selectAll.assert_called_once_with()


def test_base_handle_key_defers_to_focused_search_line_edit():
    """The legacy panel key handler must also leave search-box keys alone."""
    from AssetsManager.panels.file_list._base import FileListPanel

    panel = type("_Panel", (), {"_view_mode": "Grid"})()
    panel._search = Mock()
    panel._search.hasFocus.return_value = True
    panel._go_up = Mock()
    panel._delete = Mock()
    backspace = type("_Event", (), {
        "key": lambda _self: Qt.Key.Key_Backspace,
        "modifiers": lambda _self: Qt.KeyboardModifier.NoModifier,
    })()
    delete = type("_Event", (), {
        "key": lambda _self: Qt.Key.Key_Delete,
        "modifiers": lambda _self: Qt.KeyboardModifier.NoModifier,
    })()

    assert FileListPanel._handle_key(panel, backspace) is False
    assert FileListPanel._handle_key(panel, delete) is False
    panel._go_up.assert_not_called()
    panel._delete.assert_not_called()


def test_zoom_animation_object_is_reused_across_zoom_changes():
    """Rapid zoom changes must reuse one QVariantAnimation instead of
    accumulating child QObjects."""
    from AssetsManager.panels.file_list import QWidgetFileListPanel

    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel._thumb_size = 96
        panel._zoom_anim = None
        panel._zoom_generation = 0
        panel._grid_widget = Mock()
        panel._grid_widget._zoom_relayout_active = False
        panel._grid_widget._reduce_motion = False
        panel._grid_widget.width.return_value = 400
        panel._on_zoom_frame = Mock()
        panel._on_zoom_done = Mock()

        QWidgetFileListPanel._on_zoom_changed(panel, "128px")
        first = panel._zoom_anim
        QWidgetFileListPanel._on_zoom_changed(panel, "192px")
        second = panel._zoom_anim

        assert first is not None
        assert first is second
        second.stop()
    finally:
        panel.shutdown()
        # Drop the animation references so the conftest teardown's second
        # shutdown does not warn about disconnecting already-empty signals.
        panel._zoom_anim = None
        panel._scroll_anim = None
        app.processEvents()


def test_scroll_animation_object_is_reused_across_wheel_events():
    from AssetsManager.panels.file_list import QWidgetFileListPanel

    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel._grid_widget._scrollbar.setRange(0, 1000)
        event = type("_Event", (), {
            "angleDelta": lambda _self: type("_Delta", (), {"y": lambda _d: 120})(),
        })()
        panel._smooth_scroll(event)
        first = panel._scroll_anim
        panel._smooth_scroll(event)
        second = panel._scroll_anim

        assert first is not None
        assert first is second
        first.stop()
    finally:
        panel.shutdown()
        # Drop the animation references so the conftest teardown's second
        # shutdown does not warn about disconnecting already-empty signals.
        panel._zoom_anim = None
        panel._scroll_anim = None
        app.processEvents()
