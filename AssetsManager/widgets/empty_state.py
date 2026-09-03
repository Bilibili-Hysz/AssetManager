"""EmptyStateWidget — reusable vector empty/loading/error placeholder for desktop.

Aligns with the Dark Archive design philosophy established for the project,
providing unified iconography, typography, and action handling across panels
and dialogs.
"""
from __future__ import annotations

from typing import Callable, Literal
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton

from AssetsManager import i18n
from AssetsManager.core import icons, themes
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.widgets.stylekit import StyleKit

tr = i18n.tr

StateKind = Literal["directory", "search", "offline", "empty", "loading", "error"]

_STATE_SPECS: dict[str, tuple[str, str, str, str, str]] = {
    # kind: (icon_name, icon_semantic_color, title_color, default_title_key, default_subtitle_key)
    "directory": ("folder", "icon_muted", "heading", "panel.empty", "panel.empty.hint"),
    "search":    ("search", "icon_muted", "heading", "filelist.search_no_results", "sidebar.empty_hint"),
    "offline":   ("close",  "danger",     "danger",  "panel.error", "panel.error.hint"),
    "empty":     ("folder", "icon_muted", "heading", "panel.empty", "panel.empty.hint"),
    "loading":   ("clock",  "icon_accent","accent",   "panel.loading", ""),
    "error":     ("close",  "danger",     "danger",  "panel.error", "panel.error.hint"),
}


class EmptyStateWidget(QWidget):
    """Reusable empty/loading/error state placeholder widget."""

    action_clicked = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        kind: StateKind = "empty",
        title: str = "",
        subtitle: str = "",
        action_text: str = "",
        on_action: Callable[[], None] | None = None,
    ):
        super().__init__(parent)
        self._kind: StateKind = kind if kind in _STATE_SPECS else "empty"
        self._title_override = title
        self._subtitle_override = subtitle
        self._action_text = action_text
        self._on_action = on_action
        self._bus_connections: list[tuple] = []

        self._init_ui()
        self._connect_lifecycle()
        self._apply_theme()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(scaled_px(16), scaled_px(16), scaled_px(16), scaled_px(16))
        layout.setSpacing(scaled_px(8))
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # ── Icon ───────────────────────────────────────────────
        self._icon_label = QLabel(self)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._icon_label, 0, Qt.AlignmentFlag.AlignCenter)

        # ── Title ──────────────────────────────────────────────
        self._title_label = QLabel(self)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setWordWrap(True)
        layout.addWidget(self._title_label, 0, Qt.AlignmentFlag.AlignCenter)

        # ── Subtitle ───────────────────────────────────────────
        self._subtitle_label = QLabel(self)
        self._subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle_label.setWordWrap(True)
        layout.addWidget(self._subtitle_label, 0, Qt.AlignmentFlag.AlignCenter)

        # ── Action Button ──────────────────────────────────────
        self._action_btn = QPushButton(self)
        self._action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        themes.set_button_variant(self._action_btn, "secondary")
        self._action_btn.clicked.connect(self._handle_action)
        self._action_btn.hide()
        layout.addWidget(self._action_btn, 0, Qt.AlignmentFlag.AlignCenter)

    def _connect_lifecycle(self) -> None:
        def _connect(signal, slot):
            signal.connect(slot)
            self._bus_connections.append((signal, slot))

        _connect(bus().theme_changed, self._on_theme_changed)
        _connect(bus().language_changed, self._on_language_changed)
        _connect(bus().ui_scale_changed, self._on_ui_scale_changed)

    def shutdown(self) -> None:
        """Disconnect lifecycle bus signals to prevent leaks."""
        for sig, slot in self._bus_connections:
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._bus_connections.clear()

    def set_state(
        self,
        kind: StateKind = "empty",
        title: str = "",
        subtitle: str = "",
        action_text: str = "",
        on_action: Callable[[], None] | None = None,
    ) -> None:
        """Update the presentation state."""
        self._kind = kind if kind in _STATE_SPECS else "empty"
        self._title_override = title
        self._subtitle_override = subtitle
        if action_text or on_action:
            self._action_text = action_text
            self._on_action = on_action
        self._apply_theme()

    def _handle_action(self) -> None:
        self.action_clicked.emit()
        if self._on_action is not None:
            self._on_action()

    def _on_theme_changed(self, _name: str = "") -> None:
        self._apply_theme()

    def _on_language_changed(self, _lang: str = "") -> None:
        self._apply_theme()

    def _on_ui_scale_changed(self, _scale: float = 1.0) -> None:
        self._apply_theme()

    def _apply_theme(self) -> None:
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        icon_name, icon_color, title_color, def_title_key, def_sub_key = _STATE_SPECS[self._kind]

        icon_size = scaled_px(44)
        self._icon_label.setPixmap(
            icons.icon(icon_name, color=icon_color, size=icon_size).pixmap(QSize(icon_size, icon_size))
        )

        title_text = self._title_override or tr(def_title_key, default="Empty")
        self._title_label.setText(title_text)
        self._title_label.setStyleSheet(sk.label_css(title_color, size=16, bold=True))

        sub_text = self._subtitle_override or (tr(def_sub_key, default="") if def_sub_key else "")
        self._subtitle_label.setText(sub_text)
        self._subtitle_label.setVisible(bool(sub_text))
        self._subtitle_label.setStyleSheet(sk.muted_css(12))

        if self._action_text:
            self._action_btn.setText(self._action_text)
            self._action_btn.setVisible(True)
        else:
            self._action_btn.setVisible(False)
