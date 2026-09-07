"""Stable, public response DTOs for the LAN API.

Timestamp contract: every ``created_at`` field is a Unix epoch timestamp
in **seconds** with **UTC** semantics (timezone-naive, no DST offset).
Consumers should render it in their local zone; producers must convert
to UTC before serializing. ``uptime`` is a duration in seconds, not a
timestamp.
"""
from dataclasses import dataclass
from typing import Iterable, Mapping, TypedDict, cast
import json


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
    """Return a safe iterable of child records.

    Only genuine ``list``/``tuple`` payloads are honored; anything else
    (``None``, a string, a number, ...) degrades to an empty sequence so
    the recursive parse can never iterate over an unexpected type.
    """
    if isinstance(value, (list, tuple)):
        return cast(Iterable[Mapping[str, object]], value)
    return []


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
    """Public user payload.

    ``created_at``: Unix epoch seconds, UTC (see module docstring).
    """

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
    """Public invite payload.

    ``created_at``: Unix epoch seconds, UTC (see module docstring).
    """

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
class CollectionResponse:
    """One user collection row (manual reference set or smart query view).

    ``asset_count`` carries the live evaluated total for smart collections
    (their ``member_count`` is always 0 — they hold no membership rows).
    It is None when the count could not be computed or for manual rows.
    """

    id: int
    name: str
    kind: str
    query: dict[str, object]
    member_count: int
    created_at: float
    updated_at: float
    asset_count: int | None = None

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> "CollectionResponse":
        try:
            query = json.loads(str(record.get("query_json") or "{}"))
        except json.JSONDecodeError:
            query = {}
        if not isinstance(query, dict):
            query = {}
        member_count = record.get("member_count", 0)
        asset_count = record.get("asset_count")
        return cls(
            _as_int(record["id"]),
            str(record["name"]),
            str(record["kind"]),
            query,
            member_count if isinstance(member_count, int) else int(member_count),  # type: ignore[arg-type]
            float(record.get("created_at", 0.0)),  # type: ignore[arg-type]
            float(record.get("updated_at", 0.0)),  # type: ignore[arg-type]
            None if asset_count is None else int(asset_count),  # type: ignore[arg-type]
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "query": self.query,
            "member_count": self.member_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "asset_count": self.asset_count,
        }


@dataclass(frozen=True)
class CollectionsResponse:
    """Page of user collections (wrapper for ``GET /api/collections``)."""

    collections: tuple[CollectionResponse, ...]


@dataclass(frozen=True)
class CollectionMemberResponse:
    """One member path of a user collection (manual reference set)."""

    path: str
    added_at: float
    exists: bool


@dataclass(frozen=True)
class CollectionMembersResponse:
    """Member listing for one collection (``GET /api/collections/{id}/members``)."""

    members: tuple[CollectionMemberResponse, ...]


@dataclass(frozen=True)
class CollectionEvaluateResultResponse:
    """One asset row produced by evaluating a smart collection query."""

    path: str
    name: str
    extension: str
    size: int
    mtime: float


@dataclass(frozen=True)
class CollectionEvaluateResponse:
    """Paged evaluation output (``GET /api/collections/{id}/evaluate``)."""

    results: tuple[CollectionEvaluateResultResponse, ...]


# Maximum nesting depth accepted when (de)serializing tree payloads.
# ``ProjectDepthConfig`` clamps real trees to 32 levels and emits empty
# ``children`` on the deepest nodes, so truncating at this cap never alters
# legitimate output; it only bounds recursion for malicious/corrupted input.
_MAX_TREE_DEPTH = 32


