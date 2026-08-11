"""Performance baselines — Phase 8 regression guardrails.

These tests establish lower-bound performance expectations for core
operations. They are designed to catch 10x+ regressions, not micro-benchmarks.
All thresholds are calibrated for a developer machine; CI may adjust upward.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.perf  # opt in with `pytest -m perf`

import time
import os
from unittest.mock import patch


# ── Threshold constants (in seconds unless noted) ──────────────

DIRECTORY_LIST_1K_MAX = 2.0      # 1,000 files in a single directory
DIRECTORY_LIST_10K_MAX = 15.0     # 10,000 files
METADATA_READ_MAX = 0.02          # single-file metadata fetch
TAG_LIST_MAX = 0.1                # full tag listing
PATHGUARD_RESOLVE_MAX = 0.001     # single path resolution
SEARCH_INDEXED_MAX = 0.5          # indexed name search
BATCH_SIZE_SANITY = 500 * 1024 * 1024  # 500 MB — must match LAN limit


# ── Directory listing ─────────────────────────────────────────

def test_directory_listing_1k_files_performance(tmp_path):
    """Listing 1,000 files must complete under threshold."""
    from AssetsManager.application import AssetService, DirectoryListOptions

    for i in range(1000):
        (tmp_path / f"file_{i:04d}.txt").write_text(f"content {i}", encoding="utf-8")

    svc = AssetService()
    start = time.perf_counter()
    listing = svc.list_directory(tmp_path, tmp_path,
                                 DirectoryListOptions(sort_by="name", order="asc"))
    elapsed = time.perf_counter() - start

    assert len(listing.items) > 0
    assert elapsed < DIRECTORY_LIST_1K_MAX, (
        f"1k file listing: {elapsed:.3f}s exceeds {DIRECTORY_LIST_1K_MAX}s"
    )


def test_directory_listing_10k_files_performance(tmp_path):
    """Listing 10,000 files must complete under threshold."""
    from AssetsManager.application import AssetService, DirectoryListOptions

    for i in range(10000):
        (tmp_path / f"file_{i:05d}.txt").write_text(f"content {i}", encoding="utf-8")

    svc = AssetService()
    start = time.perf_counter()
    listing = svc.list_directory(tmp_path, tmp_path,
                                 DirectoryListOptions(sort_by="name", order="asc"))
    elapsed = time.perf_counter() - start

    assert len(listing.items) > 0
    assert elapsed < DIRECTORY_LIST_10K_MAX, (
        f"10k file listing: {elapsed:.3f}s exceeds {DIRECTORY_LIST_10K_MAX}s"
    )


def test_directory_listing_many_subdirs_skip_summaries(tmp_path):
    """Listing 200 subdirs with scan_summaries=False must be significantly faster."""
    from AssetsManager.application import AssetService, DirectoryListOptions

    for i in range(200):
        d = tmp_path / f"dir_{i:04d}"
        d.mkdir()
        for j in range(5):
            (d / f"file_{j}.txt").write_text(f"content {j}", encoding="utf-8")

    svc = AssetService()

    start = time.perf_counter()
    listing_full = svc.list_directory(tmp_path, tmp_path,
                                      DirectoryListOptions(sort_by="name", scan_summaries=True))
    elapsed_full = time.perf_counter() - start

    start = time.perf_counter()
    listing_fast = svc.list_directory(tmp_path, tmp_path,
                                      DirectoryListOptions(sort_by="name", scan_summaries=False))
    elapsed_fast = time.perf_counter() - start

    assert len(listing_full.items) == 200
    assert len(listing_fast.items) == 200
    assert listing_full.items[0].item_count is not None
    assert listing_fast.items[0].item_count is None
    assert elapsed_fast < elapsed_full * 0.5, (
        f"scan_summaries=False ({elapsed_fast:.3f}s) should be <50% of "
        f"scan_summaries=True ({elapsed_full:.3f}s)"
    )


# ── Metadata service ──────────────────────────────────────────

def test_metadata_read_performance(tmp_path, request):
    """Single-file metadata fetch must be fast."""
    from AssetsManager.application import MetadataService
    from AssetsManager.core.database import DatabaseManager

    root = tmp_path
    (root / "test.txt").write_text("hello", encoding="utf-8")

    mgr = DatabaseManager()
    request.addfinalizer(mgr.close)
    conn = mgr.connection_for(root)
    svc = MetadataService(connection_provider=lambda r: conn)
    svc.set_notes(str(root), str(root / "test.txt"), "sample notes")

    start = time.perf_counter()
    for _ in range(50):
        meta = svc.get_metadata(str(root), str(root / "test.txt"))
    avg = (time.perf_counter() - start) / 50

    assert meta.notes == "sample notes"
    assert avg < METADATA_READ_MAX, (
        f"avg metadata read: {avg*1000:.2f}ms exceeds {METADATA_READ_MAX*1000:.0f}ms"
    )


# ── Tag service ───────────────────────────────────────────────

def test_tag_list_performance(tmp_path, request):
    """Full tag listing must be reasonably fast."""
    from AssetsManager.application import TagService
    from AssetsManager.core.database import DatabaseManager

    root = tmp_path
    mgr = DatabaseManager()
    request.addfinalizer(mgr.close)
    conn = mgr.connection_for(root)
    svc = TagService(connection_provider=lambda r: conn)

    # Add 100 tags across 20 files
    for i in range(20):
        fp = str(root / f"file_{i}.txt")
        (root / f"file_{i}.txt").write_text(f"c{i}", encoding="utf-8")
        for t in range(5):
            svc.add_tag(str(root), fp, f"tag_{i*5+t}")

    start = time.perf_counter()
    tags = svc.list_tags(str(root))
    elapsed = time.perf_counter() - start

    assert len(tags) >= 100
    assert elapsed < TAG_LIST_MAX, (
        f"tag listing: {elapsed:.3f}s exceeds {TAG_LIST_MAX}s"
    )


# ── PathGuard ─────────────────────────────────────────────────

def test_pathguard_resolve_performance(tmp_path):
    """Single path resolution must be near-instant."""
    from AssetsManager.lan.path_guard import PathGuard

    guard = PathGuard(tmp_path)
    (tmp_path / "deep" / "nest").mkdir(parents=True)

    start = time.perf_counter()
    for _ in range(1000):
        guard.resolve("deep/nest")
    avg = (time.perf_counter() - start) / 1000

    assert avg < PATHGUARD_RESOLVE_MAX, (
        f"avg pathguard resolve: {avg*1e6:.0f}µs exceeds {PATHGUARD_RESOLVE_MAX*1e6:.0f}µs"
    )


# ── Search (indexed) ──────────────────────────────────────────

def test_indexed_search_performance(tmp_path, request):
    """Indexed name search must complete under threshold."""
    from AssetsManager.application import SearchService
    from AssetsManager.core.database import DatabaseManager

    root = tmp_path
    for i in range(500):
        (root / f"asset_{i:04d}.txt").write_text(f"data {i}", encoding="utf-8")

    mgr = DatabaseManager()
    request.addfinalizer(mgr.close)
    conn = mgr.connection_for(root)

    # Build index
    from AssetsManager.application.asset_index_service import AssetIndexService
    indexer = AssetIndexService()
    indexer.index_directory(conn, str(root), str(root))

    svc = SearchService()
    start = time.perf_counter()
    results = svc.search_by_name_indexed(str(root), "asset_0", db_conn=conn)
    elapsed = time.perf_counter() - start

    assert len(results) > 0
    assert elapsed < SEARCH_INDEXED_MAX, (
        f"indexed search: {elapsed:.3f}s exceeds {SEARCH_INDEXED_MAX}s"
    )


# ── Batch download size sanity ────────────────────────────────

def test_batch_download_size_limit_matches_code():
    """The batch download size test constant must match the production limit."""
    from AssetsManager.lan.routes.downloads import MAX_BATCH_DOWNLOAD_BYTES
    assert MAX_BATCH_DOWNLOAD_BYTES == BATCH_SIZE_SANITY, (
        f"MAX_BATCH_DOWNLOAD_BYTES ({MAX_BATCH_DOWNLOAD_BYTES}) "
        f"does not match test constant ({BATCH_SIZE_SANITY})"
    )


# ── ShareRepository write/read ────────────────────────────────

def test_share_repository_create_and_read_performance(tmp_path):
    """Share link creation and retrieval must be fast."""
    import sqlite3
    from AssetsManager.repositories.share_repository import ShareRepository, SHARE_LINKS_SCHEMA

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(SHARE_LINKS_SCHEMA)
    conn.commit()
    repo = ShareRepository(conn)

    start = time.perf_counter()
    ok = repo.insert(
        share_id="test_share_001",
        paths=["project/file.txt"],
        password_hash=None,
        expires_at=None,
        max_downloads=None,
        allow_preview=True,
        created_by="test",
    )
    elapsed_create = time.perf_counter() - start

    assert ok
    assert elapsed_create < 0.01, (
        f"share create: {elapsed_create*1000:.2f}ms exceeds 10ms"
    )

    start = time.perf_counter()
    for _ in range(50):
        row = repo.get("test_share_001")
    avg_get = (time.perf_counter() - start) / 50

    assert row is not None
    assert avg_get < 0.001, (
        f"avg share get: {avg_get*1000:.2f}ms exceeds 1ms"
    )


# ── DirectoryCache integration ────────────────────────────────

def test_directory_listing_with_cache_uses_cached_summaries(tmp_path, request):
    """Warm listings skip subdirectory scans without relying on wall-clock timing."""
    from AssetsManager.application import AssetService, DirectoryListOptions
    from AssetsManager.core.database import DatabaseManager
    from AssetsManager.core.directory_cache import DirectoryCache

    for i in range(200):
        d = tmp_path / f"dir_{i:04d}"
        d.mkdir()
        for j in range(3):
            (d / f"file_{j}.txt").write_text("content")

    mgr = DatabaseManager()
    request.addfinalizer(mgr.close)
    conn = mgr.connection_for(tmp_path)
    cache = DirectoryCache(conn)
    svc = AssetService(directory_cache=cache)

    cold_listing = svc.list_directory(tmp_path, tmp_path, DirectoryListOptions(scan_summaries=True))
    original_scandir = os.scandir
    calls = 0

    def counting_scandir(path, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original_scandir(path, *args, **kwargs)

    with patch("os.scandir", side_effect=counting_scandir):
        warm_listing = svc.list_directory(tmp_path, tmp_path, DirectoryListOptions(scan_summaries=True))

    def summary(items):
        return [
            (item.name, item.path, item.type, item.size_fmt, item.preview_path, item.item_count)
            for item in items
        ]

    assert summary(warm_listing.items) == summary(cold_listing.items)
    assert calls == 1
