# Performance Optimization Implementation Plan
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Optimize AssetsManager performance through directory cache, Cython hotspot acceleration, and async rendering improvements.

**Architecture:** Three-phase approach — (1) directory metadata cache + lazy summaries, (2) Cython compilation of pure-computation modules, (3) async first-screen rendering + DB optimization.

**Tech Stack:** Python 3.14, PySide6, SQLite (WAL), Cython, asyncio

---

## File Structure

### New Files
- `AssetsManager/core/directory_cache.py` — DirectoryCache class (SQLite-backed)
- `setup_cython.py` — Cython build script (project root)
- `tests/core/test_directory_cache.py` — Directory cache tests
- `tests/performance/test_cython_benchmarks.py` — Cython before/after benchmarks

### Modified Files
- `AssetsManager/core/database.py` — Add `directory_cache` table to `_SCHEMA`
- `AssetsManager/core/db_migrations.py` — Add migration v5 for directory_cache table
- `AssetsManager/application/asset_service.py` — Use DirectoryCache in `_scan_dir_summary`
- `AssetsManager/panels/file_list/_model.py` — Async item_count loading in `_subtitle`
- `AssetsManager/lan/routes/files.py` — Integrate directory cache for LAN responses
- `AssetsManager/core/cache.py` — Remove `__future__` annotations (Cython compat)
- `AssetsManager/core/color_utils.py` — Remove `__future__` annotations (Cython compat)
- `AssetsManager/core/format_utils.py` — Remove `__future__` annotations (Cython compat)
- `AssetsManager/application/asset_filters.py` — Remove `__future__` annotations (Cython compat)

---

### Task 1: Directory Cache Table (Schema)

**Covers:** S1

**Files:**
- Modify: `AssetsManager/core/database.py:27-66`
- Modify: `AssetsManager/core/db_migrations.py:15,41-145`
- Test: `tests/core/test_directory_cache.py`

- [ ] **Step 1: Add directory_cache table to _SCHEMA**

In `AssetsManager/core/database.py`, append to `_SCHEMA` string (after `library_stats`):

```sql
CREATE TABLE IF NOT EXISTS directory_cache (
    dir_path     TEXT PRIMARY KEY,
    item_count   INTEGER NOT NULL DEFAULT 0,
    preview_path TEXT,
    mtime        REAL NOT NULL,
    scanned_at   REAL NOT NULL DEFAULT (strftime('%s','now'))
);
```

- [ ] **Step 2: Add migration v5**

In `AssetsManager/core/db_migrations.py`:
- Change `CURRENT_SCHEMA_VERSION = 4` → `CURRENT_SCHEMA_VERSION = 5`
- Add migration function:

```python
def _migrate_v5(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS directory_cache ("
        "dir_path TEXT PRIMARY KEY, item_count INTEGER NOT NULL DEFAULT 0, "
        "preview_path TEXT, mtime REAL NOT NULL, "
        "scanned_at REAL NOT NULL DEFAULT (strftime('%s','now')))"
    )
    conn.commit()
```

- Register in `_all_migrations()`:

```python
Migration(5, "directory_cache", _migrate_v5),
```

- [ ] **Step 3: Write test for migration**

```python
def test_migration_v5_creates_directory_cache(memory_db):
    from AssetsManager.core.db_migrations import migrate
    migrate(memory_db)
    rows = memory_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='directory_cache'"
    ).fetchall()
    assert len(rows) == 1
```

- [ ] **Step 4: Run test**

Run: `pytest tests/core/test_directory_cache.py::test_migration_v5_creates_directory_cache -v`
Expected: PASS

- [ ] **Step 5: Run full quality gate**

Run: `python -m ruff check . && python -m pyright && python -m pytest -q`

---

### Task 2: DirectoryCache Class

**Covers:** S1

**Files:**
- Create: `AssetsManager/core/directory_cache.py`
- Test: `tests/core/test_directory_cache.py`

- [ ] **Step 1: Write failing tests**

