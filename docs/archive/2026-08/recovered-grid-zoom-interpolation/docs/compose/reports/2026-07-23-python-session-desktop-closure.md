# Day 2 Python Session/Desktop Closure

## Scope and Environment

- Isolated worktree: `.worktrees/grid-zoom-interpolation-fix`
- Verified HEAD: `0885d77c74baa6caa94f0a6e98b155a5f3fef399`
- All results in this report are from that HEAD. The worktree was not clean at entry: `docs/compose/reports/2026-07-22-grid-zoom-investigation.md` was already untracked.
- No application code, test code, dependency file, or lock file was changed. This report is the only file modified by this follow-up audit.

## Original Planned Focused Suite

Exact command executed:

```powershell
python -m pytest tests/unit/test_architecture_boundaries.py tests/integration/test_library_service.py tests/integration/test_file_operation_service.py tests/integration/test_undo_service.py tests/desktop/test_settings_dialog.py tests/desktop/test_tag_editor_dialog.py tests/desktop/test_plugin_manager_dialog.py -q
```

Observed result: collection failed before any test ran (`no tests ran in 0.01s`). At HEAD `0885d77`, these requested paths do not exist:

- `tests/desktop/test_settings_dialog.py`
- `tests/desktop/test_plugin_manager_dialog.py`

The collection error was `ERROR: file or directory not found` for the first absent path. The second absent path was independently confirmed absent. This P1 verification/process gap remains: the original planned command was not executable and did not run tests. The passing replacement suite below is not success of the original command.

## Replacement Focused Suite

To execute existing tests that directly cover S6/S10 concerns, the following replacement focused suite was run:

```powershell
python -m pytest tests/unit/test_architecture_boundaries.py tests/integration/test_library_service.py tests/integration/test_file_operation_service.py tests/integration/test_undo_service.py tests/desktop/test_file_event_session_routing.py tests/desktop/test_info_async_identity.py tests/desktop/test_tag_event_session_routing.py tests/desktop/test_sidebar_lifecycle.py tests/desktop/test_sharing_settings_dialog.py tests/desktop/test_tag_editor_dialog.py -q
```

Observed result: `173 passed in 29.28s`.

This substitute run lowers the product-behavior risks where its actual nodes provide evidence. It does not make the original command runnable or eliminate coverage gaps from the two missing test files.

## Required Invariant Coverage

### S6: panel-owned work stopped or invalidated before a library switch

Executed behavioral nodes:

- `tests/desktop/test_file_event_session_routing.py::test_file_list_shutdown_ignores_filesystem_watcher` shuts down `QWidgetFileListPanel`, emits a filesystem watcher callback, and proves cache-clearing and post-refresh work do not run after shutdown.
- `tests/desktop/test_sidebar_lifecycle.py::test_sidebar_prepare_invalidates_pending_library_search` calls `SidebarPanel.prepare_library_switch()`, delivers stale preload completions, and proves the search timer stops and no entries are applied.

`tests/unit/test_architecture_boundaries.py::test_file_list_shutdown_releases_tracked_panel_subscriptions` also executed, but only source-inspects that `FileList.shutdown()` calls `super().shutdown()`. Gap: the suite does not prove every panel-owned asynchronous work type is stopped or invalidated on every library-switch path.

### S6: old session event and async completion cannot refresh the new library

Executed behavioral nodes:

- `tests/desktop/test_file_event_session_routing.py::test_file_list_ignores_foreign_session_file_events` proves `QWidgetFileListPanel` ignores foreign-token `FileSystemChanged` and refreshes only for the current token.
- `tests/desktop/test_tag_event_session_routing.py::test_info_ignores_foreign_tag_events_and_other_assets`, `::test_tag_tree_ignores_foreign_catalog_events`, and `::test_info_ignores_foreign_metadata_events` prove Info and Tag Tree reject foreign-session events, with Info also rejecting non-current assets.
- `tests/desktop/test_info_async_identity.py::test_async_callbacks_reject_old_same_root_session_completion` delivers old same-root session file-info and preview completions after a new request and proves the current name, plugin field, and preview remain unchanged.
- `tests/desktop/test_info_async_identity.py::test_file_info_and_preview_reject_old_navigate_away_back_completion` and `::test_directory_size_rejects_stale_zero_for_reused_path_and_session` cover stale completion rejection across navigation and reused path/session.
- `tests/desktop/test_info_async_identity.py::test_closed_session_rejects_file_info_preview_plugin_and_directory_callbacks` proves callbacks do not change the UI after the owning session closes.
- `tests/integration/test_library_service.py::test_same_root_reopen_publishes_new_library_opened_token` proves same-root reopening publishes distinct `LibraryOpened.session_token` values.

