# AssetManager Next — Refactoring Results

**Workspace:** `Project/AssetsManager_Python_Rewrite_refactor`
**Baseline:** 90 passed, 4 warnings
**Current:** 536 passed, 0 warnings
**New tests:** 446+ (from 90 to 536)

> Archived snapshot. The active workspace was flattened to the repository root on 2026-06-16. See `docs/workspace.md`, `docs/refactor-baseline.md`, and `docs/testing.md` for current status.

---

## Summary

This refactoring transforms AssetManager from a monolithic PySide6 file browser into a layered platform with shared application services, modular LAN routes, versioned database migrations, and a plugin system. The desktop UI and LAN web server now share the same service layer for browsing, metadata, tags, thumbnails, search, authentication, shares, and file operations.

---

## Architecture

```
Presentation
├── Desktop (PySide6)
│   ├── MainWindow → LibraryService, PluginService
│   ├── FileListPanel → FileOperationService, UndoService
│   ├── InfoPanel → MetadataService
│   └── SidebarPanel → LibraryService
└── LAN (aiohttp)
    └── routes/ → AssetService, MetadataService, TagService,
                  ThumbnailService, SearchService, AuthService

Application (16 services/repositories)
├── LibraryService      — library lifecycle
├── AssetService        — directory browsing
├── AssetIndexService   — assets table CRUD
├── MetadataService     — notes, URLs, dir size
├── TagService          — tag CRUD + tree queries
├── FileOperationService — copy, move, rename, trash, duplicate
├── ThumbnailService    — resolve, blur, process
├── ThumbnailRepository — thumbnail_cache persistence
├── SearchService       — by tags, by name, by index
├── ShareService        — share link lifecycle
├── PluginService       — plugin lifecycle
├── ProjectService      — project listing/detail/tree/home and depth rules
├── AuthService         — LAN users, auth tokens, invites
├── UndoService         — undo/redo stack
├── AssetFilters        — shared sort/filter/category rules
└── LibraryContext       — per-library runtime state and connection provider

Infrastructure
├── core/database.py    — SQLite per-library, WAL, write lock
├── core/db_migrations  — v1 baseline, v2 assets index, v3 tag metadata, v4 plugin metadata
├── core/format_utils   — format_size, CATEGORY_MAP
├── application/asset_filters — shared sort/filter/category rules
├── core/settings.py    — JSON settings, atomic writes
├── core/signal_bus.py  — Qt cross-panel signals
├── core/plugins/       — descriptor, loader, host_context, manager
└── lan/path_guard.py   — path traversal protection
```

---

## What Changed

### Application Services (new)

| Service | File | Purpose | Tests |
|---|---|---|---|
| LibraryService | `library_service.py` | Open/close libraries, cache contexts | 2 |
| AssetService | `asset_service.py` | Directory listing, filtering, sorting | 4 |
| AssetIndexService | `asset_index_service.py` | Populate/query assets table | 9 |
| MetadataService | `metadata_service.py` | Notes, URLs, tags, dir size | 5 |
| TagService | `tag_service.py` | Tag CRUD, tree queries | 4 |
| FileOperationService | `file_operation_service.py` | File mutations | 6 |
| ThumbnailService | `thumbnail_service.py` | Image resolve/blur/process | 7 |
| ThumbnailRepository | `thumbnail_repository.py` | Desktop thumbnail cache table access | via loader tests |
| SearchService | `search_service.py` | Search by tags/name/index | 9 |
| ShareService | `share_service.py` | Share link lifecycle | 15 |
| PluginService | `plugin_service.py` | Plugin discovery/load/enable | 7 |
| ProjectService | `project_service.py` | Project listing/detail/tree/home/depth rules | 10 |
| AuthService | `auth_service.py` | Users, tokens, invites, share links | 8 |
| UndoService | `undo_service.py` | Undo/redo stack | 8 |
| LibraryContext | `context.py` | Per-library runtime bundle and scoped connection provider | via LibraryService |

### LAN Routes (split)

`api.py` reduced from **1753 lines** to **98 lines** (thin wrapper).

