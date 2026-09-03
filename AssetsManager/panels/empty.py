"""Empty placeholder panel with visible border, background, and status hint."""
from __future__ import annotations

from typing import cast
from PySide6.QtWidgets import QVBoxLayout
from AssetsManager.panels.base import PanelContent
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.widgets.empty_state import EmptyStateWidget, StateKind
from AssetsManager import i18n

tr = i18n.tr


class EmptyPanel(PanelContent):
    """Fallback / placeholder panel wrapping EmptyStateWidget."""

    def __init__(self, parent=None, subtitle: str = "", *,
                 state: str = "empty", message: str = ""):
        super().__init__(parent)
        self.setMinimumHeight(scaled_px(100))
        self._widget = EmptyStateWidget(
            self,
            kind=cast(StateKind, state),
            title=message,
            subtitle=subtitle,
        )
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.addWidget(self._widget)
        self.content_layout.addLayout(col)

    def shutdown(self):
        super().shutdown()
        if hasattr(self, "_widget"):
            self._widget.shutdown()

    @classmethod
    def for_loading(cls, parent=None, subtitle: str = ""):
        """Return an EmptyPanel styled as a loading state."""
        return cls(
            parent=parent,
            subtitle=subtitle or tr("panel.loading", default="Loading…"),
            state="loading",
        )

    @classmethod
    def for_error(cls, parent=None, message: str = "", subtitle: str = ""):
        """Return an EmptyPanel styled as an error state."""
        return cls(
            parent=parent,
            subtitle=subtitle or tr(
                "panel.error.hint", default="Something went wrong"),
            state="error",
            message=message,
        )
