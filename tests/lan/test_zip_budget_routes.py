"""ZIP admission covers scanning, building, and response-owned storage."""
import asyncio
import concurrent.futures
import json
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import make_mocked_request

from AssetsManager.lan.routes import downloads
from AssetsManager.lan.routes._helpers import LAN_APP_KEY, ZIP_EXECUTOR_APP_KEY
from AssetsManager.lan.zip_resources import ZIP_BUDGET_APP_KEY, ZipResourceBudget
from AssetsManager.lan.zip_sources import ZipLimitExceeded


@pytest.fixture
def zip_request(tmp_path, monkeypatch):
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "asset.txt").write_bytes(b"payload")
    monkeypatch.setattr(downloads, "require_permission", lambda *_args: True)
    monkeypatch.setattr(downloads, "validate_path", lambda *_args: folder)
    monkeypatch.setattr(downloads, "_preflight_exhausted_response", lambda _request: None)
    monkeypatch.setattr(downloads, "consume_free_download_quota", lambda _request: {
        "allowed": True, "info": {},
    })
    monkeypatch.setattr(downloads, "apply_free_quota_headers", lambda *_args: None)
    monkeypatch.setattr(downloads, "apply_free_quota_identity_cookie", lambda *_args: None)

    def make(batch, budget):
        request = make_mocked_request(
            "POST" if batch else "GET", "/api/download/batch" if batch else "/api/download/folder",
            app={LAN_APP_KEY: SimpleNamespace(library_root=tmp_path), ZIP_BUDGET_APP_KEY: budget},
            match_info={"path": "folder"},
        )

        async def body():
            return {"paths": ["folder"]}

        request.json = body
        return request, downloads.handle_batch_download if batch else downloads.handle_download

    return make


@pytest.mark.anyio
@pytest.mark.parametrize("batch", [False, True])
async def test_full_budget_denies_before_scan_or_temp_creation(zip_request, monkeypatch, batch):
    request, handler = zip_request(batch, ZipResourceBudget(max_jobs=0))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("full budget must reject before expensive work")

    monkeypatch.setattr(downloads, "estimate_zip_source_bytes", forbidden)
    monkeypatch.setattr(tempfile, "mkstemp", forbidden)
    response = await handler(request)
    assert response.status == 503
    assert json.loads(response.text)["code"] == "zip_capacity_exhausted"
    assert response.headers["Retry-After"] == "1"


@pytest.mark.anyio
async def test_single_file_download_bypasses_zip_capacity(zip_request, monkeypatch, tmp_path):
    request, handler = zip_request(False, ZipResourceBudget(max_jobs=0))
    file = tmp_path / "ordinary.bin"
    file.write_bytes(b"file")
    monkeypatch.setattr(downloads, "validate_path", lambda *_args: file)
    response = await handler(request)
    try:
        assert response.status == 200
        assert response.content_length == 4
    finally:
        response.close()


@pytest.mark.anyio
async def test_tempfile_creation_failure_returns_budget(zip_request, monkeypatch):
    budget = ZipResourceBudget(max_jobs=1)
    request, handler = zip_request(False, budget)

    def fail(*_args, **_kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(tempfile, "mkstemp", fail)
    response = await handler(request)
    assert response.status == 500
    assert budget.snapshot()["active_jobs"] == 0


@pytest.mark.anyio
@pytest.mark.parametrize("batch", [False, True])
async def test_response_cleanup_returns_storage_budget(zip_request, batch):
    budget = ZipResourceBudget(max_jobs=1)
    request, handler = zip_request(batch, budget)
    response = await handler(request)
    try:
        assert response.status == 200
        assert budget.snapshot()["active_jobs"] == 1
        assert budget.try_acquire() is None
        assert Path(response._path).exists()
    finally:
        response._owner.cleanup()
    assert not Path(response._path).exists()
    assert budget.snapshot() == {"active_jobs": 0, "reserved_bytes": 0}


@pytest.mark.anyio
@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("phase", ["scan", "build"])
async def test_typed_limit_is_opaque_413_and_releases(zip_request, monkeypatch, batch, phase):
    budget = ZipResourceBudget(max_jobs=1)
    request, handler = zip_request(batch, budget)

    def fail(*_args, **_kwargs):
        raise ZipLimitExceeded("private/library/path/file.txt")

    async def fail_build(*args, **kwargs):
        fail(*args, **kwargs)

    if phase == "scan":
        monkeypatch.setattr(downloads, "estimate_zip_source_bytes", fail)
    else:
        monkeypatch.setattr(downloads, "build_zip_async", fail_build)
    response = await handler(request)
    assert response.status == 413
    assert json.loads(response.text)["code"] == "zip_limits_exceeded"
    assert "private" not in response.text
    assert budget.snapshot()["active_jobs"] == 0


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["build", "response", "quota_cancel"])
async def test_pre_handoff_failure_cleans_archive_and_releases(zip_request, monkeypatch, failure):
    budget = ZipResourceBudget(max_jobs=1)
    request, handler = zip_request(False, budget)
    created = []

    async def build(_request, _targets, path, **_kwargs):
        created.append(Path(path))
        Path(path).write_bytes(b"zip")
        return None if failure == "build" else path

    def construct(*_args, **_kwargs):
        raise RuntimeError("response failed")

    def cancel(_request):
        raise asyncio.CancelledError()

    monkeypatch.setattr(downloads, "build_zip_async", build)
    if failure == "response":
        monkeypatch.setattr(downloads, "_file_response_with_cleanup", construct)
        with pytest.raises(RuntimeError, match="response failed"):
            await handler(request)
    elif failure == "quota_cancel":
        monkeypatch.setattr(downloads, "consume_free_download_quota", cancel)
        with pytest.raises(asyncio.CancelledError):
            await handler(request)
    else:
        assert (await handler(request)).status == 500
    assert created and all(not path.exists() for path in created)
    assert budget.snapshot()["active_jobs"] == 0