| Module | Routes | Lines |
|---|---|---|
| `_helpers.py` | Shared utilities | ~160 |
| `pages.py` | `/`, `/detail` | ~20 |
| `files.py` | `/api/files` | ~90 |
| `metadata.py` | `/api/meta`, search, home, tree, projects | ~370 |
| `tags.py` | `/api/tags/*` | ~70 |
| `thumbnails.py` | `/api/thumbnails/*` | ~80 |
| `downloads.py` | `/api/download/*` | ~100 |
| `auth.py` | `/api/auth/*` | ~100 |
| `users.py` | `/api/users/*`, `/api/invites/*` | ~80 |
| `shares.py` | `/api/shares/*`, `/s/*` | ~290 |
| `system.py` | `/api/info`, tunnel, stats | ~110 |
| `websocket.py` | `/ws` | ~15 |

### Desktop Integration

| Operation | Delegates to |
|---|---|
| Rename | `FileOperationService().move()` |
| Duplicate | `FileOperationService().duplicate()` |
| Permanent delete | `FileOperationService().delete_permanent()` |
| Paste (copy) | `FileOperationService().copy_to_directory()` |
| Paste (cut) | `FileOperationService().move_to_directory()` |
| Delete to trash | `FileOperationService().delete_to_trash()` |
| New folder | `FileOperationService().create_folder()` |
| Drag/drop copy | `FileOperationService().copy_to_directory()` |
| Undo/redo | `UndoService.record_rename()` / `record_delete()` / `execute_undo()` / `execute_redo()` |
| Plugin commands | `PluginHostContext` menu contributions |

### Database

| Version | Name | Description |
|---|---|---|
| 1 | `baseline_current_schema` | Records existing schema |
| 2 | `add_assets_index` | Adds `assets` table with 4 indexes |
| 3 | `add_tag_metadata` | Adds `tag_metadata` table with category index |
| 4 | `add_plugin_metadata` | Adds persisted plugin metadata fields |

### Shared Utilities

- `core/format_utils.py` — `format_size()` + `CATEGORY_MAP` (single source of truth)
- `lan/path_guard.py` — `PathGuard` for all LAN path validation
- `conftest.py` — `_cleanup_stores` autouse fixture closes DB connections

---

## File Counts

| Location | .py files |
|---|---|
| `AssetsManager/` | 97 |
| `tests/` | 25 |
| `docs/` | 6 (md) |
| **Total** | 122 source + 25 test |

---

## Test Coverage

| Category | Tests |
|---|---|
| Application services | 75 |
| Core (database, settings, themes, etc.) | 30 |
| LAN API integration | 25 |
| Plugin infrastructure | 24 |
| File list model/details/shim | 35 |
| Thumbnail loader | 1 |
| Path guard | 5 |
| Other | 7 |
| **Total** | **326** |

---

## Migration Guide

### For existing users

No action required. The refactored code:
- Reads the same `RuntimeData/` directory structure
- Opens the same per-library SQLite databases
- Automatically applies migrations through v4 on first open
- Preserves all settings, tags, notes, URLs, and thumbnail caches

### For developers

1. New features should use application services, not direct DB access
2. LAN routes go in `lan/routes/` modules
3. Shared constants go in `core/format_utils.py`
4. Database schema changes require a new migration in `core/db_migrations.py`
5. See `docs/development.md` for the full rule set

---

## Remaining Low-Priority Work

1. Desktop file_list + AssetService sort/filter logic unification — **done** (shared via `application/asset_filters.py`)
2. Full-repository Ruff cleanup — **done** (`ruff check .` passes)
3. Packaging verification (spec file updated, needs runtime test)
4. Test warning cleanup — **done** (ResourceWarning and aiohttp NotAppKeyWarning are cleared)
5. Pyright check — **done** (scoped gate: 0 errors on application/lan/core)
6. ProjectService extraction complete — **done** (`lan/routes/metadata.py` is now a thin route shell)
7. DB boundary cleanup — **done** (all route DB reads delegated to services)
8. Thumbnail cache key unification — **done** (desktop and LAN share `thumbnail_cache_key()`)
9. Pyright coverage expansion — **done** (all core non-UI modules including plugins)
10. Packaging spec update — **done** (all new services/modules included)
11. Performance baseline script — **done** (`tests/perf_baseline.py`)
7. Performance baselines — **done** (`tests/perf_baseline.py`, `tests/perf_real_world.py`, `tests/perf_startup.py`)
