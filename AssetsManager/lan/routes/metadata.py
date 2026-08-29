"""Metadata routes: /api/meta/{path}, /api/search, /api/home, /api/tree, /api/projects, /api/projects/{path}."""
import asyncio
import logging
import sqlite3
from time import perf_counter
from urllib.parse import urlparse

from aiohttp import web

from AssetsManager.application import ProjectDepthConfig
from AssetsManager.application.search_service import SearchError, SearchResultSet, SearchStatus
from AssetsManager.domain.errors import DomainError, ValidationError
from AssetsManager.lan.dto import TreeItemResponse
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import (
    get_lan, validate_path, get_metadata_service, get_project_service,
    get_search_service, oversized_query, require_permission, require_user_write,
    validated_existing_key,
)
from AssetsManager.lan.routes._telemetry import record_route_event
from AssetsManager.lan.routes._resource_urls import (
    project_detail_response, project_home_response, project_listing_response,
    search_result_response,
)


_log = logging.getLogger(__name__)


MAX_NOTES_LENGTH = 4000

# Structured-search order whitelist (must mirror the repository's whitelist).
_SEARCH_ORDER_VALUES = ("name", "size", "mtime")
_SEARCH_STRUCTURED_LIMIT = 200


def _parse_structured_search_params(request) -> dict:
    """Parse optional structured-filter query params, 400 on malformed values.

    Returns a dict with ``filters`` (the structured predicate set, possibly
    empty), ``order``, and ``offset``. ``size_*`` are bytes (int);
    ``mtime_*`` are epoch seconds (float), matching the assets.mtime column.
    """
    extensions_raw = request.query.get("ext", "")
    extensions = [
        ext.lower().lstrip(".")
        for ext in (raw.strip() for raw in extensions_raw.split(","))
        if ext
    ]

    def _number(field: str, converter):
        raw = request.query.get(field)
        if raw is None or raw == "":
            return None
        try:
            return converter(raw)
        except (TypeError, ValueError):
            raise ValidationError(field, f"must be a valid {'integer' if converter is int else 'number'}") from None

    size_min = _number("size_min", int)
    size_max = _number("size_max", int)
    mtime_after = _number("mtime_after", float)
    mtime_before = _number("mtime_before", float)

    order = request.query.get("order", "name").lower()
    if order not in _SEARCH_ORDER_VALUES:
        raise ValidationError("order", f"must be one of {list(_SEARCH_ORDER_VALUES)}")

    try:
        offset = int(request.query.get("offset", "0"))
    except (TypeError, ValueError):
        raise ValidationError("offset", "must be an integer") from None
    if offset < 0:
        raise ValidationError("offset", "must be non-negative")

    filters = {
        "extensions": extensions or None,
        "size_min": size_min,
        "size_max": size_max,
        "mtime_after": mtime_after,
        "mtime_before": mtime_before,
    }
    return {"filters": filters, "order": order, "offset": offset}


async def handle_meta(request):
    if not require_permission(request, "browse"):
        return error_response("Browse access required", status=403, code="forbidden")
    lan = get_lan(request)
    rel_path = request.match_info.get("path", "")  # aiohttp decodes match_info once
    target = validate_path(lan, rel_path)
    svc = get_metadata_service(request)

    metadata = await asyncio.to_thread(
        svc.get_metadata, lan.library_root, target
    )
    urls = []
    for url in metadata.urls:
        try:
            parsed = urlparse(url)
        except ValueError:
            continue
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            urls.append(url)
    return web.json_response({
        "path": rel_path,
        "tags": list(metadata.tags),
        "notes": metadata.notes,
        "urls": urls,
    })


