"""W5: LAN resource measurement probe — real server, real HTTP, real RSS.

Builds a synthetic library (100 × 512×512 PNG), starts the actual LAN server
on a dynamic port, health-checks it, authenticates with a password principal,
then measures the real routes registered in ``AssetsManager/lan/api.py``:

  - GET  /api/files                      (browse listing, items verified)
  - GET  /api/thumbnails/{path}          (single thumbnail delivery, image/* verified)
  - POST /api/thumbnails/batch           (50-item batch: full membership + every
                                          payload decoded as a real ≤256px PNG)
  - GET  /api/download/{path}            (single-file download, full byte equality)
  - POST /api/download/batch             (20-item ZIP: CRC pass + membership +
                                          per-member byte equality vs sources)
  - true concurrency (asyncio.gather + semaphore) over mixed routes
  - mid-download cancellation: a 192MB target aborted after 1MB (genuinely
    still-sending slow client) → health re-check + byte-verified re-download
  - RSS: post-phase spot samples AND a 100ms daemon sampler capturing
    request-phase peaks; loop heartbeats scheduled on BOTH the client loop
    and the LAN server's own background loop record max scheduling lag

Every request must answer HTTP 200 with the expected body contract; anything
else counts as a failed request and invalidates the run. Any failure, missing
health, or measurement defect makes the probe print ``INVALID`` and exit
non-zero — it can never reach the "budget satisfied" branch on failed traffic.
RSS growth over the repeat batches above the budget exits non-zero with
``unbounded-growth``. results.json carries ``valid`` AND a separate ``rss``
block with ``budget_mb`` plus a top-level ``verdict`` (invalid /
unbounded-growth / bounded) so consumers never infer budget approval from
``valid`` alone (weekly-recheck 2026-09-08 R4).

Usage: python scripts/perf/w5_lan_resource_probe.py
"""
from __future__ import annotations

import asyncio
import base64
import concurrent.futures as concurrent_futures
import gc
import hashlib
import io
import json
import os
import shutil
import socket
import statistics
import sys
import tempfile
import threading
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
BIG_BLOB_MB = 192  # slow-client cancel target: abort must land mid-transfer


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


def _build_slow_download_blob(root: Path, size_mb: int = 192) -> Path:
    """One large download target so a mid-transfer abort is genuinely
    still-sending: a few-kilobyte file can be fully transmitted before the
    client closes, which made the old cancel probe vacuous (weekly-recheck
    2026-09-08 R4). PNG magic keeps the extension-consistent serving path."""
    import secrets
    path = root / "big_blob.png"
    chunk = secrets.token_bytes(4 * 1024 * 1024)
    with path.open("wb") as stream:
        stream.write(b"\x89PNG\r\n\x1a\n")
        written = 8
        target = size_mb * 1024 * 1024
        while written < target:
            stream.write(chunk[: min(4 * 1024 * 1024, target - written)])
            written = min(target, written + 4 * 1024 * 1024)
    return path


