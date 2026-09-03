"""Shared plugin-manager UI components (audit I5, finding D6).

A single canonical implementation of the plugin card and detail panel,
consumed by both the standalone :class:`PluginManagerDialog` and the
embeddable :class:`PluginManagerWidget` (settings tab). Before this module
existed the two hosts carried near-copies that had drifted apart (dot
policy, toggle size, click semantics, detail fields).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from AssetsManager.core import themes
from AssetsManager.core import icons
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.plugins.descriptor import (
    PLUGIN_STATE_ACTIVE,
    PLUGIN_STATE_DISABLED,
    PLUGIN_STATE_ERROR,
    PLUGIN_STATE_LOADABLE,
    PLUGIN_STATE_LOADED,
)
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.widgets.elevation import apply_elevation
from AssetsManager.widgets.stylekit import StyleKit
from AssetsManager import i18n

tr = i18n.tr


# ── Plugin card widget ────────────────────────────────────────

class PluginCard(QFrame):
    """A single plugin card with status, toggle, and click-to-select."""

    clicked = Signal(str)  # plugin_id

    def __init__(self, plugin_id: str, name: str, version: str,
                 description: str, state: str, enabled: bool, parent=None):
        super().__init__(parent)
        self._plugin_id = plugin_id
        self._enabled = enabled
        self._state = state
        self._selected = False
        self._name = name
        self._version = version
        self._description = description

        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._layout = QHBoxLayout(self)

        # Status indicator (colored dot)
        self._status_dot = QLabel()
        self._layout.addWidget(self._status_dot, 0, Qt.AlignmentFlag.AlignVCenter)

        # Plugin info (name + description)
        self._info_layout = QVBoxLayout()

        self._name_label = QLabel(name)
        self._info_layout.addWidget(self._name_label)

        desc_text = description[:60] + ("..." if len(description) > 60 else "") if description else plugin_id
        self._desc_label = QLabel(desc_text)
        self._info_layout.addWidget(self._desc_label)

        self._layout.addLayout(self._info_layout, 1)

        # Version badge
        self._version_label = QLabel(f"v{version}" if version else "")
        self._layout.addWidget(self._version_label, 0, Qt.AlignmentFlag.AlignVCenter)

        # Toggle button
        self._toggle = QToolButton()
        self._toggle.setCheckable(True)
        self._toggle.setChecked(enabled)
        self._toggle.setAccessibleName(tr("plugins.toggle", default="Toggle Enabled"))
        self._toggle.setToolTip(tr("plugins.toggle", default="Toggle Enabled"))
        self._toggle.toggled.connect(self._on_toggle)
        self._layout.addWidget(self._toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        self.refresh_presentation()

    def refresh_presentation(self):
        t = themes.get()
        self.setFixedHeight(scaled_px(72))
        br_sm = scaled_px(int(themes.prop("border_radius", "sm")))
        sp_xs = scaled_px(int(themes.prop("spacing", "xs")))
        sp_md = scaled_px(int(themes.prop("spacing", "md")))
        self._layout.setContentsMargins(sp_md, scaled_px(int(themes.prop("spacing", "sm"))), sp_md, scaled_px(int(themes.prop("spacing", "sm"))))
        self._layout.setSpacing(sp_md)
        self._info_layout.setSpacing(scaled_px(2))
        self._status_dot.setFixedSize(scaled_px(10), scaled_px(10))
        self._name_label.setStyleSheet(
            f"font-size: {scaled_pt(int(themes.prop('font_size', 'md')))}px; font-weight: bold; color: {themes.color('heading')}; background: transparent; border: none;")
        self._desc_label.setStyleSheet(
            f"font-size: {scaled_pt(int(themes.prop('font_size', 'sm')))}px; color: {themes.color('muted')}; background: transparent; border: none;")
        self._version_label.setStyleSheet(
            f"font-size: {scaled_pt(int(themes.prop('font_size', 'sm')))}px; color: {themes.color('muted')}; background: {themes.color('header')}; "
            f"border: {scaled_px(1)}px solid {themes.color('border_subtle') or alpha(themes.color('border'), 0.5)}; border-radius: {br_sm}px; "
            f"padding: {sp_xs}px {scaled_px(int(themes.prop('spacing', 'sm')))}px;")
        self._toggle.setFixedSize(scaled_px(44), scaled_px(24))
        self._update_dot()
        self._update_style(t)
        self._update_toggle_style(t)

    def _update_dot(self):
        t = themes.get()
        if self._state == PLUGIN_STATE_ERROR:
            color = t["danger"]
        elif self._state in (PLUGIN_STATE_ACTIVE, PLUGIN_STATE_LOADED):
            color = t["success"]
        elif self._state == PLUGIN_STATE_LOADABLE:
            # Loadable but enabled: treated as running, so use the green
            # indicator; otherwise fall back to the neutral muted dot.
            color = t["success"] if self._enabled else t["muted"]
        else:
            color = t["muted"]
        self._status_dot.setStyleSheet(
            f"background: {color}; border-radius: {scaled_px(int(themes.prop('border_radius', 'sm')))}px; border: none;"
        )

    def _update_toggle_style(self, _t):
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        self._toggle.setStyleSheet(sk.switch_css())
        self._toggle.setAccessibleName(
            f"{self._name} — {tr('plugins.disable' if self._toggle.isChecked() else 'plugins.enable', default='Toggle Enabled')}"
        )

    def _update_style(self, t):
        br_md = scaled_px(int(themes.prop("border_radius", "md")))
        border_subtle = t.get("border_subtle", alpha(t["border"], 0.5))
        hover_bg = alpha(t["hover_overlay"], themes.prop("opacity", "hover"))
        if self._selected:
            self.setStyleSheet(
                f"PluginCard {{ background: {alpha(themes.color('accent'), 0.13)}; border: {scaled_px(1)}px solid {themes.color('accent')}; "
                f"border-radius: {br_md}px; }}"
            )
        else:
            self.setStyleSheet(
                f"PluginCard {{ background: {themes.color('panel')}; border: {scaled_px(1)}px solid {border_subtle}; "
                f"border-radius: {br_md}px; }}"
                f"PluginCard:hover {{ border-color: {alpha(themes.color('accent'), 0.5)}; background: {hover_bg}; }}"
            )

    def set_selected(self, selected: bool):
        t = themes.get()
        self._selected = selected
        self._update_style(t)

    def _on_toggle(self, checked: bool):
        self._enabled = checked
        self.clicked.emit(self._plugin_id)

    def mouseReleaseEvent(self, event):
        # Make the whole card body clickable. Child widgets (e.g. the toggle
        # button) accept their own mouse events, so they never propagate here
        # and cannot cause a duplicate emission.
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._plugin_id)
        super().mouseReleaseEvent(event)

    @property
    def plugin_id(self) -> str:
        return self._plugin_id

    @property
    def is_enabled(self) -> bool:
        return self._toggle.isChecked()


# ── Detail panel ──────────────────────────────────────────────

class PluginDetailPanel(QWidget):
    """Right-side detail panel showing plugin info and actions."""

    toggle_requested = Signal(str, bool)  # plugin_id, enable

    def __init__(self, parent=None):
        super().__init__(parent)
        # E2 Floating: persistent raised panel (unified depth ladder,
        # design-language-unification-2026-09-03, P0-4).
        apply_elevation(self, level=2)
        self._layout = QVBoxLayout(self)

        # Plugin name header
        self._name_label = QLabel(tr("plugins.select_hint", default="Select a plugin"))
        self._name_label.setWordWrap(True)
        self._layout.addWidget(self._name_label)

        # Status badge
        self._status_badge = QLabel("")
        self._layout.addWidget(self._status_badge)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        self._separator = sep
        self._layout.addWidget(sep)

        # Info fields
        self._fields_widget = QWidget()
        self._fields_layout = QVBoxLayout(self._fields_widget)
        self._fields_layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self._fields_widget)

        # Description
        self._desc_label = QLabel("")
        self._desc_label.setWordWrap(True)
        self._layout.addWidget(self._desc_label)

        # Diagnostics (error messages)
        self._diag_label = QLabel("")
        self._diag_label.setWordWrap(True)
        self._diag_label.setVisible(False)
        self._layout.addWidget(self._diag_label)

        self._layout.addStretch()

        # Action buttons
        self._button_layout = QHBoxLayout()

        self._toggle_btn = QPushButton(tr("plugins.toggle", default="Toggle Enabled"))
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setAccessibleName(tr("plugins.toggle", default="Toggle Enabled"))
        self._toggle_btn.clicked.connect(self._on_toggle)
        self._button_layout.addWidget(self._toggle_btn)

        self._layout.addLayout(self._button_layout)

        self._current_pid = None
        self._current_enabled = False
        self.refresh_presentation()

    def refresh_presentation(self):
        t = themes.get()
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        br_sm = scaled_px(int(themes.prop("border_radius", "sm")))
        sp_sm = scaled_px(int(themes.prop("spacing", "sm")))
        sp_lg = scaled_px(int(themes.prop("spacing", "lg")))
        self._layout.setContentsMargins(sp_lg, sp_lg, sp_lg, sp_lg)
        self._layout.setSpacing(scaled_px(int(themes.prop("spacing", "md"))))
        self._fields_layout.setSpacing(scaled_px(6))
        self._button_layout.setSpacing(sp_sm)
        self._name_label.setStyleSheet(sk.label_css("heading", size=18, bold=True))
        self._separator.setStyleSheet(f"color: {sk.token('border_subtle')};")
        self._desc_label.setStyleSheet(sk.label_css("body", size=12))
        danger = t["danger"]
        self._diag_label.setStyleSheet(
            f"font-size: {scaled_pt(int(themes.prop('font_size', 'sm')))}px; color: {danger}; background: {alpha(danger, 0.08)}; "
            f"border: {scaled_px(1)}px solid {alpha(danger, 0.19)}; border-radius: {br_sm}px; padding: {sp_sm}px;")
        self._toggle_btn.setStyleSheet(
            sk.button_css("primary", font_size_key="sm",
                          padding_y=sp_sm, padding_x=sp_lg))
        self._update_toggle_text()

    def show_plugin(self, plugin_id: str, record):
        """Display plugin details."""
        self._current_pid = plugin_id
        desc = record.descriptor
        t = themes.get()

        # Name
        name = desc.name if desc else plugin_id
        self._name_label.setText(name)

        # Status badge
        state = record.state
        if state == PLUGIN_STATE_ERROR:
            badge_text = tr("plugins.state.error", default="Error")
            badge_color = t["danger"]
        elif state in (PLUGIN_STATE_ACTIVE, PLUGIN_STATE_LOADED):
            badge_text = tr("plugins.state.active", default="Active")
            badge_color = t["success"]
        elif state == PLUGIN_STATE_DISABLED:
            badge_text = tr("plugins.state.disabled", default="Disabled")
            badge_color = t["muted"]
        else:
            badge_text = tr("plugins.state.loadable", default="Loadable")
            badge_color = t["muted"]

        self._status_badge.setText(badge_text)
        br_sm = scaled_px(int(themes.prop("border_radius", "sm")))
        sp_xs = scaled_px(int(themes.prop("spacing", "xs")))
        self._status_badge.setStyleSheet(
            f"font-size: {scaled_pt(int(themes.prop('font_size', 'sm')))}px; font-weight: bold; color: {themes.color('on_accent')}; "
            f"background: {badge_color}; border-radius: {br_sm}px; "
            f"padding: {sp_xs}px {scaled_px(int(themes.prop('spacing', 'sm')))}px;"
        )

        # Fields
        self._clear_fields()
        if desc:
            self._add_field(tr("plugins.detail.id"), desc.id)
            self._add_field(tr("plugins.detail.version"), desc.version)
            if desc.description:
                self._add_field(tr("plugins.detail.description"), desc.description)
            if getattr(desc, "author", ""):
                self._add_field(tr("plugins.field.author", default="Author"), desc.author)
            self._add_field(tr("plugins.detail.kind"), desc.kind)
            if desc.permissions:
                self._add_field(tr("plugins.detail.permissions"), ", ".join(sorted(desc.permissions)))
            if desc.display_fields:
                fields = [f"{df.key} ({df.type})" for df in desc.display_fields]
                self._add_field(tr("plugins.detail.display_fields"), ", ".join(fields))
        self._add_field(tr("plugins.detail.root"), record.root_dir or "-")

        # Description
        if desc and desc.description:
            self._desc_label.setText(desc.description)
            self._desc_label.setVisible(True)
        else:
            self._desc_label.setVisible(False)

        # Diagnostics
        if record.diagnostics:
            diag_lines = [f"[{d.level}] {d.code}: {d.message}" for d in record.diagnostics]
            self._diag_label.setText("\n".join(diag_lines))
            self._diag_label.setVisible(True)
        else:
            self._diag_label.setVisible(False)

        # Toggle button
        self._current_enabled = record.enabled
        self._update_toggle_text()

    def _add_field(self, label: str, value: str):
        fs_sm = scaled_pt(int(themes.prop("font_size", "sm")))
        row = QHBoxLayout()
        row.setSpacing(scaled_px(int(themes.prop("spacing", "sm"))))

        lbl = QLabel(f"{label}:")
        lbl.setStyleSheet(
            f"font-size: {fs_sm}px; font-weight: bold; color: {themes.color('muted')}; "
            f"background: transparent; border: none; min-width: {scaled_px(80)}px;"
        )
        row.addWidget(lbl)

        val = QLabel(str(value))
        val.setStyleSheet(
            f"font-size: {fs_sm}px; color: {themes.color('heading')}; background: transparent; border: none;"
        )
        val.setWordWrap(True)
        row.addWidget(val, 1)

        container = QWidget()
        container.setLayout(row)
        container.setStyleSheet("background: transparent;")
        self._fields_layout.addWidget(container)

    def _clear_fields(self):
        while self._fields_layout.count():
            item = self._fields_layout.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.deleteLater()

    def _update_toggle_text(self):
        if self._current_enabled:
            label = tr("plugins.disable", default="Disable")
            icon_name = "close"
        else:
            label = tr("plugins.enable", default="Enable")
            icon_name = "check"
        self._toggle_btn.setText(label)
        self._toggle_btn.setIcon(
            icons.icon(icon_name, color="icon_on_accent", size=scaled_px(15)))
        self._toggle_btn.setIconSize(QSize(scaled_px(15), scaled_px(15)))
        self._toggle_btn.setAccessibleName(label)
        self._toggle_btn.setToolTip(label)

    def _on_toggle(self):
        if self._current_pid:
            self._current_enabled = not self._current_enabled
            self._update_toggle_text()
            self.toggle_requested.emit(self._current_pid, self._current_enabled)