async def handle_save_notes(request):
    """Persist notes for an existing library path (admin or can_write user)."""
    if not require_user_write(request):
        return error_response("Write access required", status=403, code="forbidden")

    lan = get_lan(request)
    rel_path = request.match_info.get("path", "")  # aiohttp decodes match_info once
    if not rel_path:
        return error_response("path required", status=400, code="bad_request")

    try:
        body = await request.json()
    except Exception:
        return error_response("Invalid request", status=400, code="bad_request")
    if not isinstance(body, dict):
        return error_response("Invalid request", status=400, code="bad_request")

    notes = body.get("notes")
    if not isinstance(notes, str):
        return error_response("notes must be a string", status=400, code="bad_request")
    if len(notes) > MAX_NOTES_LENGTH:
        return error_response(
            f"notes must be at most {MAX_NOTES_LENGTH} characters",
            status=400,
            code="bad_request",
        )

    try:
        key = validated_existing_key(lan, rel_path)
        await asyncio.to_thread(
            get_metadata_service(request).set_notes,
            lan.library_root,
            key,
            notes,
        )
    except web.HTTPException:
        raise
    except DomainError as exc:
        # validated_existing_key now propagates domain path errors
        # (escape / missing) instead of bare HTTPExceptions; they keep
        # their centrally mapped JSON contract here (shape unification).
        return error_response(exc)
    except Exception:
        _log.exception("Failed to save LAN notes")
        return error_response("Failed to save notes", status=500, code="internal_error")

    return web.json_response({"ok": True, "path": rel_path, "notes": notes})


async def handle_search(request):
    lan = get_lan(request)
    started = perf_counter()
    outcome = "error"
    status = 500
    result_count = -1
    search_status: str | None = None
    try:
        if not require_permission(request, "browse"):
            status = 403
            return error_response("Browse access required", status=status, code="forbidden")
        query_error = oversized_query(request)
        if query_error is not None:
            status = 400
            return error_response(query_error, status=400, code="bad_request")
        try:
            structured = _parse_structured_search_params(request)
        except ValidationError as exc:
            status = 400
            return error_response(exc)
        query = request.query.get("q", "").lower()
        tags_param = request.query.get("tags", "")
        category = request.query.get("category", "all")
        include_status = request.query.get("include_status", "").lower() in {"1", "true", "yes"}

        tag_filter = [t.strip() for t in tags_param.split(",") if t.strip()] if tags_param else []

        svc = get_search_service(request)

        def _search() -> SearchResultSet:
            if any(value is not None for value in structured["filters"].values()):
                # Structured predicates (extension/size/mtime) are only
                # executable efficiently by the assets index; the scanner
                # source cannot apply them without a full in-memory scan, so
                # a structured search deliberately runs indexed-only. The
                # name substring (q) still narrows the indexed query. When a
                # tag filter is combined with structured filters, the
                # structured predicate set wins (tags are not merged here).
                return svc.search_structured_detailed(
                    lan.library_root,
                    name_substring=query,
                    category=category,
                    order_by=structured["order"],
                    offset=structured["offset"],
                    limit=_SEARCH_STRUCTURED_LIMIT,
                    **structured["filters"],
                )
            if tag_filter:
                return svc.search_by_tags_detailed(
                    lan.library_root, tag_filter, query=query, category=category,
                )
            if query:
                primary = svc.search_by_name_detailed(
                    query, category=category, scanner=lan.scanner,
                )
                if primary.results:
                    return primary
                try:
                    fallback = svc.search_by_name_indexed_detailed(
                        lan.library_root, query, category=category,
                    )
                except sqlite3.OperationalError:
                    # The indexed source is optional for legacy LAN fixtures and
                    # older libraries. Preserve the default response shape while
                    # retaining the failure in the opt-in detailed contract.
                    fallback = SearchResultSet.from_source(
                        "indexed",
                        status=SearchStatus.ERROR,
                        errors=(SearchError("search_source_failed", "indexed", recoverable=True),),
                    )
                return SearchResultSet.merge(primary, fallback, fallback_used=True)
            return SearchResultSet.from_source("request", status=SearchStatus.EMPTY)

        result_set = await asyncio.to_thread(_search)

        results = [search_result_response(result) for result in result_set.results]
        outcome = "success"
        status = 200
        result_count = len(results)
        search_status = result_set.status.value
        response = {"results": results, "count": result_count}
        if include_status:
            response["status"] = result_set.status.value
            response["sources"] = [
                {
                    "source": source.source,
                    "status": source.status.value,
                    "result_count": source.result_count,
                    "dropped_count": source.dropped_count,
                    "error_count": source.error_count,
                }
                for source in result_set.sources
            ]
            response["errors"] = [
                {
                    "code": error.code,
                    "source": error.source,
                    "recoverable": error.recoverable,
                }
                for error in result_set.errors
            ]
            response["dropped_count"] = result_set.dropped_count
            response["fallback_used"] = result_set.fallback_used
        return web.json_response(response)
    finally:
        record_route_event(
            lan,
            "lan.search",
            started=started,
            status=status,
            outcome=outcome,
            result_count=result_count,
            search_status=search_status,
        )


