"""W5: LAN resource measurement probe — real server, real HTTP, real RSS.

Builds a synthetic library (100 × 512×512 PNG), starts the actual LAN server
on a dynamic port, health-checks it, authenticates with a password principal,
then measures the real routes registered in ``AssetsManager/lan/api.py``:

  - GET  /api/files                      (browse listing, items verified)
  - GET  /api/thumbnails/{path}          (single thumbnail delivery, image/* verified)
  - POST /api/thumbnails/batch           (50-item thumbnail batch)
  - GET  /api/download/{path}            (single-file download, byte length verified)
  - POST /api/download/batch             (20-item ZIP download, PK signature verified)
  - true concurrency (asyncio.gather + semaphore) over mixed routes
  - mid-download cancellation → server health re-check (resource reclaim)
  - RSS peak tracking sampled after every phase and every repeat batch

Every request must answer HTTP 200 with the expected body contract; anything
else counts as a failed request and invalidates the run. Any failure, missing
health, or measurement defect makes the probe print ``INVALID`` and exit
non-zero — it can never reach the "budget satisfied" branch on failed traffic.
RSS growth over the repeat batches above the budget exits non-zero with
``unbounded-growth``.

Usage: python scripts/perf/w5_lan_resource_probe.py
"""
from __future__ import annotations

import asyncio
import gc
import io
import json
import os
import socket
import statistics
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

RESULTS: list[dict] = []

PROBE_PASSWORD = "w5-lan-resource-probe"
LIBRARY_SIZE = 100
HEALTH_CHECK_RETRIES = 40
HEALTH_CHECK_INTERVAL_S = 0.25
REQUEST_TIMEOUT_S = 30.0
RSS_GROWTH_BUDGET_MB = 50.0
CONCURRENCY = 8


class ProbeInvalid(RuntimeError):
    """A measurement precondition failed; the run cannot be trusted."""


def _rss_mb() -> float:
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except ImportError:
        import ctypes

        class PM(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("pf", ctypes.c_ulong),
                        ("peak_ws", ctypes.c_size_t), ("ws", ctypes.c_size_t),
                        *[(f"_q{i}", ctypes.c_size_t) for i in range(6)]]

        pm = PM()
        pm.cb = ctypes.sizeof(PM)
        ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(pm), pm.cb)
        return pm.ws / (1024 * 1024)


def _build_images(root: Path, count: int) -> None:
    from PIL import Image
    root.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        r, g, b = (i * 7) % 256, (i * 13) % 256, (i * 29) % 256
        img = Image.new("RGB", (512, 512), (r, g, b))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        (root / f"img_{i:04d}.png").write_bytes(buf.getvalue())


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def _summary(times: list[float]) -> dict:
    return {
        "count": len(times),
        "total_s": round(sum(times), 3),
        "p50_ms": round(statistics.median(times) * 1000, 1) if times else 0,
        "max_ms": round(max(times) * 1000, 1) if times else 0,
    }


