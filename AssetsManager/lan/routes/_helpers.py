"""Shared helpers for LAN API route handlers."""
from __future__ import annotations

import asyncio
import hashlib
import io
import re
import concurrent.futures
import logging
import os
import time
import threading
import zipfile
from collections import deque
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiohttp import web

from AssetsManager.application.asset_filters import matches_exclude
from AssetsManager.application.thumbnail_service import process_image_snapshot
from AssetsManager.core.database import db_write_lock
from AssetsManager.core.format_utils import CATEGORY_MAP, format_size
from AssetsManager.domain.asset import IMAGE_EXTS
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import ActivityChanged, PresenceChanged
from AssetsManager.lan.path_guard import MissingPathError, PathEscapeError, PathGuard, PathGuardError
from AssetsManager.lan import zip_resources
from AssetsManager.lan.zip_sources import ZipLimitExceeded, scan_zip_sources
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.safe_open import (
    FileIdentity,
    iter_safe_file,
)
from AssetsManager.lan.zip_resources import ZipReservation
from AssetsManager.lan.zip_cleanup import cleanup_zip_path

_log = logging.getLogger(__name__)

LAN_APP_KEY = web.AppKey("lan", object)
AUTH_SERVICE_APP_KEY = web.AppKey("auth_service", object)
PRINCIPAL_REQUEST_KEY = web.RequestKey("principal", object)
ZIP_EXECUTOR_APP_KEY = web.AppKey("zip_executor", object)

_format_size = format_size

ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLE_GUEST = "guest"

_SANITIZE_RE = re.compile(r'[\x00-\x1f\x7f"\\/]')

# Preview responses can become sensitive when blur tags change. Blurred
# output is never stored; other previews must revalidate before reuse.
PRIVATE_PREVIEW_HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
}
PUBLIC_PREVIEW_HEADERS = {
    "Cache-Control": "private, no-cache",
    "X-Content-Type-Options": "nosniff",
}

# Every reuse must consult the current authorization and blur policy. ETags
# still save transfer bytes, but cannot bypass those checks with a fresh hit.
MEDIA_CACHE_HEADERS = {
    "Cache-Control": "private, no-cache",
    "X-Content-Type-Options": "nosniff",
}


def build_media_etag(*identity_parts: object, query: dict[str, str] | None = None) -> str:
    """Weak ETag over the source identity plus the normalized request query.

    The query participates in the hash so different processing parameters
    (e.g. thumbnail ``size``) produce different validators, and routes pass
    the blur decision as an identity part so a policy flip invalidates
    previously cached copies.
    """
    hasher = hashlib.sha256()
    for part in identity_parts:
        hasher.update(f"{part}".encode("utf-8", "replace"))
    if query:
        for key in sorted(query):
            hasher.update(f"{key}={query[key]}".encode("utf-8", "replace"))
    return f'W/"{hasher.hexdigest()[:32]}"'


def build_snapshot_media_etag(
    kind: str,
    identity: FileIdentity,
    body: bytes,
    content_type: str,
    *,
    query: dict[str, str] | None = None,
) -> str:
    """Bind a preview validator to its admitted source and rendered bytes."""
    return build_media_etag(
        kind, *identity.as_tuple(), content_type,
        hashlib.sha256(body).hexdigest(), query=query,
    )


def inspect_raster_bytes(body: bytes) -> str | None:
    """Verify the exact captured raster bytes before original-byte delivery."""
    content_types = {
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "GIF": "image/gif",
        "BMP": "image/bmp",
        "WEBP": "image/webp",
        "TIFF": "image/tiff",
        "ICO": "image/x-icon",
    }
    try:
        from PIL import Image

        with io.BytesIO(body) as stream:
            with Image.open(stream) as image:
                image.verify()
                return content_types.get(str(image.format).upper())
    except Exception:
        return None


def etag_matches(request: web.Request, etag: str) -> bool:
    """RFC 7232 If-None-Match comparison (comma lists and ``*``)."""
    header = request.headers.get("If-None-Match")
    if not header:
        return False
    candidates = [candidate.strip() for candidate in header.split(",")]
    return "*" in candidates or etag in candidates


def media_not_modified(etag: str) -> web.Response:
    """304 short-circuit that keeps the validator and cache policy alive."""
    return web.Response(status=304, headers={**MEDIA_CACHE_HEADERS, "ETag": etag})

