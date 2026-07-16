from unittest.mock import Mock

from AssetsManager.controllers.info_controller import FileInfo, PluginField
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
