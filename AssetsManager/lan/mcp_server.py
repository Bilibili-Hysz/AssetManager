"""Read-only MCP (Model Context Protocol) surface on the LAN app (H2-d2).

Minimal hand-rolled MCP StreamableHTTP endpoint — stateless (no session
header), JSON-RPC 2.0 over a single POST route, zero additional
dependencies.  Rationale: the official python SDK is ASGI/Starlette based
while the LAN server is aiohttp; a stateless server only needs the
initialize / tools-list / tools-call triangle, which is smaller and more
testable than an ASGI bridge.

Gating (fail-closed): AppSettings ``lan_mcp_token`` — empty (the default)
means the route answers 404 (the surface is invisible, same posture as the
commerce feature flag); non-empty requires ``Authorization: Bearer
<token>`` (timing-safe compare).  v1 is strictly read-only: the five tools
project the library through the existing application services and there is
no write path.  Tool errors come back as MCP ``isError`` results, never as
transport 500s.  Heavy service calls run in a worker thread.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import math
from collections.abc import Mapping

from aiohttp import web

from AssetsManager.core.constants import APP_VERSION
from AssetsManager.core.settings import LAN_MCP_TOKEN_KEY, AppSettings

_log = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2025-06-18"
_MAX_BODY_BYTES = 1_000_000
_TOOL_OUTPUT_LIMIT = 200_000

_JSON_RPC_PARSE_ERROR = -32700
_JSON_RPC_INVALID_REQUEST = -32600
_JSON_RPC_INVALID_PARAMS = -32602
_JSON_RPC_METHOD_NOT_FOUND = -32601


class _InvalidToolArguments(ValueError):
    """Raised when a tools/call payload does not match the advertised schema."""


def _is_integer(value: object) -> bool:
    """Return whether *value* is a JSON integer (booleans are not integers)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    """Return whether *value* is a finite JSON number (booleans are not)."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _validate_tool_arguments(name: str, arguments: object) -> dict:
    """Validate and normalize one MCP tool argument mapping.

    The endpoint intentionally keeps this validator dependency-free.  The
    same constraints are reflected in ``_tool_definitions`` and are applied
    before dispatch so malformed values cannot turn into broad service
    exceptions or expensive unbounded queries.
    """
    if not isinstance(arguments, Mapping):
        raise _InvalidToolArguments("arguments must be an object")
    values = dict(arguments)

    specs: dict[str, set[str]] = {
        "search_assets": {
            "query", "ext", "size_min", "size_max", "mtime_after",
            "mtime_before", "limit", "offset",
        },
        "get_asset_metadata": {"path"},
        "list_collections": set(),
        "evaluate_smart_collection": {"collection_id", "limit", "offset"},
        "recent_activity": {"count"},
    }
    allowed = specs.get(name)
    if allowed is None:
        raise _InvalidToolArguments(f"unknown tool: {name}")
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise _InvalidToolArguments(
            "unknown argument(s): " + ", ".join(str(key) for key in unknown)
        )

    def require_string(key: str, *, max_length: int | None = None) -> None:
        value = values.get(key)
        if not isinstance(value, str):
            raise _InvalidToolArguments(f"{key} must be a string")
        if max_length is not None and len(value) > max_length:
            raise _InvalidToolArguments(f"{key} must be at most {max_length} characters")

    def optional_integer(
        key: str,
        *,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> None:
        if key not in values:
            return
        value = values[key]
        if not _is_integer(value):
            raise _InvalidToolArguments(f"{key} must be an integer")
        if minimum is not None and value < minimum:
            raise _InvalidToolArguments(f"{key} must be at least {minimum}")
        if maximum is not None and value > maximum:
            raise _InvalidToolArguments(f"{key} must be at most {maximum}")

    def optional_number(key: str) -> None:
        if key in values and not _is_number(values[key]):
            raise _InvalidToolArguments(f"{key} must be a finite number")

    if name == "search_assets":
        if "query" in values:
            require_string("query", max_length=256)
        if "ext" in values:
            require_string("ext", max_length=256)
        optional_integer("size_min", minimum=0)
        optional_integer("size_max", minimum=0)
        optional_number("mtime_after")
        optional_number("mtime_before")
        optional_integer("limit", minimum=0, maximum=100)
        optional_integer("offset", minimum=0)
        if (
            "size_min" in values and "size_max" in values
            and values["size_min"] > values["size_max"]
        ):
            raise _InvalidToolArguments("size_min must not exceed size_max")
        if (
            "mtime_after" in values and "mtime_before" in values
            and values["mtime_after"] > values["mtime_before"]
        ):
            raise _InvalidToolArguments("mtime_after must not exceed mtime_before")
    elif name == "get_asset_metadata":
        if "path" not in values:
            raise _InvalidToolArguments("path is required")
        require_string("path", max_length=4096)
        if not values["path"]:
            raise _InvalidToolArguments("path must not be empty")
    elif name == "evaluate_smart_collection":
        if "collection_id" not in values:
            raise _InvalidToolArguments("collection_id is required")
        optional_integer("collection_id", minimum=1)
        optional_integer("limit", minimum=0, maximum=100)
        optional_integer("offset", minimum=0)
    elif name == "recent_activity":
        optional_integer("count", minimum=0, maximum=200)

    return values


def _error_response(request_id, code: int, message: str) -> web.Response:
    return web.json_response(
        {"jsonrpc": "2.0", "id": request_id,
         "error": {"code": code, "message": message}},
        status=200,
    )


def _tool_definitions() -> list[dict]:
    """Static read-only tool catalog (Agent-readable descriptions)."""
    return [
        {
            "name": "search_assets",
            "description": (
                "Search the library index by name substring with optional "
                "extension/size/mtime filters. impact=read, approval=none."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "name substring"},
                    "ext": {"type": "string",
                            "description": "comma-separated extensions (e.g. 'jpg,png')"},
                    "size_min": {"type": "integer"},
                    "size_max": {"type": "integer"},
                    "mtime_after": {"type": "number"},
                    "mtime_before": {"type": "number"},
                    "limit": {"type": "integer", "maximum": 100},
                    "offset": {"type": "integer", "minimum": 0},
                },
            },
        },
        {
            "name": "get_asset_metadata",
            "description": (
                "Read one asset's metadata (tags/notes/urls) by library path. "
                "impact=read, approval=none."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
        {
            "name": "list_collections",
            "description": (
                "List user collections (manual + smart) with member counts. "
                "impact=read, approval=none."
            ),
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "evaluate_smart_collection",
            "description": (
                "Evaluate a smart collection's saved query and return the "
                "current member assets. impact=read, approval=none."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "collection_id": {"type": "integer"},
                    "limit": {"type": "integer", "maximum": 100},
                    "offset": {"type": "integer", "minimum": 0},
                },
                "required": ["collection_id"],
            },
        },
        {
            "name": "recent_activity",
            "description": (
                "Newest rows from the library activity log (desktop and LAN "
                "operations). impact=read, approval=none."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"count": {"type": "integer", "maximum": 200}},
            },
        },
    ]


async def _run_tool(request, name: str, arguments: dict) -> dict:
    """Dispatch one read-only tool; heavy bodies run in a worker thread."""
    from AssetsManager.lan.routes._helpers import (
        get_collection_service,
        get_lan,
        get_metadata_service,
        get_search_service,
        get_services,
    )

    services = get_services(request)
    library_root = get_lan(request).library_root
    if name == "search_assets":
        search_service = get_search_service(request)
        extensions = None
        if arguments.get("ext"):
            extensions = [
                e.strip().lower().lstrip(".")
                for e in str(arguments["ext"]).split(",") if e.strip()
            ]
        limit = min(int(arguments.get("limit", 50)), 100)
        offset = max(int(arguments.get("offset", 0)), 0)
        result_set = await asyncio.to_thread(
            search_service.search_structured_detailed,
            library_root,
            name_substring=str(arguments.get("query", "")),
            extensions=extensions,
            size_min=arguments.get("size_min"),
            size_max=arguments.get("size_max"),
            mtime_after=arguments.get("mtime_after"),
            mtime_before=arguments.get("mtime_before"),
            limit=limit,
            offset=offset,
        )
        from AssetsManager.lan.routes.metadata import search_result_response
        return {
            "count": len(result_set.results),
            "status": result_set.status.value,
            "results": [search_result_response(result) for result in result_set.results],
        }
    if name == "get_asset_metadata":
        metadata_service = get_metadata_service(request)
        metadata = await asyncio.to_thread(
            metadata_service.get_metadata,
            library_root, str(arguments["path"]),
        )
        from dataclasses import asdict
        return asdict(metadata)
    if name == "list_collections":
        collection_service = get_collection_service(request)
        collections = await asyncio.to_thread(
            collection_service.list_collections, library_root
        )
        from dataclasses import asdict
        return {"collections": [
            asdict(collection) if hasattr(collection, "__dataclass_fields__")
            else collection
            for collection in collections
        ]}
    if name == "evaluate_smart_collection":
        collection_service = get_collection_service(request)
        entries = await asyncio.to_thread(
            collection_service.evaluate,
            library_root, int(arguments["collection_id"]),
            limit=min(int(arguments.get("limit", 50)), 100),
            offset=max(int(arguments.get("offset", 0)), 0),
        )
        from dataclasses import asdict
        return {"count": len(entries),
                "entries": [asdict(entry) if hasattr(entry, "__dataclass_fields__")
                            else {"path": getattr(entry, "file_path", str(entry))}
                            for entry in entries]}
    if name == "recent_activity":
        activity_log = services.activity_log
        count = min(int(arguments.get("count", 50)), 200)
        rows = await asyncio.to_thread(activity_log.recent, count)
        return {"rows": [
            {"timestamp": row[0], "action": row[1],
             "username": row[2], "details": row[3]}
            for row in rows
        ]}
    raise KeyError(name)


async def handle_mcp_post(request: web.Request) -> web.Response:
    """Bearer-gated JSON-RPC 2.0 dispatch for the read-only MCP surface."""
    token = AppSettings.instance().get(LAN_MCP_TOKEN_KEY, "") or ""
    if not token:
        # Disabled: keep the surface invisible rather than 401-leaking that
        # the feature exists.
        raise web.HTTPNotFound
    auth = request.headers.get("Authorization", "")
    if not hmac.compare_digest(auth, f"Bearer {token}"):
        return web.json_response({"error": "unauthorized"}, status=401)

    # ``content_length`` is optional for HTTP/1.1 chunked requests.  Never
    # rely on it as the only body limit: read at most MAX_BODY_BYTES + 1 bytes
    # in bounded chunks, then reject the request if the extra byte exists.
    content_length = request.content_length
    if isinstance(content_length, int) and content_length > _MAX_BODY_BYTES:
        return web.json_response({"error": "payload too large"}, status=413)
    try:
        body_parts: list[bytes] = []
        body_size = 0
        while body_size <= _MAX_BODY_BYTES:
            chunk = await request.content.read(
                min(64 * 1024, _MAX_BODY_BYTES + 1 - body_size)
            )
            if not chunk:
                break
            body_parts.append(chunk)
            body_size += len(chunk)
            if body_size > _MAX_BODY_BYTES:
                return web.json_response({"error": "payload too large"}, status=413)
        payload = json.loads(b"".join(body_parts))
    except Exception:
        return _error_response(None, _JSON_RPC_PARSE_ERROR, "invalid JSON body")
    if not isinstance(payload, dict):
        return _error_response(None, _JSON_RPC_INVALID_REQUEST, "batch unsupported")
    method = payload.get("method")
    request_id = payload.get("id")
    if not isinstance(method, str):
        return _error_response(request_id, _JSON_RPC_INVALID_REQUEST, "missing method")

    if method.startswith("notifications/"):
        return web.Response(status=202)
    if method == "initialize":
        result = {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "assetmanager", "version": APP_VERSION},
        }
        return web.json_response({"jsonrpc": "2.0", "id": request_id, "result": result})
    if method == "ping":
        return web.json_response({"jsonrpc": "2.0", "id": request_id, "result": {}})
    if method == "tools/list":
        return web.json_response(
            {"jsonrpc": "2.0", "id": request_id, "result": {"tools": _tool_definitions()}})
    if method == "tools/call":
        params = payload.get("params")
        if params is None:
            params = {}
        if not isinstance(params, Mapping):
            return _error_response(request_id, _JSON_RPC_INVALID_PARAMS,
                                   "tools/call params must be an object")
        name = params.get("name")
        if not isinstance(name, str) or not name:
            return _error_response(request_id, _JSON_RPC_INVALID_PARAMS,
                                   "tools/call requires a tool name")
        arguments = params.get("arguments", {})
        try:
            validated_arguments = _validate_tool_arguments(name, arguments)
        except _InvalidToolArguments as exc:
            return _error_response(request_id, _JSON_RPC_INVALID_PARAMS, str(exc))
        try:
            payload_out = await _run_tool(request, name, validated_arguments)
            return web.json_response({
                "jsonrpc": "2.0", "id": request_id,
                "result": {"content": [{"type": "text", "text": json.dumps(
                    payload_out, ensure_ascii=False, default=str)}],
                    "isError": False},
            })
        except Exception as exc:
            _log.warning("MCP tool %s failed: %s", name, exc)
            return web.json_response({
                "jsonrpc": "2.0", "id": request_id,
                "result": {"content": [{"type": "text", "text": str(exc)}],
                           "isError": True},
            })
    return _error_response(request_id, _JSON_RPC_METHOD_NOT_FOUND,
                           f"unknown method {method}")
