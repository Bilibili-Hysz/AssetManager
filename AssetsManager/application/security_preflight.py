"""Pure, UI-neutral contract for LAN sharing security preflight.

This module deliberately has no dependency on LanServer, ShareManager, or
any UI code.  Callers provide persisted acknowledgement data, the effective
server authentication status, and the requested bind address.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


from AssetsManager.core.settings import (
    DEFAULT_SHARE_SAFETY_ACK_VERSION,
    DEFAULT_TRUSTED_NETWORK_CONFIRMED,
    SHARE_LAST_SUCCESSFUL_AUTH_KEY,
    SHARE_LAST_SUCCESSFUL_BIND_KEY,
    SHARE_SAFETY_ACK_VERSION_KEY,
    TRUSTED_NETWORK_CONFIRMED_KEY,
)

CURRENT_SHARE_SAFETY_ACK_VERSION = 1


class ShareState(str, Enum):
    OFF = "off"
    CONFIRMATION_REQUIRED = "confirmation_required"
    STARTING = "starting"
    LOCAL_ACTIVE = "local_active"
    FAILED = "failed"


class TunnelState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    PUBLIC_ACTIVE = "public_active"
    BLOCKED = "blocked"
    FAILED = "failed"


def _as_bool(value: Any, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def normalized_ack_version(value: Any) -> int:
    """Normalize persisted acknowledgement versions without inferring trust."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def settings_security_values(settings: Mapping[str, Any] | Any) -> tuple[int, bool]:
    """Read the two security fields from a mapping or AppSettings-like object."""
    if isinstance(settings, Mapping):
        ack = settings.get(SHARE_SAFETY_ACK_VERSION_KEY, DEFAULT_SHARE_SAFETY_ACK_VERSION)
        trusted = settings.get(TRUSTED_NETWORK_CONFIRMED_KEY, DEFAULT_TRUSTED_NETWORK_CONFIRMED)
    else:
        getter = getattr(settings, "get", None)
        if not callable(getter):
            return 0, False
        ack = getter(SHARE_SAFETY_ACK_VERSION_KEY, DEFAULT_SHARE_SAFETY_ACK_VERSION)
        trusted = getter(TRUSTED_NETWORK_CONFIRMED_KEY, DEFAULT_TRUSTED_NETWORK_CONFIRMED)
    return normalized_ack_version(ack), _as_bool(trusted)


