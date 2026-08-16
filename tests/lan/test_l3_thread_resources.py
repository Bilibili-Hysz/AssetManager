"""L3 tests — symmetric shutdown for LAN-owned threads and executors."""
from __future__ import annotations

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

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ── Source-level ownership locks ────────────────────────────────────


def test_zip_executor_is_no_longer_module_global():
    source = (
        ROOT / "AssetsManager" / "lan" / "routes" / "_helpers.py"
    ).read_text(encoding="utf-8")
    assert "_zip_executor =" not in source
    assert "ZIP_EXECUTOR_APP_KEY = web.AppKey" in source


def test_server_owns_zip_executor_and_tracks_prewarm_thread():
    source = (ROOT / "AssetsManager" / "lan" / "server.py").read_text(
        encoding="utf-8")
    assert "self._zip_executor = concurrent.futures.ThreadPoolExecutor(" in source
    assert "app[ZIP_EXECUTOR_APP_KEY] = self._zip_executor" in source
    assert "self._gallery_prewarm_thread = thread" in source
    assert "self._join_gallery_prewarm()" in source
    assert "zip_executor.shutdown(wait=False, cancel_futures=True)" in source


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