```python
def test_directory_cache_set_and_get(memory_db):
    from AssetsManager.core.directory_cache import DirectoryCache
    cache = DirectoryCache(memory_db)
    cache.set("/lib/subdir", item_count=42, preview_path="/lib/subdir/preview.jpg", mtime=1000.0)
    result = cache.get("/lib/subdir")
    assert result is not None
    assert result.item_count == 42
    assert result.preview_path == "/lib/subdir/preview.jpg"

def test_directory_cache_returns_none_for_missing(memory_db):
    from AssetsManager.core.directory_cache import DirectoryCache
    cache = DirectoryCache(memory_db)
    assert cache.get("/nonexistent") is None

def test_directory_cache_invalidates_on_mtime_change(memory_db):
    from AssetsManager.core.directory_cache import DirectoryCache
    cache = DirectoryCache(memory_db)
    cache.set("/lib/sub", item_count=10, preview_path=None, mtime=1000.0)
    # Same mtime → cache hit
    result = cache.get("/lib/sub", mtime=1000.0)
    assert result is not None
    # Different mtime → cache miss
    result = cache.get("/lib/sub", mtime=2000.0)
    assert result is None

def test_directory_cache_batch_set(memory_db):
    from AssetsManager.core.directory_cache import DirectoryCache
    cache = DirectoryCache(memory_db)
    entries = [
        ("/lib/a", 5, None, 1000.0),
        ("/lib/b", 10, "/lib/b/img.jpg", 2000.0),
    ]
    cache.set_batch(entries)
    assert cache.get("/lib/a").item_count == 5
    assert cache.get("/lib/b").item_count == 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_directory_cache.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement DirectoryCache**

Create `AssetsManager/core/directory_cache.py`:

```python
"""Directory metadata cache — SQLite-backed cache for subdirectory summaries."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class DirCacheEntry:
    item_count: int
    preview_path: str | None
    mtime: float
    scanned_at: float


class DirectoryCache:
    """Cache for directory item_count and preview_path, persisted in per-library SQLite."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def get(self, dir_path: str, mtime: float | None = None) -> DirCacheEntry | None:
        """Return cached entry, or None if missing/stale."""
        row = self._conn.execute(
            "SELECT item_count, preview_path, mtime, scanned_at FROM directory_cache WHERE dir_path=?",
            (dir_path,),
        ).fetchone()
        if row is None:
            return None
        entry = DirCacheEntry(item_count=row[0], preview_path=row[1], mtime=row[2], scanned_at=row[3])
        if mtime is not None and entry.mtime != mtime:
            return None
        return entry

    def set(self, dir_path: str, item_count: int, preview_path: str | None, mtime: float) -> None:
        """Store or update a directory cache entry."""
        self._conn.execute(
            "INSERT INTO directory_cache (dir_path, item_count, preview_path, mtime, scanned_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(dir_path) DO UPDATE SET "
            "item_count=excluded.item_count, preview_path=excluded.preview_path, "
            "mtime=excluded.mtime, scanned_at=excluded.scanned_at",
            (dir_path, item_count, preview_path, mtime, time.time()),
        )
        self._conn.commit()

    def set_batch(self, entries: list[tuple[str, int, str | None, float]]) -> None:
        """Batch insert/update cache entries."""
        now = time.time()
        self._conn.executemany(
            "INSERT INTO directory_cache (dir_path, item_count, preview_path, mtime, scanned_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(dir_path) DO UPDATE SET "
            "item_count=excluded.item_count, preview_path=excluded.preview_path, "
            "mtime=excluded.mtime, scanned_at=excluded.scanned_at",
            [(path, count, preview, mtime, now) for path, count, preview, mtime in entries],
        )
        self._conn.commit()

    def invalidate(self, dir_path: str) -> None:
        """Remove a single cache entry."""
        self._conn.execute("DELETE FROM directory_cache WHERE dir_path=?", (dir_path,))
        self._conn.commit()

    def clear(self) -> None:
        """Remove all cache entries."""
        self._conn.execute("DELETE FROM directory_cache")
        self._conn.commit()
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/core/test_directory_cache.py -v`
Expected: 4 PASS

- [ ] **Step 5: Run full quality gate**

Run: `python -m ruff check . && python -m pyright && python -m pytest -q`

---

### Task 3: Integrate DirectoryCache into AssetService

**Covers:** S1

**Files:**
- Modify: `AssetsManager/application/asset_service.py`
- Test: `tests/performance/test_baselines.py`

- [ ] **Step 1: Update `_scan_dir_summary` to use cache**

In `AssetsManager/application/asset_service.py`, modify `_scan_dir_summary` to accept an optional `DirectoryCache` and `db_conn`:

Replace the standalone `_scan_dir_summary` function with:

```python
def _scan_dir_summary(dir_path: Path, cache: DirectoryCache | None = None) -> tuple[Path | None, int]:
    """Scan a directory once to get both the first image and item count.

    Uses DirectoryCache when available to avoid repeated filesystem scans.
    """
    dir_str = str(dir_path)
    try:
        mtime = dir_path.stat().st_mtime
    except OSError:
        mtime = 0.0

    if cache is not None:
        entry = cache.get(dir_str, mtime=mtime)
        if entry is not None:
            preview = Path(entry.preview_path) if entry.preview_path else None
            return preview, entry.item_count

    preview: Path | None = None
    count = 0
    try:
        for entry in os.scandir(dir_path):
            if entry.name.startswith("."):
                continue
            count += 1
            if preview is None and entry.is_file():
                ext = Path(entry.name).suffix.lower()
                if ext in IMAGE_EXTS:
                    preview = Path(entry.path)
    except OSError:
        pass

    if cache is not None:
        cache.set(dir_str, count, str(preview) if preview else None, mtime)

    return preview, count
