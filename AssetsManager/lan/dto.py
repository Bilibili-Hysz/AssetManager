"""Stable, public response DTOs for the LAN API."""
from dataclasses import dataclass
from typing import Iterable, Mapping, TypedDict, cast


class UserRecord(TypedDict, total=False):
    """Persisted user fields consumed by the public user DTO."""

    id: int | str
    username: str
    role: str
    is_active: bool
    created_at: int | float


class InviteRecord(TypedDict, total=False):
    """Persisted invite fields consumed by the public invite DTO."""

    code: str
    created_at: int | float
    used_by: str | None
    is_active: bool


def _as_int(value: object) -> int:
    if value is None or isinstance(value, bool):
        raise ValueError(f"expected an integer, got {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        try:
            return int(round(value))
        except (ValueError, OverflowError) as error:
            raise ValueError(f"expected an integer, got {value!r}") from error
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (bytes, bytearray)):
        try:
            text = bytes(value).decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise ValueError("expected an integer, got non-text bytes") from error
    else:
        raise ValueError(f"expected an integer, got {value!r}")
    if not text:
        raise ValueError("expected an integer, got empty string")
    try:
        return int(round(float(text)))
    except (ValueError, OverflowError) as error:
        raise ValueError(f"expected an integer, got {value!r}") from error


def _as_float(value: object) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"expected a number, got {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (bytes, bytearray)):
        try:
            text = bytes(value).decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise ValueError("expected a number, got non-text bytes") from error
    else:
        raise ValueError(f"expected a number, got {value!r}")
    if not text:
        raise ValueError("expected a number, got empty string")
    try:
        return float(text)
    except ValueError as error:
        raise ValueError(f"expected a number, got {value!r}") from error


def _as_children(value: object) -> Iterable[Mapping[str, object]]:
    return cast(Iterable[Mapping[str, object]], value or [])


def _as_optional_str(value: object) -> str | None:
    return None if value is None else str(value)


@dataclass(frozen=True)
class CapabilitiesResponse:
    browse: bool
    preview: bool
    download: bool
    upload: bool
    manage_links: bool
    manage_users: bool
    settings: bool
    realtime: bool

    def to_dict(self) -> dict[str, bool]:
        return {name: bool(getattr(self, name)) for name in (
            "browse", "preview", "download", "upload", "manage_links",
            "manage_users", "settings", "realtime")}


@dataclass(frozen=True)
class SessionPrincipalResponse:
    kind: str
    authenticated: bool
    role: str
    display_name: str
    capabilities: CapabilitiesResponse
    user_profile: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        result = {"kind": self.kind, "authenticated": self.authenticated, "role": self.role,
                  "display_name": self.display_name, "capabilities": self.capabilities.to_dict()}
        if self.user_profile is not None:
            result["user_profile"] = dict(self.user_profile)
        return result


@dataclass(frozen=True)
class UserResponse:
    id: int
    username: str
    role: str
    active: bool
    created_at: float

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> "UserResponse":
        user_id = record.get("id")
        if user_id is None:
            raise ValueError("user record missing 'id'")
        return cls(_as_int(user_id),
                   str(record.get("username") or ""),
                   str(record.get("role") or ""),
                   bool(record.get("is_active", True)),
                   _as_float(record.get("created_at") or 0))

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "username": self.username, "role": self.role,
                "active": self.active, "created_at": self.created_at}


@dataclass(frozen=True)
class InviteResponse:
    code: str
    created_at: float
    used_by: str | None
    revoked: bool

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> "InviteResponse":
        code = record.get("code")
        if code is None:
            raise ValueError("invite record missing 'code'")
        return cls(str(code), _as_float(record.get("created_at") or 0),
                   _as_optional_str(record.get("used_by")),
                   not bool(record.get("is_active", False)))

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code, "created_at": self.created_at, "used_by": self.used_by,
                "revoked": self.revoked}


@dataclass(frozen=True)
class TagResponse:
    id: int | None
    name: str
    count: int

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> "TagResponse":
        return cls(None if record.get("id") is None else _as_int(record["id"]),
                   str(record["name"]), _as_int(record["count"]))

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "name": self.name, "count": self.count}


@dataclass(frozen=True)
class TreeItemResponse:
    name: str
    path: str
    type: str
    is_leaf: bool
    children: tuple["TreeItemResponse", ...]

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> "TreeItemResponse":
        children = _as_children(record.get("children"))
        is_leaf = record.get("is_leaf")
        if not isinstance(is_leaf, bool):
            raise TypeError("is_leaf must be bool")
        raw_type = record.get("type")
        if raw_type is None or raw_type == "":
            item_type = "dir"
        elif isinstance(raw_type, str):
            item_type = raw_type
        else:
            raise ValueError("tree type must be 'dir'")
        if item_type != "dir":
            raise ValueError("tree type must be 'dir'")
        return cls(str(record["name"]), str(record["path"]),
                   item_type,
                   is_leaf,
                   tuple(cls.from_record(child) for child in children))

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "path": self.path, "type": self.type,
                "is_leaf": self.is_leaf, "children": [child.to_dict() for child in self.children]}


@dataclass(frozen=True)
class StatsResponse:
    connections: int
    requests: int
    bytes_transferred: int | None
    bytes_transferred_fmt: str | None
    uptime: float

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> "StatsResponse":
        bytes_transferred = record.get("bytes_transferred")
        return cls(_as_int(record.get("connections", 0)), _as_int(record.get("requests", 0)),
                   _as_int(bytes_transferred) if bytes_transferred is not None else None,
                   str(record["bytes_transferred_fmt"]) if record.get("bytes_transferred_fmt") is not None else None,
                   _as_float(record.get("uptime", 0)))

    def to_dict(self) -> dict[str, object]:
        return {"connections": self.connections, "requests": self.requests,
                "bytes_transferred": self.bytes_transferred,
                "bytes_transferred_fmt": self.bytes_transferred_fmt, "uptime": self.uptime}


@dataclass(frozen=True)
class RuntimeCursorResponse:
    epoch: str
    revision: int

    def to_dict(self) -> dict[str, object]:
        return {"epoch": self.epoch, "revision": self.revision}


@dataclass(frozen=True)
class ProjectionInvalidationResponse:
    epoch: str
    revision: int
    domains: tuple[str, ...]
    paths: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"type": "projection_invalidated", "epoch": self.epoch,
                "revision": self.revision, "domains": list(self.domains),
                "paths": list(self.paths)}
