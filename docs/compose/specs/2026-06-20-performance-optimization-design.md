# Performance Optimization Design

Date: 2026-06-20
Scope: AssetsManager architecture optimization + Cython hotspot acceleration

## [S1] Phase 1: Async Directory Scanning + Cache

### Problem
- `os.scandir` per directory: ~280µs. 200 subdirs = 56ms blocking.
- PathGuard resolve: 1.3ms/op (filesystem I/O).
- N+1 scan pattern fixed but directory summaries still scan on every listing.

### Solution: Directory Metadata Cache

New SQLite table in `DatabaseManager`:

```sql
CREATE TABLE IF NOT EXISTS directory_cache (
    dir_path TEXT PRIMARY KEY,
    item_count INTEGER,
    preview_path TEXT,
    mtime REAL,
    scanned_at REAL
);
```

- `_scan_dir_summary()` → check cache first, validate mtime, rescan if stale
- Cache persisted per-library (same DB as tags/metadata)
- Invalidation: directory mtime change triggers rescan

### Solution: Lazy Directory Summaries

- `AssetService.list_directory()` defaults `scan_summaries=False`
- LAN API: `?summaries=true` query parameter for on-demand
- Desktop UI: `FileSystemModel._subtitle()` extended to load item_count async

### Solution: Async First-Screen Rendering

- `FileSystemModel.set_directory()` already has `_ScanTask` async scan
- Optimize: return entry list first (without stat), async fill stat/thumbnail
- Target: 1000-file directory first screen < 100ms

## [S2] Phase 2: Cython Hotspot Acceleration

### Compilation Targets (pure computation, no I/O/Qt)

| Module | Functions | Reason |
|--------|-----------|--------|
| `core/cache.py` | LRUCache all | High-frequency OrderedDict ops |
| `core/color_utils.py` | `_hex_to_rgb`, `_rgb_to_hex` | Theme rendering hotspot |
| `core/format_utils.py` | `format_size` | Called per row in list rendering |
| `application/asset_filters.py` | `matches_search`, `is_hidden`, `sort_key_for_entry` | Sort/filter hotspot |

### Excluded from Compilation

- Qt-dependent modules (PySide6 incompatible with Cython .pyd)
- Modules with `__future__ annotations` (Cython doesn't support)
- I/O-intensive modules (DB/filesystem, bottleneck not in CPU)

### Build Strategy

- `setup_cython.py` lists only target modules
- `python setup_cython.py build_ext --inplace` generates `.pyd`
- `.pyd` takes precedence over `.py` on import — no code changes needed
- Add Cython build step to CI

### Expected Improvements

| Operation | Current | Expected Cython |
|-----------|---------|-----------------|
| LRUCache set | 1.2M ops/s | 3M ops/s |
| LRUCache get | 2.7M ops/s | 7M ops/s |
| hex_to_rgb | 2.1M ops/s | 5M ops/s |
| format_size | 1.2M ops/s | 3M ops/s |

## [S3] Phase 3: Database Query Optimization

### Batch Tag Queries

Current: N individual queries (16µs each):
```python
for path in file_paths:
    tags = tag_store.get_tags(path)
```

Optimized: single batch query:
```python
tags_map = tag_store.get_tags_batch(file_paths)
# SQL: SELECT file_path, tag_name FROM file_tags WHERE file_path IN (...)
```

New method: `TagStore.get_tags_batch(paths: list[str]) -> dict[str, list[str]]`

### Precompiled SQL

- `TagRepository` and `MetadataRepository` use class-level `_compiled_stmts` cache
- `sqlite3.Connection.prepare()` auto-caches, but explicit management is more controllable

### LAN Batch Stat Cache Extension

- `files.py` `batch_cached_stats()` already has caching
- Extend to also cache directory item_count (integrates with Phase 1 cache table)

## Execution Order

1. Phase 1a: Directory cache table + cache-aware `_scan_dir_summary`
2. Phase 1b: Lazy summaries (default off, LAN opt-in)
3. Phase 3a: Batch tag query
4. Phase 2: Cython compilation of 4 target modules
5. Phase 1c: Async first-screen optimization
6. Phase 3b: Precompiled SQL + LAN cache extension

## Quality Gate

```powershell
python -m ruff check . && python -m pyright && python -m compileall AssetsManager -q && python -m pytest -q
```

Performance regression tests in `tests/performance/test_baselines.py` must pass.
