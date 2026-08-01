"""Metadata routes: /api/meta/{path}, /api/search, /api/home, /api/tree, /api/projects, /api/projects/{path}."""
import asyncio
from time import perf_counter
from urllib.parse import unquote
from urllib.parse import urlparse

from aiohttp import web

from AssetsManager.application import ProjectDepthConfig
from AssetsManager.lan.dto import TreeItemResponse
from AssetsManager.lan.routes._helpers import (
    get_lan, validate_path, get_metadata_service, get_project_service,
    get_search_service, require_permission,
)
from AssetsManager.lan.routes._resource_urls import (
    project_detail_response, project_home_response, project_listing_response,
    search_result_response,
)


async def handle_meta(request):
    if not require_permission(request, "browse"):
        return web.json_response({"error": "Browse access required"}, status=403)
    lan = get_lan(request)
    rel_path = unquote(request.match_info.get("path", ""))
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


async def handle_search(request):
    lan = get_lan(request)
    started = perf_counter()
    outcome = "error"
    status = 500
    result_count = -1
    try:
        if not require_permission(request, "browse"):
            status = 403
            return web.json_response({"error": "Browse access required"}, status=status)
        query = request.query.get("q", "").lower()
        tags_param = request.query.get("tags", "")
        category = request.query.get("category", "all")

        tag_filter = [t.strip() for t in tags_param.split(",") if t.strip()] if tags_param else []

        svc = get_search_service(request)

        def _search():
            if tag_filter:
                return svc.search_by_tags(
                    lan.library_root, tag_filter, query=query, category=category,
                )
            if query:
                results = svc.search_by_name(query, category=category, scanner=lan.scanner)
                if not results:
                    results = svc.search_by_name_indexed(
                        lan.library_root, query, category=category,
                    )
                return results
            return []

        search_results = await asyncio.to_thread(_search)

        results = [search_result_response(result) for result in search_results]
        outcome = "success"
        status = 200
        result_count = len(results)
        return web.json_response({"results": results, "count": result_count})
    finally:
        _record_search_route(lan, started, outcome, status, result_count)


def _record_search_route(lan, started: float, outcome: str, status: int, result_count: int) -> None:
    recorder = getattr(lan, "performance_recorder", None)
    if recorder is None or not recorder.enabled:
        return
    try:
        recorder.record(
            "lan.search",
            (perf_counter() - started) * 1000,
            session_token=getattr(lan, "session_token", None),
            attributes={"outcome": outcome, "status": status, "result_count": result_count},
        )
    except Exception:
        # Observability must not change a route response or search fallback.
        pass


async def handle_home(request):
    if not require_permission(request, "browse"):
        return web.json_response({"error": "Browse access required"}, status=403)
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
        return web.json_response({"error": "Browse access required"}, status=403)
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
        return web.json_response({"error": "Browse access required"}, status=403)
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
        return web.json_response({"error": "Not a directory"}, status=404)

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
        return web.json_response({"error": "Permission denied"}, status=403)
    except OSError:
        return web.json_response({"error": "Failed to list projects"}, status=500)
    return web.json_response(project_listing_response(listing))


async def handle_project_detail(request):
    if not require_permission(request, "browse"):
        return web.json_response({"error": "Browse access required"}, status=403)
    lan = get_lan(request)
    rel_path = unquote(request.match_info["path"])
    target = validate_path(lan, rel_path)

    if not target.is_dir():
        return web.json_response({"error": "Project not found"}, status=404)

    try:
        detail = await asyncio.to_thread(
            get_project_service(request).get_project_detail,
            lan.library_root, target, rel_path=rel_path,
        )
    except OSError:
        return web.json_response({"error": "Failed to load project"}, status=500)
    return web.json_response(project_detail_response(detail))
