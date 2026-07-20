"""Real-world performance baseline — tests against real asset library.

Usage:
    python -m tests.perf_real_world

Tests key operations against a large real-world asset library to identify
performance bottlenecks.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

LIBRARY_ROOT = Path(r"H:\VrChat\Costume（服装）")


def _timed(fn, *args, iterations=3, **kwargs):
    """Run fn multiple times and return (avg_ms, min_ms, result)."""
    times = []
    result = None
    for _ in range(iterations):
        t0 = time.perf_counter()
        result = fn(*args, **kwargs)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)
    return sum(times) / len(times), min(times), result  # type: ignore[return-value]


def bench_scandir_top_level():
    """Benchmark os.scandir on the top-level directory."""
    def run():
        return list(os.scandir(str(LIBRARY_ROOT)))
    avg, min_t, entries = _timed(run)
    dirs = sum(1 for e in entries if e.is_dir())
    files = sum(1 for e in entries if e.is_file())
    return {
        "operation": "os.scandir (top-level)",
        "entries": len(entries),
        "dirs": dirs,
        "files": files,
        "avg_ms": f"{avg:.1f}",
        "min_ms": f"{min_t:.1f}",
    }


def bench_scandir_subdir():
    """Benchmark os.scandir on a single subdirectory."""
    subdirs = [e for e in os.scandir(str(LIBRARY_ROOT)) if e.is_dir()]
    if not subdirs:
        return {"operation": "os.scandir (subdir)", "error": "no subdirs"}
    target = subdirs[0]
    def run():
        return list(os.scandir(target.path))
    avg, min_t, entries = _timed(run)
    return {
        "operation": f"os.scandir ({target.name})",
        "entries": len(entries),
        "avg_ms": f"{avg:.1f}",
        "min_ms": f"{min_t:.1f}",
    }


def bench_asset_service_list():
    """Benchmark AssetService.list_directory on the top-level."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "AssetsManager"))
    from application.asset_service import AssetService, DirectoryListOptions
    svc = AssetService()
    options = DirectoryListOptions(sort_by="name", order="asc")
    def run():
        return svc.list_directory(LIBRARY_ROOT, LIBRARY_ROOT, options=options)
    avg, min_t, listing = _timed(run, iterations=2)
    return {
        "operation": "AssetService.list_directory (top-level)",
        "items": len(listing.items),
        "avg_ms": f"{avg:.1f}",
        "min_ms": f"{min_t:.1f}",
    }


def bench_project_service_list():
    """Benchmark ProjectService.list_projects on the top-level."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "AssetsManager"))
    from core import database
    from core.db_migrations import migrate
    from repositories.auth_repository import AuthRepository
    from repositories.share_repository import ShareRepository
    from application.project_service import ProjectDepthConfig, ProjectService

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(database._SCHEMA)
    migrate(conn)
    AuthRepository(conn).init_tables()
    ShareRepository(conn).init_table()

    svc = ProjectService(connection_provider=lambda _root: conn)
    cfg = ProjectDepthConfig(global_depth=1)
    def run():
        return svc.list_projects(LIBRARY_ROOT, LIBRARY_ROOT, depth_config=cfg, db_conn=conn)
    avg, min_t, listing = _timed(run, iterations=2)
    conn.close()
    return {
        "operation": "ProjectService.list_projects (top-level, depth=1)",
        "items": len(listing.items),
        "avg_ms": f"{avg:.1f}",
        "min_ms": f"{min_t:.1f}",
    }


def bench_project_service_tree():
    """Benchmark ProjectService.build_tree on the top-level."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "AssetsManager"))
    from application.project_service import ProjectDepthConfig, ProjectService
    svc = ProjectService(connection_provider=lambda _root: sqlite3.connect(":memory:"))
    cfg = ProjectDepthConfig(global_depth=1)
    def run():
        return svc.build_tree(LIBRARY_ROOT, depth_config=cfg)
    avg, min_t, tree = _timed(run, iterations=2)
    return {
        "operation": "ProjectService.build_tree (depth=1)",
        "nodes": len(tree.tree),
        "avg_ms": f"{avg:.1f}",
        "min_ms": f"{min_t:.1f}",
    }


def bench_thumbnail_cache_key():
    """Benchmark thumbnail_cache_key on a sample file."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "AssetsManager"))
    from application.thumbnail_service import thumbnail_cache_key

    subdirs = [e for e in os.scandir(str(LIBRARY_ROOT)) if e.is_dir()]
    sample = None
    for d in subdirs:
        for f in os.scandir(d.path):
            if f.is_file():
                sample = f.path
                break
        if sample:
            break
    if not sample:
        return {"operation": "thumbnail_cache_key", "error": "no files found"}

    def run():
        for _ in range(10000):
            thumbnail_cache_key(sample)
    avg, min_t, _ = _timed(run, iterations=3)
    return {
        "operation": "thumbnail_cache_key x10000",
        "avg_ms": f"{avg:.1f}",
        "min_ms": f"{min_t:.1f}",
    }


def main():
    print("# Real-World Performance Baseline\n")
    print(f"Library: `{LIBRARY_ROOT}`")
    print(f"Date: {time.strftime('%Y-%m-%d %H:%M')}")
    print(f"Python: {sys.version.split()[0]}\n")

    if not LIBRARY_ROOT.exists():
        print("ERROR: Library path does not exist.")
        return

    results = [
        bench_scandir_top_level(),
        bench_scandir_subdir(),
        bench_asset_service_list(),
        bench_project_service_list(),
        bench_project_service_tree(),
        bench_thumbnail_cache_key(),
    ]

    print("| Operation | Details | Avg | Min |")
    print("|---|---|---|---|")
    for r in results:
        if "error" in r:
            print(f"| {r['operation']} | ERROR: {r['error']} | — | — |")
            continue
        details = []
        if "entries" in r:
            details.append(f"{r['entries']} entries")
        if "items" in r:
            details.append(f"{r['items']} items")
        if "nodes" in r:
            details.append(f"{r['nodes']} nodes")
        detail_str = ", ".join(details) if details else ""
        print(f"| {r['operation']} | {detail_str} | {r['avg_ms']} ms | {r['min_ms']} ms |")

    print("\nRun `python -m tests.perf_real_world` to regenerate.")


if __name__ == "__main__":
    import sys
    main()
