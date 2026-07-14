# AssetsManager Architecture Diagram

**Version:** 2026-06-16
**Tests:** 603 passed, 0 warnings

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
│                   APPLICATION SERVICES (16)                        │
│                                                                     │
│  LibraryService    AssetService      TagService                    │
│  MetadataService   ThumbnailService  SearchService                 │
│  ProjectService    FileOpService     UndoService                   │
│  AuthService       PluginService     AssetIndexService             │
│  AssetFilters      ThumbnailRepository                             │
│  LibraryContext     (dataclass)                                     │
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
│  lan/server.py → lan/api.py → lan/routes/*                         │
│  lan/auth.py   lan/security.py  lan/path_guard.py                  │
│  lan/scanner.py  lan/ws.py  lan/tunnel.py                          │
│  lan/manager.py (lifecycle)                                         │
│                                                                     │
│  LAN → application services (auth, project, asset, search, tags)   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow: Library Opening

```
StartupWindow.library_opened
  → LibraryService.open_session(path)
    → DatabaseManager.connection_for(path) → SQLite
    → TagStore(root) → ProjectData(root)
    → LibraryContext → LibrarySession (scoped connection provider)
    → ApplicationBootstrap.for_library(session) → LibraryScopedServices
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
    → InfoPanel.update_info()
```

## Data Flow: LAN Request

```
HTTP → aiohttp
  → security_middleware (rate limit, IP blacklist)
  → _auth_middleware (token verification)
  → route handler
    → PathGuard.resolve() (path traversal protection)
    → application service (AssetService, ProjectService, etc.)
    → JSON response
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
2. `application/` depends on `core/`
3. `lan/` depends on `application/` + `core/`
4. `panels/` + `widgets/` depend on `application/` + `core/`
5. `panels/` do NOT depend on `lan/` (except `lan_sharing.py` mixin)
6. `SignalBus` is the Qt presentation communication channel; `domain.event_bus` is the application/domain event channel
7. `tests/unit/test_architecture_boundaries.py` guards these rules with documented transitional exceptions

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
| **Total** | **140+** | **~25,000+** | **603 passed, 0 warnings** |
