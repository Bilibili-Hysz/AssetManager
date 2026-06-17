"""Shared helpers for LAN API route handlers."""
from __future__ import annotations

import asyncio
import concurrent.futures
import fnmatch
import logging
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web

from AssetsManager.core.format_utils import CATEGORY_MAP, format_size
from AssetsManager.domain.asset import IMAGE_EXTS
from AssetsManager.lan.path_guard import MissingPathError, PathEscapeError, PathGuard

_log = logging.getLogger(__name__)

_zip_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

LAN_APP_KEY = web.AppKey("lan", object)
AUTH_SERVICE_APP_KEY = web.AppKey("auth_service", object)
AUTH_USER_REQUEST_KEY = web.RequestKey("user", dict)
AUTH_KIND_REQUEST_KEY = web.RequestKey("auth_kind", str)

_format_size = format_size

__all__ = [
    "CATEGORY_MAP",
    "IMAGE_EXTS",
    "AUTH_SERVICE_APP_KEY",
    "AUTH_KIND_REQUEST_KEY",
    "AUTH_USER_REQUEST_KEY",
    "LAN_APP_KEY",
    "LanScopedServices",
    "_format_size",
    "build_zip_async",
    "build_zip_sync",
    "batch_cached_stats",
    "find_first_image",
    "get_auth_service",
    "get_auth_token",
    "get_lan",
    "get_metadata_service",
    "get_project_service",
    "get_request_auth_kind",
    "get_request_user",
    "get_services",
    "get_tag_service",
    "matches_exclude",
    "set_request_auth_context",
    "set_auth_cookie",
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


def _build_lan_services(lan) -> LanScopedServices:
    """Build a LanScopedServices bundle from a LAN server instance."""
    from AssetsManager.application import MetadataService, ProjectService, TagService
    from AssetsManager.application.auth_service import AuthService

    provider = lan.connection_for
    auth_service = getattr(lan, "_auth_service", None)
    if auth_service is None:
        auth_service = AuthService(lan.db_conn, lan.token_secret)
    return LanScopedServices(
        auth_service=auth_service,
        metadata_service=MetadataService(connection_provider=provider),
        project_service=ProjectService(connection_provider=provider),
        tag_service=TagService(connection_provider=provider),
    )


def get_lan(request) -> Any:
    return request.app[LAN_APP_KEY]


def set_request_auth_context(request, auth_kind: str, user: dict[str, Any]) -> None:
    request[AUTH_KIND_REQUEST_KEY] = auth_kind
    request[AUTH_USER_REQUEST_KEY] = user


def get_request_user(request) -> dict[str, Any] | None:
    return request.get(AUTH_USER_REQUEST_KEY)


def get_request_auth_kind(request) -> str | None:
    return request.get(AUTH_KIND_REQUEST_KEY)


def get_services(request) -> LanScopedServices:
    """Return the cached LAN service bundle, creating it on first access."""
    lan = get_lan(request)
    services = getattr(lan, "_services", None)
    if services is None:
        services = _build_lan_services(lan)
        lan._services = services
    return services


def get_auth_service(request):
    return get_services(request).auth_service


def get_metadata_service(request):
    return get_services(request).metadata_service


def get_project_service(request):
    return get_services(request).project_service


def get_tag_service(request):
    return get_services(request).tag_service


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


def get_auth_token(request) -> str:
    token = request.cookies.get("lan_token")
    if token:
        return token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    # Accept both ?token= and ?key= for access key compatibility.
    # Note: query parameters may appear in server logs, browser history,
    # and HTTP referer headers. Prefer Authorization: Bearer header.
    token = request.query.get("token", "")
    if token:
        return token
    return request.query.get("key", "")


def find_first_image(dir_path: Path) -> str | None:
    try:
        entries = sorted(
            [e for e in os.scandir(dir_path)
             if e.is_file() and Path(e.name).suffix.lower() in IMAGE_EXTS],
            key=lambda e: e.name.lower(),
        )
        return entries[0].path if entries else None
    except OSError:
        return None


def batch_cached_stats(lib_root: str, file_paths: list[str], connection_provider=None) -> dict[str, tuple[int, float]]:
    from AssetsManager.application import MetadataService
    return MetadataService(connection_provider=connection_provider).get_cached_stats(lib_root, file_paths)


def matches_exclude(name: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
        if fnmatch.fnmatch(name.lstrip("."), pattern.lstrip(".")):
            return True
    return False


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
                                pass
        return zip_path
    except Exception:
        _log.exception("Failed to create ZIP at %s", zip_path)
        return None


async def build_zip_async(targets: list[tuple[Path, str | None]], zip_path: str) -> str | None:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_zip_executor, build_zip_sync, targets, zip_path)
