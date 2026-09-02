"""MCP read-only surface — token gating, handshake, tools (H2-d2)."""
import pytest

from AssetsManager.core.settings import LAN_MCP_TOKEN_KEY, AppSettings

pytestmark = pytest.mark.anyio


@pytest.fixture
async def app_and_client(tmp_path):
    """The full LAN app (with /mcp mounted) plus a test client."""
    from tests.lan.test_collection_routes import (
        _index_asset,
        _make_client,
        _make_lan_app,
    )

    app, library, conn = _make_lan_app(tmp_path)
    _index_asset(conn, library, "a")
    client = await _make_client(app)
    try:
        yield app, client, library
    finally:
        await client.close()
        _set_token("")


def _set_token(value: str):
    AppSettings.instance().set(LAN_MCP_TOKEN_KEY, value)


async def test_mcp_disabled_without_token_returns_404(app_and_client):
    app, client, _ = app_and_client
    _set_token("")
    response = await client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert response.status == 404


async def test_mcp_wrong_bearer_returns_401(app_and_client):
    app, client, _ = app_and_client
    _set_token("secret-token")
    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status == 401


async def test_mcp_initialize_handshake(app_and_client):
    app, client, _ = app_and_client
    _set_token("secret-token")
    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Authorization": "Bearer secret-token"},
    )
    assert response.status == 200
    payload = await response.json()
    assert payload["result"]["serverInfo"]["name"] == "assetmanager"
    assert payload["result"]["protocolVersion"]
    assert "tools" in payload["result"]["capabilities"]


async def test_mcp_tools_list(app_and_client):
    app, client, _ = app_and_client
    _set_token("secret-token")
    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers={"Authorization": "Bearer secret-token"},
    )
    payload = await response.json()
    names = {tool["name"] for tool in payload["result"]["tools"]}
    assert {
        "search_assets", "get_asset_metadata", "list_collections",
        "evaluate_smart_collection", "recent_activity",
    } <= names


async def test_mcp_tools_call_search_assets(app_and_client):
    app, client, _ = app_and_client
    _set_token("secret-token")
    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "search_assets", "arguments": {"query": "a"}}},
        headers={"Authorization": "Bearer secret-token"},
    )
    payload = await response.json()
    result = payload["result"]
    assert result["isError"] is False
    body = __import__("json").loads(result["content"][0]["text"])
    assert "results" in body


async def test_mcp_notification_returns_202(app_and_client):
    app, client, _ = app_and_client
    _set_token("secret-token")
    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={"Authorization": "Bearer secret-token"},
    )
    assert response.status == 202


async def test_mcp_unknown_method_returns_procedure_error(app_and_client):
    app, client, _ = app_and_client
    _set_token("secret-token")
    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 9, "method": "no/such/method"},
        headers={"Authorization": "Bearer secret-token"},
    )
    payload = await response.json()
    assert payload["error"]["code"] == -32601


async def test_mcp_batch_requests_are_rejected(app_and_client):
    app, client, _ = app_and_client
    _set_token("secret-token")
    response = await client.post(
        "/mcp",
        json=[{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}],
        headers={"Authorization": "Bearer secret-token"},
    )
    payload = await response.json()
    assert payload["error"]["code"] == -32600


async def test_mcp_chunked_body_is_bounded_without_content_length(app_and_client):
    """A chunked request cannot bypass the MCP body budget."""
    _app, client, _ = app_and_client
    _set_token("secret-token")
    oversized = b"{" + b"\"padding\":\"" + b"x" * 1_000_000 + b"\"}"

    async def body_chunks():
        for start in range(0, len(oversized), 32 * 1024):
            yield oversized[start:start + 32 * 1024]

    response = await client.post(
        "/mcp",
        data=body_chunks(),
        headers={
            "Authorization": "Bearer secret-token",
            "Content-Type": "application/json",
        },
    )
    assert response.status == 413
    assert await response.json() == {"error": "payload too large"}


async def test_mcp_tools_call_rejects_invalid_arguments(app_and_client):
    _app, client, _ = app_and_client
    _set_token("secret-token")
    response = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "search_assets",
                "arguments": {"limit": "100"},
            },
        },
        headers={"Authorization": "Bearer secret-token"},
    )
    payload = await response.json()
    assert response.status == 200
    assert payload["error"]["code"] == -32602
    assert "limit must be an integer" in payload["error"]["message"]


async def test_mcp_search_dispatches_service_on_worker_thread(app_and_client, monkeypatch):
    _app, client, _ = app_and_client
    _set_token("secret-token")
    from AssetsManager.lan import mcp_server

    calls: list[str] = []

    async def fake_to_thread(function, *args, **kwargs):
        calls.append(getattr(function, "__name__", repr(function)))
        return function(*args, **kwargs)

    monkeypatch.setattr(mcp_server.asyncio, "to_thread", fake_to_thread)
    response = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {"name": "search_assets", "arguments": {}},
        },
        headers={"Authorization": "Bearer secret-token"},
    )
    assert response.status == 200
    assert "search_structured_detailed" in calls