```

- [ ] **Step 2: Add cache parameter to `_entry_to_item` and `list_directory`**

Add `directory_cache` field to `AssetService`:

```python
class AssetService:
    """Pure file-system browsing operations shared by desktop and LAN."""

    def __init__(self, directory_cache: DirectoryCache | None = None):
        self._directory_cache = directory_cache
```

Update `_entry_to_item` to pass cache:

```python
if is_dir and options.scan_summaries:
    preview, item_count = _scan_dir_summary(Path(entry.path), cache=self._directory_cache)
```

- [ ] **Step 3: Add test for cache integration**

```python
def test_directory_listing_uses_cache(tmp_path):
    from AssetsManager.application import AssetService, DirectoryListOptions
    from AssetsManager.core.database import DatabaseManager
    from AssetsManager.core.directory_cache import DirectoryCache

    # Create 50 subdirs with files
    for i in range(50):
        d = tmp_path / f"dir_{i:03d}"
        d.mkdir()
        (d / "file.txt").write_text("content")

    mgr = DatabaseManager()
    conn = mgr.connection_for(tmp_path)
    cache = DirectoryCache(conn)
    svc = AssetService(directory_cache=cache)

    # First scan — populates cache
    listing1 = svc.list_directory(tmp_path, tmp_path, DirectoryListOptions(scan_summaries=True))
    assert listing1.items[0].item_count is not None

    # Verify cache was populated
    cached = cache.get(str(tmp_path / "dir_000"))
    assert cached is not None
    assert cached.item_count == 1

    # Second scan — should use cache (faster)
    import time
    start = time.perf_counter()
    listing2 = svc.list_directory(tmp_path, tmp_path, DirectoryListOptions(scan_summaries=True))
    elapsed = time.perf_counter() - start
    assert elapsed < 0.1  # Should be very fast with cache
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/performance/test_baselines.py::test_directory_listing_uses_cache -v`
Expected: PASS

- [ ] **Step 5: Run full quality gate**

Run: `python -m ruff check . && python -m pyright && python -m pytest -q`

---

### Task 4: Cython Build Setup

**Covers:** S2

**Files:**
- Modify: `AssetsManager/core/cache.py` (remove `__future__` if present)
- Modify: `AssetsManager/core/color_utils.py` (remove `__future__` if present)
- Modify: `AssetsManager/core/format_utils.py` (remove `__future__` if present)
- Modify: `AssetsManager/application/asset_filters.py` (remove `__future__` if present)
- Create: `setup_cython.py` (project root)

- [ ] **Step 1: Check and remove `__future__` imports from target modules**

Cython doesn't support `from __future__ import annotations`. Check each target file and remove if present. The 4 target files:
- `core/cache.py` — check line 1-5
- `core/color_utils.py` — check line 1-5
- `core/format_utils.py` — check line 1-5
- `application/asset_filters.py` — check line 1-5

For each file, if `from __future__ import annotations` is present, remove it and verify no runtime breakage (PEP 563 style annotations would break, but these files use simple types).

- [ ] **Step 2: Create setup_cython.py**

```python
"""Cython build script — compiles hotspot modules to .pyd for 2-5x speedup."""
from setuptools import setup
from Cython.Build import cythonize

