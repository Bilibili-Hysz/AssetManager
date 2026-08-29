import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from aiohttp import ClientSession


from PySide6.QtCore import QMimeData, QPoint, QUrl, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.core import themes
from AssetsManager.i18n import tr
from AssetsManager.panels.file_list._base import FileListPanel
from AssetsManager.panels.file_list._shortcuts import handle_key


def test_grid_visible_thumbnails_are_requested_before_prefetch_rows():
    from AssetsManager.panels.file_list import FileListPanel
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

    FileListPanel._load_visible(panel)

    assert IMAGE_EXTS
    panel._loader.retain_deferred.assert_called_once_with({f"/library/{row}.png" for row in range(10)})
    assert [(call.args[0], call.kwargs["priority"]) for call in panel._loader.request.call_args_list] == [
        (3, 0), (4, 0), (0, 1), (1, 1), (2, 1), (5, 1), (6, 1), (7, 1), (8, 1), (9, 1),
    ]


def test_file_list_state_controls_keep_semantic_icons_after_state_changes(plain_panel):
    panel = plain_panel
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


def test_file_list_toolbar_combos_have_tooltips_and_accessible_names(plain_panel):
    panel = plain_panel
    for combo in (
        panel._sort_combo,
        panel._filter_combo,
        panel._view_combo,
        panel._zoom_combo,
    ):
        assert combo.toolTip()
        assert combo.accessibleName() == combo.toolTip()


def test_file_list_status_bar_uses_border_subtle_hairline(plain_panel):
    panel = plain_panel
    from AssetsManager.core import themes

    hairline = themes.get()["border_subtle"]
    assert hairline in panel._status_bar.styleSheet()


def test_file_list_chrome_style_is_stable_across_refresh(plain_panel):
    panel = plain_panel
    before = (
        panel._header.styleSheet(),
        panel._header_title.styleSheet(),
        panel._nav_buttons[0].styleSheet(),
    )

    panel._apply_chrome_style()

    after = (
        panel._header.styleSheet(),
        panel._header_title.styleSheet(),
        panel._nav_buttons[0].styleSheet(),
    )
    assert before == after
    assert "min-width" in panel._nav_buttons[0].styleSheet()


def test_file_list_breadcrumb_highlights_current_segment(plain_panel):
    panel = plain_panel
    from AssetsManager.core import themes
    from PySide6.QtWidgets import QPushButton

    panel._current = Path("C:/library/assets/characters")
    panel._render_bc()

    buttons = panel._breadcrumb.findChildren(QPushButton)
    assert buttons
    assert themes.get()["heading"] in buttons[-1].styleSheet()
    assert "font-weight: bold" in buttons[-1].styleSheet()
    assert themes.get()["muted"] in buttons[0].styleSheet()


def test_lan_mutation_event_refreshes_desktop_file_list_for_same_session(tmp_path, file_list_panel_ctx):
    """A LAN-originated filesystem event reaches the active Desktop panel."""
    panel, session, _bootstrap, _services = file_list_panel_ctx
    app = QApplication.instance() or QApplication([])
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

    panel._post_refresh.assert_called_once_with()


def test_file_list_captures_thumbnail_service_from_runtime_snapshot_and_clears_on_shutdown(tmp_path):
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path)
    runtime = bootstrap.runtime_for(session)
    panel = FileListPanel()

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


def test_grid_scan_commit_starts_one_presentation_after_loading_reset(tmp_path, plain_panel):
    panel = plain_panel
    (tmp_path / "asset.txt").write_text("asset")
    app = QApplication.instance() or QApplication([])
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


def test_empty_grid_scan_does_not_start_presentation_or_thumbnail_load(tmp_path, plain_panel):
    panel = plain_panel
    app = QApplication.instance() or QApplication([])
    panel._grid_widget.begin_presentation = Mock()
    panel._load_visible = Mock()

    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()
    app.processEvents()

    panel._grid_widget.begin_presentation.assert_not_called()
    panel._load_visible.assert_not_called()


def test_grid_visibility_toggle_does_not_replay_presentation(tmp_path, plain_panel):
    panel = plain_panel
    (tmp_path / "asset.txt").write_text("asset")
    app = QApplication.instance() or QApplication([])
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


def test_details_scan_commits_latest_grid_presentation_before_switching_back(tmp_path, plain_panel):
    panel = plain_panel
    (tmp_path / "asset.txt").write_text("asset")
    app = QApplication.instance() or QApplication([])
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
    assert panel._grid_widget._animator._pending_presentation is not None
    assert panel._grid_widget._animator._pending_presentation[0] == panel._model.scan_generation


def test_grid_reset_discards_pending_thumbnail_batch(tmp_path, plain_panel):
    panel = plain_panel
    (tmp_path / "asset.txt").write_text("asset")
    panel._thumbnail_delivery._batch = {0: str(tmp_path / "asset.txt")}
    panel._thumbnail_delivery._timer.start()

    panel._model.set_directory(str(tmp_path))

    assert panel._thumbnail_delivery._batch == {}
    assert panel._thumbnail_delivery._timer.isActive() is False


def test_grid_thumbnail_delivery_batches_only_current_model_rows(tmp_path, plain_panel):
    panel = plain_panel
    (tmp_path / "asset.png").write_bytes(b"not decoded by this test")
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


def test_thumbnail_result_is_ignored_after_panel_shutdown():
    panel = type("_Panel", (), {})()
    panel._model = type("_Model", (), {"is_shutdown": True})()

    FileListPanel._on_thumbnail_ready(panel, 0, "/library/asset.png", Mock())


def test_grid_thumbnail_delivery_is_ignored_after_panel_shutdown():
    panel = type("_Panel", (), {})()
    panel._model = type("_Model", (), {"is_shutdown": True})()
    panel._thumbnail_delivery = Mock()

    FileListPanel._on_thumbnail_ready(panel, 0, "/library/asset.png", Mock())

    panel._thumbnail_delivery.handle_ready.assert_not_called()


def test_delayed_grid_load_is_ignored_after_panel_shutdown():
    panel = type("_Panel", (), {})()
    panel._model = type("_Model", (), {"is_shutdown": True})()
    panel._loader = Mock()

    FileListPanel._load_visible(panel)

    panel._loader.request.assert_not_called()


