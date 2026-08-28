"""LAN search result projection compatibility and opt-in status tests."""

from __future__ import annotations

import pytest

from tests.lan.support.api_helpers import _make_client, _make_lan_app


@pytest.mark.anyio
async def test_search_default_response_keeps_legacy_shape(tmp_path):
    app, _library, _conn = _make_lan_app(tmp_path)
    client = await _make_client(app)
    try:
        response = await client.get("/api/search?include_status=1")
        assert response.status == 200
        data = await response.json()
        assert set(data) == {"results", "count", "status", "sources", "errors", "dropped_count", "fallback_used"}
        assert data["status"] == "empty"
        assert data["sources"] == [{
            "source": "request",
            "status": "empty",
            "result_count": 0,
            "dropped_count": 0,
            "error_count": 0,
        }]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_search_query_exposes_degraded_fallback_without_changing_default_shape(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    (library / "not-the-query.txt").write_text("content")
    client = await _make_client(app)
    try:
        default_response = await client.get("/api/search?q=missing")
        assert default_response.status == 200
        default_data = await default_response.json()
        assert set(default_data) == {"results", "count"}

        detailed_response = await client.get("/api/search?q=missing&include_status=1")
        assert detailed_response.status == 200
        detailed_data = await detailed_response.json()
        assert detailed_data["count"] == 0
        assert detailed_data["status"] == "degraded"
        assert detailed_data["fallback_used"] is True
        assert {source["source"] for source in detailed_data["sources"]} == {"scanner", "indexed"}
    finally:
        await client.close()