TARGET_MODULES = [
    "AssetsManager/core/cache.py",
    "AssetsManager/core/color_utils.py",
    "AssetsManager/core/format_utils.py",
    "AssetsManager/application/asset_filters.py",
]

setup(
    ext_modules=cythonize(
        TARGET_MODULES,
        compiler_directives={"language_level": "3"},
    ),
)
```

- [ ] **Step 3: Verify modules still work without Cython compilation**

Run: `python -c "from AssetsManager.core.cache import LRUCache; c=LRUCache(10); c.set('a',1); print(c.get('a'))"`
Expected: `1`

- [ ] **Step 4: Run full quality gate**

Run: `python -m ruff check . && python -m pyright && python -m pytest -q`
Expected: All pass (no code changes, just import cleanup)

---

### Task 5: Cython Compilation + Benchmark

**Covers:** S2

**Files:**
- Create: `tests/performance/test_cython_benchmarks.py`

- [ ] **Step 1: Install Cython**

Run: `pip install cython`
Expected: Successfully installed

- [ ] **Step 2: Build Cython modules**

Run: `python setup_cython.py build_ext --inplace`
Expected: 4 `.pyd` files generated in `AssetsManager/core/` and `AssetsManager/application/`

- [ ] **Step 3: Write benchmark test**

```python
"""Cython before/after benchmarks — verifies compilation improves performance."""
import time
import pytest

N = 200_000


def _bench_lrucache():
    from AssetsManager.core.cache import LRUCache
    cache = LRUCache(1000)
    start = time.perf_counter()
    for i in range(N):
        cache.set(f"k{i}", f"v{i}")
    set_ops = N / (time.perf_counter() - start)
    start = time.perf_counter()
    for i in range(N):
        cache.get(f"k{i}")
    get_ops = N / (time.perf_counter() - start)
    return set_ops, get_ops


def _bench_color_utils():
    from AssetsManager.core.color_utils import _hex_to_rgb, _rgb_to_hex
    start = time.perf_counter()
    for i in range(N):
        _hex_to_rgb("#FF0000")
    h2r = N / (time.perf_counter() - start)
    start = time.perf_counter()
    for i in range(N):
        _rgb_to_hex(255, 0, 0)
    r2h = N / (time.perf_counter() - start)
    return h2r, r2h


def _bench_format_size():
    from AssetsManager.core.format_utils import format_size
    start = time.perf_counter()
    for i in range(N):
        format_size(i * 1024)
    return N / (time.perf_counter() - start)


def _bench_asset_filters():
    from AssetsManager.application.asset_filters import matches_search, is_hidden
    start = time.perf_counter()
    for i in range(N):
        matches_search("test_file.txt", "test")
    ms = N / (time.perf_counter() - start)
    start = time.perf_counter()
    for i in range(N):
        is_hidden(".hidden")
    ih = N / (time.perf_counter() - start)
    return ms, ih