# Blurred output is resized to this bound (like the high-resolution
# thumbnail route) so a hostile multi-GB raster cannot force unbounded
# memory/CPU work; original previews use bounded, verified byte snapshots.
BLURRED_PREVIEW_SIZE = 1920


class ActivityLog:
    def __init__(self, max_entries=100, *, event_bus=None, library_root="",
                 session_token="", connection_provider=None):
        self._entries = deque(maxlen=max_entries)
        self._lock = threading.Lock()
        self._next_id = 1
        self._event_bus = event_bus or get_event_bus()
        self._library_root = library_root
        self._session_token = session_token
        # Zero-arg callable returning the library DB connection; None keeps
        # the in-memory behavior (tests, no-DB server paths). Persistence SQL
        # lives here (not a repository) because the LAN routes layer may not
        # import the repositories package (architecture gate).
        self._connection_provider = connection_provider

    def _connection(self):
        if self._connection_provider is None:
            return None
        try:
            return self._connection_provider()
        except Exception:
            _log.exception("Activity log connection unavailable")
            return None

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
        conn = self._connection()
        if conn is not None:
            try:
                with db_write_lock(conn):
                    conn.execute(
                        "INSERT INTO activity_log "
                        "(username, action, details, ip, timestamp) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (user or "guest", action, detail, ip or "unknown", time.time()),
                    )
                    conn.commit()
            except Exception:
                _log.exception("Activity log persistence failed")
        if self._library_root and self._session_token:
            try:
                self._event_bus.publish(ActivityChanged(
                    library_root=self._library_root,
                    session_token=self._session_token,
                ))
            except Exception:
                _log.exception("Activity projection notification failed")

    def recent(self, count=10):
        conn = self._connection()
        if conn is not None:
            try:
                # Same connection-lock discipline as add(): readers must not
                # race the single library connection against concurrent
                # writers.
                with db_write_lock(conn):
                    rows = conn.execute(
                        "SELECT id, username, action, details, ip, timestamp "
                        "FROM activity_log ORDER BY id DESC LIMIT ?",
                        (count,),
                    ).fetchall()
                return [
                    {
                        "id": row[0],
                        "username": row[1],
                        "action": row[2],
                        "details": row[3],
                        "ip": row[4],
                        "timestamp": row[5],
                    }
                    for row in rows
                ]
            except Exception:
                _log.exception("Activity log read failed")
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
    "BLURRED_PREVIEW_SIZE",
    "CATEGORY_MAP",
    "IMAGE_EXTS",
    "AUTH_SERVICE_APP_KEY",
    "PRINCIPAL_REQUEST_KEY",
    "MEDIA_CACHE_HEADERS",
    "PRIVATE_PREVIEW_HEADERS",
    "PUBLIC_PREVIEW_HEADERS",
    "build_media_etag",
    "build_snapshot_media_etag",
    "etag_matches",
    "media_not_modified",
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
    "get_collection_service",
    "get_gallery_service",
    "get_favorite_service",
    "get_metadata_service",
    "get_project_service",
    "get_search_service",
    "get_share_token",
    "get_services",
    "get_share_service",
    "get_tag_service",
    "get_thumbnail_service",
    "inspect_raster_bytes",
    "matches_exclude",
    "MAX_QUERY_LENGTH",
    "oversized_query",
    "require_admin",
    "require_permission",
    "require_role",
    "require_user_write",
    "sanitize_filename",
    "serve_blur_gated_raster",
    "should_blur_target",
    "set_request_principal",
    "set_auth_cookie",
    "set_share_cookie",
    "validate_path",
    "validated_existing_key",
    "ZIP_EXECUTOR_APP_KEY",
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
    gallery_service: Any = None
    favorite_service: Any = None
    collection_service: Any = None
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


def request_owner_key(request) -> str:
    """Resolve the requester's favorites owner key, or raise 401.

    Canonical owner identity for principal-scoped data (library_favorites):
    authenticated users are scoped by user id, other principals by their
    kind. Routes that need a viewer-scoped dimension (rating/favorite
    filters, favorites themselves) share this derivation.
    """
    principal = get_request_principal(request)
    if principal is None:
        raise web.HTTPUnauthorized(reason="Authentication required")
    if principal.kind == "user" and principal.user_profile is not None:
        user_id = principal.user_profile.get("id")
        if user_id is not None:
            return f"user:{user_id}"
    return f"principal:{principal.kind}"