async def handle_home(request):
    if not require_permission(request, "browse"):
        return error_response("Browse access required", status=403, code="forbidden")
    lan = get_lan(request)

    from AssetsManager.core.settings import AppSettings
    depth_config = ProjectDepthConfig.from_dict(AppSettings.instance().get("sidebar_depth_cfg"))

    home = await asyncio.to_thread(
        get_project_service(request).get_home,
        lan.library_root, depth_config=depth_config,
    )
    return web.json_response(project_home_response(home))


async def handle_tree(request):
    if not require_permission(request, "browse"):
        return error_response("Browse access required", status=403, code="forbidden")
    lan = get_lan(request)

    from AssetsManager.core.settings import AppSettings
    depth_config = ProjectDepthConfig.from_dict(AppSettings.instance().get("sidebar_depth_cfg"))

    tree = await asyncio.to_thread(
        get_project_service(request).build_tree, lan.library_root, depth_config=depth_config
    )
    response = tree.to_response()
    response["tree"] = [TreeItemResponse.from_record(item).to_dict() for item in response["tree"]]
    return web.json_response(response)


async def handle_projects(request):
    if not require_permission(request, "browse"):
        return error_response("Browse access required", status=403, code="forbidden")
    lan = get_lan(request)
    rel_path = request.query.get("path", "")
    sort_by = request.query.get("sort", "name")
    order = request.query.get("order", "asc")
    search = request.query.get("search", "").lower()
    try:
        offset = max(int(request.query.get("offset", "0")), 0)
    except (ValueError, TypeError):
        offset = 0
    try:
        limit = max(int(request.query.get("limit", "0")), 0)
    except (ValueError, TypeError):
        limit = 0

    target = validate_path(lan, rel_path)
    if not target.is_dir():
        return error_response("Not a directory", status=404, code="not_found")

    from AssetsManager.core.settings import AppSettings
    depth_config = ProjectDepthConfig.from_dict(AppSettings.instance().get("sidebar_depth_cfg"))
    try:
        listing = await asyncio.to_thread(
            get_project_service(request).list_projects,
            lan.library_root, target,
            rel_path=rel_path, sort_by=sort_by, order=order, search=search,
            depth_config=depth_config,
            offset=offset, limit=limit,
        )
    except PermissionError:
        return error_response("Permission denied", status=403, code="forbidden")
    except OSError:
        return error_response("Failed to list projects", status=500, code="internal_error")
    return web.json_response(project_listing_response(listing))


async def handle_project_detail(request):
    if not require_permission(request, "browse"):
        return error_response("Browse access required", status=403, code="forbidden")
    lan = get_lan(request)
    rel_path = request.match_info["path"]  # aiohttp decodes match_info once
    target = validate_path(lan, rel_path)

    if not target.is_dir():
        return error_response("Project not found", status=404, code="not_found")

    try:
        detail = await asyncio.to_thread(
            get_project_service(request).get_project_detail,
            lan.library_root, target, rel_path=rel_path,
        )
    except OSError:
        return error_response("Failed to load project", status=500, code="internal_error")
    return web.json_response(project_detail_response(detail))
