"""P2 measurements 3+4 — thumbnail pipeline throughput & DB write-gate concurrency.

Thumbnail throughput (production API):
    ``ThumbnailService.process_image`` is the shared production entry ("Snapshot
    and process an image without reopening its path after validation") — the
    same decode → exif-transpose → LANCZOS resize → WEBP q80 encode tail
    (``finalize_pil_image``) every LAN consumer ships.  200 true-color
    512x512 PNGs are generated and pushed through it; total and per-image
    amortized cost are reported.  The grid-side ``_FULL_REBUILD_TEXTURE_BUDGET``
    (= 12 textures per full rebuild) is put in context against this per-image
    cost.

DB write-gate concurrency (qualitative):
    Session-bound ``TagService.add_tag`` writes go through the connection-level
    ``db_write_lock`` (repositories/tag_repository.add_tag → _write_scope).
    100 writes are issued (a) serially from one thread and (b) concurrently
    from two threads (50 + 50, barrier start) against the same session
    connection.  concurrent_total / serial_total ≫ 1 indicates lock queuing
    amplification; > 3x is the register threshold.

Usage:
    QT_QPA_PLATFORM=offscreen python scripts/perf/p2_pipeline_probe.py \
        [--thumbs N] [--reps N] [--keep]

Isolation: ``AM_RUNTIME_ROOT`` under the system temp dir; scratch libraries
under ``.pytest-tmp-p2/`` (project drive, never an external disk), removed at
exit unless ``--keep``.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SCRATCH = PROJECT_ROOT / ".pytest-tmp-p2" / "p2_pipeline"


def isolate_runtime_root() -> Path:
    base = Path(os.environ.get("AM_PROBE_RUNTIME_PARENT", tempfile.gettempdir()))
    root = base / f"p2_pipeline_runtime_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    (root / "RuntimeData").mkdir(parents=True, exist_ok=True)
    os.environ["AM_RUNTIME_ROOT"] = str(root / "RuntimeData")
    return root


def make_test_images(root: Path, count: int, size: int = 512) -> list[Path]:
    """True-color gradient PNGs (deterministic, C-speed PIL channel ops)."""
    from PIL import Image

    root.mkdir(parents=True, exist_ok=True)
    row = bytes((x * 7) % 256 for x in range(size))
    gx = Image.frombytes("L", (size, size), row * size)  # horizontal ramp
    col = bytes((y * 5) % 256 for y in range(size))
    gy = Image.frombytes(
        "L", (size, size), b"".join(bytes([c]) * size for c in col)
    )  # vertical ramp
    gyx = gx.rotate(90)  # diagonal component
    paths: list[Path] = []
    for i in range(count):
        r = gx.point([(v + i) % 256 for v in range(256)])
        g = gy.point([(v + i * 3) % 256 for v in range(256)])
        b = gyx.point([(v + i * 11) % 256 for v in range(256)])
        img = Image.merge("RGB", (r, g, b))
        path = root / f"img_{i:04d}.png"
        img.save(path, format="PNG")
        paths.append(path)
    return paths


def probe_thumbnails(services, image_paths: list[Path], reps: int) -> dict:
    """Batch-produce thumbnails through ThumbnailService.process_image."""
    svc = services.thumbnail_service
    sizes: list[int] = []
    samples: list[float] = []
    for _ in range(reps):
        t0 = time.perf_counter()
        for path in image_paths:
            out = svc.process_image(path, max_size=512, should_blur=False)
            if out is None:
                raise RuntimeError(f"process_image returned None for {path}")
            sizes.append(len(out[0]))
        samples.append(time.perf_counter() - t0)
    total = statistics.median(samples)
    return {
        "images": len(image_paths),
        "total_s_median": round(total, 3),
        "per_image_ms": round(total / len(image_paths) * 1000, 2),
        "images_per_s": round(len(image_paths) / total, 1),
        "webp_bytes_median": round(statistics.median(sizes), 0),
        "samples_s": [round(s, 3) for s in samples],
    }


def probe_write_gate(session, services, reps: int) -> dict:
    """100 tag writes: serial 1x100 vs concurrent 2x50 on one connection.

    Driven at the repository layer (``TagRepository.add_tag`` → ``_write_scope``
    → ``db_write_lock(conn)``) — the connection-level write gate itself.
    ``TagService.add_tag`` cannot be used for the concurrent phase: its
    ``_require_event_safe_transaction`` pre-check runs OUTSIDE the write lock,
    so any in-flight write from the other thread fail-closes the call (that
    behavior is quantified separately below and registered as a finding).
    """
    from AssetsManager.repositories.tag_repository import TagRepository

    repo = TagRepository.for_session(session)
    root = session.root
    conn = session.connection_for(root)

    seed_dir = Path(session.root_str) / "__write_gate_probe__"
    seed_dir.mkdir(exist_ok=True)
    paths = []
    for i in range(200):
        p = seed_dir / f"gate_{i:04d}.txt"
        if not p.exists():
            p.write_text("probe", encoding="utf-8")
        paths.append(p)

    guard = {"stray": 0}

    def add_tags(paths_sel: list[Path], tag: str) -> None:
        for path in paths_sel:
            if conn.in_transaction:  # stray deferred writer (PF register)
                guard["stray"] += 1
                conn.rollback()
            repo.add_tag(str(path), tag)

    results: dict = {}
    for rep in range(reps):
        # serial 100
        serial_paths = paths[:100]
        t0 = time.perf_counter()
        add_tags(serial_paths, f"serial_rep{rep}")
        results.setdefault("serial_s", []).append(time.perf_counter() - t0)

        # concurrent 2x50, barrier start
        left = paths[:50]
        right = paths[50:100]
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def worker(sel: list[Path], tag: str, barrier=barrier, errors=errors) -> None:
            try:
                barrier.wait(timeout=10)
                add_tags(sel, tag)
            except BaseException as exc:  # noqa: BLE001 - probe telemetry
                errors.append(exc)

        t0 = time.perf_counter()
        threads = [
            threading.Thread(target=worker, args=(left, f"conc_left_rep{rep}")),
            threading.Thread(target=worker, args=(right, f"conc_right_rep{rep}")),
        ]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        conc = time.perf_counter() - t0
        if errors:
            raise RuntimeError(f"write-gate probe worker failed: {errors[0]!r}")
        results.setdefault("concurrent_s", []).append(conc)

    serial_total = statistics.median(results["serial_s"])
    concurrent_total = statistics.median(results["concurrent_s"])
    return {
        "writes": 100,
        "serial_100_s_median": round(serial_total, 3),
        "concurrent_2x50_s_median": round(concurrent_total, 3),
        "amplification_ratio": round(concurrent_total / serial_total, 2) if serial_total else None,
        "per_write_ms_serial": round(serial_total / 100 * 1000, 2),
        "per_write_ms_concurrent": round(concurrent_total / 100 * 1000, 2),
        "stray_txn_rollbacks": guard["stray"],
        "raw": {k: [round(v, 3) for v in vals] for k, vals in results.items()},
    }


def probe_tag_service_concurrent_failclose(session, services) -> dict:
    """Quantify TagService.add_tag fail-close under two concurrent writers.

    Both threads call the session-bound service (with the
    ``_require_event_safe_transaction`` pre-check) exactly like the gate probe
    above; here we count how many calls succeed vs raise the
    "clean transaction boundary" RuntimeError.
    """
    tag_svc = services.tag_service
    root = session.root
    conn = session.connection_for(root)
    seed_dir = Path(session.root_str) / "__write_gate_probe__"

    ok_count = 0
    raise_count = 0
    barrier = threading.Barrier(2)

    def worker(sel: list[Path], tag: str) -> None:
        nonlocal ok_count, raise_count
        barrier.wait(timeout=10)
        for path in sel:
            try:
                tag_svc.add_tag(root, path, tag)
                ok_count += 1
            except RuntimeError as exc:
                if "clean transaction boundary" in str(exc):
                    raise_count += 1
                else:
                    raise

    left = [seed_dir / f"gate_{i:04d}.txt" for i in range(50)]
    right = [seed_dir / f"gate_{i:04d}.txt" for i in range(50, 100)]
    threads = [
        threading.Thread(target=worker, args=(left, "svc_failclose_left")),
        threading.Thread(target=worker, args=(right, "svc_failclose_right")),
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    _ = conn  # connection touched only via the guard in repo probe
    return {"calls": 100, "succeeded": ok_count, "failed_clean_boundary": raise_count}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--thumbs", type=int, default=200)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--skip-images", type=int, default=0,
                    help="skip generation CPU time of the first N images (reuse)")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    runtime_root = isolate_runtime_root()
    SCRATCH.mkdir(parents=True, exist_ok=True)

    from AssetsManager.application.tag_canonicalizer import install_tag_canonicalizer
    from AssetsManager.core.tag_library import get_library

    install_tag_canonicalizer(get_library().canonical)

    from AssetsManager.application.bootstrap import ApplicationBootstrap

    payload: dict = {"measurement": "p2-pipeline"}

    # ── thumbnail throughput (service-only, no session needed for process_image)
    img_dir = SCRATCH / f"thumbs_{args.thumbs}"
    print(f"[p2_pipeline] generating {args.thumbs} 512x512 PNGs ...", flush=True)
    t0 = time.perf_counter()
    image_paths = make_test_images(img_dir, args.thumbs)
    payload["image_generation_s"] = round(time.perf_counter() - t0, 2)

    class _SvcHost:
        """Minimal host exposing a production ThumbnailService instance."""

        def __init__(self) -> None:
            from AssetsManager.application.thumbnail_service import ThumbnailService

            self.thumbnail_service = ThumbnailService()

    host = _SvcHost()
    print("[p2_pipeline] measuring process_image throughput ...", flush=True)
    payload["thumbnail_process_image"] = probe_thumbnails(host, image_paths, args.reps)
    print(payload["thumbnail_process_image"])

    # ── DB write gate (needs a real session)
    lib_dir = SCRATCH / "write_gate_lib"
    lib_dir.mkdir(exist_ok=True)
    (lib_dir / "seed.txt").write_text("seed", encoding="utf-8")
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(lib_dir)
    services = bootstrap.runtime_for(session).services
    print("[p2_pipeline] measuring db write gate ...", flush=True)
    payload["db_write_gate"] = probe_write_gate(session, services, args.reps)
    print(payload["db_write_gate"])
    payload["tag_service_concurrent_failclose"] = probe_tag_service_concurrent_failclose(
        session, services
    )
    print(payload["tag_service_concurrent_failclose"])
    bootstrap.library_service.close_session(session)

    evidence_dir = PROJECT_ROOT / "docs" / "reports" / "performance-audit-2026-09-06" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "p2-pipeline.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    print(f"[evidence] wrote {evidence_dir / 'p2-pipeline.json'}")

    if not args.keep:
        shutil.rmtree(SCRATCH, ignore_errors=True)
    shutil.rmtree(runtime_root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
