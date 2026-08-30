"""LAN route tests for /api/sequence/neighbors (media stack N-C)."""
from __future__ import annotations

import pytest
from PIL import Image

from tests.lan.support.api_helpers import _make_client, _make_lan_app, _local_ui_headers


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _frame(path, color=(60, 120, 200)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), color).save(path)


@pytest.mark.anyio
async def test_sequence_neighbors_require_browse_capability(tmp_path, monkeypatch):
    from AssetsManager.core.settings import AppSettings

    class _NoGuestBrowseSettings:
        def get(self, key, default=None):
            return {"lan_guest_list": False}.get(key, default)

    monkeypatch.setattr(
        AppSettings, "instance", classmethod(lambda cls: _NoGuestBrowseSettings()))
    app, library, _conn = _make_lan_app(tmp_path)
    _frame(library / "shots" / "render.0001.png")
    _frame(library / "shots" / "render.0002.png")
    _frame(library / "shots" / "render.0003.png")
    client = await _make_client(app)
    try:
        response = await client.get(
            "/api/sequence/neighbors", params={"path": "shots/render.0001.png"})
        assert response.status == 403
        body = await response.json()
        assert body["code"] == "forbidden"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_sequence_neighbors_for_sequence_member(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    frames = [library / "shots" / f"render.{i:04d}.png" for i in range(1, 5)]
    for frame in frames:
        _frame(frame)
    client = await _make_client(app)
    try:
        response = await client.get(
            "/api/sequence/neighbors",
            params={"path": "shots/render.0002.png"},
            headers=_local_ui_headers(app),
        )
        assert response.status == 200
        body = await response.json()
        assert body["sequence"] is True
        assert body["index"] == 1
        assert body["count"] == 4
        assert body["prev"] == "shots/render.0001.png"
        assert body["next"] == "shots/render.0003.png"
        assert body["fps"] is None
    finally:
        await client.close()


@pytest.mark.anyio
async def test_sequence_neighbors_non_member_reports_flat_payload(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    _frame(library / "solo.png")
    # A two-frame prefix never qualifies (>=3 frames required).
    _frame(library / "pair.0001.png")
    _frame(library / "pair.0002.png")
    client = await _make_client(app)
    try:
        for name in ("solo.png", "pair.0001.png"):
            response = await client.get(
                "/api/sequence/neighbors",
                params={"path": name},
                headers=_local_ui_headers(app),
            )
            assert response.status == 200
            body = await response.json()
            assert body == {
                "sequence": False, "index": None, "count": 0,
                "prev": None, "next": None, "fps": None,
            }
    finally:
        await client.close()


@pytest.mark.anyio
async def test_sequence_neighbors_rejects_outside_library_paths(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    outside = tmp_path / "outside.png"
    _frame(outside)
    client = await _make_client(app)
    try:
        escaped = await client.get(
            "/api/sequence/neighbors",
            params={"path": "../outside.png"},
            headers=_local_ui_headers(app),
        )
        assert escaped.status == 400
        missing = await client.get(
            "/api/sequence/neighbors",
            params={"path": "no/such/frame.png"},
            headers=_local_ui_headers(app),
        )
        assert missing.status == 404
        empty = await client.get(
            "/api/sequence/neighbors", headers=_local_ui_headers(app))
        assert empty.status == 400
    finally:
        await client.close()
