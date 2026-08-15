"""Presentation-side sharing contracts shared by the LAN mixin and dialog.

Holding the setting classification and security confirmation helper here
(imported by both ``widgets/lan_sharing.py`` and
``dialogs/sharing_settings_dialog.py``) removes the bidirectional import
between those two modules while keeping every presentation module free of
direct ``AssetsManager.lan`` imports.
"""
from __future__ import annotations

import logging

from PySide6.QtWidgets import QMessageBox, QWidget
from AssetsManager import i18n
from AssetsManager.core.constants import DEFAULT_LAN_THEME_COLOR

tr = i18n.tr
_log = logging.getLogger(__name__)

# These settings are passed through to LanServer.reload_settings without a
# server restart. Configuration presentation imports this declaration so its
# impact summary cannot drift from the lifecycle owner.
HOT_SHARING_SETTINGS = {
    "lan_share_name": "share_name",
    "lan_blur_tags": "blur_tags",
    "lan_theme_color": "theme_color",
    "lan_welcome_msg": "welcome_msg",
    "lan_footer_text": "footer_text",
    "lan_show_hidden": "show_hidden",
    "lan_max_depth": "max_depth",
    "lan_include_types": "include_types",
    "lan_exclude_patterns": "exclude_patterns",
}
HOT_SHARING_DEFAULTS = {
    "lan_share_name": "AssetManager", "lan_blur_tags": [], "lan_theme_color": DEFAULT_LAN_THEME_COLOR,
    "lan_welcome_msg": "", "lan_footer_text": "", "lan_show_hidden": False,
    "lan_max_depth": 0, "lan_include_types": None, "lan_exclude_patterns": None,
}
RESTART_SHARING_SETTINGS = frozenset({
    "lan_port", "lan_bind", "lan_auth_mode", "lan_password", "lan_access_key",
    "lan_rate_limit", "lan_blocked_ips", "lan_ip_whitelist", "lan_ssl_cert", "lan_ssl_key",
})
_CONFIRMABLE_SECURITY_REASONS = frozenset({
    "share_safety_ack_required",
    "bind_scope_expanded",
    "authentication_removed",
    "trusted_network_confirmation_required",
})
_SECURITY_REASON_KEYS = {
    "share_safety_ack_required": "sharing.security.reason_ack_required",
    "bind_scope_expanded": "sharing.security.reason_bind_scope_expanded",
    "authentication_removed": "sharing.security.reason_authentication_removed",
    "trusted_network_confirmation_required": "sharing.security.reason_trusted_required",
}


def _security_blocked_message(reason: str) -> str:
    reason_key = _SECURITY_REASON_KEYS.get(reason)
    reason_text = tr(reason_key) if reason_key else tr("sharing.security.reason_generic")
    return tr("sharing.security.blocked_message", reason=reason_text)


def confirm_security_preflight(
    parent: QWidget | None,
    *,
    settings,
    preflight,
    snapshot,
    bind: str | None,
    auth_status,
) -> bool:
    """Ask for an explicit user decision and atomically persist it.

    This is deliberately the only UI-facing confirmation helper.  It never
    starts a server; callers must re-run the pure preflight snapshot after a
    successful commit and only then enter the lifecycle path.
    """
    from AssetsManager.application.security_preflight import effective_auth, is_lan_bind

    reason = getattr(snapshot, "failure_reason", None)
    if reason not in _CONFIRMABLE_SECURITY_REASONS:
        return False

    auth = effective_auth(auth_status)
    if is_lan_bind(bind) and not auth["enabled"]:
        title_key = "sharing.security.confirm_trusted_title"
        message_key = "sharing.security.confirm_trusted_message"
        confirm_decision = preflight.confirm_trusted_lan
    elif is_lan_bind(bind):
        title_key = "sharing.security.confirm_authenticated_title"
        message_key = "sharing.security.confirm_authenticated_message"
        confirm_decision = preflight.confirm_authenticated_lan
    else:
        title_key = "sharing.security.confirm_local_title"
        message_key = "sharing.security.confirm_local_message"
        confirm_decision = preflight.confirm_authenticated_lan

    # Do not mutate confirmation state until the user explicitly accepts.
    decision = QMessageBox.question(
        parent,
        tr(title_key),
        tr(message_key),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if decision != QMessageBox.StandardButton.Yes:
        preflight.cancel()
        return False

    confirm_decision()
    committer = getattr(settings, "commit_share_safety_confirmation", None)
    persisted = False
    if callable(committer):
        try:
            persisted = bool(
                committer(
                    preflight.ack_version,
                    preflight.trusted_network_confirmed,
                )
            )
        except Exception:
            _log.exception("Unable to persist LAN security confirmation")
            persisted = False

    if not persisted:
        preflight.cancel()
        QMessageBox.warning(
            parent,
            tr("sharing.security.persist_failed_title"),
            tr("sharing.security.persist_failed_message"),
        )
        return False
    return True
