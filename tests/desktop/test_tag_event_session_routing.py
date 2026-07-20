import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from AssetsManager.domain.events import (
    AssetNotesChanged, AssetTagsChanged, AssetUrlsChanged, TagCatalogChanged,
)
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
