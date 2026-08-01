"""Shared helpers for LAN API route handlers."""
from __future__ import annotations

import asyncio
import re
import concurrent.futures
import logging
import os
import time
import threading
import zipfile
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiohttp import web

from AssetsManager.application.asset_service import matches_exclude
from AssetsManager.core.format_utils import CATEGORY_MAP, format_size
from AssetsManager.domain.asset import IMAGE_EXTS
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import ActivityChanged, PresenceChanged
from AssetsManager.lan.path_guard import MissingPathError, PathEscapeError, PathGuard

_log = logging.getLogger(__name__)

_zip_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

LAN_APP_KEY = web.AppKey("lan", object)
AUTH_SERVICE_APP_KEY = web.AppKey("auth_service", object)
PRINCIPAL_REQUEST_KEY = web.RequestKey("principal", object)

_format_size = format_size

ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLE_GUEST = "guest"

_SANITIZE_RE = re.compile(r'[\x00-\x1f\x7f"\\/]')


class ActivityLog:
    def __init__(self, max_entries=100, *, event_bus=None, library_root="", session_token=""):
        self._entries = deque(maxlen=max_entries)
        self._lock = threading.Lock()
        self._next_id = 1
        self._event_bus = event_bus or get_event_bus()
        self._library_root = library_root
        self._session_token = session_token

    def add(self, user, action, detail="", *, ip="unknown"):
        with self._lock:
            self._entries.append({
                "id": self._next_id,
                "username": user or "guest",
                "action": action,
                "details": detail,
                "ip": ip or "unknown",
                "timestamp": time.time(),
            })
            self._next_id += 1
        if self._library_root and self._session_token:
            try:
                self._event_bus.publish(ActivityChanged(
                    library_root=self._library_root,
                    session_token=self._session_token,
                ))
            except Exception:
                _log.exception("Activity projection notification failed")

    def recent(self, count=10):
        with self._lock:
            return list(self._entries)[-count:]


class OnlineUsers:
    def __init__(self, *, event_bus=None, library_root="", session_token=""):
        self._users = {}
        self._counts = {}
        self._lock = threading.Lock()
        self._event_bus = event_bus or get_event_bus()
        self._library_root = library_root
        self._session_token = session_token

    def _publish_changed(self):
        if self._library_root and self._session_token:
            try:
                self._event_bus.publish(PresenceChanged(
                    library_root=self._library_root,
                    session_token=self._session_token,
                ))
            except Exception:
                _log.exception("Presence projection notification failed")

    def connect(self, user_id, username, ip):
        visible_change = False
        with self._lock:
            self._counts[user_id] = self._counts.get(user_id, 0) + 1
            if user_id not in self._users:
                self._users[user_id] = {"username": username, "ip": ip, "connected_at": time.time()}
                visible_change = True
        if visible_change:
            self._publish_changed()

    def disconnect(self, user_id):
        visible_change = False
        with self._lock:
            count = self._counts.get(user_id, 0) - 1
            if count > 0:
                self._counts[user_id] = count
            else:
                self._counts.pop(user_id, None)
                visible_change = user_id in self._users
                self._users.pop(user_id, None)
        if visible_change:
            self._publish_changed()

    def list_all(self):
        with self._lock:
            return [{"user_id": k, **v} for k, v in self._users.items()]


def sanitize_filename(name: str) -> str:
    """Sanitize a filename for Content-Disposition header.

    - Strip control characters
    - Strip path separators
    - Limit length to 200 chars
    - Fallback to 'download' if empty
    """
    clean = _SANITIZE_RE.sub('', name)
    if len(clean) > 200:
        clean = clean[:200]
    return clean or 'download'


__all__ = [
    "ActivityLog",
    "OnlineUsers",
    "CATEGORY_MAP",
    "IMAGE_EXTS",
    "AUTH_SERVICE_APP_KEY",
    "PRINCIPAL_REQUEST_KEY",
    "LAN_APP_KEY",
    "LanScopedServices",
    "ROLE_ADMIN",
    "ROLE_GUEST",
    "ROLE_USER",
    "_format_size",
    "build_zip_async",
    "build_zip_sync",
    "find_first_image",
    "get_asset_service",
    "get_auth_service",
    "get_auth_token",
    "get_lan",
    "get_metadata_service",
    "get_project_service",
    "get_search_service",
    "get_share_token",
    "get_services",
    "get_share_service",
    "get_tag_service",
    "get_thumbnail_service",
    "get_user_permissions",
    "matches_exclude",
    "require_admin",
    "require_permission",
    "require_role",
    "sanitize_filename",
    "set_request_principal",
    "set_auth_cookie",
    "set_share_cookie",
    "validate_path",
    "validated_existing_key",
]


@dataclass(frozen=True)
class LanScopedServices:
    """Service bundle bound to a LAN server instance.

    Created once when the server starts and reused for all requests.
    Services receive ``connection_provider=server.connection_for`` so they
    always use the server's single DB connection.
    """

    auth_service: Any
    metadata_service: Any
    project_service: Any
    tag_service: Any
    search_service: Any
    thumbnail_service: Any
    asset_service: Any
    share_service: Any
    activity_log: Any = field(default_factory=ActivityLog)
    online_users: Any = field(default_factory=OnlineUsers)
    runtime_services: Any = None


def get_lan(request) -> Any:
    return request.app[LAN_APP_KEY]


def set_request_principal(request, principal, user: dict[str, Any] | None = None) -> None:
    """Attach canonical identity to the request."""
    request[PRINCIPAL_REQUEST_KEY] = principal


def get_request_principal(request):
    return request.get(PRINCIPAL_REQUEST_KEY) or request.get("principal")


