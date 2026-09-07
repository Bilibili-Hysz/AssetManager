"""P2 measurement 1 — measured values behind the gate baselines.

``tests/performance/test_baselines.py`` asserts pass/fail but never prints the
measured numbers, so the threshold headroom (margin to the red line) cannot be
read off a green run.  This probe mirrors the timed section of every wall-clock
baseline 1:1 (same services, same operation shape, same item counts) and prints
measured vs threshold vs margin.

Not asserted anywhere — telemetry only.  The authoritative gate stays
``pytest tests/performance -m perf``.

Usage:
    QT_QPA_PLATFORM=offscreen python scripts/perf/p2_gate_baselines.py [--reps N]

Every measurement runs ``--reps`` times (default 3) and the median is reported.
Isolation: an ``AM_RUNTIME_ROOT`` under the system temp dir, same mechanism as
``tests/conftest.py``, so no user settings/RuntimeData are touched.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import tempfile
import time
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def isolate_runtime_root() -> Path:
    base = Path(os.environ.get("AM_PROBE_RUNTIME_PARENT", tempfile.gettempdir()))
    root = base / f"p2_gate_runtime_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    (root / "RuntimeData").mkdir(parents=True, exist_ok=True)
    os.environ["AM_RUNTIME_ROOT"] = str(root / "RuntimeData")
    return root


def make_library(root: Path, files: int, prefix: str = "file") -> None:
    root.mkdir(parents=True, exist_ok=True)
    for i in range(files):
        (root / f"{prefix}_{i:05d}.txt").write_text(f"content {i}", encoding="utf-8")


def measure(reps: int):
    # Same composition-root seam tests/conftest.py installs for the suite.
    from AssetsManager.application.tag_canonicalizer import install_tag_canonicalizer
    from AssetsManager.core.tag_library import get_library

    install_tag_canonicalizer(get_library().canonical)

    from AssetsManager.application import (
        AssetService,
        DirectoryListOptions,
        MetadataService,
        SearchService,
        TagService,
    )
    from AssetsManager.application.asset_index_service import AssetIndexService
    from AssetsManager.core.database import DatabaseManager

    results: list[dict] = []

    def record(name: str, samples: list[float], threshold: float, unit: str = "s") -> None:
        med = statistics.median(samples)
        margin = (threshold - med) / threshold if threshold > 0 else 0.0
        results.append({
            "baseline": name,
            "median": med,
            "min": min(samples),
            "max": max(samples),
            "threshold": threshold,
            "margin_pct": round(margin * 100, 1),
            "unit": unit,
        })
        flag = "  <-- NEAR RED LINE" if margin < 0.30 and margin >= 0 else "  (FAILING)" if margin < 0 else ""
        print(f"  {name:<44} median {med:.4f}{unit}  threshold {threshold}{unit}  "
              f"margin {margin * 100:+.0f}%{flag}")

    # ── directory listing 1k / 10k (tests/performance/test_baselines.py:31,50)
    for count, threshold in ((1000, 2.0), (10000, 15.0)):
        samples: list[float] = []
        tmp = Path(tempfile.mkdtemp(prefix="p2_gate_list_"))
        try:
            make_library(tmp, count)
            svc = AssetService()
            for _ in range(reps):
                t0 = time.perf_counter()
                listing = svc.list_directory(tmp, tmp, DirectoryListOptions(sort_by="name", order="asc"))
                samples.append(time.perf_counter() - t0)
            assert len(listing.items) > 0
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        record(f"directory_listing_{count // 1000}k", samples, threshold)

    # ── metadata read avg of 50 (test_baselines.py:103)
    samples = []
    tmp = Path(tempfile.mkdtemp(prefix="p2_gate_meta_"))
    mgr = DatabaseManager()
    try:
        (tmp / "test.txt").write_text("hello", encoding="utf-8")
        conn = mgr.connection_for(tmp)
        svc = MetadataService(connection_provider=lambda r: conn)
        svc.set_notes(str(tmp), str(tmp / "test.txt"), "sample notes")
        for _ in range(reps):
            t0 = time.perf_counter()
            for _ in range(50):
                meta = svc.get_metadata(str(tmp), str(tmp / "test.txt"))
            samples.append((time.perf_counter() - t0) / 50)
        assert meta.notes == "sample notes"
    finally:
        mgr.close()
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    record("metadata_read_avg50", samples, 0.02)

    # ── tag list (test_baselines.py:130)
    samples = []
    tmp = Path(tempfile.mkdtemp(prefix="p2_gate_tags_"))
    mgr = DatabaseManager()
    try:
        conn = mgr.connection_for(tmp)
        svc = TagService(connection_provider=lambda r: conn)
        for i in range(20):
            fp = str(tmp / f"file_{i}.txt")
            (tmp / f"file_{i}.txt").write_text(f"c{i}", encoding="utf-8")
            for t in range(5):
                svc.add_tag(str(tmp), fp, f"tag_{i * 5 + t}")
        for _ in range(reps):
            t0 = time.perf_counter()
            tags = svc.list_tags(str(tmp))
            samples.append(time.perf_counter() - t0)
        assert len(tags) >= 100
    finally:
        mgr.close()
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    record("tag_list_full", samples, 0.1)

    # ── pathguard resolve avg of 1000 (test_baselines.py:160)
    # Threshold mirrors PATHGUARD_RESOLVE_MAX in tests/performance/test_baselines.py
    # (relaxed 0.001 -> 0.003 in the 2026-09-07 P2 audit; see its comment).
    from AssetsManager.lan.path_guard import PathGuard

    samples = []
    tmp = Path(tempfile.mkdtemp(prefix="p2_gate_guard_"))
    try:
        (tmp / "deep" / "nest").mkdir(parents=True)
        guard = PathGuard(tmp)
        for _ in range(reps):
            t0 = time.perf_counter()
            for _ in range(1000):
                guard.resolve("deep/nest")
            samples.append((time.perf_counter() - t0) / 1000)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    record("pathguard_resolve_avg1k", samples, 0.003, unit="s")

    # ── indexed search (test_baselines.py:179)
    samples = []
    tmp = Path(tempfile.mkdtemp(prefix="p2_gate_search_"))
    mgr = DatabaseManager()
    try:
        for i in range(500):
            (tmp / f"asset_{i:04d}.txt").write_text(f"data {i}", encoding="utf-8")
        conn = mgr.connection_for(tmp)
        indexer = AssetIndexService()
        indexer.index_directory(conn, str(tmp), str(tmp))
        svc = SearchService()
        for _ in range(reps):
            t0 = time.perf_counter()
            found = svc.search_by_name_indexed(str(tmp), "asset_0", db_conn=conn)
            samples.append(time.perf_counter() - t0)
        assert len(found) > 0
    finally:
        mgr.close()
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    record("search_indexed_name", samples, 0.5)

    # ── share repository create/get (test_baselines.py:221)
    import sqlite3

    from AssetsManager.repositories.share_repository import SHARE_LINKS_SCHEMA, ShareRepository

    create_samples: list[float] = []
    get_samples: list[float] = []
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(SHARE_LINKS_SCHEMA)
    conn.commit()
    repo = ShareRepository(conn)
    for rep in range(reps):
        share_id = f"test_share_{rep:03d}"
        t0 = time.perf_counter()
        ok = repo.insert(
            share_id=share_id,
            paths=["project/file.txt"],
            password_hash=None,
            expires_at=None,
            max_downloads=None,
            allow_preview=True,
            created_by="test",
        )
        create_samples.append(time.perf_counter() - t0)
        assert ok
        t0 = time.perf_counter()
        for _ in range(50):
            row = repo.get(share_id)
        get_samples.append((time.perf_counter() - t0) / 50)
        assert row is not None
    conn.close()
    record("share_repo_create", create_samples, 0.01)
    record("share_repo_get_avg50", get_samples, 0.001)

    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    args = ap.parse_args()

    runtime_root = isolate_runtime_root()
    print(f"[p2_gate_baselines] isolated runtime: {runtime_root}")
    print(f"[p2_gate_baselines] reps per measurement: {args.reps}\n")
    measure(args.reps)
    import shutil

    shutil.rmtree(runtime_root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
