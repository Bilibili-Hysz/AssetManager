"""Worker reservations outlive request loops, including executor shutdown."""
import asyncio
import concurrent.futures
import threading
from types import SimpleNamespace

import pytest
from aiohttp import web

from AssetsManager.lan.routes import _helpers
from AssetsManager.lan.zip_resources import ZipResourceBudget


@pytest.mark.anyio
async def test_undersized_reservation_cannot_start_archive(tmp_path):
    budget = ZipResourceBudget(max_jobs=1)
    reservation = budget.try_acquire(1)
    assert reservation is not None
    archive = tmp_path / "undersized.zip"
    try:
        with pytest.raises(ValueError, match="smaller"):
            await _helpers.build_zip_async(None, [], str(archive), reservation=reservation)
        assert not archive.exists()
    finally:
        reservation.release()
    assert budget.snapshot()["active_jobs"] == 0


def test_cancelled_worker_releases_after_request_loop_has_closed(tmp_path, monkeypatch):
    archive = tmp_path / "late.zip"
    budget = ZipResourceBudget(max_jobs=1)
    reservation = budget.try_acquire()
    assert reservation is not None
    entered = threading.Event()
    release = threading.Event()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    app = web.Application()
    app[_helpers.ZIP_EXECUTOR_APP_KEY] = executor
    request = SimpleNamespace(app=app)

    def slow_build(_targets, path, *, cancel_event):
        with open(path, "wb") as output:
            entered.set()
            assert release.wait(10)
            output.write(b"late result")
        return path

    monkeypatch.setattr(_helpers, "build_zip_sync", slow_build)
    loop = asyncio.new_event_loop()

    async def cancel_request():
        task = asyncio.create_task(_helpers.build_zip_async(
            request, [], str(archive), reservation=reservation,
        ))
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # The initial reference may remain when a Windows writer prevents
        # route-side deletion. The worker must eventually settle both.
        assert budget.snapshot()["active_jobs"] == 1
        assert budget.try_acquire() is None

    try:
        loop.run_until_complete(cancel_request())
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()
        release.set()
        executor.shutdown(wait=True)
        assert not archive.exists()
        assert budget.snapshot() == {"active_jobs": 0, "reserved_bytes": 0}
        reservation.release()
        assert budget.snapshot()["active_jobs"] == 0
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)
        if not loop.is_closed():
            loop.close()


@pytest.mark.anyio
async def test_executor_shutdown_releases_queued_job_before_it_starts(tmp_path):
    budget = ZipResourceBudget(max_jobs=1)
    reservation = budget.try_acquire()
    assert reservation is not None
    archive = tmp_path / "queued.zip"
    archive.write_bytes(b"")
    release = threading.Event()
    queued = asyncio.Event()

    class ObservedExecutor(concurrent.futures.ThreadPoolExecutor):
        submissions = 0

        def submit(self, fn, /, *args, **kwargs):
            future = super().submit(fn, *args, **kwargs)
            self.submissions += 1
            if self.submissions == 2:
                queued.set()
            return future

    executor = ObservedExecutor(max_workers=1)
    executor.submit(release.wait, 10)
    app = web.Application()
    app[_helpers.ZIP_EXECUTOR_APP_KEY] = executor
    request = SimpleNamespace(app=app)
    task = asyncio.create_task(_helpers.build_zip_async(
        request, [], str(archive), reservation=reservation,
    ))
    try:
        await asyncio.wait_for(queued.wait(), 5)
        executor.shutdown(wait=False, cancel_futures=True)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not archive.exists()
        assert budget.snapshot() == {"active_jobs": 0, "reserved_bytes": 0}
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)


@pytest.mark.anyio
async def test_successful_build_keeps_response_reservation(tmp_path):
    archive = tmp_path / "success.zip"
    budget = ZipResourceBudget(max_jobs=1)
    reservation = budget.try_acquire()
    assert reservation is not None
    try:
        assert await _helpers.build_zip_async(
            None, [], str(archive), reservation=reservation,
        ) == str(archive)
        assert budget.snapshot()["active_jobs"] == 1
        assert budget.try_acquire() is None
    finally:
        archive.unlink(missing_ok=True)
        reservation.release()
    assert budget.snapshot()["active_jobs"] == 0
