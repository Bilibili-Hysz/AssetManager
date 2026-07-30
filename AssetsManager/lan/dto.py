"""Stable, public response DTOs for the LAN API."""
from dataclasses import dataclass
from typing import Mapping


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
        return cls(int(record["id"]), str(record["username"]), str(record["role"]),
                   bool(record["is_active"]), float(record["created_at"]))

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
        return cls(str(record["code"]), float(record["created_at"]),
                   record.get("used_by") if record.get("used_by") is None else str(record["used_by"]),
                   not bool(record["is_active"]))

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
        return cls(None if record.get("id") is None else int(record["id"]),
                   str(record["name"]), int(record["count"]))

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
        children = record.get("children") or []
        is_leaf = record.get("is_leaf")
        if not isinstance(is_leaf, bool):
            raise TypeError("is_leaf must be bool")
        raw_type = record.get("type")
        item_type = "dir" if raw_type is None or raw_type == "" else raw_type
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
        return cls(int(record.get("connections", 0)), int(record.get("requests", 0)),
                   int(bytes_transferred) if bytes_transferred is not None else None,
                   str(record["bytes_transferred_fmt"]) if record.get("bytes_transferred_fmt") is not None else None,
                   float(record.get("uptime", 0)))

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