def require_role(request, *roles):
    """Return the canonical principal when its role is allowed."""
    principal = get_request_principal(request)
    return principal if principal is not None and principal.role in roles else None


def require_admin(request):
    """Return user dict if admin, else None."""
    return require_role(request, ROLE_ADMIN)


def require_user_write(request):
    """Return the canonical principal when it may write metadata/tags.

    LAN admin principals (password / access_key / local_ui) are always
    allowed. A ``user`` principal is allowed only when the persisted user
    record carries ``can_write``. Guests and shares never qualify.
    """
    principal = get_request_principal(request)
    if principal is None:
        return None
    if principal.kind in ("password", "access_key", "local_ui"):
        return principal
    if principal.kind == "user" and bool(getattr(principal, "can_write", False)):
        return principal
    return None


def require_permission(request, permission: str) -> bool:
    """Return True when the current request user has a named LAN permission."""
    principal = get_request_principal(request)
    if principal is not None:
        return bool(getattr(principal.capabilities, permission, False))
    return False


# L2 input budget: search query strings are capped before they reach the
# scanner/index so a hostile client cannot force unbounded memory/cpu work
# through the public /api/search and /api/quicksearch endpoints.
MAX_QUERY_LENGTH = 256


def oversized_query(request, field: str = "q") -> str | None:
    """Return the 400 message when a query parameter exceeds its budget."""
    value = request.query.get(field, "")
    if len(value) > MAX_QUERY_LENGTH:
        return f"{field} must be at most {MAX_QUERY_LENGTH} characters"
    return None


def get_services(request) -> LanScopedServices:
    """Return the eagerly attached LAN service bundle."""
    lan = get_lan(request)
    if getattr(lan, "services", None) is None:
        raise RuntimeError("LAN service bundle is absent; compose the server with a Runtime")
    return lan.services


def get_auth_service(request):
    return get_services(request).auth_service


def get_gallery_service(request):
    return get_services(request).gallery_service


def get_favorite_service(request):
    return get_services(request).favorite_service


def get_metadata_service(request):
    return get_services(request).metadata_service


def get_project_service(request):
    return get_services(request).project_service


def get_tag_service(request):
    return get_services(request).tag_service


def get_collection_service(request):
    return get_services(request).collection_service


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
        raise web.HTTPBadRequest(reason="Path escape detected") from None
    except PathGuardError:
        # Invalid characters (NUL / control chars, Windows ADS separators)
        # are a client error, not a server fault — return 400 like escapes.
        raise web.HTTPBadRequest(reason="Invalid path") from None


def validated_existing_key(lan, rel_path: str) -> str:
    """Return the storage key for an existing library path.

    Path escape and missing-path failures propagate as their domain errors
    (``PathEscapeError`` / ``MissingPathError``) so they are serialized by the
    central mapping in ``_errors.py`` (route handlers map them explicitly; the
    error_contract_middleware is the fallback) instead of being flattened into
    bare aiohttp HTTPExceptions with non-contract text bodies. Status stays
    400/404; only the body shape is unified.
    """
    try:
        return PathGuard(lan.library_root).existing_key(rel_path)
    except (PathEscapeError, MissingPathError):
        # Domain errors propagate to the central error contract (route
        # handlers map them explicitly; error_contract_middleware is the
        # fallback). Both subclass PathGuardError, so they must be re-raised
        # before the generic guard clause below.
        raise
    except PathGuardError:
        # Invalid characters (NUL / control chars, Windows ADS separators)
        # have no dedicated domain type; they stay a 400 client error.
        raise web.HTTPBadRequest(reason="Invalid path") from None


def set_auth_cookie(response: web.Response, token: str, *, secure: bool = False):
    """Set the LAN auth cookie.

    ``secure`` must stay False on plain HTTP, otherwise browsers discard the
    cookie and login breaks; callers pass ``secure=lan.ssl_active`` so the
    flag is only set when the server is actually served over TLS.
    """
    response.set_cookie(
        "lan_token", token, httponly=True, samesite="Lax", path="/", max_age=86400,
        secure=secure,
    )


