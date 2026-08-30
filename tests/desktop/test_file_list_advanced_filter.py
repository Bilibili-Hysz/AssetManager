"""Advanced structured filter popup for the FileList search entry.

Covers the desktop side of T7: the popup refines the single existing
FileList search input (no new search entry), the model narrows the current
listing through the shared filter pipeline, and the library-wide count is
requested through the shared application SearchService.
"""
from unittest.mock import Mock

from AssetsManager.application.search_service import SearchResultSet, SearchStatus
from AssetsManager.panels.file_list._base import FileListPanel


def test_advanced_filter_popup_hidden_by_default_and_toggles(plain_panel):
    panel = plain_panel
    assert not panel._advanced_popup.isVisible()
    assert panel._advanced_btn.toolTip()
    assert panel._advanced_btn.accessibleName() == panel._advanced_btn.toolTip()

    panel._toggle_advanced_filter()
    assert panel._advanced_popup.isVisible()
    panel._toggle_advanced_filter()
    assert not panel._advanced_popup.isVisible()


def test_advanced_filter_widgets_start_unset(plain_panel):
    panel = plain_panel
    assert panel._structured_search_params() == {}
    assert panel._model._structured_filter == {}


def test_structured_search_params_convert_units(plain_panel):
    from PySide6.QtCore import QDate

    panel = plain_panel
    after = QDate(2024, 5, 1)
    before = QDate(2024, 5, 31)
    panel._adv_mtime_after.setDate(after)
    panel._adv_mtime_before.setDate(before)
    panel._adv_size_min.setValue(2)
    panel._adv_size_max.setValue(500)
    panel._adv_extensions.setText(" PNG, .Jpg, ")

    params = panel._structured_search_params()
    assert params["mtime_after"] > 0
    assert params["mtime_before"] > params["mtime_after"]
    assert params["size_min"] == 2 * 1024 * 1024
    assert params["size_max"] == 500 * 1024 * 1024
    assert params["extensions"] == ["png", "jpg"]

    # Clear resets the widgets and therefore the params.
    panel._clear_advanced_filter()
    assert panel._structured_search_params() == {}


def test_rating_range_rides_shared_query_not_local_model(file_list_panel_ctx, tmp_path, monkeypatch):
    """The rating spins feed the shared structured query; the local model
    filter stays untouched (it has no rating data)."""
    panel, _session, _bootstrap, _services = file_list_panel_ctx
    (tmp_path / "a.png").write_bytes(b"a")
    (tmp_path / "b.png").write_bytes(b"b")
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()
    assert panel._model.rowCount() == 2

    mock_service = Mock()
    mock_service.search_structured_detailed.return_value = SearchResultSet.from_source(
        "indexed", status=SearchStatus.EMPTY,
    )
    monkeypatch.setattr(panel, "_search_service", mock_service)
    monkeypatch.setattr(
        panel, "_run_in_background",
        lambda func, *args, on_done=None: on_done(func()) if on_done else func(),
    )

    panel._adv_rating_min.setValue(3)
    panel._adv_rating_max.setValue(5)
    panel._apply_advanced_filter()

    # The shared application query carries the rating bounds.
    kwargs = mock_service.search_structured_detailed.call_args.kwargs
    assert kwargs["rating_min"] == 3
    assert kwargs["rating_max"] == 5
    # Presentation keeps the full listing (no local rating narrowing).
    assert panel._model.rowCount() == 2
    assert panel._model._structured_filter == {}

    # Params omit the bounds when both spins sit on the "any" sentinel.
    panel._clear_advanced_filter()
    panel._adv_rating_min.setValue(2)
    params = panel._structured_search_params()
    assert params == {"rating_min": 2}
    panel._clear_advanced_filter()
    assert panel._structured_search_params() == {}


def test_apply_advanced_filter_narrows_model_and_calls_shared_service(file_list_panel_ctx, tmp_path, monkeypatch):
    panel, _session, _bootstrap, _services = file_list_panel_ctx
    (tmp_path / "small.png").write_bytes(b"a")
    (tmp_path / "big.png").write_bytes(b"x" * (2 * 1024 * 1024))
    (tmp_path / "note.txt").write_text("t")
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()
    assert panel._model.rowCount() == 3

    mock_service = Mock()
    mock_service.search_structured_detailed.return_value = SearchResultSet.from_source(
        "indexed", status=SearchStatus.EMPTY,
    )
    monkeypatch.setattr(panel, "_search_service", mock_service)
    calls = []

    def _sync_run(func, *args, on_done=None):
        result = func(*args)
        calls.append(result)
        if on_done is not None:
            on_done(result)

    monkeypatch.setattr(panel, "_run_in_background", _sync_run)

    panel._adv_size_min.setValue(1)  # 1 MiB in the spinbox
    panel._adv_extensions.setText("png")
    panel._apply_advanced_filter()

    # Presentation flows through the existing filtered model pipeline.
    assert panel._model.rowCount() == 1
    assert panel._model.entries[0].name == "big.png"
    assert not panel._advanced_popup.isVisible()
    # The structured query went to the shared application SearchService.
    kwargs = mock_service.search_structured_detailed.call_args.kwargs
    assert kwargs["size_min"] == 1024 * 1024
    assert kwargs["extensions"] == ["png"]
    assert kwargs["name_substring"] == ""
    assert len(calls) == 1


def test_clear_advanced_filter_restores_full_listing(file_list_panel_ctx, tmp_path):
    panel, _session, _bootstrap, _services = file_list_panel_ctx
    (tmp_path / "a.png").write_bytes(b"a")
    (tmp_path / "b.png").write_bytes(b"bb")
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()

    panel._model.set_structured_filter(size_min=2)
    assert panel._model.rowCount() == 1

    panel._clear_advanced_filter()
    assert panel._model.rowCount() == 2
    assert panel._model._structured_filter == {}


def test_set_structured_filter_keeps_directories_navigable(file_list_panel_ctx, tmp_path):
    panel, _session, _bootstrap, _services = file_list_panel_ctx
    (tmp_path / "subdir").mkdir()
    (tmp_path / "tiny.png").write_bytes(b"a")
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()

    panel._model.set_structured_filter(size_min=1024)
    names = [entry.name for entry in panel._model.entries]
    assert names == ["subdir"]  # directory survives, undersized file is hidden


def test_advanced_filter_without_search_service_reports_locally(file_list_panel_ctx, tmp_path, monkeypatch):
    panel, _session, _bootstrap, _services = file_list_panel_ctx
    (tmp_path / "a.png").write_bytes(b"a")
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()

    monkeypatch.setattr(panel, "_search_service", None)
    toasts = []
    monkeypatch.setattr(FileListPanel, "_toast", lambda self, text: toasts.append(text))

    panel._adv_extensions.setText("png")
    panel._apply_advanced_filter()

    assert panel._model.rowCount() == 1
    assert len(toasts) == 1
