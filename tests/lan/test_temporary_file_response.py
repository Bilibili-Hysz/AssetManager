"""HTTP contracts and deterministic temporary-archive ownership races."""
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor, wait as wait_futures
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

from AssetsManager.lan.routes.downloads import _file_response_with_cleanup


@pytest.mark.anyio
@pytest.mark.parametrize("case", ["get", "range", "head", "not_modified", "precondition", "invalid_range", "empty"])
async def test_temporary_archive_preserves_http_contracts(tmp_path, case):
    archive = tmp_path / "download.zip"
    payload = b"" if case == "empty" else b"0123456789"
    archive.write_bytes(payload)
    st = archive.stat()
    etag = f'"{st.st_mtime_ns:x}-{st.st_size:x}"'
    headers = {
        "range": {"Range": "bytes=2-5"},
        "not_modified": {"If-None-Match": etag},
        "precondition": {"If-Match": '"different"'},
        "invalid_range": {"Range": "bytes=99-100"},
    }.get(case, {})
    expected_status = {"range": 206, "not_modified": 304, "precondition": 412, "invalid_range": 416}.get(case, 200)
    prepared = asyncio.Event()

    async def handler(request):
        response = _file_response_with_cleanup(request, str(archive), filename="download.zip")
        original_prepare = response.prepare

        async def observe_prepare(request):
            try:
                return await original_prepare(request)
            finally:
                prepared.set()

        response.prepare = observe_prepare
        return response

    app = web.Application()
    app.router.add_get("/download", handler)
    async with TestClient(TestServer(app)) as client:
        response = await client.request("HEAD" if case == "head" else "GET", "/download", headers=headers)
        body = await response.read()
        await asyncio.wait_for(prepared.wait(), 5)
        assert response.status == expected_status
        assert body == (payload[2:6] if case == "range" else payload if case == "get" else b"")
        if case == "range":
            assert response.headers["Content-Range"] == "bytes 2-5/10"
        if case in {"head", "empty"}:
            assert response.content_length == len(payload)
        if case == "invalid_range":
            assert response.headers["Content-Range"] == "bytes */10"
        assert not archive.exists()


@pytest.mark.anyio
async def test_temporary_archive_prepare_failure_closes_then_deletes(tmp_path, monkeypatch):
    archive = tmp_path / "download.zip"
    archive.write_bytes(b"zip")
    opened = []
    real_make = web.FileResponse._make_response

    def record_open(self, *args):
        result = real_make(self, *args)
        opened.append(result[1])
        return result

    monkeypatch.setattr(web.FileResponse, "_make_response", record_open)
    monkeypatch.setattr(web.FileResponse, "_prepare_open_file", AsyncMock(side_effect=ConnectionResetError("disconnected")))
    request = make_mocked_request("GET", "/download")
    response = _file_response_with_cleanup(request, str(archive), filename="download.zip")
    with pytest.raises(ConnectionResetError):
        await response.prepare(request)
    assert len(opened) == 1 and opened[0].closed
    assert not archive.exists()


@pytest.mark.anyio
@pytest.mark.parametrize("pause", ["before_open", "after_open"])
async def test_cancelled_archive_prepare_owns_late_open_result(tmp_path, monkeypatch, pause):
    archive = tmp_path / "download.zip"
    archive.write_bytes(b"zip")
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    opened = []
    real_make = web.FileResponse._make_response
    real_run = loop.run_in_executor
    executor = ThreadPoolExecutor(max_workers=1)

    def blocked_make(self, *args):
        if pause == "after_open":
            result = real_make(self, *args)
            opened.append(result[1])
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5)
        if pause == "before_open":
            result = real_make(self, *args)
            opened.append(result[1])
        return result

    monkeypatch.setattr(web.FileResponse, "_make_response", blocked_make)
    monkeypatch.setattr(loop, "run_in_executor", lambda selected, fn, *args: real_run(selected or executor, fn, *args))
    request = make_mocked_request("GET", "/download")
    response = _file_response_with_cleanup(request, str(archive), filename="download.zip")
    task = asyncio.create_task(response.prepare(request))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        # Let cancellation reach prepare before releasing the executor worker.
        cancellation_delivered = loop.create_future()
        loop.call_soon(cancellation_delivered.set_result, None)
        await cancellation_delivered
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        # The single-worker barrier waits for late open and cleanup operations.
        await loop.run_in_executor(executor, lambda: None)
        assert len(opened) == 1 and opened[0].closed
        assert not archive.exists()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        executor.shutdown(wait=True)
        for handle in opened:
            handle.close()


@pytest.mark.anyio
@pytest.mark.parametrize("pause", ["before_open", "after_open"])
async def test_cancelled_archive_cleanup_finishes_before_late_opener(tmp_path, monkeypatch, pause):
    archive = tmp_path / "download.zip"
    archive.write_bytes(b"zip")
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    opened = []
    open_workers = []
    real_make = web.FileResponse._make_response
    real_run = loop.run_in_executor
    executor = ThreadPoolExecutor(max_workers=2)

    def blocked_make(self, *args):
        if pause == "after_open":
            result = real_make(self, *args)
            opened.append(result[1])
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5)
        if pause == "before_open":
            result = real_make(self, *args)
            opened.append(result[1])
        return result

    def run_in_executor(selected, fn, *args):
        if selected is not None:
            return real_run(selected, fn, *args)
        worker = executor.submit(fn, *args)
        if getattr(fn, "__name__", None) == "_make_response":
            open_workers.append(worker)
        return asyncio.wrap_future(worker, loop=loop)

    monkeypatch.setattr(web.FileResponse, "_make_response", blocked_make)
    monkeypatch.setattr(loop, "run_in_executor", run_in_executor)
    request = make_mocked_request("GET", "/download")
    response = _file_response_with_cleanup(request, str(archive), filename="download.zip")
    task = asyncio.create_task(response.prepare(request))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        # Worker 2 completes prepare's cleanup while worker 1 still owns open.
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        assert archive.exists()
        assert len(open_workers) == 1 and not open_workers[0].done()
        if pause == "after_open":
            assert not opened[0].closed
        release.set()
        # Await the native future: cancellation already detached its asyncio
        # wrapper, and an idle-executor sentinel would not wait for worker 1.
        done, pending = await real_run(None, wait_futures, open_workers, 5)
        assert len(done) == 1 and not pending
        assert len(opened) == 1 and opened[0].closed
        assert not archive.exists()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        executor.shutdown(wait=True)
        for handle in opened:
            handle.close()


@pytest.mark.anyio
async def test_unprepared_archive_is_deleted_when_request_task_finishes(tmp_path, monkeypatch):
    from AssetsManager.lan import temporary_file_response

    archive = tmp_path / "download.zip"
    archive.write_bytes(b"zip")
    loop = asyncio.get_running_loop()
    deleted = asyncio.Event()
    real_unlink = temporary_file_response.os.unlink

    def observe_unlink(path, *args, **kwargs):
        result = real_unlink(path, *args, **kwargs)
        if str(path) == str(archive):
            loop.call_soon_threadsafe(deleted.set)
        return result

    monkeypatch.setattr(temporary_file_response.os, "unlink", observe_unlink)

    async def abandon_response():
        request = SimpleNamespace(task=asyncio.current_task())
        return _file_response_with_cleanup(request, str(archive), filename="download.zip")

    request_task = asyncio.create_task(abandon_response())
    response = await request_task
    assert not response.prepared
    await asyncio.wait_for(deleted.wait(), 5)
    assert not archive.exists()
