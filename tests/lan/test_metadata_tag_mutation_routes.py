from __future__ import annotations

import pytest

from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import AssetNotesChanged, AssetTagsChanged
from tests.lan.test_lan_api import _local_ui_headers, _make_client, _make_lan_app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_notes_route_is_admin_only_path_guarded_and_evented(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    target = library / "folder" / "asset.txt"
    target.parent.mkdir()
    target.write_text("asset", encoding="utf-8")
    events = []
    subscription = get_event_bus().subscribe(AssetNotesChanged, events.append)
    client = await _make_client(app)
    try:
        guest = await client.put("/api/notes/folder%2Fasset.txt", json={"notes": "guest"})
        assert guest.status == 403

        response = await client.put(
            "/api/notes/folder%2Fasset.txt",
            json={"notes": "hello\nworld"},
            headers=_local_ui_headers(app),
        )
        assert response.status == 200
        assert await response.json() == {
            "ok": True,
            "path": "folder/asset.txt",
            "notes": "hello\nworld",
        }
        assert conn.execute(
            "SELECT notes FROM file_meta WHERE file_path=?", (str(target.resolve()),)
        ).fetchone() == ("hello\nworld",)
        assert len(events) == 1
        assert events[0].file_path == str(target.resolve())

        invalid_type = await client.put(
            "/api/notes/folder%2Fasset.txt", json={"notes": None}, headers=_local_ui_headers(app)
        )
        assert invalid_type.status == 400
        too_long = await client.put(
            "/api/notes/folder%2Fasset.txt",
            json={"notes": "x" * 4001},
            headers=_local_ui_headers(app),
        )
        assert too_long.status == 400
        escape = await client.put(
            "/api/notes/%2E%2E%2Foutside.txt",
            json={"notes": "blocked"},
            headers=_local_ui_headers(app),
        )
        assert escape.status == 400
    finally:
        subscription.close()
        await client.close()


@pytest.mark.anyio
async def test_tag_remove_route_reuses_tag_service_and_publishes_change(tmp_path):
    app, library, conn = _make_lan_app(tmp_path)
    target = library / "asset.txt"
    target.write_text("asset", encoding="utf-8")
    headers = _local_ui_headers(app)
    events = []
    subscription = get_event_bus().subscribe(AssetTagsChanged, events.append)
    client = await _make_client(app)
    try:
        guest = await client.post(
            "/api/tags/remove", json={"tag": "hero", "file_path": "asset.txt"}
        )
        assert guest.status == 403

        created = await client.post(
            "/api/tags", json={"tag": "hero", "file_path": "asset.txt"}, headers=headers
        )
        assert created.status == 200
        removed = await client.post(
            "/api/tags/remove",
            json={"tag": "hero", "file_path": "asset.txt"},
            headers=headers,
        )
        assert removed.status == 200
        assert await removed.json() == {"ok": True}
        assert conn.execute(
            "SELECT tag FROM file_tags WHERE file_path=?", (str(target.resolve()),)
        ).fetchone() is None
        assert any(event.file_path == str(target.resolve()) and event.new_tags == () for event in events)

        invalid = await client.post(
            "/api/tags/remove",
            json={"tag": "", "file_path": "asset.txt"},
            headers=headers,
        )
        assert invalid.status == 400
        escape = await client.post(
            "/api/tags/remove",
            json={"tag": "hero", "file_path": "../outside.txt"},
            headers=headers,
        )
        assert escape.status == 400
    finally:
        subscription.close()
        await client.close()