def test_file_operation_is_ignored_after_panel_shutdown():
    panel = type("_Panel", (), {})()
    panel._model = type("_Model", (), {"is_shutdown": True})()
    panel._file_op_timer = Mock()

    FileListPanel._on_file_operation(panel, Mock())

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

    FileListPanel._update_status(panel)

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

    FileListPanel._update_status(panel)

    panel._compute_total_sz.assert_called_once_with()
    panel._controller.format_total_size_suffix.assert_called_once_with(1024)


def test_grid_status_projects_explicit_file_list_states(tmp_path, plain_panel):
    panel = plain_panel
    app = QApplication.instance() or QApplication([])
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


def test_operation_feedback_projects_running_success_and_partial_states(tmp_path, file_list_panel_ctx):
    panel, session, _bootstrap, _services = file_list_panel_ctx
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
    panel = FileListPanel()
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


def test_duplicate_feedback_reports_partial_failures(tmp_path, monkeypatch, file_list_panel_ctx):
    panel, _session, _bootstrap, scoped = file_list_panel_ctx
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first")
    second.write_text("second")
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


def test_grid_selects_requested_operation_result_after_refresh(tmp_path, file_list_panel_ctx):
    panel, session, _bootstrap, _services = file_list_panel_ctx
    app = QApplication.instance() or QApplication([])
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()
    target = tmp_path / "created.txt"
    target.write_text("created")

    panel._request_operation_selection(session, [target])
    panel._post_refresh()
    panel._model._wait_for_scan()
    app.processEvents()
    panel._model._wait_for_scan()
    panel._model._wait_for_scan()

    assert panel._grid_widget.selection_model_rows() == {panel._model._path_index[str(target)]}


def test_operation_selection_is_discarded_after_directory_or_session_change(tmp_path):
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    target = first / "created.txt"
    target.write_text("created")
    panel = FileListPanel()
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


def test_grid_deletion_candidates_prefer_next_visible_item(tmp_path, file_list_panel_ctx):
    panel, session, _bootstrap, _services = file_list_panel_ctx
    app = QApplication.instance() or QApplication([])
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text(name)
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()
    deleted = tmp_path / "b.txt"

    candidates = panel._deletion_selection_candidates([deleted])
    deleted.unlink()
    panel._request_operation_selection(session, candidates)
    panel._post_refresh()
    panel._model._wait_for_scan()
    app.processEvents()
    panel._model._wait_for_scan()

    assert panel._grid_widget.selection_model_rows() == {panel._model._path_index[str(tmp_path / "c.txt")]}


def test_grid_deletion_candidates_fall_back_to_previous_visible_item(tmp_path, file_list_panel_ctx):
    panel, session, _bootstrap, _services = file_list_panel_ctx
    app = QApplication.instance() or QApplication([])
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text(name)
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()
    deleted = tmp_path / "b.txt"

    candidates = panel._deletion_selection_candidates([deleted])
    deleted.unlink()
    panel._request_operation_selection(session, candidates)
    panel._post_refresh()
    panel._model._wait_for_scan()
    app.processEvents()
    panel._model._wait_for_scan()

    assert panel._grid_widget.selection_model_rows() == {panel._model._path_index[str(tmp_path / "a.txt")]}


def test_grid_undo_rename_selects_restored_path_after_refresh(tmp_path, file_list_panel_ctx):
    panel, _session, _bootstrap, scoped = file_list_panel_ctx
    app = QApplication.instance() or QApplication([])
    old = tmp_path / "old.txt"
    new = tmp_path / "new.txt"
    old.write_text("asset")
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()
    scoped.undo_service.record_rename(str(old), str(new))
    scoped.file_operation_service.move(old, new)
    panel._run_in_background = lambda func, *args, on_done=None: (func(), on_done and on_done())

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


def test_grid_scrollbar_uses_shared_animation_gate(plain_panel):
    panel = plain_panel
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


def test_grid_selection_rows_support_actions_api(tmp_path, plain_panel):
    panel = plain_panel
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()
    panel._grid_widget.update_layout(panel._model.rowCount(), 400)

    panel._grid_widget._selection.add(0)
    panel._grid_widget.update()

    assert [idx.row() for idx in panel._view_selected_rows()] == [0]

    panel._grid_widget.clear_selection()

    assert panel._view_selected_rows() == []


def test_grid_selection_change_reaches_panel_listeners(tmp_path, plain_panel):
    panel = plain_panel
    (tmp_path / "a.txt").write_text("a")
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()
    panel._grid_widget.update_layout(panel._model.rowCount(), 400)

    seen = []
    panel._grid_widget.selection_changed.connect(lambda: seen.append(True))

    panel._select_grid_paths({str(panel._model.path_at(0))})

    assert seen == [True]


def test_grid_selection_survives_sort_by_path(tmp_path, plain_panel):
    panel = plain_panel
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "a.txt").write_text("a")
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()
    panel._grid_widget.update_layout(panel._model.rowCount(), 400)
    target = str(tmp_path / "b.txt")
    row = panel._model._path_index[target]
    panel._grid_widget._selection = {row}

    panel._model.set_sort("name", asc=True)

    selected = [panel._model.path_at(r) for r in panel._grid_widget.selection_model_rows()]
    assert selected == [target]


def test_grid_selection_drops_filtered_paths(tmp_path, plain_panel):
    panel = plain_panel
    (tmp_path / "image.png").write_text("image")
    (tmp_path / "readme.txt").write_text("readme")
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()
    panel._grid_widget.update_layout(panel._model.rowCount(), 400)
    panel._grid_widget._selection = {panel._model._path_index[str(tmp_path / "readme.txt")]}

    panel._model.set_filter(category="images")

    assert panel._grid_widget.selection_model_rows() == set()


def test_set_root_uses_injected_scoped_library_runtime(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = FileListPanel()
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
    panel = FileListPanel()
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
    panel = FileListPanel()
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
        "is_shutdown": True,
        "_pending_dir_sizes": {"/library/folder"},
    })()

    FileListPanel._on_dir_size_ready(panel, "/library/folder", "1.0 KB", 1)

    assert panel._model._pending_dir_sizes == {"/library/folder"}


