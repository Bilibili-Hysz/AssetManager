"""Endpoint page construction for the sharing settings dialog."""
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame

from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.widgets.stylekit import StyleKit
from AssetsManager import i18n
from AssetsManager.application.desktop_ports import ShareSettingsPort

tr = i18n.tr


class EndpointPageMixin:
    """Endpoint (overview) page: status card, tunnel card, and activity card."""

    # Widgets built by _setup_overview_tab (annotated here so the main dialog
    # and sibling pages can type-check attribute access).
    _status_frame: QFrame
    _status_icon: QLabel
    _status_label: QLabel
    _exposure_label: QLabel
    _toggle_btn: QPushButton
    _url_label: QLabel
    _copy_btn: QPushButton
    _open_btn: QPushButton
    _qr_btn: QPushButton
    _ip_info: QVBoxLayout
    _ip_info_value: QLabel
    _port_info: QVBoxLayout
    _port_info_value: QLabel
    _online_info: QVBoxLayout
    _online_info_value: QLabel
    _traffic_info: QVBoxLayout
    _traffic_info_value: QLabel
    _tunnel_status: QLabel
    _tunnel_url_label: QLabel
    _tunnel_btn: QPushButton
    _tunnel_copy_btn: QPushButton
    _tunnel_open_btn: QPushButton
    _tunnel_section: Any
    _activity_list: QLabel

    # Supplied by the main dialog / TabbedDialog.
    _sharing_port: ShareSettingsPort
    make_primary_btn: Any
    make_secondary_btn: Any
    make_muted: Any
    _on_primary_endpoint_action: Any
    _copy_link: Any
    _open_endpoint: Any
    _show_endpoint_qr: Any
    _toggle_tunnel: Any
    _copy_tunnel_url: Any
    _open_tunnel_url: Any
    _set_action_icon: Any

    def _make_card(self, title: str, icon: str = "") -> tuple[QFrame, QVBoxLayout]:
        """Create a styled dashboard card with title and return (frame, content_layout)."""
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {sk.token('panel')}; border: {scaled_px(1)}px solid {sk.token('border_subtle')}; "
            f"border-radius: {sk.px(int(sk.prop('border_radius', 'md')))}px; }}")

        outer = QVBoxLayout(frame)
        outer.setContentsMargins(scaled_px(16), scaled_px(14), scaled_px(16), scaled_px(14))
        outer.setSpacing(scaled_px(10))

        header = QLabel(f"{icon}  {title}" if icon else title)
        header.setStyleSheet(sk.label_css("heading", size=13, bold=True) + "QLabel { border: none; }")
        outer.addWidget(header)

        # Register for theme refresh (audit B2⑥) — widget-level sheets here
        # do not follow the app stylesheet automatically.
        if not hasattr(self, "_endpoint_card_frames"):
            self._endpoint_card_frames = []
            self._endpoint_card_headers = []
        self._endpoint_card_frames.append(frame)
        self._endpoint_card_headers.append(header)

        content = QVBoxLayout()
        content.setSpacing(scaled_px(8))
        outer.addLayout(content)

        return frame, content

    def _setup_overview_tab(self, parent):
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(scaled_px(16), scaled_px(16), scaled_px(16), scaled_px(16))
        layout.setSpacing(scaled_px(12))

        self._status_frame = QFrame()
        endpoint_layout = QVBoxLayout(self._status_frame)
        endpoint_layout.setContentsMargins(scaled_px(16), scaled_px(16), scaled_px(16), scaled_px(16))
        endpoint_layout.setSpacing(scaled_px(10))
        status_row = QHBoxLayout()
        self._status_icon = QLabel()
        self._status_icon.setFixedSize(scaled_px(12), scaled_px(12))
        self._status_icon.setAccessibleName(tr("sharing.endpoint.status_indicator"))
        status_row.addWidget(self._status_icon)
        self._status_label = QLabel(tr("sharing.status_off"))
        self._status_label.setStyleSheet(sk.label_css("heading", size=20, bold=True))
        status_row.addWidget(self._status_label)
        self._exposure_label = QLabel()
        self._exposure_label.setVisible(False)
        status_row.addWidget(self._exposure_label)
        status_row.addStretch()
        self._toggle_btn = self.make_primary_btn(tr("sharing.btn_start_sharing"), self._on_primary_endpoint_action)
        self._set_action_icon(self._toggle_btn, "share")
        status_row.addWidget(self._toggle_btn)
        endpoint_layout.addLayout(status_row)

        self._url_label = QLabel()
        self._url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._url_label.setWordWrap(False)
        self._url_label.setStyleSheet(sk.label_css("accent", size=15))
        endpoint_layout.addWidget(self._url_label)
        action_row = QHBoxLayout()
        self._copy_btn = self.make_secondary_btn(tr("sharing.btn_copy_link"), self._copy_link)
        self._set_action_icon(self._copy_btn, "copy")
        self._open_btn = self.make_secondary_btn(tr("sharing.btn_open"), self._open_endpoint)
        self._set_action_icon(self._open_btn, "arrow_right")
        self._qr_btn = self.make_secondary_btn(tr("sharing.qr.show"), self._show_endpoint_qr)
        self._set_action_icon(self._qr_btn, "qr_code")
        action_row.addWidget(self._copy_btn)
        action_row.addWidget(self._open_btn)
        action_row.addWidget(self._qr_btn)
        action_row.addStretch()
        endpoint_layout.addLayout(action_row)
        metadata_row = QHBoxLayout()
        metadata_row.setSpacing(scaled_px(24))
        self._ip_info, self._ip_info_value = self._make_info_pair(tr("sharing.overview.ip_address"), "—")
        self._port_info, self._port_info_value = self._make_info_pair(tr("sharing.overview.port"), "—")
        self._online_info, self._online_info_value = self._make_info_pair(tr("sharing.endpoint.connections"), "0")
        self._traffic_info, self._traffic_info_value = self._make_info_pair(tr("sharing.overview.traffic"), "0 B")
        for info in (self._ip_info, self._port_info, self._online_info, self._traffic_info):
            metadata_row.addLayout(info)
        metadata_row.addStretch()
        endpoint_layout.addLayout(metadata_row)
        layout.addWidget(self._status_frame)

        # Tunnel remains an independent exposure control; it never stops local sharing.
        if self._sharing_port.tunnel_is_available():
            tunnel_card, tunnel_cl = self._make_card(tr("sharing.card_tunnel"))
            self._tunnel_status = self.make_muted(tr("sharing.tunnel_not_connected"))
            tunnel_cl.addWidget(self._tunnel_status)
            self._tunnel_url_label = QLabel("")
            self._tunnel_url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._tunnel_url_label.setVisible(False)
            tunnel_cl.addWidget(self._tunnel_url_label)
            tunnel_btn_row = QHBoxLayout()
            self._tunnel_btn = self.make_primary_btn(tr("sharing.btn_start_tunnel"), self._toggle_tunnel)
            self._set_action_icon(self._tunnel_btn, "share")
            self._tunnel_copy_btn = self.make_secondary_btn(tr("sharing.btn_copy"), self._copy_tunnel_url)
            self._set_action_icon(self._tunnel_copy_btn, "copy")
            self._tunnel_copy_btn.setVisible(False)
            self._tunnel_open_btn = self.make_secondary_btn(tr("sharing.btn_open"), self._open_tunnel_url)
            self._set_action_icon(self._tunnel_open_btn, "arrow_right")
            self._tunnel_open_btn.setVisible(False)
            tunnel_btn_row.addWidget(self._tunnel_btn)
            tunnel_btn_row.addWidget(self._tunnel_copy_btn)
            tunnel_btn_row.addWidget(self._tunnel_open_btn)
            tunnel_btn_row.addStretch()
            tunnel_cl.addLayout(tunnel_btn_row)
            layout.addWidget(tunnel_card)
        else:
            self._tunnel_section = None

        activity_card, activity_cl = self._make_card(tr("sharing.card_recent_activity"))
        self._activity_list = QLabel(tr("sharing.overview.no_activity"))
        self._activity_list.setWordWrap(True)
        self._activity_list.setStyleSheet(sk.muted_css(11))
        activity_cl.addWidget(self._activity_list)
        self._apply_endpoint_theme()
        layout.addWidget(activity_card)
        layout.addStretch()

    def _make_info_pair(self, label_text, value_text):
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        layout = QVBoxLayout()
        layout.setSpacing(scaled_px(2))
        lbl = QLabel(label_text)
        lbl.setStyleSheet(sk.muted_css(10))
        val = QLabel(value_text)
        val.setStyleSheet(sk.label_css("heading", size=12, bold=True))
        layout.addWidget(lbl)
        layout.addWidget(val)
        if not hasattr(self, "_endpoint_info_labels"):
            self._endpoint_info_labels = []
            self._endpoint_value_labels = []
        self._endpoint_info_labels.append(lbl)
        self._endpoint_value_labels.append(val)
        return layout, val

    def _apply_endpoint_theme(self):
        """Re-derive widget-level overview styles from current tokens (B2⑥)."""
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        card_qss = (
            f"QFrame {{ background: {sk.token('panel')}; border: {scaled_px(1)}px solid {sk.token('border_subtle')}; "
            f"border-radius: {sk.px(int(sk.prop('border_radius', 'md')))}px; }}")
        header_qss = sk.label_css("heading", size=13, bold=True) + "QLabel { border: none; }"
        for frame in getattr(self, "_endpoint_card_frames", []):
            try:
                frame.setStyleSheet(card_qss)
            except RuntimeError:
                pass
        for header in getattr(self, "_endpoint_card_headers", []):
            try:
                header.setStyleSheet(header_qss)
            except RuntimeError:
                pass
        for lbl in getattr(self, "_endpoint_info_labels", []):
            try:
                lbl.setStyleSheet(sk.muted_css(10))
            except RuntimeError:
                pass
        for val in getattr(self, "_endpoint_value_labels", []):
            try:
                val.setStyleSheet(sk.label_css("heading", size=12, bold=True))
            except RuntimeError:
                pass
        activity = getattr(self, "_activity_list", None)
        if activity is not None:
            try:
                activity.setStyleSheet(sk.muted_css(11))
            except RuntimeError:
                pass
