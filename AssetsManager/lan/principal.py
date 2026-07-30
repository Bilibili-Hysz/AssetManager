"""Pure LAN session identity and capability mapping."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, Any

from AssetsManager.lan.dto import UserResponse

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
    all_caps = Capabilities(True, True, True, True, True, True, True, True)
    user_caps = Capabilities(True, True, True, False, False, False, False, True)
    if kind == "user":
        if user is None:
            raise ValueError("user principal requires a persisted user")
        try:
            profile = UserResponse.from_record(user).to_dict()
        except (KeyError, TypeError, ValueError):
            profile = {"id": int(user.get("id", 0)), "username": str(user.get("username", "user")),
                       "role": str(user.get("role", "user")), "active": bool(user.get("is_active", True)),
                       "created_at": float(user.get("created_at", 0))}
        role = "admin" if str(user.get("role", "user")) == "admin" else "user"
        return SessionPrincipal(kind, True, role, str(user.get("username", "user")),
                                all_caps if role == "admin" else user_caps, profile)
    if kind in ("password", "access_key", "local_ui"):
        return SessionPrincipal(kind, True, "admin", kind, all_caps)
    if kind == "share":
        return SessionPrincipal(kind, True, "guest", "share", _guest_capabilities(settings))
    if kind == "guest":
        return SessionPrincipal(kind, False, "guest", "Guest", _guest_capabilities(settings))
    raise ValueError(f"unknown principal kind: {kind}")
