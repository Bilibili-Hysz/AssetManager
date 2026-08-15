"""Public Commerce catalog and item-management HTTP routes."""
from __future__ import annotations

from pathlib import Path

from aiohttp import web

from AssetsManager.application.shop_authorization import (
    UnauthorizedShopPathError,
)
from AssetsManager.domain.errors import (
    MissingPathError,
    NotFoundError,
    ValidationError,
)
from AssetsManager.lan.path_guard import PathGuardError, assert_under_root
from AssetsManager.lan.routes.commerce_policy import (
    seller_gate,
)
from AssetsManager.lan.routes.shop._common import (
    _catalog_query_value,
    _error_response,
    _item_id,
    _log,
    _package_function,
)


async def handle_shop_items(request: web.Request) -> web.Response:
    disabled = _package_function("commerce_gate")() if request.method == "GET" else seller_gate()
    if disabled is not None:
        return disabled
    lan = _package_function("get_lan")(request)
    services = _package_function("get_commerce_services")(request)
    try:
        if request.method == "GET":
            seller = await _package_function("require_seller")(request)
            requested_status = request.query.get("status")
            if requested_status is not None:
                requested_status = requested_status.strip().lower()
                if requested_status not in {"active", "draft", "archived"}:
                    raise ValidationError("status", "must be active, archived, or draft")
            # Public catalog responses are always active. Sellers retain the
            # legacy include_disabled gate for non-active catalog states.
            include_disabled = seller is not None and request.query.get("include_disabled") in {"1", "true"}
            list_kwargs = {
                "include_disabled": include_disabled,
                "status": requested_status if seller is not None else "active",
            }
            return web.json_response({"items": services.shop.list_items(
                lan.library_root, **list_kwargs
            )})
        seller = await _package_function("require_seller")(request)
        if seller is None:
            return _error_response("Seller authentication required", status=403, code="forbidden")
        body = await _package_function("_json_body")(request) if (request.can_read_body and (request.content_length or 0) > 0) else {}
        if request.method == "POST":
            item = services.shop.create_item(lan.library_root, body)
            return web.json_response({"item": item}, status=201)
        item_id = _item_id(request, body)
        if request.method == "PUT":
            item = services.shop.update_item(lan.library_root, item_id, body)
            return web.json_response({"item": item})
        deleted = services.shop.delete_item(lan.library_root, item_id)
        return web.json_response({"ok": deleted})
    except Exception as exc:
        return _error_response(exc)


async def handle_public_shop_catalog(request: web.Request) -> web.Response:
    """Serve a paginated public Commerce catalog without seller authentication."""
    disabled = _package_function("commerce_gate")()
    if disabled is not None:
        return disabled
    try:
        lan = _package_function("get_lan")(request)
        services = _package_function("get_commerce_services")(request)
        q = _catalog_query_value(request, "q")
        raw_page = _catalog_query_value(request, "page", "1")
        raw_page_size = _catalog_query_value(request, "page_size", "24")
        sort = _catalog_query_value(request, "sort", "newest")
        try:
            page = int(raw_page if raw_page is not None else "1")
        except (TypeError, ValueError) as exc:
            raise ValidationError("page", "must be an integer") from exc
        try:
            page_size = int(raw_page_size if raw_page_size is not None else "24")
        except (TypeError, ValueError) as exc:
            raise ValidationError("page_size", "must be an integer") from exc
        catalog = services.shop.list_catalog(
            lan.library_root,
            q=q,
            page=page,
            page_size=page_size,
            sort=sort,
        )
        return web.json_response(catalog)
    except Exception as exc:
        return _error_response(exc)

async def handle_public_shop_item(request: web.Request) -> web.Response:
    """Serve one active Commerce item without requiring seller authentication."""
    disabled = _package_function("commerce_gate")()
    if disabled is not None:
        return disabled
    try:
        lan = _package_function("get_lan")(request)
        services = _package_function("get_commerce_services")(request)
        item = services.shop.get_public_item(lan.library_root, _item_id(request))
        return web.json_response({"item": item})
    except Exception as exc:
        return _error_response(exc)


async def handle_public_shop_item_by_path(request: web.Request) -> web.Response:
    """Serve one active Commerce item addressed by its relative library path."""
    disabled = _package_function("commerce_gate")()
    if disabled is not None:
        return disabled
    try:
        lan = _package_function("get_lan")(request)
        services = _package_function("get_commerce_services")(request)
        item = services.shop.get_public_item_by_path(
            lan.library_root, request.query.get("path")
        )
        return web.json_response({"item": item})
    except Exception as exc:
        return _error_response(exc)


async def handle_public_shop_item_media(request: web.Request) -> web.StreamResponse:
    """Serve only the selected media slot of an active public Commerce item."""
    disabled = _package_function("commerce_gate")()
    if disabled is not None:
        return disabled
    try:
        lan = _package_function("get_lan")(request)
        services = _package_function("get_commerce_services")(request)
        item_id = _item_id(request)
        slot = request.match_info.get("slot", "")
        relative = services.shop.get_public_item_media_path(lan.library_root, item_id, slot)
        try:
            size = min(max(int(request.query.get("size", "512")), 16), 2048)
        except (TypeError, ValueError):
            size = 512
        # The media path comes from the database, not the query string, but it
        # must still be confined to the library root — resolve + containment
        # go through the shared predicate so no route re-implements it.
        try:
            target = assert_under_root(lan.library_root, Path(lan.library_root) / relative)
        except (PathGuardError, ValueError, OSError):
            return web.Response(status=404)
        return await _package_function("serve_verified_image")(request, target, max_size=size, public=True)
    except Exception as exc:
        if isinstance(exc, (NotFoundError, MissingPathError, UnauthorizedShopPathError, ValueError, LookupError)):
            return web.Response(status=404)
        _log.exception("Public Commerce media delivery failed")
        return web.Response(status=404)