def test_directory_size_result_skips_redundant_subtitle_emission():
    model = Mock()
    model.is_shutdown = False
    model.dir_size_generation = 1
    model.subtitle_for.return_value = "1.0 KB"
    panel = Mock()
    panel._model = model

    FileListPanel._on_dir_size_ready(panel, "/library/folder", "1.0 KB", 1)

    model.discard_pending_dir_size.assert_called_once_with("/library/folder")
    model.set_subtitle.assert_not_called()
    model.dataChanged.emit.assert_not_called()


def test_external_drop_defers_copy_to_background_worker(tmp_path, monkeypatch):
    """A drop must classify sources on the UI thread, then submit the copy to
    the existing background operation mode instead of running it synchronously
    inside the drop handler."""
    from unittest.mock import Mock

    from AssetsManager.panels.file_list._base import FileListPanel

    library = tmp_path / "library"
    library.mkdir()
    external = tmp_path / "external.txt"
    external.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = FileListPanel()
    queued = []
    try:
        scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
        panel.set_scoped_services(scoped)
        panel.navigate_to(str(library), set_root=True)
        panel._post_refresh = Mock()
        panel._load_visible = Mock()
        panel._run_in_background = lambda func, *args, on_done=None: queued.append((func, on_done))

        class DropEvent:
            def mimeData(self):
                class MimeData:
                    def urls(self):
                        class Url:
                            def toLocalFile(self):
                                return str(external)
                        return [Url()]
                return MimeData()

        copied = Mock(
            return_value=type("Result", (), {"errors": (), "changed_paths": (), "warnings": ()})()
        )
        monkeypatch.setattr(scoped.file_operation_service, "copy_to_directory", copied)

        assert panel._on_drop(DropEvent()) is True
        # The copy must be deferred to the background pool — the drop handler
        # returns before any service call runs on the UI thread.
        copied.assert_not_called()
        assert queued

        func, on_done = queued.pop()
        func()
        copied.assert_called_once_with(
            [str(external)], str(library), library_root=str(library),
        )
        on_done()
        panel._post_refresh.assert_called_once()
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_in_library_drop_moves_and_records_only_successful_undo_entries(tmp_path, monkeypatch):
    """In-library drop runs its move/undo work through the background mode:
    successful moves are recorded for undo, per-item failures surface through
    the operation feedback after the worker completes."""
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
    panel = FileListPanel()
    try:
        scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
        panel.set_scoped_services(scoped)
        panel._current = destination
        panel._post_refresh = Mock()
        panel._load_visible = Mock()
        panel._undo_svc = Mock()
        panel._run_in_background = lambda func, *args, on_done=None: (func(), on_done and on_done())

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
        panel._undo_svc.record_rename_batch.assert_called_once_with(
            [(str(source), str(moved))]
        )
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
        panel._undo_svc.record_rename_batch.assert_called_once_with(
            [(str(source), str(moved))]
        )

    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_external_drop_without_scoped_services_refuses_copy(tmp_path, monkeypatch, plain_panel):
    panel = plain_panel
    from unittest.mock import Mock

    from AssetsManager.panels.file_list._base import FileListPanel

    library = tmp_path / "library"
    external = tmp_path / "external.txt"
    library.mkdir()
    external.write_text("asset")
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


def test_paste_uses_scoped_service_for_local_system_clipboard_urls(tmp_path, monkeypatch):
    from unittest.mock import Mock

    library = tmp_path / "library"
    library.mkdir()
    external = tmp_path / "external.txt"
    external.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = FileListPanel()
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
    panel = FileListPanel()
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
    panel = FileListPanel()
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
    panel = FileListPanel()
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
        # The whole cut-paste move is ONE batch undo entry.
        panel._undo_svc.record_rename_batch.assert_called_once_with([
            (str(source), str(moved)),
            (str(second_source), str(second_moved)),
        ])

        panel._undo_svc.reset_mock()
        move.reset_mock()
        panel._clipboard_source = [str(source), str(second_source)]
        panel._clipboard_cut = True
        move.return_value = FileOperationResult((moved, second_moved), ("move failed",))

        panel._paste()

        panel._undo_svc.record_rename_batch.assert_not_called()
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
    panel = FileListPanel()
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
        # …through that channel alone: the redundant modal error dialog was
        # removed (the feedback label already carries the failure detail).
        import AssetsManager.panels.file_list._actions as actions_module
        actions_module.QMessageBox.warning.assert_not_called()
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
    panel = FileListPanel()
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
    panel = FileListPanel()
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
        entry = panel._undo_svc.peek_undo()
        assert entry.type == "batch"
        assert [child.path for child in entry.children] == [str(target)]
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
    panel = FileListPanel()
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


def test_permanent_delete_backup_failure_warns_user_and_still_deletes(tmp_path, monkeypatch):
    """A failed undo backup is surfaced; the deletion itself still executes."""
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
    panel = FileListPanel()
    try:
        scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
        panel.set_scoped_services(scoped)
        panel._run_in_background = lambda func, *args, on_done=None: (func(), on_done and on_done())
        panel._post_refresh = Mock()
        service = Mock()
        service.delete_permanent.return_value = FileOperationResult((target,), ())
        monkeypatch.setattr(panel, "_get_file_operation_service", lambda: service)
        warning = Mock(return_value=QMessageBox.StandardButton.Yes)
        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QMessageBox.warning", warning,
        )
        undo = Mock()
        undo.prepare_delete.return_value = None
        undo.last_backup_error = "simulated copy failure"
        undo.commit_delete = Mock()
        undo.discard_delete = Mock()
        undo.can_undo.return_value = False
        panel._undo_svc = undo

        panel._delete_permanent([str(target)])

        # The deletion still executed (current semantics) ...
        service.delete_permanent.assert_called_once_with([str(target)], library_root=str(library))
        undo.commit_delete.assert_not_called()
        undo.discard_delete.assert_not_called()
        # ... and the broken "You can undo this deletion" promise is
        # surfaced with the undo service's last_backup_error reason.
        presentations = [
            call for call in warning.call_args_list
            if "simulated copy failure" in str(call)
        ]
        assert len(presentations) == 1
        assert "asset.txt" in str(presentations[0])
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
    panel = FileListPanel()
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
        entry = panel._undo_svc.peek_undo()
        assert entry.type == "batch"
        assert [child.path for child in entry.children] == [str(first_target)]
        entries = list(Path(panel._undo_svc._undo_dir).iterdir())
        # The backup file plus its projection snapshot file.
        assert len(entries) == 2
        assert sum(1 for entry in entries if entry.name.endswith(".projection.json")) == 1
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_partial_delete_selects_neighbor_of_successfully_deleted_path(tmp_path, monkeypatch, file_list_panel_ctx):
    panel, session, _bootstrap, _services = file_list_panel_ctx
    from AssetsManager.application.file_operation_service import FileOperationResult
    from PySide6.QtWidgets import QMessageBox

    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text(name)
    monkeypatch.setattr(
        "AssetsManager.panels.file_list._actions.QMessageBox.question",
        lambda *args: QMessageBox.StandardButton.Yes,
    )
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


