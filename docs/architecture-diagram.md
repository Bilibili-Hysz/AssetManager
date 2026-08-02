# AssetsManager Architecture Diagram

**Version:** 2026-08-02 B2 working-tree follow-up (baseline figures retained as snapshots)
**Tests:** Python 1590 passed, 1 Windows platform skip plus Ubuntu WSL symlink gate passed; WebUI 37 files / 289 passed; Task E cross-surface 186 passed; typecheck and build passed

---

## Layer Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         ENTRY POINTS                                │
│   main.py / run.py → app.py → window.py                            │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│                      PRESENTATION LAYER                             │
│                                                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │
│  │  panels/    │  │  widgets/   │  │ dock_factory│                 │
│  │  sidebar    │  │  workspace  │  │  window.py  │                 │
│  │  file_list  │  │  tray       │  │             │                 │
│  │  info       │  │  lan_sharing│  │             │                 │
│  │  tag_tree   │  │  title_bar  │  │             │                 │
│  │  image_view │  │  tab_cont.  │  │             │                 │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                 │
│         └────────────────┼────────────────┘                        │
│                          │                                         │
└──────────────────────────┼─────────────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────────────┐
│                 APPLICATION + RUNTIME LAYER                       │
│                                                                     │
│  LibraryService    AssetService      TagService                    │
│  MetadataService   ThumbnailService  SearchService                 │
│  ProjectService    FileOpService     UndoService                   │
│  AuthService       PluginService     AssetIndexService             │
│  AssetFilters                                                      │
│  LibraryContext  LibrarySession  LibraryRuntime                    │
│  RuntimeEventRouter  DTOs  SessionPrincipal                         │
└──────────────────────────┬─────────────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────────────┐
│                   CORE INFRASTRUCTURE                               │
│                                                                     │
│  database.py       db_migrations.py   settings.py                  │
│  project_data.py   tag_store.py       tag_library.py               │
│  signal_bus.py     singleton.py       themes.py                    │
│  path_resolver.py  format_utils.py    color_utils.py               │
│  cache.py          json_store.py      config_migrator.py           │
│  protocols.py      crash_handler.py   tool_scheduler.py            │
│  library_manager.py  ui_scale.py                                  │
│  repositories/thumbnail_repository.py                              │
│  plugins/ (descriptor, loader, manager, host_context)              │
└──────────────────────────┬─────────────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────────────┐
│                      EXTERNAL DEPS                                  │
│  PySide6  sqlite3  PIL/Pillow  aiohttp  send2trash  cloudflared   │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                    LAN LAYER (OPTIONAL)                              │
│                                                                     │
│  LanServer(runtime) → lan/api.py → lan/routes/*                    │
│  lan/auth.py   lan/security.py  lan/path_guard.py                  │
│  lan/scanner.py  lan/ws.py  lan/tunnel.py                          │
│  lan/manager.py (lifecycle)                                         │
│                                                                     │
│  LAN → Runtime services → auth/principal/capabilities              │
│  Windows Task E matrix: Chromium + Desktop + LAN passed            │
│  Linux directory-symlink gate: Ubuntu WSL passed                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow: Library Opening

```
StartupWindow.library_opened
  → LibraryService.open_session(path)
    → per-library QLockFile admission (RuntimeData/Shared/library-<hash>.lock)
    → DatabaseManager.connection_for(path) → SQLite
    → TagStore(root) → ProjectData(root)
    → LibraryContext → LibrarySession (scoped connection provider)
    → ApplicationBootstrap.runtime_for(session) → LibraryRuntime.services
  → MainWindow
  → SidebarPanel.navigate_to(root)
  → FileListPanel.navigate_to(root, set_root=True)
    → FileListPanel._configure_library_runtime(root)
  → InfoPanel / TagTreePanel library_opened handlers
    → scoped services required
```

## Data Flow: File Browsing

```
SidebarPanel.directory_selected
  → FileListPanel.navigate_to(path)
    → FileSystemModel.set_directory(path) → os.scandir()
    → AssetFilters (sort/filter/category)
    → ThumbnailLoader (background threads)
      → immutable Runtime snapshot → ThumbnailService
      → memory LRU / disk WEBP cache metadata
    → InfoPanel.update_info()
```

## Data Flow: LAN Request

```
HTTP → aiohttp security/auth middleware
  → SessionPrincipal + Capabilities
  → route handler → PathGuard
  → Runtime-owned application service → DTO response
Runtime DomainEvent → RuntimeEventRouter
  → epoch/revision invalidation → authenticated WebSocket
  → React RealtimeProvider → authoritative HTTP refetch
```

## Data Flow: Theme Change

```
SettingsDialog → themes.set_theme(name)
  → AppSettings.set("theme", name) → save()
  → SignalBus.theme_changed
    → MainWindow (animated transition)
    → All panels (style refresh)
```

---

## Dependency Rules

1. `domain/` should not depend on presentation, LAN, controllers, or repositories
2. `application/` owns runtime assembly and depends on `core/`
3. `lan/` consumes an injected `LibraryRuntime`; routes do not assemble services
4. `panels/` + `widgets/` depend on scoped application services and runtime
5. `panels/` do NOT depend on `lan/` (except `lan_sharing.py` mixin)
6. `SignalBus` is the Qt presentation communication channel; `domain.event_bus` is the application/domain event channel
7. `ThumbnailLoader` may depend on the scoped `ThumbnailService` and immutable runtime snapshot, but must not depend directly on SQLite connections or `ThumbnailRepository`
8. `tests/unit/test_architecture_boundaries.py` guards runtime, principal, DTO, and teardown rules

---

## Module Statistics

| Layer | Files | Lines | Tests |
|-------|-------|-------|-------|
| `application/` | 16 | ~2,100 | 15 test files |
| `core/` | 34 | ~5,800 | 11 test files |
| `lan/` | 24 | ~3,200 | 2 test files |
| `panels/` | 18 | ~6,100 | 3 test files |
| `widgets/` | 6 | ~900 | 0 test files |
| `tests/` | 50+ | ~5,000+ | — |
| **Total** | **150+** | **~27,000+** | **Python 1590 passed, 1 Windows skip; Linux symlink gate passed; WebUI 37 files / 289 passed; Task E 186 passed** |
