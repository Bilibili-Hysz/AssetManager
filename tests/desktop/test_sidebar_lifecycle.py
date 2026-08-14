import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTreeWidgetItem

from AssetsManager.panels.sidebar import SidebarPanel


def test_sidebar_prepare_invalidates_pending_library_search(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    panel = SidebarPanel()
    try:
        panel._library_root = str(tmp_path / "old-library")
        old_gen = panel._controller.next_search_gen()
        panel._search_timer.start()
        applied = []
        monkeypatch.setattr(
            panel,
            "_apply_preloaded_entries",
            lambda parent_path, entries: applied.append((parent_path, entries)),
        )

        panel.prepare_library_switch()
        panel._on_preload_done("query", [(panel._library_root, [])], old_gen, panel._library_root)
        panel._on_preload_done("query", [("other-root", [])], panel._controller.search_gen, "other-root")

        assert panel._search_timer.isActive() is False
        assert applied == []
    finally:
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()


def test_sidebar_treats_missing_tree_item_as_unroutable():
    assert SidebarPanel._get_vtype(None) == ""


def test_sidebar_search_counts_only_direct_matches():
    app = QApplication.instance() or QApplication([])
    panel = SidebarPanel()
    try:
        branch = QTreeWidgetItem(["Models"])
        child = QTreeWidgetItem(["hero.blend"])
        branch.addChild(child)
        panel._tree.addTopLevelItem(branch)
        panel._match_count = 0

        panel._filter_item(branch, "hero")

        # Only the directly matching child counts; the ancestor branch that is
        # kept visible for context must not inflate the match counter.
        assert panel._match_count == 1
        assert not branch.isHidden()
    finally:
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()


def test_sidebar_expand_all_persists_virtual_header_expansion():
    app = QApplication.instance() or QApplication([])
    panel = SidebarPanel()
    try:
        panel._expand_all()

        assert panel._fav_expanded is True
        assert panel._rec_expanded is True
    finally:
        # Stop any pending progressive-expand tick before destroying the panel.
        panel._expand_frontier = []
        app.processEvents()
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()


def test_sidebar_restores_section_visibility_preferences(monkeypatch):
    app = QApplication.instance() or QApplication([])

    class _Settings:
        def get(self, key, default=None):
            if key == "sidebar_depth_cfg":
                return {"show_favs": False, "show_recs": False, "show_filter": False}
            return default

    monkeypatch.setattr(
        "AssetsManager.core.settings.AppSettings.instance", classmethod(lambda _cls: _Settings())
    )
    panel = SidebarPanel()
    try:
        assert not panel._show_favs
        assert not panel._show_recs
        assert not panel._show_filter
        assert panel._search.isHidden()
    finally:
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()
