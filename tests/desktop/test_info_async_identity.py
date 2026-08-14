from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtWidgets import QPushButton

from AssetsManager.controllers.info_controller import FileInfo, PluginField
from AssetsManager.panels import info as info_module
from AssetsManager.panels.info import InfoPanel


def _file_info(path, *, name, plugin_value):
    return FileInfo(
        path=str(path),
        name=name,
        is_dir=False,
        file_type="File",
        size_display="1.00 KB",
        modified_display="2026-07-15 12:00:00",
        parent_path=str(path.parent),
        tags=(),
        notes="",
        urls=(),
        plugin_fields=(PluginField("author", plugin_value, "test"),),
        dir_summary=None,
        preview_path=None,
        is_project=False,
    )


def _plugin_value(panel):
    field = panel._plugin_fields_layout.itemAt(0).widget()
    return field.layout().itemAt(1).widget().text()


def test_info_language_refresh_updates_visible_labels():
    panel = InfoPanel()
    try:
        panel._refresh_language("zh")

        assert panel._meta_grp.title()
        assert panel._tags_grp.title()
        assert panel._notes.placeholderText()
        assert panel._open_btn.text()
    finally:
        panel.shutdown()
        panel.deleteLater()


def test_info_group_qss_is_stable_across_theme_refresh():
    panel = InfoPanel()
    try:
        before = panel._meta_grp.styleSheet()
        panel._refresh_theme("Navy")
        assert panel._meta_grp.styleSheet() == before
        assert "QGroupBox" in before
    finally:
        panel.shutdown()
        panel.deleteLater()


def test_info_scaled_geometry_refresh_recalculates_fixed_metrics(monkeypatch):
    panel = InfoPanel()
    try:
        panel._set_link_field("")
        monkeypatch.setattr(info_module, "scaled_px", lambda value: value * 2)

        panel.refresh_scaled_geometry()

        assert panel._act_bar.height() == 56
        assert panel._preview.minimumHeight() == 120
        assert panel._tags_flow_layout.spacing() == 8
        link_buttons = panel._field_link.findChildren(QPushButton)
        assert link_buttons
        assert all(button.width() == 36 for button in link_buttons)
    finally:
        panel.shutdown()
        panel.deleteLater()


def test_file_info_and_preview_reject_old_navigate_away_back_completion(tmp_path):
    panel = InfoPanel()
    session = Mock(is_closed=False)
    panel._scoped_services = Mock(session=session)
    path_a = tmp_path / "a.txt"
    path_b = tmp_path / "b.txt"
    path_a.write_text("a", encoding="utf-8")
    path_b.write_text("b", encoding="utf-8")

    panel._current_path = str(path_a)
    old_request = panel._new_async_request(str(path_a))
    panel._current_path = str(path_b)
    panel._new_async_request(str(path_b))
    panel._current_path = str(path_a)
    current_request = panel._new_async_request(str(path_a))

    current_info = _file_info(path_a, name="current", plugin_value="current-plugin")
    stale_info = _file_info(path_a, name="stale", plugin_value="stale-plugin")
    current_pixmap = Mock()
    current_pixmap.__bool__ = Mock(return_value=True)

    panel._on_file_info_ready(current_request, current_info)
    panel._on_preview_ready(current_request, current_pixmap)
    panel._on_file_info_ready(old_request, stale_info)
    panel._on_preview_ready(old_request, None)

    assert panel._name.text() == "current"
    assert _plugin_value(panel) == "current-plugin"
    assert panel._preview_pixmap is current_pixmap


def test_async_callbacks_reject_old_same_root_session_completion(tmp_path):
    panel = InfoPanel()
    path = tmp_path / "asset.txt"
    path.write_text("asset", encoding="utf-8")
    old_session = Mock(root_str=str(tmp_path), is_closed=False)
    new_session = Mock(root_str=str(tmp_path), is_closed=False)

    panel._scoped_services = Mock(session=old_session)
    panel._current_path = str(path)
    old_request = panel._new_async_request(str(path))
    panel._scoped_services = Mock(session=new_session)
    panel._current_path = str(path)
    current_request = panel._new_async_request(str(path))

    current_info = _file_info(path, name="current", plugin_value="new-session")
    stale_info = _file_info(path, name="stale", plugin_value="old-session")
    panel._on_file_info_ready(current_request, current_info)
    panel._on_file_info_ready(old_request, stale_info)
    panel._on_preview_ready(current_request, Mock())
    current_preview = panel._preview_pixmap
    panel._on_preview_ready(old_request, None)

    assert panel._name.text() == "current"
    assert _plugin_value(panel) == "new-session"
    assert panel._preview_pixmap is current_preview


def test_directory_size_rejects_stale_zero_for_reused_path_and_session(tmp_path):
    panel = InfoPanel()
    path = tmp_path / "folder"
    path.mkdir()
    old_session = Mock(root_str=str(tmp_path), is_closed=False)
    new_session = Mock(root_str=str(tmp_path), is_closed=False)

    panel._scoped_services = Mock(session=old_session)
    panel._current_path = str(path)
    old_request = panel._new_async_request(str(path))
    panel._scoped_services = Mock(session=new_session)
    panel._current_path = str(path)
    current_request = panel._new_async_request(str(path))

    panel._on_async_dir_size_done(current_request, 4096)
    panel._on_async_dir_size_done(old_request, 0)

    value = panel._fields["size"].layout().itemAt(1).widget().text()
    assert value == "4.00 KB"


def test_closed_session_rejects_file_info_preview_plugin_and_directory_callbacks(tmp_path):
    panel = InfoPanel()
    path = tmp_path / "asset.txt"
    path.write_text("asset", encoding="utf-8")
    session = Mock(root_str=str(tmp_path), is_closed=False)
    panel._scoped_services = Mock(session=session)
    panel._current_path = str(path)
    request = panel._new_async_request(str(path))
    panel._name.setText("unchanged")
    panel._set_field_text(panel._fields["size"], "pending")
    session.is_closed = True

    panel._on_file_info_ready(request, _file_info(path, name="stale", plugin_value="stale-plugin"))
    panel._on_preview_ready(request, Mock())
    panel._on_async_dir_size_done(request, 0)

    assert panel._name.text() == "unchanged"
    assert panel._plugin_fields_layout.count() == 0
    assert panel._preview_pixmap is None
    assert panel._fields["size"].layout().itemAt(1).widget().text() == "pending"


def test_field_update_ignores_missing_dynamic_layout():
    from PySide6.QtWidgets import QWidget

    row = QWidget()
    InfoPanel._set_field_text(row, "updated")


def test_info_panel_injects_session_and_drops_old_controller_on_switch(tmp_path):
    from unittest.mock import Mock

    from AssetsManager.application.library_service import LibraryService

    library = tmp_path / "library"
    service = LibraryService()
    session = service.open_session(library)
    panel = InfoPanel()
    try:
        metadata_service = Mock()
        metadata_service._session = session
        panel.set_scoped_services(
            SimpleNamespace(
                session=session,
                metadata_service=metadata_service,
                tag_service=Mock(),
            )
        )
        old_controller = panel._controller
        assert old_controller is not None
        assert old_controller._session is session

        panel.prepare_library_switch()

        assert panel._controller is None
        assert panel._scoped_services is None
    finally:
        panel.shutdown()
        panel.deleteLater()
        if not session.is_closed:
            session.close()
        else:
            session._finish_close()