class _RssPeakSampler:
    """Sample RSS from a daemon thread so request-phase peaks (not just the
    post-phase spot checks) are captured, weekly-recheck 2026-09-08 R4."""

    def __init__(self, interval_s: float = 0.1):
        self._interval_s = interval_s
        self._stop = threading.Event()
        self.peak_mb = 0.0
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        def _run():
            while not self._stop.is_set():
                self.peak_mb = max(self.peak_mb, _rss_mb())
                self._stop.wait(self._interval_s)

        self._thread = threading.Thread(
            target=_run, name="w5-rss-peak-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> float:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        return self.peak_mb


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

    sampler = _RssPeakSampler()
    sampler.start()
    lag_state: dict = {"client_max_lag_ms": 0.0, "server_max_lag_ms": 0.0}

    async def _lag_monitor(state_key: str) -> None:
        """Event-loop heartbeat: a 50ms tick that reports how far behind the
        loop actually ran.  Scheduled ONCE on the client loop and — via
        run_coroutine_threadsafe — on the LAN server's own background loop
        (round-3 recheck F3: a client-loop heartbeat cannot speak for the
        server loop that actually serves the requests).  Runs until its task
        or wrapping future is cancelled; never shares asyncio primitives
        across loops."""
        last = time.perf_counter()
        while True:
            await asyncio.sleep(0.05)
            now = time.perf_counter()
            lag_ms = max(0.0, (now - last - 0.05) * 1000)
            key = f"{state_key}_max_lag_ms"
            lag_state[key] = max(lag_state[key], round(lag_ms, 1))
            last = now

    client_loop = asyncio.get_running_loop()
    lag_task = client_loop.create_task(_lag_monitor("client"))
    server_loop = getattr(server, "_loop", None)
    if server_loop is None or not server_loop.is_running():
        raise ProbeInvalid("server event loop unavailable for the server-side heartbeat")
    server_lag_future = asyncio.run_coroutine_threadsafe(
        _lag_monitor("server"), server_loop)

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
            thumbs = batch.get("thumbnails", {})
            # Full membership: every requested path must come back, and every
            # payload must decode to a real ≤256px PNG (weekly-recheck R4:
            # ">0 delivered" let a 1/50 response pass).
            missing = sorted(set(names[:50]) - set(thumbs))
            if missing:
                raise ProbeInvalid(
                    f"thumbnail batch: {len(missing)}/{len(names[:50])} paths "
                    f"missing from response (first: {missing[:3]})")
            from PIL import Image
            decoded = 0
            for path, encoded in thumbs.items():
                try:
                    img = Image.open(io.BytesIO(base64.b64decode(encoded)))
                    img.load()
                except Exception as exc:
                    raise ProbeInvalid(
                        f"thumbnail batch: {path} payload is not a decodable "
                        f"image ({type(exc).__name__}: {exc})") from exc
                if max(img.size) > 256 or min(img.size) <= 0:
                    raise ProbeInvalid(
                        f"thumbnail batch: {path} rendered {img.size}, "
                        f"expected within 256px")
                decoded += 1
            record("thumbnails_batch_50", delivered=len(thumbs), verified=decoded,
                   total_s=round(dt, 3))
            gc.collect()
            record("after_thumbnails_batch")

            # ── Single-file downloads (GET /api/download/{path}), bytes verified ──
            download_times: list[float] = []
            for name in names:
                t0 = time.perf_counter()
                body, _ = await expect_200(
                    "GET", f"{base_url}/api/download/{name}", ctx=f"download {name}")
                expected = (lib / name).read_bytes()
                if body != expected:
                    raise ProbeInvalid(
                        f"download {name}: content mismatch "
                        f"({len(body)} bytes != source {len(expected)})")
                download_times.append(time.perf_counter() - t0)
            record("downloads_100", **_summary(download_times))
            gc.collect()
            record("after_downloads")

            # ── ZIP batch download (POST /api/download/batch) — every member's
            # bytes must match the source files (weekly-recheck R4: a PK
            # prefix proves nothing about membership or content) ──
            t0 = time.perf_counter()
            body, _ = await expect_200(
                "POST", f"{base_url}/api/download/batch",
                ctx="zip batch",
                json={"paths": names[:20]})
            dt = time.perf_counter() - t0
            import zipfile
            from pathlib import PurePosixPath
            try:
                with zipfile.ZipFile(io.BytesIO(body)) as zf:
                    corrupt = zf.testzip()
                    if corrupt is not None:
                        raise ProbeInvalid(f"zip batch: member {corrupt!r} fails CRC")
                    by_basename = {PurePosixPath(n).name: n for n in zf.namelist()}
                    expected_members = set(names[:20])
                    absent = sorted(expected_members - set(by_basename))
                    if absent:
                        raise ProbeInvalid(
                            f"zip batch: {len(absent)}/20 members missing "
                            f"(first: {absent[:3]})")
                    for member in expected_members:
                        if zf.read(by_basename[member]) != (lib / member).read_bytes():
                            raise ProbeInvalid(
                                f"zip batch: member {member!r} bytes differ from source")
            except zipfile.BadZipFile as exc:
                raise ProbeInvalid(
                    f"zip batch: not a readable ZIP archive ({exc}); "
                    f"first bytes: {body[:4]!r}") from exc
            record("zip_20_files", bytes=len(body), members=len(expected_members),
                   total_s=round(dt, 3))
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
                        expected = (lib / name).read_bytes()
                        if resp_body != expected:
                            raise ProbeInvalid(
                                f"concurrent download {name}: content mismatch "
                                f"({len(resp_body)} bytes != source {len(expected)})")
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

            # ── Mid-download cancellation → reclaim → same-object retry ──
            # A 192MB target is genuinely still being sent when the client
            # aborts after ~1MB (a few-KB file could finish transmitting
            # before the close, making the old probe vacuous).  Evidence
            # recorded: actual bytes consumed (read() may short-read — F3),
            # abort window, post-cancel health, RSS after the aborted
            # transfer, and a STREAMED hash-verified re-download of the SAME
            # object (a small-file re-download proves nothing about retrying
            # the big transfer; a full buffered read would pollute the RSS
            # being measured).
            big_blob = _build_slow_download_blob(lib, size_mb=BIG_BLOB_MB)
            # Stream the source hash — buffering the 192MB source here would
            # inflate the very RSS being measured (F3).
            digest = hashlib.sha256()
            with big_blob.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            big_blob_sha = digest.hexdigest()
            t0 = time.perf_counter()
            consumed = 0
            async with http.get(f"{base_url}/api/download/{big_blob.name}") as resp:
                if resp.status != 200:
                    raise ProbeInvalid(
                        f"slow-client cancel: big download returned {resp.status}")
                while consumed < 1024 * 1024:
                    chunk = await resp.content.read(64 * 1024)
                    if not chunk:
                        break
                    consumed += len(chunk)
                resp.close()  # abort while ~191MB remain unsent
            abort_s = time.perf_counter() - t0
            await asyncio.sleep(1.0)
            async with http.get(f"{base_url}/api/info") as resp:
                if resp.status != 200:
                    raise ProbeInvalid(
                        f"server unhealthy after mid-download cancel: HTTP {resp.status}")
                await resp.read()
            record("cancel_reclaim_ok", big_file_mb=BIG_BLOB_MB,
                   aborted_after_bytes=consumed, abort_window_s=round(abort_s, 3),
                   rss_after_cancel_mb=round(_rss_mb(), 1))
            # Streamed same-object retry: hash-verified without buffering.
            retry_sha = hashlib.sha256()
            retry_bytes = 0
            async with http.get(f"{base_url}/api/download/{big_blob.name}") as resp:
                if resp.status != 200:
                    raise ProbeInvalid(
                        f"post-cancel same-object retry returned {resp.status}")
                async for chunk in resp.content.iter_chunked(256 * 1024):
                    retry_sha.update(chunk)
                    retry_bytes += len(chunk)
            if retry_bytes != big_blob.stat().st_size or retry_sha.hexdigest() != big_blob_sha:
                raise ProbeInvalid(
                    "post-cancel same-object retry: hash/size mismatch "
                    f"({retry_bytes} bytes)")
            record("post_cancel_same_object_retry_ok",
                   bytes=retry_bytes, sha256=big_blob_sha[:16])

            # ── Repeat batches: RSS must stay bounded across re-requests ──
            for batch_no in range(3):
                await asyncio.gather(*[fetch("thumb", name) for name in names[:50]])
                gc.collect()
                record(f"repeat_thumbnails_{batch_no + 1}")

        return results
    finally:
        lag_task.cancel()
        try:
            await lag_task
        except (asyncio.CancelledError, Exception):
            pass
        server_lag_future.cancel()
        try:
            server_lag_future.result(timeout=5)
        except (concurrent_futures.CancelledError, concurrent_futures.TimeoutError, Exception):
            pass
        peak_mb = sampler.stop()
        record("rss_peak_during_run", peak_mb=round(peak_mb, 1),
               client_loop_max_lag_ms=lag_state["client_max_lag_ms"],
               server_loop_max_lag_ms=lag_state["server_max_lag_ms"])
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

    # Budget verdict is recorded separately from validity (weekly-recheck R4):
    # a run can be a valid measurement while FAILING its RSS budget, and JSON
    # consumers must not have to infer that from exit codes or valid alone.
    rss_values = [r["rss_mb"] for r in results if "rss_mb" in r]
    repeats = [r["rss_mb"] for r in results if r["name"].startswith("repeat_thumbnails")]
    growth = round((max(repeats) - min(repeats)) if len(repeats) >= 2 else 0.0, 1)
    peak_sample = next(
        (r for r in results if r["name"] == "rss_peak_during_run"), {})
    payload["rss"] = {
        "start_mb": rss_values[0] if rss_values else None,
        "final_mb": rss_values[-1] if rss_values else None,
        "spot_peak_mb": max(rss_values) if rss_values else None,
        "peak_during_request_mb": peak_sample.get("peak_mb"),
        "client_loop_max_lag_ms": peak_sample.get("client_loop_max_lag_ms"),
        "server_loop_max_lag_ms": peak_sample.get("server_loop_max_lag_ms"),
        "repeat_growth_mb": growth,
        "budget_mb": RSS_GROWTH_BUDGET_MB,
    }
    payload["verdict"] = (
        "invalid" if invalid_reason
        else "unbounded-growth" if growth >= RSS_GROWTH_BUDGET_MB
        else "bounded"
    )
    (out / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nevidence: {out / 'results.json'}")

    if invalid_reason:
        print(f"INVALID: {invalid_reason}")
        shutil.rmtree(tmp, ignore_errors=True)
        return 1

    first, last = rss_values[0], rss_values[-1]
    peak = max(rss_values)
    print(f"RSS: start={first}MB spot_peak={peak}MB "
          f"during_request_peak={peak_sample.get('peak_mb')}MB final={last}MB "
          f"| repeat batch growth: {growth}MB | loop max lag: "
          f"{peak_sample.get('server_loop_max_lag_ms')}ms")
    if growth >= RSS_GROWTH_BUDGET_MB:
        print("VERDICT: unbounded-growth (repeat batch RSS growth above budget)")
        shutil.rmtree(tmp, ignore_errors=True)
        return 1
    print("VERDICT: bounded")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
