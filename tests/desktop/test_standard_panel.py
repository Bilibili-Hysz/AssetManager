"""Unit tests for StandardPanel slot-based scaffolding."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLabel
from AssetsManager.panels.base import StandardPanel


class DummyPanel(StandardPanel):
    pass


def test_standard_panel_slots():
    app = QApplication.instance() or QApplication([])
    panel = DummyPanel()
    panel.resize(300, 400)

    header = QLabel("Header Content")
    toolbar = QLabel("Toolbar Content")
    body = QLabel("Body Content")
    footer = QLabel("Footer Content")

    panel.set_header(header)
    panel.set_toolbar(toolbar)
    panel.set_body(body)
    panel.set_footer(footer)

    panel.show()
    app.processEvents()
    try:
        assert panel._header_widget is header
        assert panel._toolbar_widget is toolbar
        assert panel._body_widget is body
        assert panel._footer_widget is footer
        assert header.isVisible()
        assert toolbar.isVisible()
        assert body.isVisible()
        assert footer.isVisible()
    finally:
        panel.close()
        panel.deleteLater()
        app.processEvents()


def test_standard_panel_state_overlay():
    app = QApplication.instance() or QApplication([])
    panel = DummyPanel()
    panel.resize(300, 400)

    body = QLabel("Main Body Content")
    panel.set_body(body)
    panel.show()
    app.processEvents()
    try:
        assert body.isVisible()

        panel.show_state(kind="loading", title="Fetching assets...")
        app.processEvents()
        assert not body.isVisible()
        assert panel._state_overlay is not None
        assert panel._state_overlay.isVisible()

        panel.clear_state()
        app.processEvents()
        assert body.isVisible()
        assert not panel._state_overlay.isVisible()
    finally:
        panel.close()
        panel.deleteLater()
        app.processEvents()