def _normalized_previous_bind(value: Any) -> str | None:
    """Normalize a persisted historical bind without widening its meaning."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _normalized_previous_auth_status(value: Any) -> dict[str, Any] | None:
    """Normalize a persisted historical auth posture, failing closed on bad data."""
    if value is None:
        return None
    if isinstance(value, Mapping):
        enabled = value.get("enabled")
        mode = value.get("mode")
        if not isinstance(enabled, bool) or not isinstance(mode, str):
            return None
        return {"enabled": enabled, "mode": mode if enabled else "none"}
    if isinstance(value, (tuple, list)) and value:
        enabled = value[0]
        mode = value[1] if len(value) > 1 else "none"
        if not isinstance(enabled, bool) or not isinstance(mode, str):
            return None
        return {"enabled": enabled, "mode": mode if enabled else "none"}
    return None


def settings_security_history(
    settings: Mapping[str, Any] | Any,
) -> tuple[str | None, dict[str, Any] | None]:
    """Read the last successful LAN posture without inferring confirmation.

    The history is intentionally separate from the acknowledgement fields.  A
    missing or malformed history record means ``(None, None)``; callers may
    then apply the legacy first-start contract, but never treat malformed data
    as a successful authenticated posture.
    """
    history_getter = getattr(settings, "get_share_security_history", None)
    if callable(history_getter):
        try:
            history = history_getter()
        except Exception:
            return None, None
        if isinstance(history, (tuple, list)) and len(history) == 2:
            return (
                _normalized_previous_bind(history[0]),
                _normalized_previous_auth_status(history[1]),
            )
        return None, None

    if isinstance(settings, Mapping):
        bind = settings.get(SHARE_LAST_SUCCESSFUL_BIND_KEY)
        auth = settings.get(SHARE_LAST_SUCCESSFUL_AUTH_KEY)
    else:
        getter = getattr(settings, "get", None)
        if not callable(getter):
            return None, None
        bind = getter(SHARE_LAST_SUCCESSFUL_BIND_KEY)
        auth = getter(SHARE_LAST_SUCCESSFUL_AUTH_KEY)
    return _normalized_previous_bind(bind), _normalized_previous_auth_status(auth)


def is_lan_bind(bind: str | None) -> bool:
    """Return whether a bind value exposes the service beyond localhost."""
    value = (bind or "").strip().lower().strip("[]")
    if value in {"", "localhost", "127.0.0.1", "::1"}:
        return False
    if value in {"0.0.0.0", "::", "0:0:0:0:0:0:0:0"}:
        return True
    try:
        return not ipaddress.ip_address(value).is_loopback
    except ValueError:
        # A non-local hostname is treated as exposed; unknown values must not
        # accidentally weaken the confirmation gate.
        return True


def bind_scope_expanded(previous_bind: str | None, current_bind: str | None) -> bool:
    """Whether a request changes from localhost-only to LAN-visible."""
    return not is_lan_bind(previous_bind) and is_lan_bind(current_bind)


def effective_auth(auth_status: Any) -> dict[str, Any]:
    """Normalize the server's real auth status into a stable serializable dict.

    LanServer currently reports ``(enabled, mode)``.  Mappings and objects are
    accepted as a small compatibility convenience, but a missing status is
    always disabled (fail-closed).
    """
    enabled: Any = False
    mode: Any = "none"
    if isinstance(auth_status, Mapping):
        enabled = auth_status.get("enabled", auth_status.get("auth_enabled", False))
        mode = auth_status.get("mode", auth_status.get("auth_mode", "none"))
    elif isinstance(auth_status, (tuple, list)) and len(auth_status) >= 1:
        enabled = auth_status[0]
        if len(auth_status) >= 2:
            mode = auth_status[1]
    elif auth_status is not None:
        enabled = getattr(auth_status, "enabled", getattr(auth_status, "auth_enabled", False))
        mode = getattr(auth_status, "mode", getattr(auth_status, "auth_mode", "none"))
    enabled = _as_bool(enabled)
    mode = str(mode) if mode is not None else "none"
    return {"enabled": enabled, "mode": mode if enabled else "none"}


@dataclass(frozen=True)
class SecuritySnapshot:
    """Stable, JSON-ready view of the sharing/tunnel preflight state."""

    share_state: str
    tunnel_state: str
    effective_auth: dict[str, Any]
    confirmation_required: bool
    trusted_network_confirmed: bool
    failure_reason: str | None = None
    environment_problems: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "share_state": self.share_state,
            "tunnel_state": self.tunnel_state,
            "effective_auth": dict(self.effective_auth),
            "confirmation_required": self.confirmation_required,
            "trusted_network_confirmed": self.trusted_network_confirmed,
            "failure_reason": self.failure_reason,
        }
        if self.environment_problems:
            payload["environment_problems"] = dict(self.environment_problems)
        return payload

    def as_dict(self) -> dict[str, Any]:
        return self.to_dict()


def confirmation_failure_reason(
    *,
    ack_version: Any = 0,
    trusted_network_confirmed: Any = False,
    bind: str | None = "localhost",
    previous_bind: str | None = None,
    auth_status: Any = None,
    previous_auth_status: Any = None,
) -> str | None:
    """Return the stable reason a LAN share must be confirmed again."""
    ack = normalized_ack_version(ack_version)
    trusted = _as_bool(trusted_network_confirmed)
    auth = effective_auth(auth_status)
    previous_auth = effective_auth(previous_auth_status)
    # A confirmation is bound to this exact contract version.  Future
    # versions must not silently inherit an acknowledgement written by
    # a different contract, especially after a downgrade.
    if ack != CURRENT_SHARE_SAFETY_ACK_VERSION:
        return "share_safety_ack_required"
    if previous_bind is not None and bind_scope_expanded(previous_bind, bind):
        return "bind_scope_expanded"
    if is_lan_bind(bind) and previous_auth["enabled"] and not auth["enabled"]:
        return "authentication_removed"
    if is_lan_bind(bind) and not auth["enabled"] and not trusted:
        return "trusted_network_confirmation_required"
    return None


def probe_environment(
    *,
    port: int | None = None,
    writable_dir: str | os.PathLike[str] | None = None,
) -> dict[str, str]:
    """Probe runtime prerequisites, returning a mapping of detected problems.

    Keys are stable identifiers (``port``, ``directory``); an empty mapping
    means the probed prerequisites are available.
    """
    problems: dict[str, str] = {}
    if isinstance(port, int) and port > 0:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            problems["port"] = str(port)
        finally:
            sock.close()
    if writable_dir is not None:
        try:
            probe = tempfile.NamedTemporaryFile(
                prefix=".preflight-", dir=os.fspath(writable_dir), delete=True
            )
            probe.close()
        except (OSError, TypeError, ValueError):
            problems["directory"] = os.fspath(writable_dir)
    return problems


def preflight_snapshot(
    *,
    sharing: bool,
    bind: str | None = "localhost",
    ack_version: Any = 0,
    trusted_network_confirmed: Any = False,
    auth_status: Any = None,
    previous_bind: str | None = None,
    previous_auth_status: Any = None,
    tunnel_requested: bool = False,
    share_starting: bool = False,
    tunnel_starting: bool = False,
    environment_problems: Mapping[str, str] | None = None,
) -> SecuritySnapshot:
    """Compute the contract state without starting or stopping anything."""
    auth = effective_auth(auth_status)
    trusted = _as_bool(trusted_network_confirmed)
    problems = dict(environment_problems) if environment_problems else {}
    reason = (
        confirmation_failure_reason(
            ack_version=ack_version,
            trusted_network_confirmed=trusted,
            bind=bind,
            previous_bind=previous_bind,
            auth_status=auth,
            previous_auth_status=previous_auth_status,
        )
        if sharing
        else None
    )
    if not sharing:
        share_state = ShareState.OFF.value
    elif reason:
        share_state = ShareState.CONFIRMATION_REQUIRED.value
    elif problems:
        share_state = ShareState.FAILED.value
    elif share_starting:
        share_state = ShareState.STARTING.value
    else:
        share_state = ShareState.LOCAL_ACTIVE.value

    tunnel_reason = None
    if share_state != ShareState.LOCAL_ACTIVE.value:
        # A tunnel is only meaningful after the local share is active. Keep
        # the snapshot internally consistent when callers pass stale tunnel
        # flags while sharing is off, starting, or awaiting confirmation.
        tunnel_state = TunnelState.STOPPED.value
    else:
        if tunnel_requested and not auth["enabled"]:
            tunnel_reason = "tunnel_authentication_required"
        if tunnel_requested and tunnel_reason:
            tunnel_state = TunnelState.BLOCKED.value
        elif tunnel_starting:
            tunnel_state = TunnelState.STARTING.value
        elif tunnel_requested:
            tunnel_state = TunnelState.PUBLIC_ACTIVE.value
        else:
            tunnel_state = TunnelState.STOPPED.value

    return SecuritySnapshot(
        share_state=share_state,
        tunnel_state=tunnel_state,
        effective_auth=auth,
        confirmation_required=bool(reason),
        trusted_network_confirmed=trusted,
        failure_reason=tunnel_reason or reason,
        environment_problems=problems,
    )


class SecurityPreflight:
    """Small state holder for confirmation decisions; no service side effects."""

    def __init__(
        self,
        *,
        ack_version: Any = 0,
        trusted_network_confirmed: Any = False,
        previous_bind: str | None = None,
        previous_auth_status: Any = None,
        settings: Any = None,
    ):
        self.ack_version = normalized_ack_version(ack_version)
        self.trusted_network_confirmed = _as_bool(trusted_network_confirmed)
        self.previous_bind = _normalized_previous_bind(previous_bind)
        self.previous_auth_status = _normalized_previous_auth_status(previous_auth_status)
        # The settings reference is an optional application-layer persistence
        # handle.  The contract itself never performs I/O; lifecycle owners may
        # use it only after a real service start succeeds.
        self._settings = settings
        self.cancelled = False

    def confirm_authenticated_lan(self) -> None:
        self.ack_version = CURRENT_SHARE_SAFETY_ACK_VERSION
        self.trusted_network_confirmed = False
        self.cancelled = False

    def confirm_trusted_lan(self) -> None:
        self.ack_version = CURRENT_SHARE_SAFETY_ACK_VERSION
        self.trusted_network_confirmed = True
        self.cancelled = False

    def cancel(self) -> None:
        """Cancel this start/request without revoking persisted trust.

        The holder may have been initialized from a previously persisted
        acknowledgement.  Cancellation is a decision about the current
        operation, not a request to erase that historical decision.
        """
        self.cancelled = True

    def snapshot(self, **kwargs: Any) -> SecuritySnapshot:
        values = dict(kwargs)
        values.setdefault("previous_bind", self.previous_bind)
        values.setdefault("previous_auth_status", self.previous_auth_status)
        if self.cancelled:
            values["sharing"] = False
            values["tunnel_requested"] = False
            values["tunnel_starting"] = False
        port = values.pop("port", None)
        writable_dir = values.pop("writable_dir", None)
        if port is not None or writable_dir is not None:
            values["environment_problems"] = probe_environment(
                port=port, writable_dir=writable_dir
            )
        return preflight_snapshot(
            ack_version=self.ack_version,
            trusted_network_confirmed=self.trusted_network_confirmed,
            **values,
        )


def security_preflight_from_settings(settings: Any = None) -> SecurityPreflight:
    """Build the canonical preflight holder from persisted application state."""
    if settings is None:
        from AssetsManager.application.app_settings_provider import get_app_settings

        settings = get_app_settings()
    ack_version, trusted_network_confirmed = settings_security_values(settings)
    previous_bind, previous_auth_status = settings_security_history(settings)
    return SecurityPreflight(
        ack_version=ack_version,
        trusted_network_confirmed=trusted_network_confirmed,
        previous_bind=previous_bind,
        previous_auth_status=previous_auth_status,
        settings=settings,
    )


def persist_successful_share_security_history(
    preflight: SecurityPreflight,
    *,
    bind: str | None,
    auth_status: Any,
) -> bool | None:
    """Persist a successful effective posture when the holder owns settings.

    ``None`` means the caller supplied a detached preflight and therefore did
    not opt into application settings persistence.  ``False`` is observable
    write failure and is deliberately non-fatal to the already-running service:
    the stale history causes a safe re-confirmation on the next start.
    """
    settings = getattr(preflight, "_settings", None)
    if settings is None:
        return None
    normalized_bind = _normalized_previous_bind(bind)
    normalized_auth = effective_auth(auth_status)
    committer = getattr(settings, "commit_share_security_history", None)
    if callable(committer):
        try:
            return bool(committer(normalized_bind, normalized_auth))
        except Exception:
            return False

    setter = getattr(settings, "set_share_security_history", None)
    if not callable(setter):
        return False
    try:
        setter(normalized_bind, normalized_auth)
        result = settings.save()
    except Exception:
        return False
    return result is not False


__all__ = [
    "CURRENT_SHARE_SAFETY_ACK_VERSION",
    "SHARE_LAST_SUCCESSFUL_BIND_KEY",
    "SHARE_LAST_SUCCESSFUL_AUTH_KEY",
    "DEFAULT_SHARE_SAFETY_ACK_VERSION",
    "DEFAULT_TRUSTED_NETWORK_CONFIRMED",
    "SHARE_SAFETY_ACK_VERSION_KEY",
    "TRUSTED_NETWORK_CONFIRMED_KEY",
    "SecurityPreflight",
    "SecuritySnapshot",
    "ShareState",
    "TunnelState",
    "bind_scope_expanded",
    "confirmation_failure_reason",
    "effective_auth",
    "is_lan_bind",
    "normalized_ack_version",
    "preflight_snapshot",
    "probe_environment",
    "persist_successful_share_security_history",
    "security_preflight_from_settings",
    "settings_security_history",
    "settings_security_values",
]