The static checks `tests/unit/test_architecture_boundaries.py::test_file_list_uses_session_scoped_file_events`, `::test_tag_panels_use_session_scoped_tag_events`, and `::test_info_uses_session_scoped_metadata_events` also executed. Gap: this remains focused handler/callback coverage rather than a complete composed library-switch UI flow that publishes domain events and resolves worker futures.

### S6: close rejects new work, drains accepted work, and rejects same-thread reentrant close

Executed behavioral nodes:

- `tests/integration/test_library_service.py::test_scoped_public_operation_lease_drains_before_close[close_session-*]` and `[session_close-*]` assert close blocks for an already-entered operation, marks the session closed, and rejects a newly attempted scoped operation with `RuntimeError`.
- `tests/integration/test_library_service.py::test_duplicate_direct_close_waits_for_active_operation` asserts concurrent close callers wait until active work drains.
- `tests/integration/test_library_service.py::test_session_cannot_close_from_inside_its_own_operation` asserts same-thread close raises `RuntimeError` matching `active operation` and the session remains open.
- `tests/integration/test_file_operation_service.py::test_bound_duplicate_rejects_closed_session_without_mutating` asserts a closed session rejects mutation and leaves filesystem state unchanged.

### S6: file mutation projection completes before scoped `FileSystemChanged` consumption

Executed projection-before-observer nodes:

- `tests/integration/test_file_operation_service.py::test_file_copied_observers_see_new_file_indexed`
- `tests/integration/test_file_operation_service.py::test_trash_delete_clears_projections_before_file_deleted_subscribers_run`
- `tests/integration/test_file_operation_service.py::test_file_renamed_observers_see_moved_directory_projection`
- `tests/integration/test_file_operation_service.py::test_restore_backup_reindexes_directory_tree_before_publishing_created`
- `tests/integration/test_file_operation_service.py::test_create_and_duplicate_reindex_before_publishing_created`

Those nodes consume legacy `FileCopied`, `FileDeleted`, `FileRenamed`, or `FileCreated`, not scoped `FileSystemChanged`. `tests/desktop/test_file_event_session_routing.py::test_file_list_ignores_foreign_session_file_events` covers scoped-event token routing, while `tests/unit/test_architecture_boundaries.py::test_file_list_uses_session_scoped_file_events` is source-level only. Gap: no executed test asserts projection ordering when scoped `FileSystemChanged` is consumed.

### S6: Undo/Redo isolated by canonical session

Executed behavioral nodes:

- `tests/integration/test_undo_service.py::test_undo_stacks_isolated_by_library_root`
- `tests/integration/test_undo_service.py::test_two_library_undo_redo_uses_each_session_file_operations`
- `tests/integration/test_undo_service.py::test_close_one_library_rejects_its_undo_but_other_library_remains_functional`

These prove independent histories/operations across two roots and that closing one session does not disable the other. `tests/integration/test_library_service.py::test_open_session_reuses_cached_context` and `::test_open_library_reuses_context` also execute `str(root)`/`Path(root)` reuse checks. Gap: the Undo/Redo assertions themselves do not explicitly test alternate spellings of one canonical root.

### S6: migrated dialogs retain state across runtime language and scale refresh

Executed runtime-refresh coverage is limited to `SharingSettingsDialog`:

- `tests/desktop/test_sharing_settings_dialog.py::test_configuration_navigation_is_named_and_theme_refreshes` selects configuration section 2, emits `theme_changed`, and proves the selected navigation button remains checked while `_apply_configuration_theme` runs.

