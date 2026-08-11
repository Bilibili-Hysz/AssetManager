from __future__ import annotations

from dataclasses import replace

import pytest
from PIL import Image

from AssetsManager.application.gallery_service import GalleryService
from AssetsManager.lan.routes._helpers import LAN_APP_KEY
from tests.lan.test_lan_api import _make_client, _make_lan_app


def _image(path, size=(32, 16)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (50, 90, 150)).save(path)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_gallery_routes_expose_home_collection_and_resolve_contract(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    _image(library / "set" / "art.png")
    (library / "set" / "notes.txt").write_text("notes", encoding="utf-8")
    lan = app[LAN_APP_KEY]
    lan.services = replace(
        lan.services,
        gallery_service=GalleryService(connection_provider=lan.connection_for),
    )
    client = await _make_client(app)
    try:
        home = await client.get("/api/gallery/home")
        assert home.status == 200
        home_payload = await home.json()
        assert home_payload["projects"][0]["path"] == "set"
        assert home_payload["stats"]["artworks"] == 1

        collection = await client.get("/api/gallery/collection?path=set&sort=name")
        assert collection.status == 200
        collection_payload = await collection.json()
        assert collection_payload["collection"]["kind"] == "project"
        assert collection_payload["entries"][0]["thumbnail_url"] == "/api/thumbnails/set/art.png?size=512"

        resolved = await client.get("/api/gallery/resolve?path=set%2Fart.png")
        assert resolved.status == 200
        assert await resolved.json() == {
            "kind": "artwork",
            "path": "set/art.png",
            "gallery_context": "set",
            "workspace_context": "set",
        }
    finally:
        await client.close()


@pytest.mark.anyio
async def test_gallery_routes_guard_paths_and_missing_collections(tmp_path):
    app, library, _conn = _make_lan_app(tmp_path)
    lan = app[LAN_APP_KEY]
    lan.services = replace(
        lan.services,
        gallery_service=GalleryService(connection_provider=lan.connection_for),
    )
    client = await _make_client(app)
    try:
        escape = await client.get("/api/gallery/collection?path=..%2Foutside")
        assert escape.status == 400
        missing = await client.get("/api/gallery/collection?path=missing")
        assert missing.status == 404
        non_gallery = await client.get("/api/gallery/resolve?path=missing")
        assert non_gallery.status == 404
    finally:
        await client.close()
