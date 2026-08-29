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


def _insert_asset(conn, library, name, *, ext, size, mtime, kind="file"):
    # The LAN fixture DB carries the baseline schema only; the assets table
    # arrives with migration v2, so apply that exact DDL here.
    from AssetsManager.core.db_migrations import _add_assets_index_v2
    _add_assets_index_v2(conn)
    file_path = str(library / name)
    conn.execute(
        "INSERT INTO assets (file_path, name, extension, kind, size, mtime, parent_path, library_root) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (file_path, name, ext, kind, size, mtime, str(library), str(library)),
    )
    conn.commit()


@pytest.mark.anyio
async def test_search_structured_filters_route_indexed_only(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    _insert_asset(conn, library, "old.png", ext=".png", size=100, mtime=1000.0)
    _insert_asset(conn, library, "new.png", ext=".png", size=500, mtime=2000.0)
    _insert_asset(conn, library, "new.jpg", ext=".jpg", size=9000, mtime=2000.0)
    client = await _make_client(app)
    try:
        # Extension filter matches only indexed rows; the scanner source must
        # not appear (structured predicates run indexed-only by contract).
        response = await client.get("/api/search?ext=png&include_status=1")
        assert response.status == 200
        data = await response.json()
        assert data["count"] == 2
        assert {result["name"] for result in data["results"]} == {"old.png", "new.png"}
        assert [source["source"] for source in data["sources"]] == ["indexed"]

        # Size + mtime ranges (bounds inclusive).
        response = await client.get(
            "/api/search?size_min=400&mtime_after=1500&mtime_before=2000&include_status=1"
        )
        assert response.status == 200
        data = await response.json()
        assert [result["name"] for result in data["results"]] == ["new.jpg", "new.png"]

        # A name substring narrows the structured query.
        response = await client.get("/api/search?q=old&ext=png")
        assert response.status == 200
        data = await response.json()
        assert [result["name"] for result in data["results"]] == ["old.png"]

        # Order + offset run through the indexed source as well.
        response = await client.get("/api/search?ext=png&order=size&offset=1")
        assert response.status == 200
        data = await response.json()
        assert [result["name"] for result in data["results"]] == ["new.png"]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_search_structured_invalid_params_return_400(tmp_path):
    app, _library, _conn = _make_lan_app(tmp_path)
    client = await _make_client(app)
    try:
        for query, field in (
            ("size_min=abc", "size_min"),
            ("size_max=1.5", "size_max"),
            ("mtime_after=yesterday", "mtime_after"),
            ("order=unicorn", "order"),
            ("offset=-1", "offset"),
            ("offset=NaN", "offset"),
        ):
            response = await client.get(f"/api/search?{query}")
            assert response.status == 400, query
            data = await response.json()
            assert data["code"] == "validation_error", query
            assert data["field"] == field, query

        # No structured filter given: the legacy path is untouched (no 400s).
        response = await client.get("/api/search?q=anything")
        assert response.status == 200
    finally:
        await client.close()
