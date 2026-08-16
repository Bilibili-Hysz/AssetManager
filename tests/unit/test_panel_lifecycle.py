"""D3 timer/animation lifecycle regression tests."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

import pytest


def _exercise_shutdown(panel, app):
    try:
        panel.show()
        app.processEvents()
        panel.shutdown()
        app.processEvents()
        assert getattr(panel, "_pending_timers", []) == []
    finally:
        try:
            panel.close()
        except RuntimeError:
            pass
        panel.deleteLater()
        app.processEvents()


@pytest.mark.parametrize(
    "factory",
    [
        lambda: __import__("AssetsManager.panels.info", fromlist=["InfoPanel"]).InfoPanel(),
        lambda: __import__("AssetsManager.panels.sidebar", fromlist=["SidebarPanel"]).SidebarPanel(),
        lambda: __import__("AssetsManager.panels.tag_tree", fromlist=["TagTreePanel"]).TagTreePanel(),
        lambda: __import__("AssetsManager.panels.file_list", fromlist=["FileListPanel"]).FileListPanel(),
    ],
)
def test_panel_init_show_immediate_shutdown_is_clean(factory):
    """D3 acceptance: init -> show -> immediate shutdown leaves no pending timers."""
    app = QApplication.instance() or QApplication([])
    panel = factory()
    _exercise_shutdown(panel, app)
