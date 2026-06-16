"""Performance baseline script — run manually to track key operation timings.

Usage:
    python -m tests.perf_baseline

Output: Markdown table with timings for reproducible micro-benchmarks.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path


def _setup_library(root: Path, file_count: int = 1000, dir_count: int = 50):
    """Create a synthetic library for benchmarking."""
    for i in range(dir_count):
        d = root / f"project_{i:03d}"
        d.mkdir(exist_ok=True)
        for j in range(file_count // dir_count):
            (d / f"file_{j:03d}.png").write_bytes(b"\x89PNG" + os.urandom(1024))


def _setup_db(root: Path) -> sqlite3.Connection:
    """Create an in-memory DB with schema for benchmarking."""
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(database._SCHEMA)
    migrate(conn)
    return conn


def bench_asset_service_list(root: Path, iterations: int = 5) -> dict:
    from AssetsManager.application.asset_service import AssetService, DirectoryListOptions
    svc = AssetService()
    listing = None
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        listing = svc.list_directory(root, root, options=DirectoryListOptions(sort_by="name"))
        t1 = time.perf_counter()
        times.append(t1 - t0)
    return {
        "operation": "AssetService.list_directory()",
        "items": len(listing.items) if listing else 0,
        "avg_ms": f"{sum(times) / len(times) * 1000:.1f}",
        "min_ms": f"{min(times) * 1000:.1f}",
    }


def bench_project_service_list(root: Path, conn: sqlite3.Connection, iterations: int = 5) -> dict:
    from AssetsManager.application.project_service import ProjectDepthConfig, ProjectService
    svc = ProjectService(connection_provider=lambda _root: conn)
    cfg = ProjectDepthConfig(global_depth=1)
    listing = None
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        listing = svc.list_projects(root, root, depth_config=cfg, db_conn=conn)
        t1 = time.perf_counter()
        times.append(t1 - t0)
    return {
        "operation": "ProjectService.list_projects()",
        "items": len(listing.items) if listing else 0,
        "avg_ms": f"{sum(times) / len(times) * 1000:.1f}",
        "min_ms": f"{min(times) * 1000:.1f}",
    }


def bench_project_service_tree(root: Path, iterations: int = 5) -> dict:
    from AssetsManager.application.project_service import ProjectDepthConfig, ProjectService
    svc = ProjectService(connection_provider=lambda _root: sqlite3.connect(":memory:"))
    cfg = ProjectDepthConfig(global_depth=2)
    tree = None
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        tree = svc.build_tree(root, depth_config=cfg)
        t1 = time.perf_counter()
        times.append(t1 - t0)
    return {
        "operation": "ProjectService.build_tree()",
        "nodes": len(tree.tree) if tree else 0,
        "avg_ms": f"{sum(times) / len(times) * 1000:.1f}",
        "min_ms": f"{min(times) * 1000:.1f}",
    }


def bench_thumbnail_cache_key(iterations: int = 10000) -> dict:
    from AssetsManager.application.thumbnail_service import thumbnail_cache_key
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG" + os.urandom(1024))
        path = f.name
    try:
        t0 = time.perf_counter()
        for _ in range(iterations):
            thumbnail_cache_key(path)
        t1 = time.perf_counter()
        return {
            "operation": f"thumbnail_cache_key() x{iterations}",
            "avg_us": f"{(t1 - t0) / iterations * 1_000_000:.1f}",
            "total_ms": f"{(t1 - t0) * 1000:.1f}",
        }
    finally:
        os.unlink(path)


def bench_asset_filters_sort(iterations: int = 100) -> dict:
    from AssetsManager.application.asset_filters import sort_key_for_entry
    entries = [
        (f"file_{i:04d}.png", False, 1000.0 + i, 1024 * i, ".png")
        for i in range(1000)
    ]
    times = []
    for _ in range(iterations):
        items = list(entries)
        t0 = time.perf_counter()
        items.sort(key=lambda e: sort_key_for_entry(e[0], e[1], e[2], e[3], e[4], "name"))
        t1 = time.perf_counter()
        times.append(t1 - t0)
    return {
        "operation": f"sort_key_for_entry() x1000 items x{iterations}",
        "avg_ms": f"{sum(times) / len(times) * 1000:.1f}",
        "min_ms": f"{min(times) * 1000:.1f}",
    }


def main():
    print("# Performance Baseline\n")
    print(f"Date: {time.strftime('%Y-%m-%d %H:%M')}")
    print(f"Python: {sys.version.split()[0]}\n")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "library"
        root.mkdir()
        _setup_library(root, file_count=500, dir_count=25)
        conn = _setup_db(root)

        results = [
            bench_asset_service_list(root),
            bench_project_service_list(root, conn),
            bench_project_service_tree(root),
            bench_thumbnail_cache_key(),
            bench_asset_filters_sort(),
        ]

        conn.close()

    print("| Operation | Details | Avg | Min |")
    print("|---|---|---|---|")
    for r in results:
        if "items" in r:
            details = f"{r['items']} items"
        elif "nodes" in r:
            details = f"{r['nodes']} nodes"
        else:
            details = ""
        avg = r.get("avg_ms", r.get("avg_us", ""))
        min_val = r.get("min_ms", r.get("total_ms", ""))
        unit = "ms" if "avg_ms" in r else "us" if "avg_us" in r else "ms"
        print(f"| {r['operation']} | {details} | {avg} {unit} | {min_val} {unit} |")

    print("\nRun `python -m tests.perf_baseline` to regenerate.")


if __name__ == "__main__":
    main()