async def run_measurements(lib: Path) -> list[dict]:
    import aiohttp
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.application.security_preflight import SecurityPreflight
    from AssetsManager.application.tag_canonicalizer import install_tag_canonicalizer
    from AssetsManager.core.tag_library import get_library
    install_tag_canonicalizer(get_library().canonical)

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(lib)
    runtime = bootstrap.runtime_for(session)

    from AssetsManager.lan.server import _LanServerImpl
    server = _LanServerImpl(
        runtime=runtime, password=PROBE_PASSWORD,
        rate_limit=100000,  # the probe measures resources, not rate limiting
    )

    results: list[dict] = []

    def record(name: str, **kw):
        entry = {"name": name, "rss_mb": round(_rss_mb(), 1), **kw}
        results.append(entry)
        print(json.dumps(entry, ensure_ascii=False))

    record("baseline_after_boot")

    # Start the server with a confirmed authenticated-local preflight.
    # Without an acknowledged preflight the start() contract returns a
    # "confirmation_required" snapshot instead of listening — the silent
    # no-server failure mode that invalidated the previous probe run.
    preflight = SecurityPreflight()
    preflight.confirm_authenticated_lan()
    port = _free_port()
    start_result = server.start(port=port, bind="127.0.0.1", preflight=preflight)
    if isinstance(start_result, dict) or not server.is_running():
        raise ProbeInvalid(f"server did not start on port {port}: {start_result!r}")
    record("server_started", port=port)
    base_url = f"http://127.0.0.1:{port}"

    try:
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_S)
        # unsafe=True: cookies are issued by the 127.0.0.1 loopback host, which
        # aiohttp's default jar otherwise treats as an unsafe cookie origin.
        jar = aiohttp.CookieJar(unsafe=True)
        async with aiohttp.ClientSession(timeout=timeout, cookie_jar=jar) as http:
            # ── Health check gate: no sampling before the server answers ──
            info: dict | None = None
            for _ in range(HEALTH_CHECK_RETRIES):
                try:
                    async with http.get(f"{base_url}/api/info") as resp:
                        if resp.status == 200:
                            info = await resp.json()
                            break
                except aiohttp.ClientError:
                    pass
                await asyncio.sleep(HEALTH_CHECK_INTERVAL_S)
            if info is None:
                raise ProbeInvalid("health check failed: /api/info never returned 200")
            record("health_ok", share_name=info.get("share_name"),
                   auth_mode=info.get("auth_mode"))

            # ── Login: password principal so downloads are permitted ──
            async with http.post(
                f"{base_url}/api/auth/login", json={"password": PROBE_PASSWORD},
            ) as resp:
                if resp.status != 200:
                    raise ProbeInvalid(f"login failed with HTTP {resp.status}")
                await resp.read()
            if not any(cookie.key == "lan_token" for cookie in jar):
                raise ProbeInvalid("login did not issue a lan_token cookie")
            record("login_ok")

            async def expect_200(method: str, url: str, *, ctx: str, **kw) -> tuple[bytes, str]:
                async with http.request(method, url, **kw) as resp:
                    body = await resp.read()
                    ctype = resp.headers.get("Content-Type", "")
                    if resp.status != 200:
                        raise ProbeInvalid(
                            f"{ctx}: expected HTTP 200, got {resp.status} ({method} {url})")
                    return body, ctype

            names = [f"img_{i:04d}.png" for i in range(LIBRARY_SIZE)]

            # ── Browse listing (GET /api/files) ──
            t0 = time.perf_counter()
            body, _ = await expect_200("GET", f"{base_url}/api/files?path=&limit=50",
                                       ctx="browse")
            listing = json.loads(body)
            items = listing.get("items", [])
            if not isinstance(items, list) or len(items) != 50:
                raise ProbeInvalid(
                    f"browse: expected 50 items with limit=50, got {len(items) if isinstance(items, list) else type(items).__name__}")
            record("browse_ok", items=len(items), **_summary([time.perf_counter() - t0]))

            # ── Single thumbnails, concurrency 1 (GET /api/thumbnails/{path}) ──
            thumb_times: list[float] = []
            for name in names:
                t0 = time.perf_counter()
                body, ctype = await expect_200(
                    "GET", f"{base_url}/api/thumbnails/{name}?size=512",
                    ctx=f"thumbnail {name}")
                if not body or not ctype.startswith("image/"):
                    raise ProbeInvalid(
                        f"thumbnail {name}: empty body or non-image type {ctype!r}")
                thumb_times.append(time.perf_counter() - t0)
            record("thumbnails_c1_100", **_summary(thumb_times))
            gc.collect()
            record("after_thumbnails_c1")

            # ── Thumbnail batch (POST /api/thumbnails/batch) ──
            t0 = time.perf_counter()
            body, _ = await expect_200(
                "POST", f"{base_url}/api/thumbnails/batch",
                ctx="thumbnail batch",
                json={"paths": names[:50], "size": 256})
            batch = json.loads(body)
            dt = time.perf_counter() - t0
            delivered = len(batch.get("thumbnails", {}))
            if delivered <= 0:
                raise ProbeInvalid("thumbnail batch: response contains no thumbnails")
            record("thumbnails_batch_50", delivered=delivered, total_s=round(dt, 3))
            gc.collect()
            record("after_thumbnails_batch")

            # ── Single-file downloads (GET /api/download/{path}), bytes verified ──
            download_times: list[float] = []
            for name in names:
                t0 = time.perf_counter()
                body, _ = await expect_200(
                    "GET", f"{base_url}/api/download/{name}", ctx=f"download {name}")
                expected = (lib / name).stat().st_size
                if len(body) != expected:
                    raise ProbeInvalid(
                        f"download {name}: byte length {len(body)} != source {expected}")
                download_times.append(time.perf_counter() - t0)
            record("downloads_100", **_summary(download_times))
            gc.collect()
            record("after_downloads")

            # ── ZIP batch download (POST /api/download/batch), signature verified ──
            t0 = time.perf_counter()
            body, _ = await expect_200(
                "POST", f"{base_url}/api/download/batch",
                ctx="zip batch",
                json={"paths": names[:20]})
            dt = time.perf_counter() - t0
            if not body.startswith(b"PK"):
                raise ProbeInvalid(
                    f"zip batch: body does not start with ZIP signature "
                    f"(first bytes: {body[:4]!r})")
            record("zip_20_files", bytes=len(body), total_s=round(dt, 3))
            gc.collect()
            record("after_zip")

            # ── True concurrency: gather + semaphore over mixed routes ──
            sem = asyncio.Semaphore(CONCURRENCY)

            async def fetch(kind: str, name: str) -> float:
                async with sem:
                    t0 = time.perf_counter()
                    if kind == "thumb":
                        resp_body, ctype = await expect_200(
                            "GET", f"{base_url}/api/thumbnails/{name}?size=512",
                            ctx=f"concurrent thumbnail {name}")
                        if not resp_body or not ctype.startswith("image/"):
                            raise ProbeInvalid(
                                f"concurrent thumbnail {name}: bad body/type {ctype!r}")
                    else:
                        resp_body, _ = await expect_200(
                            "GET", f"{base_url}/api/download/{name}",
                            ctx=f"concurrent download {name}")
                        expected = (lib / name).stat().st_size
                        if len(resp_body) != expected:
                            raise ProbeInvalid(
                                f"concurrent download {name}: byte length "
                                f"{len(resp_body)} != source {expected}")
                    return time.perf_counter() - t0

            t0 = time.perf_counter()
            concurrent_times = await asyncio.gather(*[
                fetch("thumb" if i % 3 else "download", names[i % LIBRARY_SIZE])
                for i in range(48)
            ])
            dt = time.perf_counter() - t0
            record(f"mixed_c{CONCURRENCY}_48", wall_s=round(dt, 3),
                   **_summary(list(concurrent_times)))
            gc.collect()
            record(f"after_mixed_c{CONCURRENCY}")

            # ── Mid-download cancellation → reclaim → health re-check ──
            async with http.get(f"{base_url}/api/download/{names[0]}") as resp:
                await resp.content.read(256)
                resp.close()  # abort the connection mid-transfer
            await asyncio.sleep(0.5)
            async with http.get(f"{base_url}/api/info") as resp:
                if resp.status != 200:
                    raise ProbeInvalid(
                        f"server unhealthy after mid-download cancel: HTTP {resp.status}")
                await resp.read()
            record("cancel_reclaim_ok")

            # ── Repeat batches: RSS must stay bounded across re-requests ──
            for batch_no in range(3):
                await asyncio.gather(*[fetch("thumb", name) for name in names[:50]])
                gc.collect()
                record(f"repeat_thumbnails_{batch_no + 1}")

        return results
    finally:
        try:
            server.stop()
        except Exception as exc:
            raise ProbeInvalid(f"server stop failed: {exc!r}") from exc
        record("server_stopped")


