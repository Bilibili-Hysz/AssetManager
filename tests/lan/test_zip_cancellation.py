"""ZIP cancellation stops source consumption, including queued workers."""
import asyncio
import concurrent.futures
import threading

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from AssetsManager.lan.routes import _helpers


def test_cancelled_before_start_never_opens_source(tmp_path, monkeypatch):
    path = tmp_path / "source"
    path.write_bytes(b"asset")
    archive = tmp_path / "out.zip"
    cancelled = threading.Event()
    cancelled.set()

    def unexpected_open(*_args, **_kwargs):
        pytest.fail("cancelled worker opened a source")

    monkeypatch.setattr(_helpers, "iter_safe_file", unexpected_open)
    assert _helpers.build_zip_sync([(path, None)], str(archive), cancel_event=cancelled) is None
    assert not archive.exists()


@pytest.mark.anyio
async def test_queued_request_cancellation_never_reads_source(tmp_path, monkeypatch):
    path = tmp_path / "source"
    path.write_bytes(b"asset")
    archive = tmp_path / "queued.zip"
    release = threading.Event()
    queued = asyncio.Event()
    submitted = []
    opened = []
    real_iter = _helpers.iter_safe_file

    class ObservedExecutor(concurrent.futures.ThreadPoolExecutor):
        def submit(self, fn, /, *args, **kwargs):
            future = super().submit(fn, *args, **kwargs)
            submitted.append(future)
            if len(submitted) == 2:
                queued.set()
            return future

    def track_open(*args, **kwargs):
        opened.append(args)
        return real_iter(*args, **kwargs)

    monkeypatch.setattr(_helpers, "iter_safe_file", track_open)
    executor = ObservedExecutor(max_workers=1)
    executor.submit(release.wait, 5)
    app = web.Application()
    app[_helpers.ZIP_EXECUTOR_APP_KEY] = executor
    request = make_mocked_request("POST", "/", app=app)
    task = asyncio.create_task(_helpers.build_zip_async(request, [(path, None)], str(archive)))
    try:
        await asyncio.wait_for(queued.wait(), 5)
        assert not submitted[1].running()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        assert submitted[1].cancelled()
        assert opened == []
        assert not archive.exists()
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)


@pytest.mark.anyio
async def test_request_cancellation_stops_real_zip_worker_at_chunk_boundary(tmp_path, monkeypatch):
    path = tmp_path / "source"
    path.write_bytes(b"x" * 4096)
    archive = tmp_path / "out.zip"
    started = threading.Event()
    release = threading.Event()
    sources = []
    reads = []
    real_iter = _helpers.iter_safe_file

    class PausedSource:
        def __init__(self, *args, **kwargs):
            self.source = real_iter(*args, **kwargs, chunk_size=32)
            sources.append(self.source)

        def __iter__(self):
            return self

        @property
        def identity(self):
            return self.source.identity

        def __next__(self):
            chunk = next(self.source)
            reads.append(len(chunk))
            started.set()
            assert release.wait(5)
            return chunk

        def close(self):
            self.source.close()

    monkeypatch.setattr(_helpers, "iter_safe_file", PausedSource)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    app = web.Application()
    app[_helpers.ZIP_EXECUTOR_APP_KEY] = executor
    request = make_mocked_request("POST", "/", app=app)
    task = asyncio.create_task(_helpers.build_zip_async(request, [(path, None)], str(archive)))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        # A barrier on the same single worker proves compression exited.
        await asyncio.wait_for(asyncio.wrap_future(executor.submit(lambda: None)), 5)
        assert reads == [32]
        assert all(source._opened.file.closed for source in sources)
        assert not archive.exists()
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)
