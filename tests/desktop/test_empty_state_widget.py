"""Unit tests for EmptyStateWidget."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from AssetsManager.widgets.empty_state import EmptyStateWidget
from AssetsManager.core.signal_bus import get as bus


def test_empty_state_widget_render():
    app = QApplication.instance() or QApplication([])
    widget = EmptyStateWidget(kind="empty")
    widget.show()
    app.processEvents()
    try:
        labels = widget.findChildren(QLabel)
        texts = [lb.text() for lb in labels]
        assert any("Empty" in t or "No selection" in t for t in texts)
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()


def test_empty_state_widget_custom_text_and_action():
    app = QApplication.instance() or QApplication([])
    clicked = []

    def on_click():
        clicked.append(True)

    widget = EmptyStateWidget(
        kind="search",
        title="No items found",
        subtitle="Try different keywords",
        action_text="Clear Filter",
        on_action=on_click,
    )
    widget.show()
    app.processEvents()
    try:
        labels = widget.findChildren(QLabel)
        texts = [lb.text() for lb in labels]
        assert "No items found" in texts
        assert "Try different keywords" in texts

        buttons = widget.findChildren(QPushButton)
        assert len(buttons) == 1
        assert buttons[0].text() == "Clear Filter"
        assert buttons[0].isVisible()

        buttons[0].click()
        assert len(clicked) == 1
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()


def test_empty_state_widget_theme_reaction():
    app = QApplication.instance() or QApplication([])
    widget = EmptyStateWidget(kind="directory")
    widget.show()
    app.processEvents()
    try:
        # Trigger bus theme change
        bus().theme_changed.emit("Slate")
        app.processEvents()
        # Ensure widget is still rendered without error
        assert widget.isVisible()
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()
