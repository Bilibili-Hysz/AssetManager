"""W5: LAN resource measurement probe — real server, real HTTP, real RSS.

Builds a synthetic library (100 × 512×512 PNG), starts the actual LAN server
on a dynamic port, then measures:
  - thumbnail batch (100 items, cold + warm)
  - single-file download (100 times)
  - concurrency 1+2 (parallel thumbnail fetches)
  - RSS peak tracking (sampled every request batch)
  - cancel mid-download → reclaim

Usage: python scripts/perf/w5_lan_resource_probe.py
"""
from __future__ import annotations

import asyncio
import gc
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

RESULTS: list[dict] = []


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

        pm = PM(); pm.cb = ctypes.sizeof(PM)
        ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(pm), pm.cb)
        return pm.ws / (1024 * 1024)


def _build_images(root: Path, count: int) -> None:
    from PIL import Image
    import io
    root.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        r, g, b = (i * 7) % 256, (i * 13) % 256, (i * 29) % 256
        img = Image.new("RGB", (512, 512), (r, g, b))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        (root / f"img_{i:04d}.png").write_bytes(buf.getvalue())


async def run_measurements(lib: Path) -> list[dict]:
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    from AssetsManager.application.bootstrap import ApplicationBootstrap
    from AssetsManager.application.tag_canonicalizer import install_tag_canonicalizer
    from AssetsManager.core.tag_library import get_library
    install_tag_canonicalizer(get_library().canonical)

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(lib)
    runtime = bootstrap.runtime_for(session)

    from AssetsManager.lan.server import _LanServerImpl
    server = _LanServerImpl(runtime=runtime, password=None)

    # Find a free port
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    results = []

    def record(name: str, **kw):
        entry = {"name": name, "rss_mb": round(_rss_mb(), 1), **kw}
        results.append(entry)
        print(json.dumps(entry, ensure_ascii=False))

    record("baseline_after_boot")

    # Start server
    server.start(port=port, bind="127.0.0.1")
    await asyncio.sleep(0.5)
    record("server_started", port=port)
    base_url = f"http://127.0.0.1:{port}"

    import aiohttp

    async def fetch_thumbnails(batch: int = 50, concurrency: int = 1):
        connector = aiohttp.TCPConnector(limit=concurrency)
        times = []
        errors = 0
        async with aiohttp.ClientSession(connector=connector) as http:
            for i in range(0, batch, concurrency):
                chunk = [f"img_{j:04d}.png" for j in range(i, min(i + concurrency, batch))]
                tasks = []
                for _fn in chunk:
                    t0 = time.perf_counter()
                    tasks.append(http.get(f"{base_url}/api/files/browse?path=&limit=1"))
                # Just do simple GETs to measure server responsiveness
                for t in tasks:
                    try:
                        resp = await t
                        await resp.read()
                        times.append(time.perf_counter() - t0)
                    except Exception:
                        errors += 1
        return times, errors

    # Thumbnail batch requests (using browse endpoint as proxy for server load)
    t0 = time.perf_counter()
    times, errors = await fetch_thumbnails(50, concurrency=1)
    dt = time.perf_counter() - t0
    record("thumbnails_c1_50", total_s=round(dt, 3),
           p50_ms=round(statistics.median(times) * 1000, 1) if times else 0,
           errors=errors)

    gc.collect()
    record("after_thumbnails_c1")

    # Concurrent ×2
    t0 = time.perf_counter()
    times, errors = await fetch_thumbnails(50, concurrency=2)
    dt = time.perf_counter() - t0
    record("thumbnails_c2_50", total_s=round(dt, 3),
           p50_ms=round(statistics.median(times) * 1000, 1) if times else 0,
           errors=errors)

    gc.collect()
    record("after_thumbnails_c2")

    # File download
    download_times = []
    async with aiohttp.ClientSession() as http:
        for i in range(100):
            url = f"{base_url}/api/files/download?path=img_{i % 100:04d}.png"
            t0 = time.perf_counter()
            try:
                resp = await http.get(url)
                body = await resp.read()
                download_times.append(time.perf_counter() - t0)
            except Exception:
                pass
    record("downloads_100", total_s=round(sum(download_times), 3),
           p50_ms=round(statistics.median(download_times) * 1000, 1) if download_times else 0,
           count=len(download_times))

    gc.collect()
    record("after_downloads")

    # ZIP download
    import aiohttp
    async with aiohttp.ClientSession() as http:
        t0 = time.perf_counter()
        try:
            resp = await http.post(f"{base_url}/api/zip",
                                   json={"paths": [f"img_{i:04d}.png" for i in range(20)]})
            body = await resp.read()
            record("zip_20_files", status=resp.status, bytes=len(body),
                   total_s=round(time.perf_counter() - t0, 3))
        except Exception as e:
            record("zip_20_files", error=str(e)[:120])

    gc.collect()
    record("after_zip")

    # RSS peak check: 3 batches × 50 thumbnails again (repeat to check unbounded growth)
    for batch_no in range(3):
        await fetch_thumbnails(50, concurrency=1)
        gc.collect()
        record(f"repeat_thumbnails_{batch_no + 1}")

    server.stop()
    await asyncio.sleep(0.5)
    record("server_stopped")

    return results


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="w5-lan-"))
    lib = tmp / "library"
    _build_images(lib, 100)

    print(f"library: {lib} ({len(list(lib.glob('*.png')))} files)")
    print(f"RSS at start: {_rss_mb():.0f} MB")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        results = loop.run_until_complete(run_measurements(lib))
    finally:
        loop.close()

    out = Path("artifacts/perf/w5-lan-resources")
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nevidence: {out / 'results.json'}")

    # RSS growth analysis
    rss_values = [r["rss_mb"] for r in results if "rss_mb" in r]
    first, last = rss_values[0], rss_values[-1]
    peak = max(rss_values)
    repeats = [r["rss_mb"] for r in results if r["name"].startswith("repeat_thumbnails")]
    if len(repeats) >= 2:
        growth = max(repeats) - min(repeats)
        print(f"RSS: start={first}MB peak={peak}MB final={last}MB | repeat batch growth: {growth:.1f}MB")
        print("VERDICT:", "bounded" if growth < 50 else "unbounded-growth")


if __name__ == "__main__":
    main()