def test_operation_request_without_current_directory_target_clears_prior_intent(tmp_path, file_list_panel_ctx):
    panel, session, _bootstrap, _services = file_list_panel_ctx
    target = tmp_path / "target.txt"
    outside = tmp_path.parent / "outside.txt"
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._request_operation_selection(session, [target])

    panel._request_operation_selection(session, [outside])

    assert panel._pending_operation_selection is None


def test_panel_undo_redo_use_perform_methods(tmp_path, monkeypatch, plain_panel):
    panel = plain_panel
    from unittest.mock import Mock

    from AssetsManager.application.file_operation_service import FileOperationWarning

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


def test_failed_grid_rename_does_not_record_undo(tmp_path, monkeypatch):
    from unittest.mock import Mock

    source = tmp_path / "asset.txt"
    source.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = FileListPanel()
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


def test_rename_and_new_folder_defer_service_calls_to_background(tmp_path, monkeypatch):
    """Rename and new-folder enqueue through _run_in_background like the
    other file operations: the UI thread only validates (dialog) and shows
    running feedback; the service call and refresh happen in the deferred
    worker/completion pair."""
    from unittest.mock import Mock

    library = tmp_path / "library"
    library.mkdir()
    source = library / "asset.txt"
    source.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = FileListPanel()
    try:
        panel.set_scoped_services(
            bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
        )
        panel.navigate_to(str(library), set_root=True)
        panel._model._wait_for_scan()
        deferred: list = []
        panel._run_in_background = lambda func, *args, on_done=None: deferred.append((func, on_done))
        panel._post_refresh = Mock()

        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QInputDialog.getText",
            lambda *args, **kwargs: ("renamed.txt", True),
        )
        panel._rename(str(source))
        assert deferred, "rename must defer its service call to the background runner"
        func, on_done = deferred.pop()
        func()
        assert (library / "renamed.txt").exists()
        assert not source.exists()
        on_done()
        panel._post_refresh.assert_called_once()

        panel._post_refresh.reset_mock()
        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QInputDialog.getText",
            lambda *args, **kwargs: ("New Folder", True),
        )
        panel._new_folder()
        assert deferred, "new_folder must defer its service call to the background runner"
        func, on_done = deferred.pop()
        func()
        assert (library / "New Folder").is_dir()
        on_done()
        panel._post_refresh.assert_called_once()
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_covered_mutations_refuse_without_scoped_services(tmp_path, monkeypatch, plain_panel):
    panel = plain_panel
    from unittest.mock import Mock

    from PySide6.QtWidgets import QMessageBox

    source = tmp_path / "asset.txt"
    destination = tmp_path / "renamed.txt"
    source.write_text("asset")
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


def test_unscoped_mutations_never_construct_unbound_services(tmp_path, monkeypatch, plain_panel):
    """Mutation paths must fail closed before reaching fallback constructors."""
    panel = plain_panel
    from unittest.mock import Mock

    from AssetsManager.panels.file_list._base import FileListPanel

    source = tmp_path / "asset.txt"
    destination = tmp_path / "renamed.txt"
    source.write_text("asset")
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
    panel = FileListPanel()
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
    panel = FileListPanel()
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
    panel = FileListPanel()
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
    panel = FileListPanel()
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


def test_file_list_does_not_construct_unbound_undo_service(monkeypatch, plain_panel):
    """The panel receives its undo service only through scoped injection."""
    panel = plain_panel
    monkeypatch.setattr(
        "AssetsManager.application.UndoService",
        lambda: (_ for _ in ()).throw(AssertionError("unbound UndoService constructed")),
    )

    assert panel._undo_svc is None


def test_grid_selection_survives_post_refresh_by_path(tmp_path, file_list_panel):
    panel = file_list_panel
    (tmp_path / "a.txt").write_text("a")
    target = tmp_path / "b.txt"
    target.write_text("b")
    app = QApplication.instance() or QApplication([])
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


def test_grid_batch_rename_selects_first_renamed_result(tmp_path, monkeypatch, file_list_panel):
    panel = file_list_panel
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text(name)
    app = QApplication.instance() or QApplication([])
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


def test_grid_selection_survives_filter_when_path_remains_visible(tmp_path, plain_panel):
    panel = plain_panel
    (tmp_path / "alpha.txt").write_text("a")
    target = tmp_path / "beta.txt"
    target.write_text("b")
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()
    panel._grid_widget._selection = {panel._model._path_index[str(target)]}

    panel._model.set_filter(text="beta")

    selected = [panel._model.path_at(row) for row in panel._grid_widget.selection_model_rows()]
    assert selected == [str(target)]


def test_grid_clear_selection_during_refresh_overrides_path_restore(tmp_path, file_list_panel):
    panel = file_list_panel
    target = tmp_path / "asset.txt"
    target.write_text("asset")
    app = QApplication.instance() or QApplication([])
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()
    panel._grid_widget._selection = {panel._model._path_index[str(target)]}

    panel._post_refresh()
    panel._grid_widget.clear_selection()
    panel._model._wait_for_scan()
    app.processEvents()

    assert panel._grid_widget.selection_model_rows() == set()


def test_grid_selection_drops_when_navigating_to_another_directory(tmp_path, file_list_panel):
    panel = file_list_panel
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    selected = first / "selected.txt"
    selected.write_text("asset")
    (second / "other.txt").write_text("asset")
    app = QApplication.instance() or QApplication([])
    panel.navigate_to(str(first), set_root=True)
    panel._model._wait_for_scan()
    panel._grid_widget._selection = {panel._model._path_index[str(selected)]}

    panel.navigate_to(str(second))
    panel._model._wait_for_scan()
    app.processEvents()

    assert panel.current_path == str(second.resolve())
    assert panel._grid_widget.selection_model_rows() == set()


