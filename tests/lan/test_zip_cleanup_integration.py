"""Failed route and worker cleanup recovers without losing ZIP admission."""
import asyncio
import concurrent.futures
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from AssetsManager.lan import zip_cleanup
from AssetsManager.lan.routes import _helpers, downloads
from AssetsManager.lan.zip_resources import ZIP_BUDGET_APP_KEY, ZipResourceBudget


@pytest.fixture
def retry_clock(monkeypatch):
    now = [0.0]
    service = zip_cleanup.ZipCleanupService(clock=lambda: now[0], start_worker=False)
    monkeypatch.setattr(zip_cleanup, "_PROCESS_ZIP_CLEANUP", service)
    yield now, service
    service.close()


def test_automatic_worker_recovers_path_and_capacity(tmp_path, monkeypatch):
    service = zip_cleanup.ZipCleanupService(base_delay=0.01, max_delay=0.05)
    monkeypatch.setattr(zip_cleanup, "_PROCESS_ZIP_CLEANUP", service)
    archive = tmp_path / "automatic.zip"
    archive.write_bytes(b"archive")
    budget = ZipResourceBudget(max_jobs=1)
    reservation = budget.try_acquire()
    assert reservation is not None
    locked = threading.Event()
    locked.set()
    finished = threading.Event()
    real_unlink = zip_cleanup.os.unlink

    def temporarily_locked(path, *args, **kwargs):
        if Path(path) == archive and locked.is_set():
            raise PermissionError("test sharing violation")
        return real_unlink(path, *args, **kwargs)

    def complete():
        reservation.release()
        finished.set()

    monkeypatch.setattr(zip_cleanup.os, "unlink", temporarily_locked)
    try:
        assert not zip_cleanup.cleanup_zip_path(archive, complete)
        assert budget.snapshot()["active_jobs"] == 1
        locked.clear()
        assert finished.wait(5)
        assert not archive.exists()
        assert budget.snapshot()["active_jobs"] == 0
    finally:
        locked.clear()
        service.close(wait_timeout=5)


@pytest.mark.anyio
@pytest.mark.parametrize("batch", [False, True])
async def test_failed_route_cleanup_recovers_reserved_capacity(tmp_path, monkeypatch, retry_clock, batch):
    now, service = retry_clock
    budget = ZipResourceBudget(max_jobs=1)
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "source").write_bytes(b"payload")
    request = make_mocked_request(
        "POST" if batch else "GET", "/download", match_info={"path": "folder"},
        app={_helpers.LAN_APP_KEY: SimpleNamespace(library_root=tmp_path), ZIP_BUDGET_APP_KEY: budget},
    )

    async def request_json():
        return {"paths": ["folder"]}

    request.json = request_json
    monkeypatch.setattr(downloads, "require_permission", lambda *_args: True)
    monkeypatch.setattr(downloads, "validate_path", lambda *_args: folder)
    monkeypatch.setattr(downloads, "_preflight_exhausted_response", lambda *_args: None)
    paths = []

    async def failed_build(_request, _targets, path, **_kwargs):
        paths.append(Path(path))
        Path(path).write_bytes(b"unfinished")
        return None

    monkeypatch.setattr(downloads, "build_zip_async", failed_build)
    real_unlink = zip_cleanup.os.unlink

    def locked_unlink(path, *args, **kwargs):
        if Path(path) in paths:
            raise PermissionError("temporary sharing violation")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(zip_cleanup.os, "unlink", locked_unlink)
    response = await (downloads.handle_batch_download if batch else downloads.handle_download)(request)
    assert response.status == 500
    assert service.snapshot()["pending_count"] == 1
    assert budget.snapshot()["active_jobs"] == 1
    assert budget.try_acquire() is None
    monkeypatch.setattr(zip_cleanup.os, "unlink", real_unlink)
    now[0] = 2.0
    service.run_due()
    assert not paths[0].exists()
    assert service.snapshot()["pending_count"] == 0
    assert budget.snapshot()["active_jobs"] == 0


@pytest.mark.anyio
async def test_cancelled_worker_cleanup_retry_returns_all_references(tmp_path, monkeypatch, retry_clock):
    now, service = retry_clock
    budget = ZipResourceBudget(max_jobs=1)
    reservation = budget.try_acquire()
    assert reservation is not None
    archive = tmp_path / "worker.zip"
    entered = threading.Event()
    release = threading.Event()

    def blocking_build(_targets, path, **_kwargs):
        Path(path).write_bytes(b"archive")
        entered.set()
        assert release.wait(5)
        return path

    monkeypatch.setattr(_helpers, "build_zip_sync", blocking_build)
    real_unlink = zip_cleanup.os.unlink

    def blocked(path, *args, **kwargs):
        if Path(path) == archive:
            raise PermissionError("busy")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(zip_cleanup.os, "unlink", blocked)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    app = web.Application()
    app[_helpers.ZIP_EXECUTOR_APP_KEY] = executor
    task = asyncio.create_task(_helpers.build_zip_async(
        SimpleNamespace(app=app), [], str(archive), reservation=reservation,
    ))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        await asyncio.to_thread(executor.shutdown, wait=True)
        assert service.snapshot()["pending_count"] >= 1
        assert budget.snapshot()["active_jobs"] == 1
        monkeypatch.setattr(zip_cleanup.os, "unlink", real_unlink)
        now[0] = 2.0
        service.run_due()
        assert not archive.exists()
        assert budget.snapshot()["active_jobs"] == 0
    finally:
        release.set()
        await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)
