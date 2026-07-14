# Core Layer Cleanup Plan

> Archived plan. This document captures the pre-flattening core/dialog cleanup direction and is kept for history only.

**Date:** 2026-06-11
**Status:** Phase 1-3 complete (classify + move + remove re-exports)

---

## Current State

`AssetsManager/core/` contains 35 modules mixing infrastructure and UI dialogs.

## Classification

### Pure Infrastructure (stay in `core/`)

| Module | Lines | Responsibility |
|--------|-------|----------------|
| `database.py` | 309 | SQLite connection manager |
| `db_migrations.py` | 108 | Schema migration runner |
| `settings.py` | 102 | JSON settings singleton |
| `config_migrator.py` | 31 | Settings schema migration |
| `json_store.py` | 92 | Atomic JSON persistence |
| `path_resolver.py` | 42 | Path resolution utilities |
| `library_manager.py` | 62 | Library CRUD |
| `project_data.py` | 173 | Per-library metadata |
| `tag_store.py` | 102 | Per-library tag storage |
| `tag_library.py` | 186 | Canonical tag definitions |
| `singleton.py` | 44 | Thread-safe singleton factory |
| `signal_bus.py` | 33 | Qt cross-panel signals |
| `themes.py` | 368 | Theme system |
| `format_utils.py` | 27 | Size formatting, category map |
| `color_utils.py` | 82 | Color utilities |
| `constants.py` | 3 | IMAGE_EXTS constant |
| `cache.py` | 100 | DictCache, LRUCache, TTLCache |
| `lru_cache.py` | 41 | LRU cache variant |
| `crash_handler.py` | 52 | Global exception hook |
| `tool_scheduler.py` | 62 | External tool launcher |
| `protocols.py` | 106 | Protocol interfaces |
| `plugins/` | 544 | Plugin subsystem |

### UI/Dialog Modules (planned migration to `dialogs/`)

| Module | Lines | Responsibility | Imported By |
|--------|-------|----------------|-------------|
| `startup.py` | 502 | Startup window | `app.py` |
| `settings_dialog.py` | 217 | Settings dialog | `startup.py`, `window.py` |
| `tabbed_dialog.py` | 377 | Tabbed dialog base | 4 dialog modules |
| `generic_settings_dialog.py` | 21 | Generic settings helper | `panels/base.py` |
| `tag_editor_dialog.py` | 184 | Tag editor dialog | `panels/info.py`, `panels/file_list/_actions.py` |
| `share_link_dialog.py` | 174 | Share link creation | `widgets/lan_sharing.py` |
| `share_link_manager.py` | 235 | Share link management | `widgets/lan_sharing.py` |
| `sharing_settings_dialog.py` | 651 | LAN sharing settings | `widgets/lan_sharing.py` |
| `sidebar_favorites.py` | 94 | Favorites sidebar | `panels/sidebar.py` |
| `sidebar_recent.py` | 97 | Recent folders sidebar | `panels/sidebar.py` |
| `sidebar_settings_dialog.py` | 126 | Sidebar settings | `panels/sidebar.py` |
| `plugin_manager_dialog.py` | 200 | Plugin manager dialog | `window.py` |

---

## Migration Strategy

### Phase 1: Document and Mark (Complete)
- ✅ Classify all modules
- ✅ Create `dialogs/` package
- ✅ Add deprecation comments to core dialog modules

### Phase 2: Move with Re-exports (Complete)
- ✅ Move files to `dialogs/`
- ✅ Add re-exports in `core/` for backward compatibility
- ✅ Update imports one module at a time

### Phase 3: Remove Re-exports (Complete)
- ✅ Remove `core/` re-exports after all imports updated
- ✅ Remove obsolete `core/` dialog excludes from pyrightconfig.json

---

## Import Impact

Moving dialog modules requires updating 17 import references:
- `window.py` — 2 imports
- `widgets/lan_sharing.py` — 3 imports
- `panels/sidebar.py` — 3 imports
- `panels/info.py` — 1 import
- `panels/file_list/_actions.py` — 1 import
- `panels/base.py` — 1 import
- `app.py` — 1 import
- Internal dialog cross-imports — 5 imports
