from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QTreeWidgetItem

from AssetsManager.controllers.info_controller import FileInfo, PluginField
from AssetsManager.core import themes
from AssetsManager.panels import info as info_module
from AssetsManager.panels.info import InfoPanel
from AssetsManager.panels.tag_tree import TagTreePanel


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


def test_info_link_buttons_are_reused_across_url_updates(tmp_path):
    panel = InfoPanel()
    try:
        panel._current_path = str(tmp_path)
        panel._set_link_field("")
        add_btn = panel._link_add_btn
        scan_btn = panel._link_scan_btn
        assert not add_btn.isHidden()
        assert not scan_btn.isHidden()  # directories offer URL scanning

        panel._set_link_field("https://example.com/asset")
        assert panel._link_rm_btn is panel._link_rm_btn
        assert not panel._link_rm_btn.isHidden()
        assert add_btn.isHidden()
        assert scan_btn.isHidden()

        panel._set_link_field("")
        assert panel._link_add_btn is add_btn
        assert not add_btn.isHidden()

        file_path = tmp_path / "asset.txt"
        file_path.write_text("x", encoding="utf-8")
        panel._current_path = str(file_path)
        panel._set_link_field("")
        assert scan_btn.isHidden()  # scan action is directory-only
    finally:
        panel.shutdown()
        panel.deleteLater()


def test_info_plugin_fields_are_reused_and_updated():
    panel = InfoPanel()
    try:
        panel._render_plugin_fields([PluginField("author", "A", "test")])
        first_row = panel._plugin_field_rows["Author"]

        panel._render_plugin_fields([
            PluginField("author", "B", "test"),
            PluginField("source", "S", "test"),
        ])

        assert panel._plugin_field_rows["Author"] is first_row
        assert first_row.layout().itemAt(1).widget().text() == "B"
        assert panel._plugin_fields_layout.count() == 2

        panel._render_plugin_fields([])
        assert first_row.isHidden()
        assert panel._plugin_fields_widget.isHidden()
    finally:
        panel.shutdown()
        panel.deleteLater()


def test_info_preview_states_are_explicit_and_sequential():
    panel = InfoPanel()
    try:
        assert panel._preview_state == "empty"

        panel._show_loading_state()
        assert panel._preview_state == "loading"
        assert panel._preview.text() == "..."
        assert not panel._preview.isHidden()

        panel._current_path = "C:/library/asset.xyz"
        panel._show_preview_fallback()
        assert panel._preview_state == "fallback"
        assert panel._preview.pixmap() is not None

        panel._show_empty_state()
        assert panel._preview_state == "empty"
        assert panel._preview.isHidden()
        assert not panel._empty_preview_state.isHidden()
    finally:
        panel.shutdown()
        panel.deleteLater()


def test_tag_tree_file_click_emits_navigation_signal():
    panel = TagTreePanel()
    try:
        tag_item = QTreeWidgetItem(["hero"])
        tag_item.setData(0, Qt.ItemDataRole.UserRole, "hero")
        file_item = QTreeWidgetItem(["asset.png"])
        file_item.setData(0, Qt.ItemDataRole.UserRole, "C:/library/asset.png")
        tag_item.addChild(file_item)
        panel._tree.addTopLevelItem(tag_item)
        captured = []
        panel.directory_selected.connect(captured.append)

        panel._on_click(file_item, 0)

        assert captured == ["C:/library/asset.png"]
    finally:
        panel.shutdown()
        panel.deleteLater()


def test_info_tag_browser_forwards_file_click_to_navigation_signal(monkeypatch):
    panel = InfoPanel()
    try:
        panel._scoped_services = Mock()
        fake_dialog = Mock()
        monkeypatch.setattr(
            "AssetsManager.dialogs.tag_browser_dialog.TagBrowserDialog",
            lambda services, parent: fake_dialog,
        )
        captured = []
        panel.navigate_requested.connect(captured.append)

        panel._open_tag_browser()

        fake_dialog.directory_selected.connect.assert_called_once()
        connected = fake_dialog.directory_selected.connect.call_args.args[0]
        connected("C:/library/asset.png")
        fake_dialog.exec.assert_called_once()
        assert captured == ["C:/library/asset.png"]
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


def _install_fake_app_settings(monkeypatch, initial=None):
    """Patch the panel's AppSettings import with an in-memory test double."""
    state = dict(initial or {})

    class _FakeAppSettings:
        def __init__(self):
            self.save_calls = 0

        @classmethod
        def instance(cls):
            if getattr(cls, "_instance", None) is None:
                cls._instance = cls()
            return cls._instance

        def get(self, key, default=None):
            return state.get(key, default)

        def set(self, key, value):
            state[key] = value

        def save(self):
            self.save_calls += 1
            return True

    fake_cls = _FakeAppSettings
    monkeypatch.setattr(info_module, "AppSettings", fake_cls)
    monkeypatch.setattr("AssetsManager.core.settings.AppSettings", fake_cls)
    return state, fake_cls.instance()