def test_grid_refresh_drops_externally_removed_selection(tmp_path, file_list_panel):
    panel = file_list_panel
    target = tmp_path / "removed.txt"
    target.write_text("asset")
    app = QApplication.instance() or QApplication([])
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


def test_context_menu_exposes_same_operation_actions_for_file_and_directory(tmp_path, plain_panel):
    """The shared builder keeps Grid and Details operation menus aligned."""
    panel = plain_panel
    file_path = tmp_path / "asset.txt"
    folder_path = tmp_path / "folder"
    file_path.write_text("asset")
    folder_path.mkdir()

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


def test_context_menu_open_uses_the_same_internal_open_behavior_as_enter(tmp_path, plain_panel):
    panel = plain_panel
    file_path = tmp_path / "asset.txt"
    file_path.write_text("asset")
    opened = Mock()
    panel.file_double_clicked.connect(opened)

    menu = panel._build_context_menu([str(file_path)], QPoint())
    menu.actions()[0].trigger()

    opened.assert_called_once_with(str(file_path))
    menu.deleteLater()


def test_context_menu_disables_mutations_without_scoped_services(tmp_path, plain_panel):
    panel = plain_panel
    path = tmp_path / "asset.txt"
    path.write_text("asset")

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


def test_context_menu_projects_scoped_undo_redo_availability(tmp_path, monkeypatch, plain_panel):
    panel = plain_panel
    path = tmp_path / "asset.txt"
    path.write_text("asset")
    panel._undo_svc = Mock()
    panel._undo_svc.can_undo.return_value = True
    panel._undo_svc.can_redo.return_value = False
    monkeypatch.setattr(panel, "_get_scoped_services", lambda: Mock())

    menu = panel._build_context_menu([str(path)], QPoint())
    actions = {action.text(): action for action in menu.actions() if not action.isSeparator()}
    assert actions[tr("filelist.menu.rename")].isEnabled() is True
    assert actions[tr("filelist.menu.duplicate")].isEnabled() is True
    assert actions[tr("filelist.menu.delete")].isEnabled() is True
    assert actions[tr("filelist.menu.delete_permanent")].isEnabled() is True
    assert actions[tr("filelist.menu.undo")].isEnabled() is True
    assert actions[tr("filelist.menu.redo")].isEnabled() is False
    menu.deleteLater()


def test_context_menu_keeps_rename_visible_but_disabled_for_multi_selection(tmp_path, monkeypatch, plain_panel):
    panel = plain_panel
    paths = [tmp_path / "first.txt", tmp_path / "second.txt"]
    for path in paths:
        path.write_text("asset")
    panel._undo_svc = Mock()
    panel._undo_svc.can_undo.return_value = False
    panel._undo_svc.can_redo.return_value = False
    monkeypatch.setattr(panel, "_get_scoped_services", lambda: Mock())

    menu = panel._build_context_menu([str(path) for path in paths], QPoint())
    actions = {action.text(): action for action in menu.actions() if not action.isSeparator()}
    assert tr("filelist.menu.rename") in actions
    assert actions[tr("filelist.menu.rename")].isEnabled() is False
    assert actions[tr("filelist.menu.duplicate")].isEnabled() is True
    menu.deleteLater()


def test_empty_context_menu_exposes_common_view_and_history_actions(plain_panel):
    panel = plain_panel
    QApplication.clipboard().clear()

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


def test_empty_context_menu_enables_paste_when_file_list_owns_clipboard(monkeypatch, plain_panel):
    panel = plain_panel
    panel._clipboard_source = ["/library/asset.txt"]
    panel._undo_svc = Mock()
    panel._undo_svc.can_undo.return_value = False
    panel._undo_svc.can_redo.return_value = False
    monkeypatch.setattr(panel, "_get_scoped_services", lambda: Mock())

    menu = panel._build_context_menu([], QPoint())
    paste = next(action for action in menu.actions() if action.text() == tr("filelist.menu.paste"))
    assert paste.isEnabled() is True
    menu.deleteLater()


def test_empty_context_menu_enables_paste_for_external_local_file_clipboard(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "asset.txt"
    source.write_text("asset")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(source))])
    QApplication.clipboard().setMimeData(mime)
    panel = FileListPanel()
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


def test_context_menu_projects_stable_shortcuts_from_file_list_commands(tmp_path, monkeypatch, plain_panel):
    panel = plain_panel
    path = tmp_path / "asset.txt"
    path.write_text("asset")
    panel._undo_svc = Mock()
    panel._undo_svc.can_undo.return_value = False
    panel._undo_svc.can_redo.return_value = False
    monkeypatch.setattr(panel, "_get_scoped_services", lambda: Mock())

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


def test_filelist_help_persists_seen_hint_and_uses_local_presentation(monkeypatch, plain_panel):
    panel = plain_panel
    settings = Mock()
    settings.get.return_value = False
    information = Mock()
    monkeypatch.setattr("AssetsManager.core.settings.AppSettings.instance", lambda: settings)
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.information", information)
    panel._invoke_command("help")

    settings.set.assert_called_once_with("filelist_shortcut_hints_seen", True)
    settings.save.assert_called_once_with()
    information.assert_called_once()
    assert "F4" in information.call_args.args[2]


def test_apply_tag_dialog_uses_catalog_picker_for_all_selected_paths(tmp_path, monkeypatch, file_list_panel):
    panel = file_list_panel
    service = Mock()
    service.get_all_tags.return_value = ["character", "hero"]
    monkeypatch.setattr(panel, "_get_tag_service", lambda: service)
    picker = Mock(return_value=("hero", True))
    monkeypatch.setattr("AssetsManager.panels.file_list._actions.QInputDialog.getItem", picker)
    panel._post_refresh = Mock()
    paths = [str(tmp_path / "a.txt"), str(tmp_path / "b.txt")]
    panel._apply_tag_dialog(paths)

    picker.assert_called_once_with(
        panel, tr("filelist.dialog.apply_tag"), tr("filelist.dialog.tag_label"),
        ["character", "hero"], 0, True,
    )
    assert service.add_tag.call_args_list == [
        ((str(tmp_path), path, "hero"),) for path in paths
    ]
    panel._post_refresh.assert_called_once_with()


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
def test_shared_open_command_navigates_directories_and_opens_files(tmp_path, is_dir, plain_panel):
    panel = plain_panel
    path = tmp_path / ("folder" if is_dir else "asset.txt")
    if is_dir:
        path.mkdir()
    else:
        path.write_text("asset")
    panel.navigate_to = Mock()
    opened = Mock()
    panel.file_double_clicked.connect(opened)

    panel._invoke_command("open", panel._command_context([str(path)]), shortcut=True)

    if is_dir:
        panel.navigate_to.assert_called_once_with(str(path))
        opened.assert_not_called()
    else:
        opened.assert_called_once_with(str(path))
        panel.navigate_to.assert_not_called()