def set_share_cookie(response: web.Response, share_id: str, token: str, *,
                     secure: bool = False) -> None:
    """Set a short-lived token that is sent only to one share's API routes."""
    response.set_cookie(
        "share_token", token, httponly=True, samesite="Lax",
        path=f"/api/shares/{share_id}", max_age=3600,
        secure=secure,
    )


def get_share_token(request) -> str:
    """Return a share credential from its scoped cookie or Bearer API header."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return request.cookies.get("share_token", "")


def get_auth_token(request) -> str:
    """Return a LAN credential from the Authorization header or cookie.

    Query-parameter auth (?token= / ?key=) is intentionally not supported:
    credentials in the query string leak into server logs, browser history,
    and HTTP referer headers.  Use the Authorization: Bearer header or the
    lan_token cookie instead.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    token = request.cookies.get("lan_token")
    if token:
        return token
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


async def should_blur_target(request: web.Request, target: Path) -> bool:
    """Blur-policy decision for a file a route is about to deliver.

    Uses the thumbnail service's tag check directly rather than
    ``resolve()``: the decision must apply to every raster byte a route
    serves, including formats the thumbnail pipeline cannot handle
    (``.tga`` sits outside IMAGE_EXTS, ``.ktx2`` has no Pillow decoder).
    """
    lan = get_lan(request)
    svc = get_thumbnail_service(request)
    return await asyncio.to_thread(
        svc.check_blur, target, lan.blur_tags, None, lan.library_root
    )


async def serve_blur_gated_raster(
    request: web.Request,
    target: Path,
    *,
    should_blur: bool,
    content_type: str,
    max_size: int,
    source_body: bytes,
    source_identity: FileIdentity | None = None,
    etag: str | None = None,
) -> web.StreamResponse:
    """Deliver captured raster bytes after the shared blur-policy decision.

    A ``should_blur`` asset is returned as the processed WEBP, and a failure is a
    500 — the original is never served for a blurred asset, otherwise an
    operational error would become a privacy leak.
    """
    if should_blur:
        svc = get_thumbnail_service(request)
        processed = await asyncio.to_thread(
            process_image_snapshot, svc, target, source_body, max_size, True,
            source_identity.as_tuple() if source_identity is not None else None,
        )
        if processed is None:
            return error_response(
                "Failed to process image",
                status=500,
                code="internal_error",
                headers=PRIVATE_PREVIEW_HEADERS,
            )
        body, processed_content_type = processed
        return web.Response(
            body=body,
            content_type=processed_content_type,
            headers=PRIVATE_PREVIEW_HEADERS,
        )
    return web.Response(
        body=source_body,
        content_type=content_type,
        headers={**MEDIA_CACHE_HEADERS, **({"ETag": etag} if etag else {})},
    )


MAX_ZIP_SOURCE_BYTES = 500 * 1024 * 1024


class _ZipBuildCancelled(Exception):
    """Internal worker exit after its requesting coroutine is cancelled."""


class _BoundedZipOutput(io.BufferedRandom):
    """Seekable output that rejects writes beyond its reserved disk extent.

    ZIP headers are rewritten in place, so summing writes would overcount.
    Checking the resulting offset before every write also includes compressor
    flushes and the central directory written by ``ZipFile.close``.
    """

    def __init__(self, raw: io.RawIOBase, max_bytes: int) -> None:
        super().__init__(raw)
        self._max_bytes = max_bytes

    def write(self, data: Any, /) -> int:
        if self.tell() + memoryview(data).nbytes > self._max_bytes:
            raise ZipLimitExceeded(f"ZIP output exceeds {self._max_bytes} bytes")
        return super().write(data)


