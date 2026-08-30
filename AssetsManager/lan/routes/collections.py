"""User-collection routes: /api/collections and its members/evaluate subpaths.

Reads require the ``browse`` capability (handler-enforced, like GET /api/tags);
writes reuse the existing ``write_tags`` capability via the shared
``_WRITE_TAG_BROWSE`` policy and the ``require_user_write`` helper, so no new
capability bit is introduced for user metadata. Collections are query views /
reference sets — no handler here moves or copies files.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from pathlib import Path

from aiohttp import web

from AssetsManager.domain.errors import DomainError, DuplicateError, ValidationError
from AssetsManager.lan.dto import CollectionResponse
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import (
    get_collection_service,
    get_lan,
    request_owner_key,
    require_permission,
    require_user_write,
    validated_existing_key,
)

_log = logging.getLogger(__name__)

_MAX_EVALUATE_LIMIT = 1000


def _collection_id(request) -> int | None:
    raw = request.match_info.get("id", "")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _relative_or_none(library_root: str, file_path: str) -> str | None:
    try:
        relative = Path(file_path).relative_to(Path(library_root))
    except ValueError:
        return None
    return relative.as_posix() if relative != Path(".") else ""


async def handle_collections(request):
    if not require_permission(request, "browse"):
        return error_response("Browse access required", status=403, code="forbidden")
    lan = get_lan(request)
    svc = get_collection_service(request)
    if svc is None:
        return error_response(
            "Collections service unavailable", status=503, code="unavailable"
        )
    try:
        collections = await asyncio.to_thread(svc.list_collections, lan.library_root)
    except Exception:
        _log.exception("Failed to list LAN collections")
        return error_response("Failed to list collections", status=500, code="internal_error")

    # Live asset counts for smart rows: each smart collection is a query
    # view, so its ``member_count`` is always 0 and clients need the
    # evaluated total. This is a deliberate N+1 — collections are few
    # (sidebar-sized lists) and each count is one indexed COUNT(*) query
    # (plus in-memory dimension intersection), which stays cheap. The
    # favorites dimension is viewer-scoped: counts use the requester's
    # owner key, so the same collection can report different totals per
    # viewer. A failing count degrades to no count (None) instead of
    # failing the whole listing.
    try:
        owner_key = request_owner_key(request)
    except web.HTTPException:
        owner_key = None

    payload = []
    for record in collections:
        response = CollectionResponse.from_record(record)
        if record.get("kind") == "smart":
            try:
                count = await asyncio.to_thread(
                    svc.evaluate_count, lan.library_root, record["id"],
                    favorite_owner_key=owner_key,
                )
                response = replace(response, asset_count=int(count))
            except Exception:
                _log.exception(
                    "Failed to count LAN smart collection %s", record.get("id")
                )
        payload.append(response.to_dict())
    return web.json_response({"collections": payload})


async def handle_create_collection(request):
    if not require_user_write(request):
        return error_response("Write access required", status=403, code="forbidden")
    lan = get_lan(request)
    svc = get_collection_service(request)
    if svc is None:
        return error_response(
            "Collections service unavailable", status=503, code="unavailable"
        )
    try:
        body = await request.json()
    except Exception:
        return error_response("Invalid request", status=400, code="bad_request")
    if not isinstance(body, dict):
        return error_response("Invalid request", status=400, code="bad_request")
    kind = body.get("kind", "manual")
    if kind not in ("manual", "smart"):
        return error_response("kind must be 'manual' or 'smart'", status=400, code="bad_request")
    try:
        if kind == "smart":
            query = body.get("query", {})
            collection = await asyncio.to_thread(
                svc.create_smart, lan.library_root, body.get("name", ""), query,
            )
        else:
            collection = await asyncio.to_thread(
                svc.create, lan.library_root, body.get("name", ""), "manual",
            )
        return web.json_response(
            {"collection": CollectionResponse.from_record(collection).to_dict()},
            status=201,
        )
    except ValidationError as exc:
        return error_response(exc)
    except DuplicateError as exc:
        return error_response(exc)
    except DomainError as exc:
        return error_response(exc)
    except Exception:
        _log.exception("Failed to create LAN collection")
        return error_response("Failed to create collection", status=500, code="internal_error")


async def handle_update_collection(request):
    if not require_user_write(request):
        return error_response("Write access required", status=403, code="forbidden")
    lan = get_lan(request)
    svc = get_collection_service(request)
    if svc is None:
        return error_response(
            "Collections service unavailable", status=503, code="unavailable"
        )
    collection_id = _collection_id(request)
    if collection_id is None:
        return error_response("Invalid collection id", status=400, code="bad_request")
    try:
        body = await request.json()
    except Exception:
        return error_response("Invalid request", status=400, code="bad_request")
    if not isinstance(body, dict):
        return error_response("Invalid request", status=400, code="bad_request")
    try:
        if "name" in body:
            await asyncio.to_thread(
                svc.rename, lan.library_root, collection_id, body["name"],
            )
        if "query" in body:
            await asyncio.to_thread(
                svc.update_query, lan.library_root, collection_id, body["query"],
            )
        if "name" not in body and "query" not in body:
            return error_response(
                "name or query required", status=400, code="bad_request"
            )
        return web.json_response({"ok": True})
    except ValidationError as exc:
        return error_response(exc)
    except DuplicateError as exc:
        return error_response(exc)
    except DomainError as exc:
        return error_response(exc)
    except Exception:
        _log.exception("Failed to update LAN collection")
        return error_response("Failed to update collection", status=500, code="internal_error")


async def handle_delete_collection(request):
    if not require_user_write(request):
        return error_response("Write access required", status=403, code="forbidden")
    lan = get_lan(request)
    svc = get_collection_service(request)
    if svc is None:
        return error_response(
            "Collections service unavailable", status=503, code="unavailable"
        )
    collection_id = _collection_id(request)
    if collection_id is None:
        return error_response("Invalid collection id", status=400, code="bad_request")
    try:
        await asyncio.to_thread(svc.delete, lan.library_root, collection_id)
        return web.json_response({"ok": True})
    except DomainError as exc:
        return error_response(exc)
    except Exception:
        _log.exception("Failed to delete LAN collection")
        return error_response("Failed to delete collection", status=500, code="internal_error")


async def handle_collection_members(request):
    if not require_permission(request, "browse"):
        return error_response("Browse access required", status=403, code="forbidden")
    lan = get_lan(request)
    svc = get_collection_service(request)
    if svc is None:
        return error_response(
            "Collections service unavailable", status=503, code="unavailable"
        )
    collection_id = _collection_id(request)
    if collection_id is None:
        return error_response("Invalid collection id", status=400, code="bad_request")
    try:
        members = await asyncio.to_thread(
            svc.get_members, lan.library_root, collection_id,
        )
    except DomainError as exc:
        return error_response(exc)
    except Exception:
        _log.exception("Failed to list LAN collection members")
        return error_response("Failed to list members", status=500, code="internal_error")
    payload = []
    for member in members:
        relative = _relative_or_none(lan.library_root, member["file_path"])
        if relative is None:
            continue
        payload.append({
            "path": relative,
            "added_at": member["added_at"],
            "exists": bool(member["exists"]),
        })
    return web.json_response({"members": payload})


async def _member_paths(request) -> list[str]:
    try:
        body = await request.json()
    except Exception:
        raise ValidationError("paths", "must be a JSON body") from None
    if not isinstance(body, dict) or not isinstance(body.get("paths"), list):
        raise ValidationError("paths", "must be a list of library paths")
    paths = body["paths"]
    if not paths or not all(isinstance(p, str) and p.strip() for p in paths):
        raise ValidationError("paths", "must be a non-empty list of library paths")
    lan = get_lan(request)
    return [validated_existing_key(lan, path) for path in paths]


async def handle_add_collection_members(request):
    if not require_user_write(request):
        return error_response("Write access required", status=403, code="forbidden")
    lan = get_lan(request)
    svc = get_collection_service(request)
    if svc is None:
        return error_response(
            "Collections service unavailable", status=503, code="unavailable"
        )
    collection_id = _collection_id(request)
    if collection_id is None:
        return error_response("Invalid collection id", status=400, code="bad_request")
    try:
        paths = await _member_paths(request)
        added = await asyncio.to_thread(
            svc.add_files, lan.library_root, collection_id, paths,
        )
        return web.json_response({"added": added})
    except web.HTTPException:
        raise
    except ValidationError as exc:
        return error_response(exc)
    except DomainError as exc:
        return error_response(exc)
    except Exception:
        _log.exception("Failed to add LAN collection members")
        return error_response("Failed to add members", status=500, code="internal_error")


async def handle_remove_collection_members(request):
    if not require_user_write(request):
        return error_response("Write access required", status=403, code="forbidden")
    lan = get_lan(request)
    svc = get_collection_service(request)
    if svc is None:
        return error_response(
            "Collections service unavailable", status=503, code="unavailable"
        )
    collection_id = _collection_id(request)
    if collection_id is None:
        return error_response("Invalid collection id", status=400, code="bad_request")
    try:
        paths = await _member_paths(request)
        removed = await asyncio.to_thread(
            svc.remove_files, lan.library_root, collection_id, paths,
        )
        return web.json_response({"removed": removed})
    except web.HTTPException:
        raise
    except ValidationError as exc:
        return error_response(exc)
    except DomainError as exc:
        return error_response(exc)
    except Exception:
        _log.exception("Failed to remove LAN collection members")
        return error_response("Failed to remove members", status=500, code="internal_error")


async def handle_collection_evaluate(request):
    if not require_permission(request, "browse"):
        return error_response("Browse access required", status=403, code="forbidden")
    lan = get_lan(request)
    svc = get_collection_service(request)
    if svc is None:
        return error_response(
            "Collections service unavailable", status=503, code="unavailable"
        )
    collection_id = _collection_id(request)
    if collection_id is None:
        return error_response("Invalid collection id", status=400, code="bad_request")
    try:
        limit = int(request.query.get("limit", "200"))
        offset = int(request.query.get("offset", "0"))
    except ValueError:
        return error_response("limit/offset must be integers", status=400, code="bad_request")
    if limit < 1 or limit > _MAX_EVALUATE_LIMIT or offset < 0:
        return error_response("limit/offset out of range", status=400, code="bad_request")
    # A favorite predicate in the saved query is viewer-scoped: it is
    # evaluated against the requesting principal's owner key.
    owner_key = request_owner_key(request)
    try:
        entries = await asyncio.to_thread(
            svc.evaluate, lan.library_root, collection_id, limit, offset,
            favorite_owner_key=owner_key,
        )
    except ValidationError as exc:
        return error_response(exc)
    except DomainError as exc:
        return error_response(exc)
    except Exception:
        _log.exception("Failed to evaluate LAN collection")
        return error_response("Failed to evaluate collection", status=500, code="internal_error")
    results = []
    for entry in entries:
        relative = _relative_or_none(lan.library_root, entry.file_path)
        if relative is None:
            continue
        results.append({
            "path": relative,
            "name": entry.name,
            "extension": entry.extension,
            "size": entry.size,
            "mtime": entry.mtime,
        })
    return web.json_response({"results": results})