`tests/desktop/test_tag_editor_dialog.py::test_clear_current_chips_ignores_layout_item_without_widget` executed but only covers chip-layout cleanup, not runtime refresh or state preservation. `tests/unit/test_architecture_boundaries.py::test_startup_window_tracks_theme_and_language_connection_handles` executed but is a static Startup dialog connection-handle check.

Gaps: no executed runtime language or scale-refresh state-preservation test exists for `TagEditorDialog`. Because `test_settings_dialog.py` and `test_plugin_manager_dialog.py` are missing, this audit makes no coverage claim for `SettingsDialog` or `PluginManagerDialog`.

## S10 Architecture Guard Coverage

The replacement suite executed these static boundary tests:

- `tests/unit/test_architecture_boundaries.py::test_presentation_db_store_access_stays_in_documented_fallbacks`
- `tests/unit/test_architecture_boundaries.py::test_presentation_does_not_construct_unscoped_mutation_services`
- `tests/unit/test_architecture_boundaries.py::test_panels_do_not_import_legacy_unscoped_mutation_events`
- `tests/unit/test_architecture_boundaries.py::test_library_panels_bind_through_scoped_services_only`
- `tests/unit/test_architecture_boundaries.py::test_database_singleton_helpers_are_legacy_only`
- `tests/unit/test_architecture_boundaries.py::test_library_service_current_stays_legacy_only`
- `tests/unit/test_architecture_boundaries.py::test_production_code_does_not_read_session_raw_resources`

These source-level regression guards passed. They do not substitute for behavioral stale-event, async-completion, scoped-event ordering, or dialog-refresh coverage.

## Risks and Release Impact

### P0

- None observed. Passing focused tests are not evidence of absence of P0 defects.

### P1

- The mandated focused suite is non-runnable at HEAD `0885d77` because two referenced desktop test files are absent. This remains a P1 verification/process gap: the original required command was not exercised even though the replacement suite passed.
- The replacement suite lowers product-behavior risk for stale panel events, InfoPanel old-session async completions, file-list shutdown callbacks, sidebar pending-search invalidation, session-close leasing, legacy mutation-event projection ordering, and two-library Undo/Redo isolation. It does not eliminate the missing-file coverage gap or prove a complete composed library-switch UI flow.
- No executed behavioral test demonstrates projection completion before consumption of scoped `FileSystemChanged`.
- Runtime language/scale state-preservation coverage remains incomplete: only `SharingSettingsDialog` selected-section retention across theme refresh is verified. `TagEditorDialog` has no runtime-refresh behavior test, and the missing tests leave `SettingsDialog` and `PluginManagerDialog` unverified.

### P2

- The declared clean isolated-worktree premise did not hold: an unrelated untracked report was present before this audit and remains untouched.
- Undo isolation is behaviorally covered for two roots; canonical-path equivalence is still not explicit in the Undo/Redo assertions.

### Deferred

- Adding or recovering absent desktop tests, correcting code/test paths, or changing application/test/dependency files is outside this audit's permitted file-change scope.
- No code remediation was attempted, as required.

Release impact: this Day 2 audit cannot support a release-readiness conclusion. The original focused validation did not collect. The replacement suite lowers several S6 product-behavior risks but leaves the P1 verification/process gap and scoped `FileSystemChanged` and dialog coverage gaps unresolved. Final release status remains reserved for the Day 7 closeout after all required automated and real-LAN acceptance evidence is available.

## Final Repository Checks

- Replacement focused suite: `173 passed in 29.28s` using the command recorded in **Replacement Focused Suite**.
- `git diff --check`: completed with no output (no tracked-diff whitespace errors).
- `git status --short`: `?? docs/compose/reports/2026-07-22-grid-zoom-investigation.md` (pre-existing) and `?? docs/compose/reports/2026-07-23-python-session-desktop-closure.md` (this follow-up report). The pre-existing report remains untouched; this report is the sole file modified by this follow-up.
