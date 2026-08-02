# AssetsManager Architecture Diagram

**Version:** 2026-08-02 A3 per-presentation service assembly + A2/B2/B3 delivered boundaries
**Tests:** Python 1695 passed, 1 Windows platform skip plus Ubuntu WSL symlink gate passed; A3/architecture focused 347 passed; Task D Runtime/Desktop 431 passed; current Desktop/LAN/Chromium matrix 190 passed; WebUI 37 files / 292 passed snapshot

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
│  Eager Desktop/shared: Metadata  Tag  Thumbnail  FileOp  Undo     │
│  Shared stateless: Plugin  AssetIndex  AssetFilters                │
│  Lazy LAN-only projection: Asset  Project  Search                  │
│  LibraryContext  LibrarySession  LibraryRuntime                    │
│  LibraryScopedServices → LanRuntimeServices (single-flight)        │
│  RuntimeEventRouter  DTOs  SessionPrincipal                         │
│  AuthService/ShareService remain LAN-owned until B1               │
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
│  LAN → canonical snapshot + lazy LAN projection + Auth/Share      │
│      → auth/principal/capabilities                                  │
│  Current A3 matrix: Chromium + Desktop + LAN = 190 passed          │
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
    → ApplicationBootstrap.runtime_for(session)
      → LibraryRuntime.services_snapshot
        → eager Desktop/shared fields + private LAN single-flight holder
  → MainWindow
  → SidebarPanel.navigate_to(root)
  → FileListPanel.navigate_to(root, set_root=True)
    → FileListPanel._configure_library_runtime(root)
  → InfoPanel library_opened handler
    → scoped services required
  → TagTreePanel.set_runtime(runtime)
    → RuntimeEventSubscription → ProjectionDomain.TAGS
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
  → snapshot common service or once-materialized LanRuntimeServices → DTO response
Runtime DomainEvent → RuntimeEventRouter
  → epoch/revision invalidation → authenticated WebSocket
  → React RealtimeProvider → domain consumer
    → explicit TAGS or recovery(null) → active tag authoritative HTTP refetch
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
4. `panels/` + `widgets/` depend on scoped application services and runtime; projection subscribers use the Qt bridge rather than calling widgets directly from worker/event-bus threads
5. `panels/` do NOT depend on `lan/` (except `lan_sharing.py` mixin)
6. `SignalBus` is the Qt presentation communication channel; `domain.event_bus` is the application/domain event channel
7. `ThumbnailLoader` may depend on the scoped `ThumbnailService` and immutable runtime snapshot, but must not depend directly on SQLite connections or `ThumbnailRepository`
8. `TagService`, `ShareService`, and `AssetService` own A2 business validation; LAN routes own transport and `PathGuard` boundaries
9. A3 keeps one Runtime/snapshot: Desktop/shared fields are eager; Asset/Project/Search may be constructed only by Bootstrap's lazy LAN projection; Auth/Share remain LAN-owned until B1
10. `tests/unit/test_architecture_boundaries.py` guards runtime, principal, DTO, assembly, and teardown rules

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
| **Total** | **150+** | **~27,000+** | **Python 1695 passed, 1 Windows skip; Linux symlink gate passed; WebUI 37 files / 292 snapshot; current cross-surface 190 passed** |
