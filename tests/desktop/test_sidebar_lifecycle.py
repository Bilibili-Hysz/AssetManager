import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

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