def test_reused_scan_after_sort_during_refresh_repopulates_grid(tmp_path, plain_panel):
    """M3: sort reset during a preserved refresh zeroes the grid; the reused
    scan must repopulate it instead of leaving the canvas blank."""
    panel = plain_panel
    for name in ("b.txt", "a.txt", "c.txt"):
        (tmp_path / name).write_text(name)
    app = QApplication.instance() or QApplication([])
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


def test_go_up_cannot_escape_library_root_via_prefix_collision(tmp_path, plain_panel):
    """M4: root C:\\lib must not allow _go_up to reach sibling C:\\library."""
    panel = plain_panel
    root = tmp_path / "lib"
    child = root / "sub"
    sibling = tmp_path / "library"
    root.mkdir()
    child.mkdir()
    sibling.mkdir()
    app = QApplication.instance() or QApplication([])
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
    panel = FileListPanel()
    try:
        scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
        panel.set_scoped_services(scoped)
        panel.navigate_to(str(library), set_root=True)
        panel._post_refresh = Mock()
        panel._run_in_background = Mock()
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
        panel._run_in_background.assert_not_called()
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
    panel = FileListPanel()
    queued = []
    try:
        scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
        panel.set_scoped_services(scoped)
        panel.navigate_to(str(library), set_root=True)
        panel._post_refresh = Mock()
        panel._load_visible = Mock()
        panel._run_in_background = lambda func, *args, on_done=None: queued.append((func, on_done))
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
        # Classification happened on the UI thread: the worker is queued but
        # neither service call may run synchronously during the drop.
        assert queued
        move.assert_not_called()
        copy.assert_not_called()

        func, on_done = queued.pop()
        func()
        assert move.call_args_list == [
            (([str(asset)], str(library)), {"library_root": str(library)}),
        ]
        assert copy.call_args_list == [
            (([str(external)], str(library)), {"library_root": str(library)}),
        ]
        on_done()
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
    panel = FileListPanel()
    try:
        scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
        panel.set_scoped_services(scoped)
        panel.navigate_to(str(library), set_root=True)
        panel._post_refresh = Mock()
        panel._load_visible = Mock()
        panel._run_in_background = lambda func, *args, on_done=None: (func(), on_done and on_done())
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


def test_drop_unexpected_service_error_reports_failed_feedback(tmp_path, monkeypatch):
    library = tmp_path / "library"
    source_dir = library / "source"
    source_dir.mkdir(parents=True)
    source = source_dir / "asset.txt"
    source.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = FileListPanel()
    queued = []
    try:
        scoped = bootstrap.runtime_for(bootstrap.library_service.open_session(library)).services
        panel.set_scoped_services(scoped)
        panel.navigate_to(str(library), set_root=True)
        panel._post_refresh = Mock()
        panel._load_visible = Mock()
        panel._request_operation_selection = Mock()
        panel._run_in_background = lambda func, *args, on_done=None: queued.append((func, on_done))
        move = Mock(side_effect=RuntimeError("drop service failed"))
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
        func, on_done = queued.pop()
        func()
        on_done()

        move.assert_called_once()
        assert "failed" in panel._operation_feedback.text().lower()
        panel._request_operation_selection.assert_not_called()
        panel._post_refresh.assert_called_once()
        panel._load_visible.assert_called_once()
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_drop_closed_session_before_worker_start_is_not_zero_success(tmp_path, monkeypatch):
    library = tmp_path / "library"
    source_dir = library / "source"
    source_dir.mkdir(parents=True)
    source = source_dir / "asset.txt"
    source.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = FileListPanel()
    queued = []
    try:
        session = bootstrap.library_service.open_session(library)
        scoped = bootstrap.runtime_for(session).services
        panel.set_scoped_services(scoped)
        panel.navigate_to(str(library), set_root=True)
        panel._post_refresh = Mock()
        panel._load_visible = Mock()
        panel._request_operation_selection = Mock()
        panel._show_operation_feedback = Mock()
        panel._run_in_background = lambda func, *args, on_done=None: queued.append((func, on_done))
        move = Mock()
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
        func, on_done = queued.pop()
        session.close()
        func()
        on_done()

        move.assert_not_called()
        panel._post_refresh.assert_not_called()
        panel._load_visible.assert_not_called()
        panel._request_operation_selection.assert_not_called()
        assert panel._show_operation_feedback.call_count == 1
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_drop_worker_done_skips_feedback_and_refresh_after_library_switch(tmp_path, monkeypatch):
    """A queued drop worker keeps its originating service, and its completion
    callback must not refresh or report feedback once the panel has switched
    to another library session (same cancellation contract as paste/delete)."""
    from unittest.mock import Mock

    from AssetsManager.application.file_operation_service import FileOperationResult

    library_a = tmp_path / "library-a"
    library_b = tmp_path / "library-b"
    library_a.mkdir()
    library_b.mkdir()
    source_dir = library_a / "source"
    source_dir.mkdir()
    source = source_dir / "asset.txt"
    source.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = FileListPanel()
    queued = []
    try:
        scoped_a = bootstrap.runtime_for(bootstrap.library_service.open_session(library_a)).services
        scoped_b = bootstrap.runtime_for(bootstrap.library_service.open_session(library_b)).services
        moved = library_a / "moved.txt"
        move_a = Mock(return_value=FileOperationResult((moved,)))
        monkeypatch.setattr(scoped_a.file_operation_service, "move_to_directory", move_a)
        panel.set_scoped_services(scoped_a)
        panel.navigate_to(str(library_a), set_root=True)
        panel._post_refresh = Mock()
        panel._load_visible = Mock()
        panel._operation_feedback.clear()
        panel._operation_feedback.hide()
        panel._run_in_background = lambda func, *args, on_done=None: queued.append((func, on_done))

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
        func, on_done = queued.pop()

        # Switch the panel to another library before the worker completes, as
        # `prepare_library_switch` / navigation would.
        panel.set_scoped_services(scoped_b)
        func()
        on_done()

        # The move still ran against the captured originating service, but the
        # completion callback must not touch the (now foreign) panel state.
        move_a.assert_called_once_with(
            [str(source)], str(library_a.resolve()),
            library_root=str(library_a),
        )
        panel._post_refresh.assert_not_called()
        assert not panel._operation_feedback.isVisible()
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
    from AssetsManager.panels.file_list import FileListPanel

    app = QApplication.instance() or QApplication([])
    panel = FileListPanel()
    try:
        panel._thumb_size = 96
        panel._zoom_anim = None
        panel._zoom_generation = 0
        panel._grid_widget = Mock()
        panel._grid_widget._zoom_relayout_active = False
        panel._grid_widget._animator._reduce_motion = False
        panel._grid_widget.width.return_value = 400
        panel._on_zoom_frame = Mock()
        panel._on_zoom_done = Mock()

        FileListPanel._on_zoom_changed(panel, "128px")
        first = panel._zoom_anim
        FileListPanel._on_zoom_changed(panel, "192px")
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
    from AssetsManager.panels.file_list import FileListPanel

    app = QApplication.instance() or QApplication([])
    panel = FileListPanel()
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