def require_role(request, *roles):
    """Return the canonical principal when its role is allowed."""
    principal = get_request_principal(request)
    return principal if principal is not None and principal.role in roles else None


def require_admin(request):
    """Return user dict if admin, else None."""
    return require_role(request, ROLE_ADMIN)


def require_permission(request, permission: str) -> bool:
    """Return True when the current request user has a named LAN permission."""
    principal = get_request_principal(request)
    if principal is not None:
        return bool(getattr(principal.capabilities, permission, False))
    return False


def get_user_permissions(user):
    """Return permission dict for a user role, respecting guest settings."""
    role = user.get("role", ROLE_GUEST) if user else ROLE_GUEST
    if role == ROLE_ADMIN:
        return {"browse": True, "download": True, "upload": True, "manage_links": True, "manage_users": True, "settings": True, "preview": True}
    if role == ROLE_USER:
        return {"browse": True, "download": True, "upload": False, "manage_links": False, "manage_users": False, "settings": False, "preview": True}
    # Guest — read from settings
    try:
        from AssetsManager.core.settings import AppSettings
        s = AppSettings.instance()
        return {
            "browse": s.get("lan_guest_list", True),
            "download": s.get("lan_guest_download", False),
            "upload": False,
            "manage_links": False,
            "manage_users": False,
            "settings": False,
            "preview": s.get("lan_guest_preview", True),
        }
    except Exception:
        return {"browse": True, "download": False, "upload": False, "manage_links": False, "manage_users": False, "settings": False, "preview": True}


def get_services(request) -> LanScopedServices:
    """Return the eagerly attached LAN service bundle."""
    lan = get_lan(request)
    if getattr(lan, "services", None) is None:
        raise RuntimeError("LAN service bundle is absent; compose the server with a Runtime")
    return lan.services


def get_auth_service(request):
    return get_services(request).auth_service


def get_metadata_service(request):
    return get_services(request).metadata_service


def get_project_service(request):
    return get_services(request).project_service


def get_tag_service(request):
    return get_services(request).tag_service


def get_share_service(request):
    return get_services(request).share_service


def get_search_service(request):
    return get_services(request).search_service


def get_thumbnail_service(request):
    return get_services(request).thumbnail_service


def get_asset_service(request):
    return get_services(request).asset_service


def validate_path(lan, rel_path: str) -> Path:
    try:
        return PathGuard(lan.library_root).resolve(rel_path)
    except PathEscapeError:
        raise web.HTTPBadRequest(reason="Path escape detected")


def validated_existing_key(lan, rel_path: str) -> str:
    try:
        return PathGuard(lan.library_root).existing_key(rel_path)
    except PathEscapeError:
        raise web.HTTPBadRequest(reason="Path escape detected")
    except MissingPathError:
        raise web.HTTPNotFound(reason="File not found")


def set_auth_cookie(response: web.Response, token: str):
    response.set_cookie(
        "lan_token", token, httponly=True, samesite="Lax", path="/", max_age=86400,
    )


def set_share_cookie(response: web.Response, share_id: str, token: str) -> None:
    """Set a short-lived token that is sent only to one share's API routes."""
    response.set_cookie(
        "share_token", token, httponly=True, samesite="Lax",
        path=f"/api/shares/{share_id}", max_age=3600,
    )


def get_share_token(request) -> str:
    """Return a share credential from its scoped cookie or Bearer API header."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return request.cookies.get("share_token", "")


def get_auth_token(request, *, allow_query: bool = True) -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    token = request.cookies.get("lan_token")
    if token:
        return token
    # ── DEPRECATED: Query-parameter auth (?token=, ?key=) ──
    # These leak credentials into server logs, browser history, and HTTP
    # referer headers.  Prefer the Authorization: Bearer header or the
    # lan_token cookie.
    token = request.query.get("token", "")
    if token:
        _log.warning(
            "DEPRECATED: Query-parameter auth via ?token= is deprecated "
            "and will be removed in a future release. "
            "Use Authorization: Bearer header instead."
        )
        return token if allow_query else ""
    token = request.query.get("key", "")
    if token:
        _log.warning(
            "DEPRECATED: Query-parameter auth via ?key= is deprecated "
            "and will be removed in a future release. "
            "Use Authorization: Bearer header instead."
        )
        return token if allow_query else ""
    return ""


def find_first_image(dir_path: Path) -> str | None:
    try:
        best_entry = None
        best_name = ""
        for entry in os.scandir(dir_path):
            if not entry.is_file() or Path(entry.name).suffix.lower() not in IMAGE_EXTS:
                continue
            name = entry.name.lower()
            if best_entry is None or name < best_name:
                best_entry = entry
                best_name = name
        return best_entry.path if best_entry is not None else None
    except OSError:
        return None


def build_zip_sync(target_paths: list[tuple[Path, str | None]], zip_path: str) -> str | None:
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for target, arc_name in target_paths:
                if arc_name is None:
                    arc_name = target.name
                if target.is_file():
                    zf.write(str(target), arc_name)
                elif target.is_dir():
                    for dirpath, dirnames, filenames in os.walk(target):
                        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                        for fname in filenames:
                            if fname.startswith("."):
                                continue
                            fp = os.path.join(dirpath, fname)
                            arc = os.path.join(arc_name, os.path.relpath(fp, target))
                            try:
                                zf.write(fp, arc)
                            except OSError:
                                _log.warning("Failed to add file to ZIP: %s", fp)
        return zip_path
    except Exception:
        _log.exception("Failed to create ZIP at %s", zip_path)
        return None


async def build_zip_async(targets: list[tuple[Path, str | None]], zip_path: str) -> str | None:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_zip_executor, build_zip_sync, targets, zip_path)
