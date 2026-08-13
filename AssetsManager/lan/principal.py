"""Pure LAN session identity and capability mapping."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, SupportsFloat, SupportsInt, cast

from AssetsManager.lan.dto import UserResponse


def _as_int(value: object, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(cast(str | bytes | bytearray | SupportsInt, value))
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(cast(str | bytes | bytearray | SupportsFloat, value))
    except (TypeError, ValueError):
        return default


def _can_write(user: Mapping[str, object]) -> bool:
    """Return the persisted per-user metadata/tag write flag (default off)."""
    value = user.get("can_write", 0)
    try:
        return bool(int(cast(str | bytes | bytearray | SupportsInt, value)))
    except (TypeError, ValueError):
        return False

PrincipalKind = Literal["user", "password", "access_key", "local_ui", "guest", "share"]
PrincipalRole = Literal["admin", "user", "guest"]


@dataclass(frozen=True)
class Capabilities:
    browse: bool = False
    preview: bool = False
    download: bool = False
    upload: bool = False
    manage_links: bool = False
    manage_users: bool = False
    settings: bool = False
    realtime: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {"browse": self.browse, "preview": self.preview, "download": self.download,
                "upload": self.upload, "manage_links": self.manage_links,
                "manage_users": self.manage_users, "settings": self.settings,
                "realtime": self.realtime}


@dataclass(frozen=True)
class SessionPrincipal:
    kind: PrincipalKind
    authenticated: bool
    role: PrincipalRole
    display_name: str
    capabilities: Capabilities
    user_profile: dict[str, object] | None = None
    can_write: bool = False

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "kind": self.kind, "authenticated": self.authenticated,
            "role": self.role, "display_name": self.display_name,
            "capabilities": self.capabilities.to_dict(),
        }
        if self.kind == "user" and self.user_profile is not None:
            result["user_profile"] = dict(self.user_profile)
        return result


def _settings_get(settings: Any, key: str, default: bool) -> bool:
    if settings is None:
        try:
            from AssetsManager.core.settings import AppSettings
            settings = AppSettings.instance()
        except Exception:
            settings = None
    try:
        value = settings.get(key, default) if settings is not None else default
        return bool(value)
    except Exception:
        return default


def _guest_capabilities(settings: Any) -> Capabilities:
    return Capabilities(
        browse=_settings_get(settings, "lan_guest_list", True),
        preview=_settings_get(settings, "lan_guest_preview", True),
        download=_settings_get(settings, "lan_guest_download", False),
        realtime=False,
    )


def principal_for_request(kind: PrincipalKind, *, user: Mapping[str, object] | None = None,
                          settings: Any = None) -> SessionPrincipal:
    """Build a principal from an explicit auth kind; credentials are never accepted."""
    # ``upload`` is intentionally False for every principal: the capability is
    # retired (gap G4-1) — no upload endpoint exists, so no identity may claim
    # it.  Keeping the field (always False) preserves the public capabilities
    # shape while removing the former admin ``upload: True`` false promise.
    all_caps = Capabilities(True, True, True, False, True, True, True, True)
    user_caps = Capabilities(True, True, True, False, False, False, False, True)
    viewer_caps = Capabilities(True, True, False, False, False, False, False, True)
    if kind == "user":
        if user is None:
            raise ValueError("user principal requires a persisted user")
        try:
            profile = UserResponse.from_record(user).to_dict()
        except (KeyError, TypeError, ValueError):
            profile = {"id": _as_int(user.get("id", 0)), "username": str(user.get("username", "user")),
                       "role": str(user.get("role", "user")), "active": bool(user.get("is_active", True)),
                       "created_at": _as_float(user.get("created_at", 0))}
        role_raw = str(user.get("role", "user"))
        if role_raw == "admin":
            role, caps = "admin", all_caps
        elif role_raw == "user":
            role, caps = "user", user_caps
        else:
            # viewer（自注册默认）及其它未知角色：受限能力，无下载
            role, caps = "user", viewer_caps
        return SessionPrincipal(kind, True, role, str(user.get("username", "user")),
                                caps, profile, _can_write(user))
    if kind in ("password", "access_key", "local_ui"):
        return SessionPrincipal(kind, True, "admin", kind, all_caps)
    if kind == "share":
        return SessionPrincipal(kind, True, "guest", "share", _guest_capabilities(settings))
    if kind == "guest":
        return SessionPrincipal(kind, False, "guest", "Guest", _guest_capabilities(settings))
    raise ValueError(f"unknown principal kind: {kind}")
