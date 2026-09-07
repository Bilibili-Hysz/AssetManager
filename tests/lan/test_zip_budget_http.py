"""Real ZIP responses keep process capacity charged until storage cleanup."""
import asyncio
import io
import zipfile
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from AssetsManager.lan.routes import downloads
from AssetsManager.lan.routes._helpers import LAN_APP_KEY, ZIP_EXECUTOR_APP_KEY
from AssetsManager.lan.temporary_file_response import TemporaryFileResponse
from AssetsManager.lan.zip_resources import ZIP_BUDGET_APP_KEY, get_process_zip_budget


@pytest.mark.anyio
@pytest.mark.parametrize("batch", [False, True])
async def test_http_zip_capacity_remains_reserved_until_responses_finish(tmp_path, monkeypatch, batch):
    folder = tmp_path / "folder"
    folder.mkdir()
    payload = b"real ZIP download payload"
    (folder / "asset.txt").write_bytes(payload)

    # Isolate permission and quota policy, retaining real path validation,
    # admission, scanning, ZIP creation, temporary-file ownership, and HTTP IO.
    monkeypatch.setattr(downloads, "require_permission", lambda *_args: True)
    monkeypatch.setattr(downloads, "get_free_download_quota_info", lambda _request: {"enabled": False})
    monkeypatch.setattr(downloads, "consume_free_download_quota", lambda _request: {
        "allowed": True, "info": {"enabled": False},
    })
    budget = get_process_zip_budget()
    assert budget.snapshot() == {"active_jobs": 0, "reserved_bytes": 0}

    four_ready = asyncio.Event()
    send_responses = asyncio.Event()
    four_cleaned = asyncio.Event()
    final_cleaned = asyncio.Event()
    archives = []
    completed = 0
    original_prepare = TemporaryFileResponse.prepare

    async def hold_before_sending(self, request):
        nonlocal completed
        first_prepare = not (self.prepared or self._eof_sent)
        if first_prepare:
            archives.append(self._path)
            if len(archives) == 4:
                four_ready.set()
            await send_responses.wait()
        try:
            return await original_prepare(self, request)
        finally:
            if first_prepare:
                # The original prepare awaits its close/delete finally, so
                # this signal observes completed cleanup, not just sent bytes.
                completed += 1
                if completed == 4:
                    four_cleaned.set()
                elif completed == 5:
                    final_cleaned.set()

    monkeypatch.setattr(TemporaryFileResponse, "prepare", hold_before_sending)

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="test-zip-http") as executor:
        app = web.Application()
        app[LAN_APP_KEY] = SimpleNamespace(library_root=tmp_path)
        app[ZIP_BUDGET_APP_KEY] = budget
        app[ZIP_EXECUTOR_APP_KEY] = executor
        app.router.add_post("/api/download/batch", downloads.handle_batch_download)
        app.router.add_get("/api/download/{path:.*}", downloads.handle_download)

        async with TestClient(TestServer(app)) as client:
            async def request_zip():
                if batch:
                    return await client.post("/api/download/batch", json={"paths": ["folder"]})
                return await client.get("/api/download/folder")

            pending = [asyncio.create_task(request_zip()) for _ in range(4)]
            try:
                await asyncio.wait_for(four_ready.wait(), 10)
                assert all(archive.exists() for archive in archives)
                assert budget.snapshot() == {
                    "active_jobs": 4, "reserved_bytes": 2 * 1024 * 1024 * 1024,
                }

                denied = await asyncio.wait_for(request_zip(), 5)
                assert denied.status == 503
                assert denied.headers["Retry-After"] == "1"
                assert (await denied.json())["code"] == "zip_capacity_exhausted"
                assert len(archives) == 4

                send_responses.set()
                responses = await asyncio.wait_for(asyncio.gather(*pending), 10)
                for response in responses:
                    assert response.status == 200
                    with zipfile.ZipFile(io.BytesIO(await response.read())) as archive:
                        assert archive.namelist() == ["folder/asset.txt"]
                        assert archive.read("folder/asset.txt") == payload
                await asyncio.wait_for(four_cleaned.wait(), 5)
                assert budget.snapshot() == {"active_jobs": 0, "reserved_bytes": 0}
                assert all(not archive.exists() for archive in archives)

                recovered = await asyncio.wait_for(request_zip(), 5)
                assert recovered.status == 200
                with zipfile.ZipFile(io.BytesIO(await recovered.read())) as archive:
                    assert archive.read("folder/asset.txt") == payload
                await asyncio.wait_for(final_cleaned.wait(), 5)
                assert budget.snapshot() == {"active_jobs": 0, "reserved_bytes": 0}
            finally:
                send_responses.set()
                await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), 10)
