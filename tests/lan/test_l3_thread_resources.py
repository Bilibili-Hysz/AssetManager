"""L3 tests — symmetric shutdown for LAN-owned threads and executors."""
from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from AssetsManager.application.gallery_service import GalleryService
from AssetsManager.lan.routes._helpers import (
    ZIP_EXECUTOR_APP_KEY,
    build_zip_async,
)
from AssetsManager.lan.server import _LanServerImpl



@pytest.fixture
def anyio_backend():
    return "asyncio"


# ── Zip executor resolution ─────────────────────────────────────────


@pytest.mark.anyio
async def test_build_zip_async_uses_server_owned_executor(tmp_path):
    import concurrent.futures

    app = web.Application()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    app[ZIP_EXECUTOR_APP_KEY] = executor
    request = make_mocked_request("POST", "/", app=app)
    zip_path = str(tmp_path / "out.zip")
    try:
        result = await build_zip_async(request, [], zip_path)
        assert result == zip_path
        assert Path(zip_path).exists()
    finally:
        executor.shutdown(wait=True)


@pytest.mark.anyio
async def test_build_zip_async_falls_back_for_legacy_apps_without_executor(tmp_path):
    app = web.Application()
    request = make_mocked_request("POST", "/", app=app)
    zip_path = str(tmp_path / "legacy.zip")
    result = await build_zip_async(request, [], zip_path)
    assert result == zip_path
    assert Path(zip_path).exists()


@pytest.mark.anyio
async def test_build_zip_async_cleans_path_after_cancellation(tmp_path, monkeypatch):
    from AssetsManager.lan.routes import _helpers

    app = web.Application()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    app[ZIP_EXECUTOR_APP_KEY] = executor
    request = make_mocked_request("POST", "/", app=app)
    zip_path = str(tmp_path / "cancelled.zip")
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocking_build(_targets, path):
        started.set()
        assert release.wait(5)
        Path(path).write_bytes(b"zip")
        finished.set()
        return path

    monkeypatch.setattr(_helpers, "build_zip_sync", blocking_build)
    task = asyncio.create_task(build_zip_async(request, [], zip_path))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        assert await asyncio.to_thread(finished.wait, 5)
        executor.shutdown(wait=True)
        await asyncio.sleep(0)
        assert not Path(zip_path).exists()
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.anyio
async def test_build_zip_async_cleans_path_when_executor_rejects(tmp_path):
    app = web.Application()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    app[ZIP_EXECUTOR_APP_KEY] = executor
    request = make_mocked_request("POST", "/", app=app)
    zip_path = tmp_path / "rejected.zip"
    zip_path.write_bytes(b"temporary")
    executor.shutdown(wait=True)

    with pytest.raises(RuntimeError):
        await build_zip_async(request, [], str(zip_path))

    assert not zip_path.exists()


# ── H1: stop→start must republish a live zip executor ───────────────


def test_ensure_zip_executor_reuses_live_and_rebuilds_after_shutdown():
    server = object.__new__(_LanServerImpl)
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="lan-zip"
    )
    server._zip_executor = executor
    server._zip_executor_shutdown = False
    try:
        # A live executor is returned as-is; no rebuild happens.
        assert server._ensure_zip_executor() is executor

        executor.shutdown(wait=True)
        server._zip_executor_shutdown = True
        rebuilt = server._ensure_zip_executor()
        assert rebuilt is not executor
        assert server._zip_executor_shutdown is False
        assert rebuilt.submit(lambda: 41 + 1).result(timeout=5) == 42
    finally:
        server._ensure_zip_executor().shutdown(wait=True)


def test_shutdown_marks_zip_executor_dead_and_build_app_rebuilds_it(tmp_path):
    """stop→start on one server instance must publish a usable executor.

    Regression: ``_shutdown`` closed the server-owned zip executor but
    ``_build_app`` republished the same dead handle, so after a settings
    stop/start cycle every ZIP download raised RuntimeError → 500.
    """
    from AssetsManager.application import ApplicationBootstrap

    bootstrap = ApplicationBootstrap()
    server = None
    try:
        session = bootstrap.library_service.open_session(tmp_path / "library")
        runtime = bootstrap.runtime_for(session)
        server = _LanServerImpl(runtime=runtime)
        original = server._zip_executor
        assert server._app[ZIP_EXECUTOR_APP_KEY] is original

        asyncio.run(server._shutdown())

        assert server._zip_executor_shutdown is True
        with pytest.raises(RuntimeError):
            original.submit(int, "not-a-number")

        # start() calls _build_app() before serving; the republished executor
        # must be a fresh, working one.
        server._build_app()
        rebuilt = server._app[ZIP_EXECUTOR_APP_KEY]
        assert rebuilt is not original
        assert server._zip_executor_shutdown is False
        assert rebuilt.submit(lambda: 41 + 1).result(timeout=5) == 42
    finally:
        if server is not None:
            executor = getattr(server, "_zip_executor", None)
            if executor is not None:
                executor.shutdown(wait=False, cancel_futures=True)
        bootstrap.library_service.close()


# ── Gallery build loop honors _closed after pre_wait ────────────────


def test_gallery_background_build_skips_walk_when_closed_during_prewait(monkeypatch):
    gallery = GalleryService()
    gallery._closed = False
    calls: list[str] = []
    monkeypatch.setattr(
        gallery, "_compute_home", lambda root_key: calls.append(root_key) or None)

    def close_during_wait():
        gallery._closed = True

    try:
        gallery._build_home_background("library-root", pre_wait=close_during_wait)
        assert calls == []
    finally:
        gallery.close()


# ── Prewarm join helper ─────────────────────────────────────────────


def test_join_gallery_prewarm_waits_and_clears_handle():
    server = object.__new__(_LanServerImpl)
    thread = threading.Thread(target=lambda: time.sleep(0.05))
    server._gallery_prewarm_thread = thread
    thread.start()
    try:
        server._join_gallery_prewarm(timeout=5.0)
        assert server._gallery_prewarm_thread is None
    finally:
        thread.join(timeout=5.0)


def test_join_gallery_prewarm_bounds_the_wait():
    server = object.__new__(_LanServerImpl)
    release = threading.Event()
    thread = threading.Thread(target=release.wait)
    server._gallery_prewarm_thread = thread
    thread.start()
    try:
        started = time.monotonic()
        server._join_gallery_prewarm(timeout=0.05)
        elapsed = time.monotonic() - started
        assert elapsed < 1.0
        assert thread.is_alive()
        assert server._gallery_prewarm_thread is thread
    finally:
        release.set()
        thread.join(timeout=5.0)
