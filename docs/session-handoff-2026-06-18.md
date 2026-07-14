# Session Handoff - 2026-06-18/19

## Purpose

Use this document to migrate the current coding session to a new conversation. It summarizes the active workspace, recent changes, verification status, working rules, and recommended next tasks.

## Workspace

- Active repository: `D:\~Vibe-Coding\Projects\AssetsManager_old-bak`
- Active project source is at the repository root.
- `Project/` is a complete ignored backup of the old pre-flattened workspace. Do not edit it unless explicitly requested.
- Main edit targets are `AssetsManager/`, `tests/`, `docs/`, and `Plugins/`.

## Current Quality Gate

```powershell
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

Latest result:
- Ruff: passed
- Pyright: `0 errors, 0 warnings, 0 informations`
- Compileall: passed
- Pytest: `662 passed, 38 warnings` (38 ResourceWarning are pre-existing)

## Current Working Rules

- Make small, low-risk fixes only after verifying the issue still exists.
- Add or update focused regression tests for behavior changes.
- Run focused tests first, then the full quality gate before handoff.
- Keep docs synchronized when test baseline or behavior changes materially.
- Do not edit `Project/`; it is a backup.
- Use `docs/agent-quick-map.md` as the first navigation doc for non-trivial work.
- Use `docs/agent-architecture-map-deep.md` for large, cross-cutting, or high-risk work.

## Subagent Strategy

- Use `explore` for codebase search, architecture mapping, and audits.
- Use `general` for contained implementation tasks after scope is clear.
- Main agent should review diffs, run quality gates, and update docs.
- Subagents should read `docs/agent-quick-map.md` first for non-trivial work.
- Subagents should also read `docs/agent-architecture-map-deep.md` for medium, large, or high-risk tasks.

## Architecture Refactoring (Completed)

7-phase bottom-up refactoring completed (P1-P7):
- P1: SQLite cross-thread safety audit — SAFE, 3 regression tests added
- P2: Removed `get_lib_db()` from MetadataService, TagService, ProjectService
- P3: `lan/auth.py` cleaned from 454 to 81 lines (17 duplicate functions removed)
- P4: DatabaseManager registered in DI, 4 singletons deprecated
- P5: Panel fallback paths removed, `_service_access.py` simplified to 2 functions
- P6: LibrarySession lifecycle improved (close cleanup, switch guard)
- P7: Architecture boundary tests expanded to cover all 5 layer rules

## Security Fixes

- HMAC token migration (SHA-256 → HMAC-SHA256)
- Password hash stripped from API responses
- Auth middleware precedence bug fix
- WebSocket authentication (token validation, 50-connection limit, 30s heartbeat)
- Download filename sanitization (sanitize_filename helper)
- Share download counter moved after file response

## UI Layer Improvements

- ~260 hardcoded px values → scaled_px()/scaled_pt()
- 85 border-radius values → scaled_px()
- 15 hardcoded colors → theme tokens
- Theme refresh handlers for all panels
- InfoPanel async update_info()
- FileSystemModel async set_directory()
- 3 dialogs refactored to TabbedDialog (TagEditor, PluginManager, SidebarSettings)
- Keyboard shortcuts documented
- Empty states added
- Tab order set

## Theme System (Phase 1-3 Complete)

- Phase 1: Theme files migrated to Assets/Themes/ with D_/L_/U_ prefix convention
- Phase 1: ThemeLoader with dynamic loading, validation, QFileSystemWatcher
- Phase 1: Settings dialog with 3-section theme selector
- Phase 2: ThemePreviewWidget with 9 UI component sections
- Phase 2: ThemePreviewDialog with real-time preview
- Phase 3: ColorPickerDialog (HSV/RGB toggle, HEX input)
- Optimization: Color toolbar right sidebar, custom theme creation

## HCI Fixes

- 3 dialogs refactored to TabbedDialog (TagEditor, PluginManager, SidebarSettings)
- Keyboard shortcuts documented
- Empty states added for ShareLinkManager, SidebarPanel
- Tab order set for all dialogs
- Tooltips added to interactive elements
- i18n keys added for all new features

## Architecture Optimization Roadmap

Roadmap documented in `docs/architecture-optimization-roadmap-2026-06-19.md`.

### Phase 1: LAN/Plugin Security — 2/6 DONE

- [x] 1.1 WebSocket authentication (token validation, 50-conn limit, 30s heartbeat)
- [x] 1.2 Download filename sanitization (sanitize_filename helper)
- [ ] 1.3 Deprecate query-parameter auth (?key=, ?token=)
- [ ] 1.4 Normalize share path validation via PathGuard
- [ ] 1.5 Plugin trust model decision

### Remaining Phases (Future Work)

- Phase 2: Library Session/Scoped Services
- Phase 3: Event System Convergence
- Phase 4: Repository/Database Cleanup
- Phase 5: LAN Service Organization
- Phase 6: Desktop UI Decomposition
- Phase 7: Plugin Lifecycle Hardening
- Phase 8: Performance Baselines

## Key Technical Notes

- `ThemeLoader.get_theme()` returns nested format (`{colors: {...}, properties: {...}}`); `ThemePreviewRenderer.apply_theme()` expects flat format — flatten before passing
- `PySide6.QImage.save()` needs string format (`"WEBP"`), not bytes (`b"WEBP"`)
- `QDialogButtonBox.button()` takes `StandardButton`, not `ButtonRole`
- `QRunnable` needs `setAutoDelete(False)` to prevent GC before signal delivery
- `setIconSize()` needs `QSize`, not individual int values
- `sanitize_filename()`: strips control chars, path separators, limits 200 chars
- WebSocket: token auth + 50-connection limit + 30s heartbeat
- `_active_scan_task` prevents GC of async scan signal objects in FileSystemModel

## Files Changed This Session (Partial List)

### Core
- `AssetsManager/core/themes.py` — ThemeLoader integration, migration map
- `AssetsManager/core/theme_loader.py` — NEW: ThemeLoader class
- `AssetsManager/core/settings.py` — Legacy migration support
- `AssetsManager/core/database.py` — DatabaseManager DI registration

### Application
- `AssetsManager/application/metadata_service.py` — Removed get_lib_db() fallback
- `AssetsManager/application/tag_service.py` — Removed get_lib_db() fallback
- `AssetsManager/application/project_service.py` — Removed get_lib_db() fallback
- `AssetsManager/application/undo_service.py` — Added clear() method

### LAN
- `AssetsManager/lan/server.py` — WebSocket auth, middleware fix
- `AssetsManager/lan/routes/websocket.py` — WebSocket authentication
- `AssetsManager/lan/routes/downloads.py` — Filename sanitization
- `AssetsManager/lan/routes/shares.py` — Filename sanitization, download fix
- `AssetsManager/lan/routes/_helpers.py` — sanitize_filename helper
- `AssetsManager/lan/auth.py` — Cleaned to 81 lines
- `AssetsManager/lan/ws.py` — Connection limits, heartbeat

### UI
- `AssetsManager/widgets/theme_preview.py` — ThemePreviewWidget + ThemePreviewRenderer
- `AssetsManager/widgets/hsv_wheel.py` — NEW: HSVWheel, BrightnessSlider
- `AssetsManager/widgets/tag_chip.py` — Shared tag chip utility
- `AssetsManager/dialogs/theme_preview_dialog.py` — NEW: ThemePreviewDialog
- `AssetsManager/dialogs/color_picker_dialog.py` — NEW: ColorPickerDialog
- `AssetsManager/dialogs/settings_dialog.py` — 3-section theme selector
- `AssetsManager/dialogs/tabbed_dialog.py` — Tab order, button factories
- `AssetsManager/dialogs/tag_editor_dialog.py` — Refactored to TabbedDialog
- `AssetsManager/dialogs/plugin_manager_dialog.py` — Refactored to TabbedDialog
- `AssetsManager/dialogs/sidebar_settings_dialog.py` — Refactored to TabbedDialog
- `AssetsManager/panels/info.py` — Async update_info, theme refresh
- `AssetsManager/panels/file_list/_model.py` — Async set_directory
- `AssetsManager/panels/sidebar.py` — Async preload, theme refresh

### Tests
- `tests/core/test_theme_loader.py` — NEW: ThemeLoader tests
- `tests/lan/test_lan_api.py` — WebSocket auth tests
- `tests/lan/test_helpers.py` — sanitize_filename tests
- `tests/lan/test_concurrent_db_access.py` — DB thread safety tests

## New Session Prompt

```
We are working in D:\~Vibe-Coding\Projects\AssetsManager_old-bak. The active project is flattened at the repository root; Project/ is an ignored backup and must not be edited unless explicitly requested.

Read docs/session-handoff-2026-06-17.md, docs/workspace.md, and docs/agent-quick-map.md first. For larger or high-risk tasks, also read docs/agent-architecture-map-deep.md and docs/architecture-optimization-roadmap-2026-06-19.md.

Continue the architecture optimization work following the roadmap. The next task is Phase 1 Task 1.3: Deprecate query-parameter auth (?key=, ?token=).

Quality gate: python -m ruff check . && python -m pyright && python -m compileall AssetsManager -q && python -m pytest -q

Latest full gate: 662 passed, 38 warnings.

Working rules:
- Make small, low-risk fixes after verifying the issue exists
- Add regression tests for behavior changes
- Run focused tests first, then full quality gate
- Do not edit Project/ (it is a backup)
- Use docs/agent-quick-map.md for navigation
```