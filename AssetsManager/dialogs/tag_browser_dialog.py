"""Tag browser dialog — browse all tags and their files in a standalone window.

Opened from the Info panel's tags section. Hosts :class:`TagTreePanel` so the
tag browser lives in its own window rather than as a main-window dock.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout

from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.dialogs.tabbed_dialog import TabbedDialog
from AssetsManager.panels.tag_tree import TagTreePanel
from AssetsManager import i18n

tr = i18n.tr


class TagBrowserDialog(TabbedDialog):
    """Floating window hosting the tag browser."""

    # Emitted with the selected file path when a file row is clicked.
    directory_selected = Signal(str)

    def __init__(self, services, parent=None):
        self._services = services
        self._tag_tree: TagTreePanel | None = None
        super().__init__(parent, title=tr("tagbrowser.title"),
                         min_size=(scaled_px(380), scaled_px(460)))

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._root_layout = layout

        self._tag_tree = TagTreePanel(self)
        self._tag_tree.set_scoped_services(self._services)
        self._tag_tree.directory_selected.connect(self._on_file_selected)
        self._root_layout.addWidget(self._tag_tree)

    def _on_file_selected(self, path: str):
        """Forward the clicked file and close the modal dialog."""
        self.directory_selected.emit(path)
        self.accept()

    def _on_dialog_closed(self):
        """Release the hosted panel's bus/subscription wiring on every close."""
        tag_tree = self._tag_tree
        self._tag_tree = None
        if tag_tree is not None:
            tag_tree.shutdown()
