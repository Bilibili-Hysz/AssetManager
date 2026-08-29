from types import SimpleNamespace
from unittest.mock import Mock


from PySide6.QtWidgets import QApplication

from AssetsManager.domain.events import (
    AssetNotesChanged, AssetTagsChanged, AssetUrlsChanged, TagCatalogChanged,
)
from AssetsManager.application.runtime_events import InvalidationEvent, ProjectionDomain
from AssetsManager.panels.info import InfoPanel
from AssetsManager.panels.tag_tree import TagTreePanel


def test_info_ignores_foreign_tag_events_and_other_assets(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    panel = InfoPanel()
    asset = str((tmp_path / "asset.txt").resolve())
    panel._current_path = asset
    panel._scoped_services = SimpleNamespace(session=SimpleNamespace(event_token="current"))
    panel._controller = Mock(get_tags=Mock(return_value=["hero"]))
    rendered = []
    monkeypatch.setattr(panel, "_render_tags", rendered.append)
    try:
        panel._on_domain_tags_changed(AssetTagsChanged(session_token="foreign", file_path=asset))
        panel._on_domain_tags_changed(AssetTagsChanged(session_token="current", file_path="other"))
        panel._on_domain_tags_changed(AssetTagsChanged(session_token="current", file_path=asset))

        assert rendered == [["hero"]]
    finally:
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()


def test_tag_tree_ignores_foreign_catalog_events(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = TagTreePanel()
    panel._scoped_services = SimpleNamespace(session=SimpleNamespace(event_token="current"))
    populated = []
    monkeypatch.setattr(panel, "_populate", lambda: populated.append("refresh"))
    try:
        panel._on_domain_tags_changed(TagCatalogChanged(session_token="foreign"))
        panel._on_domain_tags_changed(TagCatalogChanged(session_token="current"))

        assert populated == ["refresh"]
    finally:
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()


def test_info_ignores_foreign_metadata_events(tmp_path):
    app = QApplication.instance() or QApplication([])
    panel = InfoPanel()
    asset = str((tmp_path / "asset.txt").resolve())
    panel._current_path = asset
    panel._scoped_services = SimpleNamespace(session=SimpleNamespace(event_token="current"))
    panel._controller = Mock(
        get_notes=Mock(return_value="new"),
        get_urls=Mock(return_value=["https://a"]),
    )
    try:
        panel._on_domain_notes_changed(AssetNotesChanged(session_token="foreign", file_path=asset))
        panel._on_domain_notes_changed(AssetNotesChanged(session_token="current", file_path="other"))
        panel._on_domain_notes_changed(AssetNotesChanged(session_token="current", file_path=asset))
        panel._on_domain_urls_changed(AssetUrlsChanged(session_token="foreign", file_path=asset))
        panel._on_domain_urls_changed(AssetUrlsChanged(session_token="current", file_path=asset))

        panel._controller.get_notes.assert_called_once_with(asset)
        panel._controller.get_urls.assert_called_once_with(asset)
    finally:
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()

class _FakeRuntimeSubscription:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FakeRuntimeRouter:
    def __init__(self):
        self.callback = None
        self.subscription = _FakeRuntimeSubscription()

    def subscribe(self, callback):
        self.callback = callback
        return self.subscription

    def emit(self, invalidation):
        assert self.callback is not None
        self.callback(invalidation)


def _fake_runtime(token, epoch):
    session = SimpleNamespace(root_str="/library", event_token=token)
    # undo_service: required by TagTreePanel.set_scoped_services since the
    # tag-delete undo-stack wiring (ed68f7e).
    services = SimpleNamespace(session=session, tag_service=Mock(), undo_service=Mock())
    router = _FakeRuntimeRouter()
    runtime = SimpleNamespace(
        session=session,
        services_snapshot=services,
        event_router=router,
        epoch=epoch,
    )
    return runtime, router


def test_tag_tree_runtime_router_filters_domains_and_refreshes_once(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = TagTreePanel()
    populated = Mock()
    monkeypatch.setattr(panel, "_populate", populated)
    runtime, router = _fake_runtime("current", "epoch-current")
    try:
        panel.set_runtime(runtime)
        populated.reset_mock()

        router.emit(InvalidationEvent(
            "epoch-current", 1, (ProjectionDomain.TAGS,), (),
        ))
        app.processEvents()
        assert populated.call_count == 1

        router.emit(InvalidationEvent(
            "epoch-current", 2, (ProjectionDomain.FILES,), (),
        ))
        app.processEvents()
        assert populated.call_count == 1
    finally:
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()


def test_tag_tree_runtime_switch_ignores_old_router_events(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = TagTreePanel()
    populated = Mock()
    monkeypatch.setattr(panel, "_populate", populated)
    runtime_a, router_a = _fake_runtime("session-a", "epoch-a")
    runtime_b, router_b = _fake_runtime("session-b", "epoch-b")
    try:
        panel.set_runtime(runtime_a)
        panel.set_runtime(runtime_b)
        populated.reset_mock()
        assert router_a.subscription.closed

        router_a.emit(InvalidationEvent(
            "epoch-a", 1, (ProjectionDomain.TAGS,), (),
        ))
        router_b.emit(InvalidationEvent(
            "epoch-b", 1, (ProjectionDomain.TAGS,), (),
        ))
        app.processEvents()

        assert populated.call_count == 1
    finally:
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()