def build_zip_sync(
    target_paths: list[tuple[Path, str | None]],
    zip_path: str,
    *,
    cancel_event: threading.Event | None = None,
) -> str | None:
    """Build an archive atomically from bounded, final-open source snapshots.

    Route size estimates are advisory: enforce the aggregate limit again on
    the opened files. Any read/write failure invalidates the entire archive,
    including failures detected after a member's last chunk was written.
    """
    remaining = MAX_ZIP_SOURCE_BYTES

    def check_cancelled() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise _ZipBuildCancelled()

    def add_member(zf: zipfile.ZipFile, root: Path, path: str | Path, name: str) -> None:
        nonlocal remaining
        check_cancelled()
        with closing(iter_safe_file(root, path)) as source:
            # Inspect the owned handle before any read. Traversal metadata
            # can be stale by the time this member is opened.
            if source.identity.size > remaining:
                raise ZipLimitExceeded("ZIP exceeds source byte limit")
            with zf.open(name, "w") as entry:
                for chunk in source:
                    check_cancelled()
                    if len(chunk) > remaining:
                        raise ZipLimitExceeded("ZIP exceeds source byte limit")
                    entry.write(chunk)
                    remaining -= len(chunk)

    try:
        check_cancelled()
        with io.FileIO(zip_path, "w+") as raw:
            with _BoundedZipOutput(raw, zip_resources.MAX_ZIP_OUTPUT_BYTES) as output:
                with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                    with closing(scan_zip_sources(
                        target_paths, source_limit=MAX_ZIP_SOURCE_BYTES,
                        check_cancelled=check_cancelled,
                    )) as sources:
                        for root, path, arc_name in sources:
                            add_member(zf, root, path, arc_name)
                        check_cancelled()
        return zip_path
    except Exception as exc:
        if isinstance(exc, _ZipBuildCancelled):
            _log.debug("Cancelled ZIP at %s", zip_path)
        else:
            _log.exception("Failed to create ZIP at %s", zip_path)
        try:
            os.unlink(zip_path)
        except OSError:
            pass
        if isinstance(exc, ZipLimitExceeded):
            raise
        return None


def _zip_executor_for(request: web.Request | None) -> concurrent.futures.Executor | None:
    """Resolve the LAN-owned ZIP executor for a request.

    L3: the executor is owned by the LAN server instance (published on the
    application key) so shutdown can close it symmetrically. Legacy test
    apps and request-less call paths return None and fall back to the
    loop's default executor.
    """
    if request is None:
        return None
    app = request.app
    executor = app.get(ZIP_EXECUTOR_APP_KEY) if isinstance(app, web.Application) else None
    if isinstance(executor, concurrent.futures.Executor):
        return executor
    try:
        executor = getattr(get_lan(request), "_zip_executor", None)
    except Exception:
        return None
    if isinstance(executor, concurrent.futures.Executor):
        return executor
    return None


async def build_zip_async(
    request: web.Request | None,
    targets: list[tuple[Path, str | None]],
    zip_path: str,
    *,
    reservation: ZipReservation | None = None,
) -> str | None:
    loop = asyncio.get_running_loop()
    executor = _zip_executor_for(request)
    if reservation is not None and reservation.reserved_bytes < zip_resources.MAX_ZIP_OUTPUT_BYTES:
        raise ValueError("ZIP reservation is smaller than the archive output limit")
    cancel_event = threading.Event()
    work_completed = threading.Event()
    worker_reservation = reservation.retain() if reservation is not None else None

    def release_cancelled_reservations() -> None:
        if reservation is not None:
            reservation.release()
        if worker_reservation is not None:
            worker_reservation.release()

    def finish_worker() -> None:
        # Runs in the worker (or a native Future callback), independently of
        # the request event loop. Old server loops may already have stopped.
        if cancel_event.is_set():
            cleanup_zip_path(zip_path, release_cancelled_reservations)
        elif worker_reservation is not None:
            worker_reservation.release()

    def run_build() -> str | None:
        try:
            return build_zip_sync(targets, zip_path, cancel_event=cancel_event)
        finally:
            work_completed.set()
            finish_worker()

    def queued_work_done(future: concurrent.futures.Future) -> None:
        if future.cancelled():
            # Executor shutdown may cancel a job before run_build executes.
            cancel_event.set()
            work_completed.set()
            finish_worker()

    submitted = None
    try:
        if executor is None:
            work = loop.run_in_executor(None, run_build)
        else:
            submitted = executor.submit(run_build)
            submitted.add_done_callback(queued_work_done)
            work = asyncio.wrap_future(submitted, loop=loop)
    except BaseException:
        cancel_event.set()
        if submitted is None:
            finish_worker()
        else:
            submitted.cancel()
            if work_completed.is_set():
                finish_worker()
        raise

    try:
        return await asyncio.shield(work)
    except asyncio.CancelledError:
        cancel_event.set()
        if submitted is not None:
            submitted.cancel()
        if work_completed.is_set():
            # Close the completion/cancellation race even when the worker
            # finished just before it could observe cancel_event.
            finish_worker()
        raise
