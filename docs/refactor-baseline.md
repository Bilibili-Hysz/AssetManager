# Refactor Baseline

Workspace: repository root. The active project was flattened from `Project/AssetsManager_Python_Rewrite_refactor`; `Project/` is retained as an ignored backup.

Initial test command:

```bash
pytest
```

Initial result:

```text
90 passed, 4 warnings
```

Initial warnings were from aiohttp `NotAppKeyWarning` in LAN tests and were not functional failures. The current audited root has no warnings.

The original `Project/` folder is now a full ignored backup of the pre-flattened workspace and should not be modified by normal refactor work.

## Refactor Progress

| Phase | Status | Tests |
|---|---|---|
| 1. Fix + desktop integration | Done | 115 passed |
| 4. Infrastructure hardening | Done | 115 passed |
| 2. LAN API route splitting | Done | 115 passed |
| 3. LAN service integration | Done | 115 passed |
| 5. ThumbnailService | Done | 122 passed |
| 6. SearchService | Done | 128 passed |
| 7. Database schema v2 | Done | 131 passed |
| 8. PluginService | Done | 138 passed |
| 8.4 Plugin bootstrap | Done | 138 passed |
| 9. AssetIndexService | Done | 147 passed |
| 10. SearchService+AssetIndex+UndoService | Done | 158 passed |
| 11. UndoService接入+TagService扩展+搜索fallback+InfoPanel+CATEGORY_MAP+PluginUI | Done | 158 passed |
| 12. ResourceWarning cleanup + Pyright scoped gate + thread-safe shutdown | Done | 192 passed |
| 13. aiohttp AppKey cleanup | Done | 192 passed, 0 warnings |
| 14. ProjectService list extraction | Done | 195 passed, 0 warnings |
| 15. ProjectService detail extraction | Done | 197 passed, 0 warnings |
| 16. ProjectService tree extraction | Done | 199 passed, 0 warnings |
| 17. ProjectService home extraction | Done | 202 passed, 0 warnings |
| 18. Shared asset_filters (sort/filter/category) | Done | 217 passed, 0 warnings |
| 19. DB boundary cleanup (system.py) | Done | 217 passed, 0 warnings |
| 20. Thumbnail cache key unification | Done | 220 passed, 0 warnings |
| 21. Pyright coverage expansion (core/settings, core/plugins) | Done | 220 passed, 0 warnings |
| 22. Packaging spec update | Done | 220 passed, 0 warnings |
| 23. Performance baseline script | Done | 220 passed, 0 warnings |
| 24. UI file review (no further split needed) | Done | 220 passed, 0 warnings |
| 25. Security fixes (7 vulnerabilities) | Done | 227 passed, 0 warnings |
| 26. Data correctness fixes (file_count, LIKE escape, cross-fs move) | Done | 228 passed, 0 warnings |
| 27. Concurrency safety fixes (DB/Library/Undo/ProjectData) | Done | 228 passed, 0 warnings |
| 28. Error handling improvements (auth/metadata/thumbnail) | Done | 228 passed, 0 warnings |
| 29. Test hardening (themes/conftest/fixtures/cleanup) | Done | 228 passed, 0 warnings |
| 30. P5 architecture (UndoEntry/IMAGE_EXTS/find_first_image) | Done | 228 passed, 0 warnings |
| 31. P5 architecture (library_root type/plugin unload) | Done | 228 passed, 0 warnings |
| 32. P5 architecture (settings validation + max_items fix) | Done | 228 passed, 0 warnings |
| 33. Architecture diagram + optimization plan | Done | docs/architecture-diagram.md, docs/architecture-optimization-plan.md |
| 34. Phase 5: Extract ShareDomain (domain/ + ShareService) | Done | 243 passed, 0 warnings |
| 35. Phase 3: Domain Events (events + event_bus) | Done | 252 passed, 0 warnings |
| 36. Phase 1: Domain Layer (errors + library + asset) | Done | 266 passed, 0 warnings |
| 37. Phase 2: DI Container (ServiceContainer + tests) | Done | 275 passed, 0 warnings |
| 38. Phase 4: Repository Pattern (Tag/Metadata/Share repos) | Done | 292 passed, 0 warnings |
| 39. Phase 6: UI Layer Cleanup (FileListController) | Done | 301 passed, 0 warnings |
| 40. Module import verification + packaging spec update | Done | 301 passed, 0 warnings |
| 41. Test directory reorganization (unit/integration/desktop/lan/perf) | Done | 301 passed, 0 warnings |
| 42. AuthRepository extraction (users + invite codes) | Done | 307 passed, 0 warnings |
| 43. Core/dialogs boundary classification | Done | 307 passed, 0 warnings |
| 44. Dialog migration Phase 2 (5 modules to dialogs/ + re-exports) | Done | 307 passed, 0 warnings |
| 45. Dialog migration Phase 3 (6 modules to dialogs/ + re-exports) | Done | 307 passed, 0 warnings |
| 46. Performance: list_projects batch cache preheat | Done | 307 passed, 0 warnings |
| 47. Performance: thumbnail_cache_key mtime cache | Done | 307 passed, 0 warnings |
| 48. Performance: list_directory scan dedup | Done | 307 passed, 0 warnings |
| 49. Performance: LAN routes async (to_thread) | Done | 307 passed, 0 warnings |
| 50. Performance: list_projects pagination (offset/limit) | Done | 308 passed, 0 warnings |
| 51. Plugin system compatibility (match/parse + display_fields) | Done | 308 passed, 0 warnings |
| 52. Port original Plugins/Addons/ (booth_link + docs) | Done | 308 passed, 0 warnings |
| 53. Blender-style plugin Phase 1 (register_file_handler + hook) | Done | 311 passed, 0 warnings |
| 54. Blender-style plugin Phase 2 (register_context_menu_item) | Done | 311 passed, 0 warnings |
| 55. Blender-style plugin Phase 3 (register_category) | Done | 313 passed, 0 warnings |
| 56. Blender-style plugin Phase 4 (register_column) | Done | 315 passed, 0 warnings |
| 57. Blender-style plugin Phase 5 (register_search_provider) | Done | 317 passed, 0 warnings |
| 58. Blender-style plugin Phase 6 (register_theme_token) | Done | 319 passed, 0 warnings |
| 59. Blender-style plugin Phase 7 (permissions manifest) | Done | 322 passed, 0 warnings |
| 60. Plugin Manager Dialog + menu entry | Done | 322 passed, 0 warnings |
| 61. DPI adaptation + UI global scale | Done | 322 passed, 0 warnings |
| 62. UI scale Phase 1 (global QSS + TabbedDialog) | Done | 322 passed, 0 warnings |
| 63. UI scale Phase 2 (Settings + PluginManager dialogs) | Done | 322 passed, 0 warnings |
| 64. UI scale Phase 3 (Info panel + Sidebar + DockFactory) | Done | 322 passed, 0 warnings |
| 65. UI scale Phase 4 (dynamic scale response via signal bus) | Done | 322 passed, 0 warnings |
| 66. Deep audit P0 fixes (singleton lock + EventBus thread safety + share auth bypass + failed_paths LRU) | Done | 322 passed, 0 warnings |
| 67. Tag system upgrade (unify repo + thread safety + tag metadata v3) | Done | 326 passed, 0 warnings |
| 68. TagStore delegates to TagRepository (eliminate duplicate SQL) | Done | 326 passed, 0 warnings |
| 69. Type annotations improvement (LibraryContext) | Done | 326 passed, 0 warnings |
| 70. Phase 1: LAN auth security (verify_auth_token + double-hash fix + UI token unify) | Done | 332 passed, 0 warnings |
| 71. Phase 2: Plugin system closure (singleton + dispatch + persistence + unregister) | Done | 332 passed, 0 warnings |
| 72. Phase 3: MetadataService → repository + PathEscapeError + domain decouple | Done | 332 passed, 0 warnings |
| 73. Phase 4: UI scale cumulative fix + i18n dock titles | Done | 332 passed, 0 warnings |
| 74. Phase 5: Plugin docs sandboxed→error-isolated + PyInstaller | Done | 332 passed, 0 warnings |
| 75. Phase A: Domain layer cleanup (PathEscapeError merge + category_for_extension + PermissionError→OperationNotPermitted + event_hook/tool_window cleanup + theme token lambda) | Done | 350 passed, 0 warnings |
| 76. Phase B: DI container (RLock + hold-lock + circular dependency detection) | Done | 352 passed, 0 warnings |
| 77. Phase C: app.py lifecycle (signal accumulation fix + window leak fix) | Done | 352 passed, 0 warnings |
| 78. Phase D: LAN access key session token + share password rate limiter | Done | 352 passed, 0 warnings |
| 79. Phase E: UI thread async (share dialogs QRunnable + LAN route asyncio.to_thread) | Done | 352 passed, 0 warnings |
| 80. Phase F: Application cleanup (MetadataRepository batch + deque + find_first_image linear scan + thumbnail_repository move) | Done | 352 passed, 0 warnings |
| 81. Phase G: Bus signal lifecycle (6 panels/dialogs disconnect) + GL widget fix | Done | 352 passed, 0 warnings |
| 82. Phase G2: UI i18n (5 dialogs ~140 strings → tr() + 418 i18n keys) | Done | 352 passed, 0 warnings |
| 83. Phase G3: Share dialog scaled_px/scaled_pt + misc i18n | Done | 352 passed, 0 warnings |
| 84. EventBus wiring (4 services publish 8 DomainEvent types) | Done | 362 passed, 0 warnings |
| 85. ApplicationBootstrap (DI container + app.py refactor) | Done | 369 passed, 0 warnings |
| 86. LAN decouple (domain/auth.py + application no longer imports lan crypto) | Done | 369 passed, 0 warnings |
| 87. P0: DI bootstrap AuthService/ShareService fix | Done | 370 passed, 0 warnings |
| 88. P0: Plugin unload cleanup (CommandContribution.plugin_id + event hooks + tool windows) | Done | 370 passed, 0 warnings |
| 89. P0: LAN access key session token fix + rate limiter for share password | Done | 370 passed, 0 warnings |
| 90. P1: MetadataService → MetadataRepository (batch ops) | Done | 370 passed, 0 warnings |
| 91. P1: DB migration v4 (plugin_metadata table) | Done | 370 passed, 0 warnings |
| 92. InfoPanel plugin metadata persistence (plugin_metadata table + PluginMetadataRepository) | Done | 370 passed, 0 warnings |
| 93. InfoPanel standardized API Phase 1-4 (InfoController + field registration + controller wiring) | Done | 377 passed, 0 warnings |
| 94. FileListController wiring (search history via controller) | Done | 377 passed, 0 warnings |
| 95. Protocol cleanup (remove unused ProjectDataProtocol/SettingsProtocol/DatabaseProtocol) | Done | 377 passed, 0 warnings |
| 96. TagTreeController (panel wired to controller) | Done | 377 passed, 0 warnings |
| 97. EventBus wiring into InfoPanel + TagTreePanel (TagsChanged/NotesChanged/UrlsChanged) | Done | 378 passed, 0 warnings |
| 98. InfoPanel EventBus unsubscribe on shutdown | Done | 378 passed, 0 warnings |
| 99. i18n gap fill (sharing.settings + sharing.ui + plugins.* + panel.empty) | Done | 378 passed, 0 warnings |
| 100. EventBus wiring: InfoPanel subscribes TagsChanged/NotesChanged/UrlsChanged | Done | 435 passed, 0 warnings |
| 101. Tag system fix: InfoPanel ↔ FileList tag sync via bus().tags_changed | Done | 435 passed, 0 warnings |
| 102. Tag system fix: InfoPanel reset _current_path on library switch | Done | 435 passed, 0 warnings |
| 103. i18n gap fill (15 missing keys: sharing.* + plugins.* + filelist.*) | Done | 435 passed, 0 warnings |
| 104. EventBus wiring: TagTreePanel subscribes TagsChanged | Done | 435 passed, 0 warnings |
| 105. InfoPanel setFixedSize → scaled_px (8 locations) | Done | 435 passed, 0 warnings |
| 106. project_service.py silent exceptions → _log.debug (10 locations) | Done | 435 passed, 0 warnings |
| 107. sidebar_favorites/sidebar_recent Path('.') sentinel fix | Done | 435 passed, 0 warnings |
| 108. Test: core/tag_library.py (+18 tests) | Done | 453 passed, 0 warnings |
| 109. Test: core/project_data.py (+12 tests) | Done | 465 passed, 0 warnings |
| 110. Test: core/ui_scale.py (+11 tests) | Done | 476 passed, 0 warnings |
| 111. Test: core/lru_cache.py (+14 tests) | Done | 490 passed, 0 warnings |
| 112. Test: core/crash_handler.py (+5 tests) | Done | 495 passed, 0 warnings |
| 113. Test: core/color_utils.py (+13 tests) | Done | 508 passed, 0 warnings |
| 114. Plugin fix: download_tracker placeholder tracker.py | Done | 509 passed, 0 warnings |
| 115. DB lifecycle: MetadataService/TagService ConnectionProvider | Done | 520 passed, 0 warnings |
| 116. DB lifecycle: LibraryContext scoped ConnectionProvider | Done | 521 passed, 0 warnings |
| 117. DB lifecycle: LAN route scoped ConnectionProvider | Done | 522 passed, 0 warnings |
| 118. DB lifecycle: Desktop scoped runtime constraints | Done | 526 passed, 0 warnings |
| 119. Event bridge: Qt-safe domain event delivery | Done | 529 passed, 0 warnings |
| 120. EventBus subscription tokens | Done | 531 passed, 0 warnings |
| 121. EventBus weak owner subscriptions | Done | 533 passed, 0 warnings |
| 122. Architecture: LibrarySession direction ADR | Done | 533 passed, 0 warnings |
| 123. LibrarySession thin wrapper + bootstrap acceptance | Done | 535 passed, 0 warnings |
| 124. LibrarySession first desktop scoped-service entry | Done | 536 passed, 0 warnings |
| 125. LibrarySession MainWindow open/switch entry | Done | 536 passed, 0 warnings |
| 126. LibrarySession app startup entry | Done | 536 passed, 0 warnings |
| 127. LibrarySession LAN sharing toggle entry | Done | 536 passed, 0 warnings |
| 128. LibrarySession service-boundary tests | Done | 539 passed, 0 warnings |
| 129. LibrarySession-only bootstrap scoped services | Done | 539 passed, 0 warnings |
| 130. LibraryService current_session transition API | Done | 539 passed, 0 warnings |
| 131. Test library initialization via open_session | Done | 539 passed, 0 warnings |
| 132. Architecture boundary guard for open_library | Done | 540 passed, 0 warnings |
| 133. LibraryService current_session lifecycle coverage | Done | 543 passed, 0 warnings |
| 134. LibraryService current legacy-only guard | Done | 545 passed, 0 warnings |
| 135. LibraryService current documented legacy API | Done | 545 passed, 0 warnings |
| 136. LibrarySession close lifecycle + LibraryService.close_session | Done | 552 passed, 0 warnings |
| 137. open_library legacy docstring | Done | 552 passed, 0 warnings |
| 138. Fix open_library TOCTOU race | Done | 557 passed, 0 warnings |
| 139. Domain layer purity: remove SQL from domain.auth | Done | 557 passed, 0 warnings |
| 140. Architecture boundary: domain sqlite3/core-infrastructure guard | Done | 557 passed, 0 warnings |
| 141. Presentation DB/store fallback: import-level guard + get_library_dir | Done | 557 passed, 0 warnings |
| 142. Scoped service access policy tests (get/warn/require) | Done | 565 passed, 0 warnings |
| 143. Pyright expanded to panels (base, tag_tree, _service_access, _event_bridge) | Done | 565 passed, 0 warnings |
| 144. Event thread safety tests (handler exception isolation + multi-worker delivery) | Done | 567 passed, 0 warnings |
| 145. Documentation structure cleanup (history archive + entry rules) | Done | 567 passed, 0 warnings |
| 146. Consolidate LRUCache (remove core/lru_cache.py, use core/cache.py) | Done | 569 passed, 0 warnings |
| 147. Architecture guard: lru_cache module removal + import prevention | Done | 569 passed, 0 warnings |
| 148. LAN scoped service bundle (LanScopedServices + cached per server) | Done | 569 passed, 0 warnings |
| 149. Path/event naming convention documented | Done | 569 passed, 0 warnings |
| 150. LAN route tests: search/projects/info endpoints | Done | 574 passed, 0 warnings |
| 151. Plugin permission enforcement at registration time | Done | 574 passed, 0 warnings |
| 152. Bug-audit regression fixes + workspace flattening | Done | 599 passed, 2 warnings |
| 153. LAN auth request context RequestKey cleanup | Done | 599 passed, 0 warnings |
| 154. LAN user cache invalidation coverage | Done | 600 passed, 0 warnings |
| 155. LAN user cache invalidation route coverage | Done | 601 passed, 0 warnings |
| 156. LAN share download limit route semantics | Done | 603 passed, 0 warnings |

Current result:

```text
603 passed, 0 warnings
```

New tests added: 513 (from 90 to 603)
