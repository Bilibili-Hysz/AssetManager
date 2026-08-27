"""Real browser/intermediary acceptance for thumbnail privacy contracts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import socket
from threading import Lock
import pytest

pytestmark = pytest.mark.e2e

playwright = pytest.importorskip("playwright.sync_api")
from aiohttp import ClientSession, web  # noqa: E402
from playwright.sync_api import Page, sync_playwright  # noqa: E402

from AssetsManager.application import ApplicationBootstrap  # noqa: E402
from AssetsManager.application.security_preflight import SecurityPreflight  # noqa: E402
from AssetsManager.lan import LanServer  # noqa: E402
from AssetsManager.lan.utils import generate_auth_token  # noqa: E402


@dataclass(frozen=True)
class _CachedResponse:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


class _LoopbackCacheProxy:
    """Deterministic, loopback-only forwarding cache for browser tests."""

    def __init__(self, upstream: str):
        self._upstream = upstream.rstrip("/")
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = None
        self._ready = None
        self._cache: dict[str, _CachedResponse] = {}
        self._counts: dict[str, dict[str, int]] = {}
        self._lock = Lock()
        self.base_url = ""

    def start(self) -> None:
        import threading

        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        assert self._ready.wait(10), "proxy did not start"

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        app = web.Application()
        app.router.add_route("*", "/{path:.*}", self._handle)
        self._loop.run_until_complete(self._start_async(app))
        self._ready.set()
        self._loop.run_forever()

    async def _start_async(self, app: web.Application) -> None:
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        self._site = web.SockSite(self._runner, sock)
        await self._site.start()
        self.base_url = f"http://127.0.0.1:{sock.getsockname()[1]}"

    @staticmethod
    def _cacheable(method: str, headers: dict[str, str]) -> bool:
        if method != "GET":
            return False
        cache_control = headers.get("Cache-Control", "").lower()
        return "public" in cache_control and "private" not in cache_control and "no-store" not in cache_control

    async def _handle(self, request: web.Request) -> web.Response:
        target = f"{self._upstream}{request.rel_url}"
        key = f"{request.method} {request.rel_url}"
        with self._lock:
            counts = self._counts.setdefault(key, {"upstream": 0, "hit": 0})
            cached = self._cache.get(key) if request.method == "GET" else None
            if cached is not None:
                counts["hit"] += 1
                return web.Response(
                    status=cached.status,
                    headers=dict(cached.headers),
                    body=cached.body,
                )
            counts["upstream"] += 1

        headers = {}
        for name in ("Cookie", "Authorization", "Content-Type", "Accept"):
            value = request.headers.get(name)
            if value:
                headers[name] = value
        body = await request.read()
        async with ClientSession() as client:
            async with client.request(request.method, target, headers=headers, data=body) as response:
                response_body = await response.read()
                response_headers = tuple(
                    (name, value)
                    for name, value in response.headers.items()
                    if name.lower() not in {"content-length", "transfer-encoding", "connection"}
                )
                cached_response = _CachedResponse(response.status, response_headers, response_body)

        if self._cacheable(request.method, dict(response_headers)) and response.status == 200:
            with self._lock:
                self._cache[key] = cached_response
        return web.Response(
            status=cached_response.status,
            headers=dict(cached_response.headers),
            body=cached_response.body,
        )

    def counts_for(self, method: str, path: str) -> dict[str, int]:
        with self._lock:
            return dict(self._counts.get(f"{method} {path}", {"upstream": 0, "hit": 0}))

    def stop(self) -> None:
        if self._loop is None:
            return
        async def cleanup() -> None:
            if self._runner is not None:
                await self._runner.cleanup()
        future = asyncio.run_coroutine_threadsafe(cleanup(), self._loop)
        future.result(timeout=10)
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=10)


def _browser_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _start_lan(runtime) -> LanServer:
    preflight = SecurityPreflight()
    preflight.confirm_authenticated_lan()
    server = LanServer(
        runtime=runtime,
        password="Task25L-Password!",
        blur_tags=["private"],
        preflight=preflight,
    )
    server.start(port=_browser_port(), bind="127.0.0.1")
    return server


def _cookie(server: LanServer, *, base_url: str | None = None) -> dict[str, str]:
    return {
        "name": "lan_token",
        "value": generate_auth_token(server.token_secret),
        "url": base_url or f"http://127.0.0.1:{server._port}",
    }


@pytest.fixture
def browser_thumbnail_runtime(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    from PIL import Image
    cover = library / "cover.png"
    private = library / "private.png"
    Image.new("RGB", (64, 48), color="green").save(cover, format="PNG")
    Image.new("RGB", (64, 48), color="red").save(private, format="PNG")
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    runtime = bootstrap.runtime_for(session)
    runtime.services.tag_service.add_tag(library, private, "private")
    server = _start_lan(runtime)
    proxy = _LoopbackCacheProxy(f"http://127.0.0.1:{server._port}")
    proxy.start()
    try:
        yield bootstrap, session, runtime, server, proxy
    finally:
        proxy.stop()
        thread = server._impl._thread
        server.stop()
        assert thread is None or not thread.is_alive()
        bootstrap.library_service.close_session(session)
        bootstrap.library_service.close()


@pytest.mark.skipif(not __import__("pathlib").Path("webui/dist/index.html").is_file(), reason="WebUI dist is unavailable")
def test_real_browser_namespace_and_private_thumbnail_headers(browser_thumbnail_runtime):
    _bootstrap, _session, _runtime, server, proxy = browser_thumbnail_runtime
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()
        page: Page = context.new_page()
        try:
            context.add_cookies([_cookie(server, base_url=proxy.base_url)])
            page.goto(f"{proxy.base_url}/browse", wait_until="domcontentloaded")
            page.get_by_test_id("browse-workspace").wait_for(timeout=10_000)
            page.wait_for_timeout(500)
            info = page.request.get(f"{proxy.base_url}/api/info")
            assert info.ok
            namespace = info.json()["thumbnail_cache_namespace"]
            assert namespace
            namespace_keys = page.evaluate(
                """(ns) => Object.keys(sessionStorage).filter((key) => key.startsWith('lan_thumb_cache:'))""",
                namespace,
            )
            assert len(namespace_keys) == 1
            assert namespace_keys[0].startswith("lan_thumb_cache:")
            encoded_namespace = page.evaluate("(ns) => encodeURIComponent(ns)", namespace)
            assert encoded_namespace in namespace_keys[0]
            assert page.evaluate("() => sessionStorage.getItem('lan_thumb_cache')") is None

            headers = page.evaluate(
                """async () => {
                    const single = await fetch('/api/thumbnails/private.png?size=128');
                    const batch = await fetch('/api/thumbnails/batch', {
                      method: 'POST',
                      headers: {'Content-Type': 'application/json'},
                      body: JSON.stringify({paths: ['private.png'], size: 128}),
                    });
                    return {
                      singleStatus: single.status,
                      singleCache: single.headers.get('cache-control'),
                      batchStatus: batch.status,
                      batchCache: batch.headers.get('cache-control'),
                    };
                }""",
            )
            assert headers == {
                "singleStatus": 200,
                "singleCache": "private, no-store",
                "batchStatus": 200,
                "batchCache": "private, no-store",
            }
        finally:
            browser.close()


def test_intermediary_does_not_cache_private_batch_responses(browser_thumbnail_runtime):
    _bootstrap, _session, _runtime, server, proxy = browser_thumbnail_runtime
    with sync_playwright() as pw:
        cookie = _cookie(server)
        cookie.pop("url", None)
        cookie.update({
            "domain": "127.0.0.1",
            "path": "/",
            "expires": -1,
            "httpOnly": False,
            "secure": False,
            "sameSite": "Lax",
        })
        request = pw.request.new_context(storage_state={"cookies": [cookie]})
        try:
            path = "/api/thumbnails/batch"
            body = {"paths": ["cover.png"], "size": 128}
            first = request.post(
                f"{proxy.base_url}{path}",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            second = request.post(
                f"{proxy.base_url}{path}",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            assert first.ok and second.ok
            assert first.headers["cache-control"] == "private, no-store"
            assert second.headers["cache-control"] == "private, no-store"
            counts = proxy.counts_for("POST", path)
            assert counts["upstream"] == 2
            assert counts["hit"] == 0
        finally:
            request.dispose()


def test_intermediary_only_caches_explicit_public_thumbnail_responses(browser_thumbnail_runtime):
    _bootstrap, _session, _runtime, server, proxy = browser_thumbnail_runtime
    with sync_playwright() as pw:
        cookie = _cookie(server)
        cookie.pop("url", None)
        cookie.update({
            "domain": "127.0.0.1",
            "path": "/",
            "expires": -1,
            "httpOnly": False,
            "secure": False,
            "sameSite": "Lax",
        })
        request = pw.request.new_context(storage_state={"cookies": [cookie]})
        try:
            path = "/api/thumbnails/cover.png?size=128"
            first = request.get(f"{proxy.base_url}{path}")
            second = request.get(f"{proxy.base_url}{path}")
            assert first.ok and second.ok
            assert first.headers["cache-control"] == "public, max-age=3600"
            assert second.headers["cache-control"] == "public, max-age=3600"
            counts = proxy.counts_for("GET", path)
            assert counts["upstream"] == 1
            assert counts["hit"] == 1
        finally:
            request.dispose()
