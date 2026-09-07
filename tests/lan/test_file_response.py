"""Real HTTP and lifecycle regressions for descriptor-backed downloads."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from AssetsManager.lan import file_response
from AssetsManager.lan.file_response import SafeFileResponse, open_download_file
from AssetsManager.lan.safe_open import SafeOpenError
from AssetsManager.lan.routes._helpers import LAN_APP_KEY
from tests.lan.support.api_helpers import _local_ui_headers, _make_client, _make_lan_app


@pytest.mark.anyio
@pytest.mark.parametrize("shared", [False, True])
async def test_large_download_and_head_preserve_bounded_reads(tmp_path, monkeypatch, shared):
    app, library, conn = _make_lan_app(tmp_path)
    target = library / "large.bin"
    size = 64 * 1024 * 1024 + 123
    with target.open("wb") as handle:
        handle.truncate(size)
    reads = []
    opened_files = []
    real_read = SafeFileResponse._read_chunk
    real_open = file_response.safe_open_under_root

    def tracked_open(*args, **kwargs):
        opened = real_open(*args, **kwargs)
        opened_files.append(opened)
        return opened

    def tracked_read(self, remaining):
        chunk = real_read(self, remaining)
        reads.append(len(chunk))
        return chunk

    monkeypatch.setattr(file_response, "safe_open_under_root", tracked_open)
    monkeypatch.setattr(SafeFileResponse, "_read_chunk", tracked_read)
    client = await _make_client(app)
    try:
        share_id = None
        if shared:
            created = await client.post(
                "/api/shares", json={"paths": ["large.bin"], "max_downloads": 1},
                headers=_local_ui_headers(app),
            )
            assert created.status == 200
            share_id = (await created.json())["id"]
            url = f"/api/shares/{share_id}/download/large.bin"
        else:
            url = "/api/download/large.bin"
        head = await client.head(url, headers=_local_ui_headers(app))
        assert head.status == 200
        assert head.content_length == size
        assert await head.read() == b""
        assert not any(reads)
        if share_id:
            assert conn.execute("SELECT download_count FROM share_links WHERE id=?", (share_id,)).fetchone() == (0,)
        response = await client.get(url, headers=_local_ui_headers(app))
        assert response.status == 200
        received = 0
        async for chunk in response.content.iter_chunked(1024 * 1024):
            assert not any(chunk)
            received += len(chunk)
        assert received == size
        assert max(reads) <= file_response.TRANSFER_CHUNK_BYTES
        assert sum(reads) == size
        # Completion of the server request also exercises task-level cleanup.
        await client.close()
        assert all(opened.file.closed for opened in opened_files)
    finally:
        await client.close()


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["prepare", "write", "cancel"])
async def test_stream_closes_handle_on_transport_failure(tmp_path, monkeypatch, failure):
    target = tmp_path / "asset.bin"
    target.write_bytes(b"payload")
    opened = await open_download_file(tmp_path, target)
    request = make_mocked_request("GET", "/")
    response = SafeFileResponse(request, opened, headers={})
    error = asyncio.CancelledError() if failure == "cancel" else ConnectionResetError()
    if failure == "prepare":
        monkeypatch.setattr(web.StreamResponse, "prepare", AsyncMock(side_effect=error))
    else:
        monkeypatch.setattr(response, "write", AsyncMock(side_effect=error))
    with pytest.raises(type(error)):
        await response.prepare(request)
    assert opened.file.closed


@pytest.mark.anyio
async def test_changed_source_is_rejected_before_headers(tmp_path):
    target = tmp_path / "asset.bin"
    target.write_bytes(b"old")
    opened = await open_download_file(tmp_path, target)
    request = make_mocked_request("GET", "/")
    response = SafeFileResponse(request, opened, headers={})
    target.write_bytes(b"changed-length")
    with pytest.raises(SafeOpenError):
        await response.prepare(request)
    assert not response.prepared
    assert opened.file.closed


@pytest.mark.anyio
async def test_mid_transfer_change_aborts_before_complete_content_length(tmp_path, monkeypatch):
    target = tmp_path / "asset.bin"
    target.write_bytes(b"x" * (file_response.TRANSFER_CHUNK_BYTES + 8))
    opened = await open_download_file(tmp_path, target)
    request = make_mocked_request("GET", "/")
    response = SafeFileResponse(request, opened, headers={})
    sent = []

    async def change_after_first_chunk(chunk):
        sent.append(chunk)
        with target.open("ab") as handle:
            handle.write(b"changed")

    monkeypatch.setattr(response, "write", change_after_first_chunk)
    with pytest.raises(SafeOpenError):
        await response.prepare(request)
    assert sum(map(len, sent)) < response.content_length
    assert opened.file.closed
    request.transport.close.assert_called_once()


@pytest.mark.anyio
async def test_cancelled_open_closes_late_worker_result(tmp_path, monkeypatch):
    import threading

    target = tmp_path / "asset.bin"
    target.write_bytes(b"asset")
    started = threading.Event()
    release = threading.Event()
    closed = asyncio.Event()
    loop = asyncio.get_running_loop()

    def delayed_open(*_args):
        started.set()
        assert release.wait(5)
        return SimpleNamespace(close=lambda: loop.call_soon_threadsafe(closed.set))

    monkeypatch.setattr(file_response, "safe_open_under_root", delayed_open)
    task = asyncio.create_task(open_download_file(tmp_path, target))
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
    await asyncio.wait_for(closed.wait(), 5)


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["deny", "unavailable", "cancel"])
async def test_download_quota_rejection_closes_opened_file(tmp_path, monkeypatch, failure):
    from AssetsManager.lan.routes import downloads
    from AssetsManager.lan.routes.quota import QuotaUnavailableError

    target = tmp_path / "asset.bin"
    target.write_bytes(b"asset")
    opened = await open_download_file(tmp_path, target)
    request = make_mocked_request(
        "GET", "/api/download/asset.bin", match_info={"path": "asset.bin"},
        app={LAN_APP_KEY: SimpleNamespace(library_root=tmp_path)},
    )
    monkeypatch.setattr(downloads, "require_permission", lambda *_args: True)
    monkeypatch.setattr(downloads, "validate_path", lambda *_args: target)
    monkeypatch.setattr(downloads, "_preflight_exhausted_response", lambda *_args: None)
    monkeypatch.setattr(downloads, "open_download_file", AsyncMock(return_value=opened))

    def consume(_request):
        if failure == "unavailable":
            raise QuotaUnavailableError()
        if failure == "cancel":
            raise asyncio.CancelledError()
        return {"allowed": False, "reason": "exhausted", "retry_after_seconds": 0,
                "info": {"enabled": False}}

    monkeypatch.setattr(downloads, "consume_free_download_quota", consume)
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await downloads.handle_download(request)
    else:
        response = await downloads.handle_download(request)
        assert response.status == (429 if failure == "deny" else 503)
    assert opened.file.closed