@dataclass(frozen=True)
class TreeItemResponse:
    name: str
    path: str
    type: str
    is_leaf: bool
    children: tuple["TreeItemResponse", ...]

    @classmethod
    def from_record(cls, record: Mapping[str, object], _depth: int = 0) -> "TreeItemResponse":
        # Non-list ``children`` (e.g. a string or an int) degrade to an
        # empty list instead of blowing up while iterating; see
        # ``_as_children``. Beyond ``_MAX_TREE_DEPTH`` the subtree is
        # truncated to ``[]`` so deeply nested input cannot overflow the
        # call stack.
        children = [] if _depth >= _MAX_TREE_DEPTH else _as_children(record.get("children"))
        is_leaf = record.get("is_leaf")
        if not isinstance(is_leaf, bool):
            raise TypeError("is_leaf must be bool")
        # The upstream builder only ever emits "dir" nodes (its leaf flag is
        # a scan-depth artifact, not a file marker). A missing type defaults
        # to "dir"; any explicit non-"dir" value is rejected — the type is
        # produced by the server itself, so a silent downgrade would mask an
        # internal bug (the public contract asserts this rejection).
        raw_type = record.get("type")
        if raw_type is None:
            raw_type = "dir"
        elif not isinstance(raw_type, str) or raw_type != "dir":
            raise ValueError("tree type must be 'dir'")
        return cls(str(record["name"]), str(record["path"]),
                   raw_type,
                   is_leaf,
                   tuple(cls.from_record(child, _depth + 1) for child in children))

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict, truncating subtrees beyond ``_MAX_TREE_DEPTH``."""
        return self._to_dict(0)

    def _to_dict(self, depth: int) -> dict[str, object]:
        # Depth cap reached: emit this node with no children instead of
        # recursing further, so nested data can never overflow the stack.
        # ``children`` is also type-checked because a caller may construct
        # this dataclass directly with a non-list value.
        if depth >= _MAX_TREE_DEPTH or not isinstance(self.children, (list, tuple)):
            return {"name": self.name, "path": self.path, "type": self.type,
                    "is_leaf": self.is_leaf, "children": []}
        return {"name": self.name, "path": self.path, "type": self.type,
                "is_leaf": self.is_leaf,
                "children": [child._to_dict(depth + 1) for child in self.children]}


@dataclass(frozen=True)
class ZipCleanupDiagnosticsResponse:
    """Safe operational counters for deferred ZIP archive cleanup.

    The cleanup service deliberately exposes counts, elapsed time, and an
    exception *type* only.  Paths, archive names, callback identities, and
    exception messages are never part of this admin diagnostic contract.
    """

    pending_count: int
    retry_attempts: int
    completed_count: int
    oldest_pending_seconds: float
    last_error_type: str | None

    @classmethod
    def from_record(
        cls, record: Mapping[str, object]
    ) -> "ZipCleanupDiagnosticsResponse":
        error_type = record.get("last_error_type")
        # ``ZipCleanupService`` records ``type(exc).__name__``.  Retain only
        # that identifier-shaped value as a defense against a future source
        # accidentally supplying exception text or another sensitive value.
        safe_error_type = (
            error_type
            if isinstance(error_type, str) and error_type.isidentifier()
            else None
        )
        return cls(
            _as_int(record.get("pending_count", 0)),
            _as_int(record.get("retry_attempts", 0)),
            _as_int(record.get("completed_count", 0)),
            _as_float(record.get("oldest_pending_seconds", 0)),
            safe_error_type,
        )

    def to_dict(self) -> dict[str, int | float | str | None]:
        return {
            "pending_count": self.pending_count,
            "retry_attempts": self.retry_attempts,
            "completed_count": self.completed_count,
            "oldest_pending_seconds": self.oldest_pending_seconds,
            "last_error_type": self.last_error_type,
        }


@dataclass(frozen=True)
class ZipResourcesResponse:
    """Admin-only ZIP admission and deferred-cleanup diagnostics."""

    active_jobs: int
    reserved_bytes: int
    max_jobs: int
    max_reserved_bytes: int
    cleanup: ZipCleanupDiagnosticsResponse

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> "ZipResourcesResponse":
        raw_cleanup = record.get("cleanup")
        cleanup = (
            ZipCleanupDiagnosticsResponse.from_record(raw_cleanup)
            if isinstance(raw_cleanup, Mapping)
            else ZipCleanupDiagnosticsResponse.from_record({})
        )
        return cls(
            _as_int(record.get("active_jobs", 0)),
            _as_int(record.get("reserved_bytes", 0)),
            _as_int(record.get("max_jobs", 0)),
            _as_int(record.get("max_reserved_bytes", 0)),
            cleanup,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "active_jobs": self.active_jobs,
            "reserved_bytes": self.reserved_bytes,
            "max_jobs": self.max_jobs,
            "max_reserved_bytes": self.max_reserved_bytes,
            "cleanup": self.cleanup.to_dict(),
        }


@dataclass(frozen=True)
class StatsResponse:
    connections: int
    requests: int
    bytes_transferred: int | None
    bytes_transferred_fmt: str | None
    uptime: float
    zip_resources: ZipResourcesResponse | None = None

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> "StatsResponse":
        # ``bytes_transferred`` is None until the first transfer happens
        # (LanServer initialises it to None). Keep the None convention
        # here -- never feed it through ``_as_int`` -- so the response
        # stays in sync with ``bytes_transferred_fmt``, which the stats
        # route only formats when the raw count is not None.
        bytes_transferred = record.get("bytes_transferred")
        bytes_transferred_fmt = record.get("bytes_transferred_fmt")
        raw_zip_resources = record.get("zip_resources")
        zip_resources = (
            ZipResourcesResponse.from_record(raw_zip_resources)
            if isinstance(raw_zip_resources, Mapping)
            else None
        )
        return cls(_as_int(record.get("connections", 0)), _as_int(record.get("requests", 0)),
                   _as_int(bytes_transferred) if bytes_transferred is not None else None,
                   str(bytes_transferred_fmt) if bytes_transferred_fmt is not None else None,
                   _as_float(record.get("uptime", 0)), zip_resources)

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"connections": self.connections, "requests": self.requests,
                "bytes_transferred": self.bytes_transferred,
                "bytes_transferred_fmt": self.bytes_transferred_fmt, "uptime": self.uptime}
        if self.zip_resources is not None:
            result["zip_resources"] = self.zip_resources.to_dict()
        return result


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