def test_info_panel_restores_and_persists_section_visibility(monkeypatch):
    state, settings = _install_fake_app_settings(monkeypatch, {
        "info_panel_layout": {
            "sections": {
                "preview": False,
                "meta": True,
                "tags": False,
                "notes": True,
                "actions": False,
            },
            "splitter": [111, 222],
        },
    })
    panel = InfoPanel()
    try:
        assert panel._preview_host.isHidden()
        assert not panel._meta_grp.isHidden()
        assert panel._tags_grp.isHidden()
        assert not panel._notes_grp.isHidden()
        assert panel._act_bar.isHidden()

        # Splitters normalize setSizes() until the panel is shown, so pin the
        # restore contract at the QSplitter call boundary.
        applied = []
        monkeypatch.setattr(panel._splitter, "setSizes", lambda sizes: applied.append(sizes))
        panel._restore_layout_state()
        assert applied == [[111, 222]]

        panel._set_section_visible("meta", panel._meta_grp, False)
        panel._set_section_visible("actions", panel._act_bar, True)
        saved = state["info_panel_layout"]
        assert saved["sections"] == {
            "preview": False,
            "meta": False,
            "tags": False,
            "notes": True,
            "actions": True,
        }
        assert isinstance(saved["splitter"], list) and len(saved["splitter"]) == 2
        assert settings.save_calls == 2
    finally:
        panel._layout_save_timer.stop()
        panel.shutdown()
        panel.deleteLater()


def test_info_panel_ignores_malformed_layout_preferences(monkeypatch):
    _install_fake_app_settings(monkeypatch, {
        "info_panel_layout": {
            "sections": {"preview": "no", "notes": 0},
            "splitter": [0, -1],
        },
    })
    panel = InfoPanel()
    try:
        # Non-bool saved visibility is ignored, so the default (all shown) is
        # kept. The unattached footer bar reports hidden until a dock hosts it.
        assert all(
            not widget.isHidden()
            for key, widget in panel._section_widgets()
            if key != "actions"
        )
        assert panel._act_bar.isHidden()
    finally:
        panel._layout_save_timer.stop()
        panel.shutdown()
        panel.deleteLater()


def test_info_tag_chips_are_reused_and_only_differences_are_rebuilt():
    panel = InfoPanel()
    panel._reduce_motion = True
    try:
        panel._render_tags(["alpha", "beta"])
        alpha = panel._tag_chip_pool["alpha"]
        beta = panel._tag_chip_pool["beta"]
        assert panel._tags_widgets == [alpha, beta]
        assert panel._tags_flow_layout.count() == 2

        # Reordering + one new tag keeps both old chip instances alive.
        panel._render_tags(["beta", "alpha", "gamma"])
        assert panel._tag_chip_pool["alpha"] is alpha
        assert panel._tag_chip_pool["beta"] is beta
        gamma = panel._tag_chip_pool["gamma"]
        assert panel._tags_widgets == [beta, alpha, gamma]
        assert panel._tags_flow_layout.count() == 3

        # Shrinking the set hides the difference instead of deleting widgets.
        panel._render_tags(["gamma"])
        assert panel._tags_widgets == [gamma]
        assert panel._tags_flow_layout.count() == 1
        assert alpha.isHidden()
        assert beta.isHidden()

        # A previously hidden chip is pulled out of the pool intact, and a
        # mid-fade opacity reset cannot leave the reused chip invisible.
        alpha.setWindowOpacity(0.0)
        panel._render_tags(["alpha"])
        assert panel._tag_chip_pool["alpha"] is alpha
        assert not alpha.isHidden()
        assert alpha.windowOpacity() == 1.0
        assert panel._tags_widgets == [alpha]
    finally:
        panel.shutdown()
        panel.deleteLater()


def test_info_tag_chip_pool_evicts_lru_hidden_chips(monkeypatch):
    monkeypatch.setattr(info_module, "_TAG_CHIP_POOL_LIMIT", 3)
    panel = InfoPanel()
    panel._reduce_motion = True
    try:
        # All rendered chips are protected from eviction, so the pool may
        # exceed the limit while the whole set is on screen.
        panel._render_tags(["a", "b", "c", "d"])
        assert set(panel._tag_chip_pool) == {"a", "b", "c", "d"}

        panel._render_tags(["e"])
        assert "a" not in panel._tag_chip_pool
        assert "b" not in panel._tag_chip_pool
        assert set(panel._tag_chip_pool) == {"c", "d", "e"}
        assert panel._tags_widgets == [panel._tag_chip_pool["e"]]

        # LRU recency: touching c keeps it while d is the next eviction victim.
        panel._render_tags(["c"])
        panel._render_tags(["f"])
        assert "d" not in panel._tag_chip_pool
        assert set(panel._tag_chip_pool) == {"c", "e", "f"}
    finally:
        panel.shutdown()
        panel.deleteLater()


def test_info_modern_styles_use_theme_tokens_and_states():
    panel = InfoPanel()
    try:
        group_qss = panel._meta_grp.styleSheet()
        assert themes.get()["border_subtle"] in group_qss

        open_qss = panel._open_btn.styleSheet()
        assert "QPushButton:hover" in open_qss
        assert "QPushButton:pressed" in open_qss
    finally:
        panel.shutdown()
        panel.deleteLater()


def test_tag_tree_add_button_uses_secondary_button_variant():
    panel = TagTreePanel()
    try:
        assert panel._add_btn.property("buttonVariant") == "secondary"
        tree_qss = panel._tree.styleSheet()
        assert "QTreeWidget::item:hover" in tree_qss
        assert "QTreeWidget::item:selected:focus" in tree_qss
    finally:
        panel.shutdown()
        panel.deleteLater()