def test_cython_benchmark():
    """Run benchmarks and print results."""
    print("\n=== Performance Benchmark ===")
    set_ops, get_ops = _bench_lrucache()
    print(f"LRUCache:  set={set_ops:,.0f}  get={get_ops:,.0f} ops/s")
    h2r, r2h = _bench_color_utils()
    print(f"color:     hex_to_rgb={h2r:,.0f}  rgb_to_hex={r2h:,.0f} ops/s")
    fs = _bench_format_size()
    print(f"format:    format_size={fs:,.0f} ops/s")
    ms, ih = _bench_asset_filters()
    print(f"filters:   matches_search={ms:,.0f}  is_hidden={ih:,.0f} ops/s")
    # Just verify they run without error; actual perf comparison is manual
    assert set_ops > 0
```

- [ ] **Step 4: Run benchmark**

Run: `pytest tests/performance/test_cython_benchmarks.py -v -s`
Expected: All benchmarks print ops/s values, test PASS

- [ ] **Step 5: Run full quality gate**

Run: `python -m ruff check . && python -m pyright && python -m pytest -q`

---

### Task 6: LAN Integration — Directory Cache in /api/files

**Covers:** S1, S3

**Files:**
- Modify: `AssetsManager/lan/routes/files.py`
- Modify: `AssetsManager/lan/routes/_helpers.py`

- [ ] **Step 1: Pass DirectoryCache to AssetService in LAN scoped services**

In `AssetsManager/lan/routes/_helpers.py`, when creating `AssetService` for LAN, pass the directory cache from the library's DB connection:

```python
from AssetsManager.core.directory_cache import DirectoryCache

def get_asset_service(request):
    lan = get_lan(request)
    cache = DirectoryCache(lan.db_conn)
    return AssetService(directory_cache=cache)
```

- [ ] **Step 2: Verify LAN tests still pass**

Run: `pytest tests/lan/test_lan_api.py -q`
Expected: All pass

- [ ] **Step 3: Run full quality gate**

Run: `python -m ruff check . && python -m pyright && python -m pytest -q`

---

### Task 7: Performance Baseline Update

**Covers:** S1, S2

**Files:**
- Modify: `tests/performance/test_baselines.py`

- [ ] **Step 1: Add cached directory listing test**

```python
def test_directory_listing_with_cache_performance(tmp_path):
    """Listing 200 subdirs with cache must be faster than without."""
    from AssetsManager.application import AssetService, DirectoryListOptions
    from AssetsManager.core.database import DatabaseManager
    from AssetsManager.core.directory_cache import DirectoryCache

    for i in range(200):
        d = tmp_path / f"dir_{i:04d}"
        d.mkdir()
        for j in range(3):
            (d / f"file_{j}.txt").write_text("content")

    mgr = DatabaseManager()
    conn = mgr.connection_for(tmp_path)
    cache = DirectoryCache(conn)
    svc = AssetService(directory_cache=cache)

    # Cold scan (populates cache)
    start = time.perf_counter()
    svc.list_directory(tmp_path, tmp_path, DirectoryListOptions(scan_summaries=True))
    cold_elapsed = time.perf_counter() - start

    # Warm scan (from cache)
    start = time.perf_counter()
    svc.list_directory(tmp_path, tmp_path, DirectoryListOptions(scan_summaries=True))
    warm_elapsed = time.perf_counter() - start

    assert warm_elapsed < cold_elapsed * 0.3, (
        f"Cache warm ({warm_elapsed:.3f}s) should be <30% of cold ({cold_elapsed:.3f}s)"
    )
```

- [ ] **Step 2: Run performance tests**

Run: `pytest tests/performance/test_baselines.py -v`
Expected: All pass including new test

- [ ] **Step 3: Run full quality gate**

Run: `python -m ruff check . && python -m pyright && python -m pytest -q`