def test_file_list_chrome_styles_use_theme_tokens_and_states():
    t = themes.get()
    header_css = FileListPanel._header_css(t)
    assert t["border_subtle"] in header_css

    nav_css = FileListPanel._nav_button_css(t)
    assert "QPushButton:hover" in nav_css
    assert "QPushButton:pressed" in nav_css


# ── Folder cover scanning (P0-3): async, generation-guarded, bounded ──────


def _make_png_file(path):
    img = QImage(8, 8, QImage.Format.Format_ARGB32)
    img.fill(0xFF0000FF)
    assert img.save(str(path), "PNG")


def _wait_for_cover_cache(panel, dir_path, timeout=5.0):
    """Pump the event loop until the async cover result lands in the cache."""
    app = QApplication.instance() or QApplication([])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if dir_path in panel._first_image_cache:
            return True
        time.sleep(0.005)
    app.processEvents()
    return dir_path in panel._first_image_cache


def test_folder_cover_cache_hit_does_not_submit_a_scan(tmp_path, plain_panel):
    panel = plain_panel
    cover = tmp_path / "cover.png"
    _make_png_file(cover)
    panel._first_image_cache[str(tmp_path)] = str(cover)

    result = panel._first_image_cached(str(tmp_path))

    # Cache hits keep the synchronous fast path and never queue a worker.
    assert result == str(cover)
    assert panel._pending_cover_scans == set()
    assert panel._active_cover_tasks == {}


def test_folder_cover_result_is_delivered_on_the_gui_thread(tmp_path):
    import threading

    class TrackingPanel(FileListPanel):
        def __init__(self):
            super().__init__()
            self.completion_threads: list[int] = []

        def _on_cover_scan_result(self, *args):
            self.completion_threads.append(threading.get_ident())
            super()._on_cover_scan_result(*args)

    app = QApplication.instance() or QApplication([])
    panel = TrackingPanel()
    entered = threading.Event()
    release = threading.Event()
    worker_threads: list[int] = []

    def blocked_scan(_dir_path):
        worker_threads.append(threading.get_ident())
        entered.set()
        release.wait(5)
        return str(tmp_path / "cover.png")

    from AssetsManager.panels.file_list import _base_logic as _bl
    original = _bl._first_image_in
    _bl._first_image_in = blocked_scan
    try:
        cover = tmp_path / "cover.png"
        _make_png_file(cover)
        gui_thread = threading.get_ident()

        assert panel._first_image_cached(str(tmp_path)) is None
        assert entered.wait(5), "worker should start the cover scan"
        assert worker_threads == [worker_threads[0]]
        assert worker_threads[0] != gui_thread

        release.set()
        assert _wait_for_cover_cache(panel, str(tmp_path))
        assert panel.completion_threads == [gui_thread]
    finally:
        release.set()
        _bl._first_image_in = original
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()


def test_folder_cover_miss_schedules_async_scan_and_returns_immediately(tmp_path):
    import threading

    app = QApplication.instance() or QApplication([])
    panel = FileListPanel()
    entered = threading.Event()
    release = threading.Event()

    def blocked_scan(_dir_path):
        entered.set()
        release.wait(5)
        return str(tmp_path / "cover.png")

    from AssetsManager.panels.file_list import _base_logic as _bl
    original = _bl._first_image_in
    _bl._first_image_in = blocked_scan
    try:
        cover = tmp_path / "cover.png"
        _make_png_file(cover)

        started = time.monotonic()
        result = panel._first_image_cached(str(tmp_path))
        elapsed = time.monotonic() - started

        # The miss must not scan on the UI thread: the worker is still blocked,
        # yet the call already returned and the request was queued.
        assert result is None
        assert str(tmp_path) in panel._pending_cover_scans
        assert elapsed < 0.5

        assert entered.wait(5), "worker should start the scan in the background"
        release.set()
        assert _wait_for_cover_cache(panel, str(tmp_path))
        assert panel._first_image_cache[str(tmp_path)] == str(cover)
        assert str(tmp_path) not in panel._pending_cover_scans
    finally:
        release.set()
        _bl._first_image_in = original
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()


def test_folder_cover_miss_without_images_caches_none(tmp_path):
    app = QApplication.instance() or QApplication([])
    panel = FileListPanel()
    try:
        empty = tmp_path / "empty"
        empty.mkdir()
        (empty / "readme.txt").write_text("x")

        result = panel._first_image_cached(str(empty))

        assert result is None
        assert _wait_for_cover_cache(panel, str(empty))
        assert panel._first_image_cache[str(empty)] is None
        # Second read is served from cache and no new scan is queued.
        assert panel._first_image_cached(str(empty)) is None
        assert panel._pending_cover_scans == set()
    finally:
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()


