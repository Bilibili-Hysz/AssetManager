# AssetsManager Architecture Diagram

> 状态:**LIVING** · updated: 2026-08-27 · 图为结构性示意;数字以 `docs/overview-2026-08-27.md` §1 实测为准。

**Version:** 2026-08-27(A3/B1 + 会话绑定维护/导出/恢复边界 + gallery 子包化 + import/reconciliation 系列)
**Tests:** Counts from prior checkpoints are historical snapshots, not a final current total; rerun the final suite before publishing new totals.

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
│  │  tag_tree   │  │  stylekit   │  │             │                 │
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
│  Integrity  Maintenance  Export  Plugin  AssetIndex                │
│  Settings adapter: Qt-free maintenance/recovery boundary           │
│  Lazy LAN-only projection: Asset  Project  Search  Gallery  Fav   │
│  LibraryContext  LibrarySession  LibraryRuntime                    │
│  LibraryScopedServices → LanRuntimeServices (single-flight)        │
│  RuntimeEventRouter  DTOs  SessionPrincipal                         │
│  frozen RuntimeSharingServices: Auth + Share + token_secret       │
│  ReconciliationQueue  ReconciliationService                        │
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
│  LAN → canonical snapshot + lazy LAN projection + Runtime sharing │
│      → auth/principal/capabilities                                  │
│  HTTP without cert/key; HTTPS only with both configured            │
│  LAN stop leaves Runtime/session/DB ownership to bootstrap         │
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
        → frozen RuntimeSharingServices (Runtime secret + same DB conn)
        → idempotent Auth/Share table init in session operation lease
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
  → snapshot common/sharing service or once-materialized LanRuntimeServices → DTO response
Runtime DomainEvent → RuntimeEventRouter
  → epoch/revision invalidation → revalidated WebSocket (local UI secret)
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
9. One Runtime/snapshot owns the frozen RuntimeSharingServices bundle; LAN derives `local_ui_auth_secret` from Runtime secret + auth configuration. Desktop calls ShareCreationTask → ShareService directly, while LAN retains HTTP management and `/s/{id}` remote sharing. Asset/Project/Search/Gallery/Favorite may be constructed only by Bootstrap's lazy LAN projection.
10. `tests/unit/test_architecture_boundaries.py` guards runtime, principal, DTO, assembly, and teardown rules
11. Repository adapters may use `core.database` and pure core path infrastructure such as `core.path_resolver`, but not application, LAN, or presentation

---

## Module Statistics

| Layer | Files | Lines | Notes |
|-------|-------|-------|-------|
| `application/` | 57(.py) | 27,661 | 51 顶层服务模块 + `gallery/` 子包 5 文件 + `__init__` |
| `core/` | 41(35 根 + plugins/ 6) | 12,735 | — |
| `lan/` | 81(顶层 51 + routes/ 30) | 12,949 + 6,677 | routes 23 个顶层模块 |
| `panels/` | 38(含 file_list/ 27) | 15,114 | — |
| `dialogs/` | 27(20 顶层模块 + sharing_settings 6 + __init__) | 8,030 | sharing_settings 外壳 1347 + 分页 1119 |
| `widgets/` | 15(14 模块) | 3,853 | — |
| `repositories/` | 18 | 6,872 | 17 个 SQL 仓库 + __init__ |
| `webui/` | 220 ts/tsx | — | 103 Vitest + 6 Playwright spec |
| `tests/` | 283 test_*.py | 97,402 | 2026-08-11 快照 2952 passed 为历史;当前须附 dated 证据 |

> 以上为 2026-08-27 工作树实测(`Get-Content` 含空行口径);旧版统计(39/33/37/22/20 模块等)全部过时。