@pytest.mark.anyio
async def test_undeleted_archive_keeps_capacity_charged(zip_request, monkeypatch):
    budget = ZipResourceBudget(max_jobs=1)
    request, handler = zip_request(False, budget)
    created = []

    async def fail_build(_request, _targets, path, **_kwargs):
        created.append(Path(path))
        Path(path).write_bytes(b"partial archive")
        return None

    monkeypatch.setattr(downloads, "build_zip_async", fail_build)
    original_unlink = downloads.os.unlink

    def blocked_unlink(path, *args, **kwargs):
        if Path(path) in created:
            raise PermissionError("archive still held open")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(downloads.os, "unlink", blocked_unlink)
    try:
        response = await handler(request)
        assert response.status == 500
        assert budget.snapshot()["active_jobs"] == 1
        assert budget.try_acquire() is None
        assert created[0].exists()
    finally:
        for path in created:
            original_unlink(path)


def test_cancelled_scan_retains_budget_after_request_loop_closes(zip_request, monkeypatch):
    budget = ZipResourceBudget(max_jobs=1)
    request, handler = zip_request(False, budget)
    entered = threading.Event()
    release = threading.Event()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    request.app[ZIP_EXECUTOR_APP_KEY] = executor

    def scan(_targets):
        entered.set()
        assert release.wait(5)
        return 0

    monkeypatch.setattr(downloads, "estimate_zip_source_bytes", scan)

    async def cancel_scan():
        task = asyncio.create_task(handler(request))
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert budget.snapshot()["active_jobs"] == 1

    try:
        asyncio.run(cancel_scan())
        assert budget.snapshot()["active_jobs"] == 1
    finally:
        release.set()
        executor.shutdown(wait=True)
    assert budget.snapshot()["active_jobs"] == 0


@pytest.mark.anyio
async def test_queued_scan_cancellation_releases_without_running(zip_request, monkeypatch):
    budget = ZipResourceBudget(max_jobs=1)
    request, handler = zip_request(False, budget)
    release = threading.Event()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    blocker = executor.submit(release.wait, 5)
    request.app[ZIP_EXECUTOR_APP_KEY] = executor
    calls = []
    monkeypatch.setattr(downloads, "estimate_zip_source_bytes", lambda _targets: calls.append(True) or 0)
    task = asyncio.create_task(handler(request))
    try:
        await asyncio.sleep(0)
        assert budget.snapshot()["active_jobs"] == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert budget.snapshot()["active_jobs"] == 0
        assert calls == []
    finally:
        release.set()
        blocker.result(3)
        executor.shutdown(wait=True)


def test_server_instances_and_rebuilds_share_process_budget(tmp_path, isolated_process_zip_budget):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.lan.server import _LanServerImpl

    bootstrap = ApplicationBootstrap()
    servers = []
    reservation = isolated_process_zip_budget.try_acquire()
    assert reservation is not None
    try:
        session = bootstrap.library_service.open_session(tmp_path / "library")
        runtime = bootstrap.runtime_for(session)
        servers = [_LanServerImpl(runtime=runtime), _LanServerImpl(runtime=runtime)]
        for server in servers:
            assert server._app[ZIP_BUDGET_APP_KEY] is isolated_process_zip_budget
        servers[0]._build_app()
        assert servers[0]._app[ZIP_BUDGET_APP_KEY] is isolated_process_zip_budget
        assert isolated_process_zip_budget.snapshot()["active_jobs"] == 1
    finally:
        reservation.release()
        for server in servers:
            server._zip_executor.shutdown(wait=True, cancel_futures=True)
        bootstrap.library_service.close()