def test_stale_cover_result_after_switch_is_discarded(tmp_path):
    import threading

    app = QApplication.instance() or QApplication([])
    panel = FileListPanel()
    entered = threading.Event()
    release = threading.Event()

    def blocked_scan(_dir_path):
        entered.set()
        release.wait(5)
        return str(tmp_path / "cover.png")

    from AssetsManager.panels.file_list import _base_logic as _bl
    original = _bl._first_image_in
    _bl._first_image_in = blocked_scan
    try:
        _make_png_file(tmp_path / "cover.png")
        panel._first_image_cached(str(tmp_path))
        assert entered.wait(5), "worker should be mid-scan before the switch"
        assert str(tmp_path) in panel._pending_cover_scans

        # Simulate a quick navigation / library switch before the scan lands.
        panel._invalidate_cover_scans()
        assert panel._pending_cover_scans == set()

        release.set()
        panel._drain_cover_scan_pool()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        app.processEvents()

        # The stale result must never reach the cache or trigger a refresh.
        assert str(tmp_path) not in panel._first_image_cache
        assert panel._active_cover_tasks == {}
    finally:
        release.set()
        _bl._first_image_in = original
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()


def test_folder_cover_pending_set_is_bounded(tmp_path):
    import threading

    app = QApplication.instance() or QApplication([])
    panel = FileListPanel()
    entered = threading.Event()
    hold = threading.Event()

    def blocked_scan(_dir_path):
        entered.set()
        hold.wait(5)
        return None

    from AssetsManager.panels.file_list import _base_logic as _bl
    original = _bl._first_image_in
    _bl._first_image_in = blocked_scan
    try:
        limit = _bl._COVER_SCAN_QUEUE_LIMIT
        for i in range(limit + 10):
            d = tmp_path / f"d{i}"
            d.mkdir()
            panel._first_image_cached(str(d))

        # Requests are deduplicated and the pending set stays bounded.
        assert len(panel._pending_cover_scans) <= limit
        panel._first_image_cached(str(tmp_path / "d0"))
        assert len(panel._pending_cover_scans) <= limit
    finally:
        hold.set()
        _bl._first_image_in = original
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()


def test_folder_cover_cancel_and_drain_are_bounded(tmp_path):
    app = QApplication.instance() or QApplication([])
    panel = FileListPanel()
    try:
        dirs = []
        for i in range(6):
            d = tmp_path / f"d{i}"
            d.mkdir()
            _make_png_file(d / "cover.png")
            dirs.append(d)
        for d in dirs:
            panel._first_image_cached(str(d))
        assert len(panel._pending_cover_scans) == 6

        pool = panel._cover_scan_pool
        assert pool is not None
        assert pool.max_thread_count == 1  # low-concurrency dedicated pool

        started = time.monotonic()
        panel.shutdown()  # must cancel + bound-drain without hanging the UI thread
        elapsed = time.monotonic() - started

        assert elapsed < 5.0
        assert pool.active_thread_count() == 0
        assert panel._pending_cover_scans == set()
        # A shutdown panel never queues new cover work.
        panel._first_image_cached(str(tmp_path))
        assert panel._pending_cover_scans == set()
    finally:
        app.processEvents()


def test_folder_cover_shutdown_reaps_a_timed_out_pool(tmp_path, monkeypatch):
    import threading

    from AssetsManager.core.workers import retained_pool_count
    from AssetsManager.panels.file_list import _base_logic as _bl

    app = QApplication.instance() or QApplication([])
    panel = FileListPanel()
    entered = threading.Event()
    release = threading.Event()

    def blocking_scan(_dir_path):
        entered.set()
        release.wait(10)
        return None

    monkeypatch.setattr(_bl, "_first_image_in", blocking_scan)
    original_close = panel._close_cover_scan_pool
    monkeypatch.setattr(panel, "_close_cover_scan_pool", lambda: original_close(100))
    try:
        panel._first_image_cached(str(tmp_path))
        assert entered.wait(5), "cover scan should reach the worker"

        initial_retained = retained_pool_count()
        started = time.monotonic()
        panel.shutdown()
        assert time.monotonic() - started < 1.0
        assert panel._cover_scan_pool is None
        assert retained_pool_count() == initial_retained + 1

        release.set()
        assert _wait_for_cover_cache(panel, str(tmp_path), timeout=0.1) is False
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and retained_pool_count() != initial_retained:
            app.processEvents()
            time.sleep(0.005)
        assert retained_pool_count() == initial_retained
    finally:
        release.set()
        panel.deleteLater()
        app.processEvents()


def test_cover_result_requests_only_its_visible_directory_row():
    panel = type("_Panel", (), {})()
    panel._model = Mock()
    panel._model.is_shutdown = False
    panel._view_mode = "Grid"
    panel._grid_widget = type("_Grid", (), {"height": lambda _self: 300, "_scroll_y": 0})()
    panel._grid_layout = type("_Layout", (), {
        "visible_rows": lambda _self, _scroll, _height: [1],
        "columns": 2,
    })()
    panel._loader = Mock()
    panel._model.rowCount = Mock(return_value=3)
    panel._model.row_for_path = Mock(return_value=1)
    entry = Mock()
    entry.is_dir.return_value = True
    panel._model.entry_at = Mock(return_value=entry)

    FileListPanel._request_cover_thumbnail(
        panel, "/library/folder-a", "/library/folder-a/cover.png",
    )
    panel._loader.request.assert_called_once_with(
        1, "/library/folder-a/cover.png", priority=0, item_path="/library/folder-a",
    )


def test_cover_result_ignores_directory_no_longer_in_model():
    panel = type("_Panel", (), {})()
    panel._model = Mock()
    panel._model.is_shutdown = False
    panel._view_mode = "Grid"
    panel._grid_widget = type("_Grid", (), {"height": lambda _self: 300, "_scroll_y": 0})()
    panel._grid_layout = type("_Layout", (), {
        "visible_rows": lambda _self, _scroll, _height: [1],
        "columns": 2,
    })()
    panel._loader = Mock()
    panel._model.rowCount = Mock(return_value=3)
    panel._model.row_for_path = Mock(return_value=-1)

    FileListPanel._request_cover_thumbnail(panel, "/library/gone", "/library/gone/cover.png")

    panel._loader.request.assert_not_called()
