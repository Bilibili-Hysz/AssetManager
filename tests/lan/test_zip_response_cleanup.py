"""Archive ownership survives failures between building and HTTP handoff."""
import asyncio
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import make_mocked_request

from AssetsManager.lan.routes import downloads
from AssetsManager.lan.routes._helpers import LAN_APP_KEY


@pytest.mark.anyio
@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("failure", ["cancel", "quota_error", "response_error", "cookie_error"])
async def test_zip_cleanup_before_response_handoff(tmp_path, monkeypatch, batch, failure):
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "asset.txt").write_text("asset", encoding="utf-8")
    request = make_mocked_request(
        "POST" if batch else "GET", "/api/download/batch" if batch else "/api/download/folder",
        app={LAN_APP_KEY: SimpleNamespace(library_root=tmp_path)},
        match_info={"path": "folder"},
    )

    async def request_json():
        return {"paths": ["folder"]}

    request.json = request_json
    monkeypatch.setattr(downloads, "require_permission", lambda *_args: True)
    monkeypatch.setattr(downloads, "validate_path", lambda *_args: folder)
    monkeypatch.setattr(downloads, "_preflight_exhausted_response", lambda *_args: None)
    created = []
    real_mkstemp = tempfile.mkstemp

    def track_tempfile(*args, **kwargs):
        descriptor, path = real_mkstemp(*args, **kwargs, dir=tmp_path)
        created.append(Path(path))
        return descriptor, path

    monkeypatch.setattr(tempfile, "mkstemp", track_tempfile)
    entered = threading.Event()
    release = threading.Event()

    def consume(_request):
        # Use the real ZIP builder and reach the previously leaking window.
        assert len(created) == 1 and created[0].exists()
        entered.set()
        if failure == "cancel":
            assert release.wait(5)
        if failure == "quota_error":
            raise RuntimeError("unexpected quota failure")
        return {"allowed": True, "info": {"enabled": False}}

    def unexpected_failure(*_args, **_kwargs):
        raise RuntimeError("response setup failure")

    monkeypatch.setattr(downloads, "consume_free_download_quota", consume)
    if failure == "response_error":
        monkeypatch.setattr(downloads, "_file_response_with_cleanup", unexpected_failure)
    elif failure == "cookie_error":
        monkeypatch.setattr(downloads, "apply_free_quota_identity_cookie", unexpected_failure)
    handler = downloads.handle_batch_download if batch else downloads.handle_download
    task = asyncio.create_task(handler(request))
    try:
        if failure == "cancel":
            assert await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(RuntimeError):
                await task
        assert len(created) == 1
        assert not created[0].exists()
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.anyio
async def test_archive_removal_does_not_race_aiohttp_deferred_close(tmp_path, monkeypatch):
    from aiohttp import web
    from unittest.mock import AsyncMock

    archive = tmp_path / "out.zip"
    archive.write_bytes(b"archive")
    loop = asyncio.get_running_loop()
    real_run = loop.run_in_executor
    deferred = []

    def defer_aiohttp_close(executor, function, *args):
        # Hold aiohttp's fire-and-forget close indefinitely: prepare must
        # close through its own owner before unlinking, even on Windows.
        if getattr(function, "__name__", None) == "close":
            future = loop.create_future()
            deferred.append((function, future))
            return future
        return real_run(executor, function, *args)

    monkeypatch.setattr(loop, "run_in_executor", defer_aiohttp_close)
    monkeypatch.setattr(web.FileResponse, "_sendfile", AsyncMock(return_value=None))
    response = downloads._file_response_with_cleanup(None, str(archive), filename="out.zip")
    try:
        await response.prepare(make_mocked_request("GET", "/out.zip"))
        assert len(deferred) == 1
        close, pending = deferred[0]
        assert not pending.done()
        assert close.__self__.closed
        assert not archive.exists()
    finally:
        # Release aiohttp's retained future as well as its redundant close.
        for close, pending in deferred:
            close()
            if not pending.done():
                pending.set_result(None)
