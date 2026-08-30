"""Desktop sidebar COLLECTIONS group tests (user collections, migration v38).

Covers the presentation contract: collections render as a virtual header
group with manual member rows; missing member paths are skipped on load;
member double-click navigates via ``directory_selected`` without touching
the recent-folders list; smart collections stay display-only (no desktop
evaluation); CollectionChanged repopulates the group.
"""
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtWidgets import QApplication

from AssetsManager.i18n import tr
from AssetsManager.panels.sidebar import (
    _COLLECTION_ID_ROLE,
    _COLLECTION_KIND_ROLE,
    SidebarPanel,
    VTYPE_COLLECTION,
    VTYPE_COLLECTION_HEADER,
    VTYPE_COLLECTION_MEMBER,
)

_app = QApplication.instance() or QApplication([])


def _collection_rows(panel):
    """Return (header, [collection items]) for the collections group."""
    for i in range(panel._tree.topLevelItemCount()):
        item = panel._tree.topLevelItem(i)
        if item is not None and panel._get_vtype(item) == VTYPE_COLLECTION_HEADER:
            return item, [item.child(j) for j in range(item.childCount())]
    return None, []


def _scoped_panel(tmp_path, collection_service):
    panel = SidebarPanel()
    panel._scoped_services = SimpleNamespace(
        collection_service=collection_service,
        session=SimpleNamespace(event_token="token-1"),
    )
    panel._library_root = str(tmp_path / "library")
    panel._populate()
    return panel


def _manual_collection(tmp_path):
    service = Mock()
    service.list_collections.return_value = [
        {"id": 1, "name": "hero", "kind": "manual", "member_count": 2},
        {"id": 2, "name": "smart ones", "kind": "smart", "member_count": 0},
    ]
    service.get_members.return_value = [
        {"file_path": str(tmp_path / "a.png"), "added_at": 1.0, "exists": True},
        {"file_path": str(tmp_path / "gone.png"), "added_at": 2.0, "exists": False},
    ]
    return service


def test_collections_group_renders_manual_and_smart_rows(tmp_path):
    service = _manual_collection(tmp_path)
    panel = _scoped_panel(tmp_path, service)
    try:
        header, rows = _collection_rows(panel)
        assert header is not None
        assert header.text(0) == tr("sidebar.collections", count=2)
        assert [r.text(0) for r in rows] == [
            tr("sidebar.collection_label", name="hero", count=2),
            tr("sidebar.smart_collection_label", name="smart ones"),
        ]
        assert panel._get_vtype(rows[0]) == VTYPE_COLLECTION
        assert rows[0].data(0, _COLLECTION_ID_ROLE) == 1
        assert rows[0].data(0, _COLLECTION_KIND_ROLE) == "manual"
    finally:
        panel.shutdown()
        panel.deleteLater()
        _app.processEvents()


def test_no_collections_group_without_scoped_services(tmp_path):
    panel = SidebarPanel()
    try:
        panel._library_root = str(tmp_path)
        panel._populate()
        header, _rows = _collection_rows(panel)
        assert header is None
    finally:
        panel.shutdown()
        panel.deleteLater()
        _app.processEvents()


def test_manual_members_lazy_load_and_skip_missing_paths(tmp_path):
    service = _manual_collection(tmp_path)
    panel = _scoped_panel(tmp_path, service)
    try:
        _header, rows = _collection_rows(panel)
        manual_row = rows[0]
        # A manual collection starts with a lazy-load placeholder.
        assert manual_row.childCount() == 1

        panel._on_tree_click(manual_row, 0)
        service.get_members.assert_called_once_with(panel._library_root, 1)
        # Members load as navigable rows; the missing file is skipped.
        assert manual_row.childCount() == 1
        member = manual_row.child(0)
        assert panel._get_vtype(member) == VTYPE_COLLECTION_MEMBER
        assert member.data(0, 0) == "a.png"
        assert manual_row.isExpanded()
    finally:
        panel.shutdown()
        panel.deleteLater()
        _app.processEvents()


def test_smart_collection_click_never_evaluates_or_loads_members(tmp_path):
    service = _manual_collection(tmp_path)
    panel = _scoped_panel(tmp_path, service)
    try:
        _header, rows = _collection_rows(panel)
        smart_row = rows[1]
        panel._on_tree_click(smart_row, 0)
        # Desktop keeps smart collections display-only: no member reads.
        service.get_members.assert_not_called()
        assert smart_row.childCount() == 0
    finally:
        panel.shutdown()
        panel.deleteLater()
        _app.processEvents()


def test_member_double_click_navigates_without_recording_a_visit(tmp_path, monkeypatch):
    service = _manual_collection(tmp_path)
    panel = _scoped_panel(tmp_path, service)
    try:
        _header, rows = _collection_rows(panel)
        panel._on_tree_click(rows[0], 0)
        member = rows[0].child(0)

        record_visit = Mock()
        monkeypatch.setattr(panel._recents, "record_visit", record_visit)
        navigated = []
        panel.directory_selected.connect(navigated.append)
        panel._on_tree_double_click(member, 0)

        assert navigated == [str(tmp_path / "a.png")]
        record_visit.assert_not_called()
    finally:
        panel.shutdown()
        panel.deleteLater()
        _app.processEvents()


def test_collection_changed_event_repopulates_matching_session(tmp_path):
    service = _manual_collection(tmp_path)
    panel = _scoped_panel(tmp_path, service)
    try:
        initial_calls = service.list_collections.call_count
        event = SimpleNamespace(session_token="token-1")
        panel._on_domain_collections_changed(event)
        assert service.list_collections.call_count == initial_calls + 1

        # A foreign session's event must not repopulate this panel.
        foreign = SimpleNamespace(session_token="token-other")
        panel._on_domain_collections_changed(foreign)
        assert service.list_collections.call_count == initial_calls + 1
    finally:
        panel.shutdown()
        panel.deleteLater()
        _app.processEvents()


def test_collection_new_and_rename_and_delete_routes_through_service(
    tmp_path, monkeypatch
):
    from AssetsManager.panels.sidebar import QInputDialog

    service = _manual_collection(tmp_path)
    panel = _scoped_panel(tmp_path, service)
    try:
        _header, rows = _collection_rows(panel)
        manual_row = rows[0]

        prompts = iter([("renamed", True), ("renamed", True)])
        monkeypatch.setattr(
            QInputDialog, "getText",
            staticmethod(lambda *args, **kwargs: next(prompts)),
        )
        panel._collection_new()
        service.create.assert_called_once_with(panel._library_root, "renamed")

        panel._collection_rename(manual_row)
        service.rename.assert_called_once_with(panel._library_root, 1, "renamed")

        panel._collection_delete(manual_row)
        service.delete.assert_called_once_with(panel._library_root, 1)
    finally:
        panel.shutdown()
        panel.deleteLater()
        _app.processEvents()