def main() -> int:
    # Isolate the probe's runtime domain (settings.json, library data slots,
    # logs) from the developer machine's real runtime data. This must happen
    # before any AssetsManager import: path_resolver pins SHARED_DIR at import
    # time. Without it, persisted settings (e.g. an enabled free-download
    # quota with a min-request interval) leak into the probe and 429 the
    # download measurement.
    tmp = Path(tempfile.mkdtemp(prefix="w5-lan-"))
    os.environ["AM_RUNTIME_ROOT"] = str(tmp / "runtime")
    lib = tmp / "library"
    _build_images(lib, LIBRARY_SIZE)

    print(f"library: {lib} ({len(list(lib.glob('*.png')))} files)")
    print(f"RSS at start: {_rss_mb():.0f} MB")

    invalid_reason: str | None = None
    results: list[dict] = []
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        results = loop.run_until_complete(run_measurements(lib))
    except ProbeInvalid as exc:
        invalid_reason = str(exc)
    except Exception as exc:  # any unexpected failure invalidates the run
        invalid_reason = f"unexpected probe failure: {exc!r}"
    finally:
        loop.close()

    out = Path("artifacts/perf/w5-lan-resources")
    out.mkdir(parents=True, exist_ok=True)
    payload: dict = {"valid": invalid_reason is None, "measurements": results}
    if invalid_reason:
        payload["invalid_reason"] = invalid_reason
    (out / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nevidence: {out / 'results.json'}")

    if invalid_reason:
        print(f"INVALID: {invalid_reason}")
        return 1

    rss_values = [r["rss_mb"] for r in results if "rss_mb" in r]
    first, last = rss_values[0], rss_values[-1]
    peak = max(rss_values)
    repeats = [r["rss_mb"] for r in results if r["name"].startswith("repeat_thumbnails")]
    growth = (max(repeats) - min(repeats)) if len(repeats) >= 2 else 0.0
    print(f"RSS: start={first}MB peak={peak}MB final={last}MB | repeat batch growth: {growth:.1f}MB")
    if growth >= RSS_GROWTH_BUDGET_MB:
        print("VERDICT: unbounded-growth (repeat batch RSS growth above budget)")
        return 1
    print("VERDICT: bounded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
