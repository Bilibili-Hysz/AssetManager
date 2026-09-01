# Day 1 Stability Baseline

- Date: 2026-07-21
- Scope: Week closure Day 1 baseline and risk ledger only. No production, test, dependency, lockfile, or `Project/` files were edited.
- HEAD commit: `0885d77`; all results below are a baseline of the recorded dirty working tree, not a clean-commit verification of `0885d77`.
- Overall status: DONE_WITH_CONCERNS. Required Python and WebUI gates ran; the full Python suite has one reproducible failure. This report does not assert release readiness.

## Environment

- Python: `3.14.3`
- Node.js: `v24.14.0`
- npm: `11.9.0`
- WebUI package: `assets-manager-webui@1.0.0`
- WebUI lockfile: `webui/package-lock.json`, lockfile version `3`; present before the run and unchanged after `npm ci`.

## Working-Tree Record

`git status --short` was recorded before the gates. The following pre-existing changes were preserved without staging, reverting, formatting, or editing:

```text
 M AssetsManager/dialogs/plugin_manager_dialog.py
 M AssetsManager/dialogs/settings_dialog.py
 M AssetsManager/dialogs/tabbed_dialog.py
 M AssetsManager/dialogs/tag_editor_dialog.py
 M AssetsManager/i18n/en.json
 M AssetsManager/i18n/ja.json
 M AssetsManager/i18n/zh.json
 M tests/desktop/test_tag_editor_dialog.py
?? .mimocode/
?? docs/Suggestions/session-optimization-summary-2026-07-15.md
?? docs/compose/plans/2026-07-21-weekly-stability-closure.md
?? docs/compose/specs/2026-07-21-weekly-stability-closure-design.md
?? docs/session-optimization-handoff-2026-07-15.md
?? tests/desktop/test_plugin_manager_dialog.py
?? tests/desktop/test_settings_dialog.py
```

## Gate Results

| Gate | Exact command | Result | Duration | Evidence |
| --- | --- | --- | ---: | --- |
| Working tree | `git status --short` | PASS | n/a | Snapshot recorded above; unrelated changes preserved. |
| Baseline revision | `git rev-parse --short HEAD` | PASS | n/a | `0885d77` |
| Ruff | `python -m ruff check .` | PASS | n/a | `All checks passed!` |
| Pyright | `python -m pyright` | PASS | n/a | `0 errors, 0 warnings, 0 informations`; update notice for Pyright `1.1.411` only. |
| Compile | `python -m compileall AssetsManager -q` | PASS | n/a | Exit code `0`; no output. |
| Targeted Python regression | `python -m pytest tests/unit/test_architecture_boundaries.py tests/integration/test_library_service.py tests/integration/test_file_operation_service.py tests/integration/test_undo_service.py tests/desktop/test_settings_dialog.py tests/desktop/test_tag_editor_dialog.py tests/desktop/test_plugin_manager_dialog.py tests/lan/test_lan_api.py tests/lan/test_path_guard.py -q` | PASS | 47.59s wall / 41.97s pytest | `311 passed` |
| Full Python regression | `python -m pytest -q` | FAIL | 95.30s wall / 92.26s pytest | `1 failed, 1306 passed` |
| WebUI dependency install | `npm ci` from `webui/` | PASS | 22.34s | Installed 237 packages; lockfile unchanged; audit reported 5 vulnerabilities: 3 moderate, 1 high, 1 critical. |
| WebUI typecheck | `npm run typecheck` from `webui/` | PASS | 5.23s | `tsc --noEmit` exit code `0`. |
| WebUI tests | `npm test` from `webui/` | PASS | 18.72s wall / 14.66s Vitest | `17 passed` test files, `59 passed` tests. React Router v7 future-flag warnings appeared in test stderr only. |
| WebUI build | `npm run build` from `webui/` | PASS | 10.92s wall / 5.42s Vite | `tsc -b && vite build` succeeded; 1,621 modules transformed. |

Historical test counts, if any, are context only. No source, test, or documentation was changed to match a historical count.

## Failure Evidence

### P2: Grid zoom interpolation regression

- Reproduction: `python -m pytest tests/desktop/test_file_list_grid_widget.py::test_grid_zoom_interpolates_toward_target_layout -q`
- Observed in full run: `tests/desktop/test_file_list_grid_widget.py::test_grid_zoom_interpolates_toward_target_layout`
- Assertion: after `begin_zoom(180)` and `set_zoom_thumb_size(128)`, `middle` remained equal to `start` (`QRect(44, 233, 176, 221)`), while the test requires an interpolated texture rectangle.
- Classification: P2. A focused desktop visual/layout behavior is broken in regression coverage; this baseline recorded it without editing code. Validate impact and workaround before elevating.

## Risk Ledger

| Priority | Status | Risk | Evidence or manual observation | Release impact |
| --- | --- | --- | --- | --- |
| P0 | None observed | Security bypass, path escape, data loss, cross-library stale write, or release-blocking crash | Targeted architecture, service, LAN API, and path guard suite: `311 passed`; no P0 symptom observed in this baseline. | No P0 gate block evidenced by this run. |
| P1 | None observed | Critical desktop/LAN journey, authorization, or WebUI build-contract failure | Targeted desktop/LAN tests passed; WebUI typecheck, tests, and production build passed. | No P1 gate block evidenced by this run. |
| P2 | Open | Grid zoom interpolation does not update its intermediate rectangle | Reproduce with the focused pytest command above; full suite result was `1 failed, 1306 passed`. | Not release-ready to claim; triage in a later batch only with this reproducible symptom. |
| Deferred | Open | WebUI dependency audit reports 5 vulnerabilities | `npm ci` reported 3 moderate, 1 high, and 1 critical vulnerability. No dependency or lockfile changes permitted in Day 1. | Requires ownership and package-level audit before release decision; not treated as a verified product exploit. |
| Deferred | Open | React Router v7 future-flag warnings in WebUI tests | Warnings appeared in `Sidebar`, `BrowsePage`, and `LoginPage` test stderr; all 59 tests passed. | Compatibility follow-up; no current contract failure. |
| Deferred | Open | Pyright update notice | Pyright reports `v1.1.410 -> v1.1.411`; current check has 0 errors. | Toolchain hygiene only. |

## Changes and Verification

- Final snapshot contains the untracked path `docs/compose/reports/2026-07-21-stability-baseline.md`, which is absent from the initial snapshot.
- The initial and final tracked-modification lists are identical; no pre-existing tracked file changed between those snapshots.
- Final working-tree audit was captured after writing this report. Its raw outputs follow so the preservation claim is independently inspectable.

### Final `git status --short`

```text
 M AssetsManager/dialogs/plugin_manager_dialog.py
 M AssetsManager/dialogs/settings_dialog.py
 M AssetsManager/dialogs/tabbed_dialog.py
 M AssetsManager/dialogs/tag_editor_dialog.py
 M AssetsManager/i18n/en.json
 M AssetsManager/i18n/ja.json
 M AssetsManager/i18n/zh.json
 M tests/desktop/test_tag_editor_dialog.py
?? .mimocode/
?? docs/Suggestions/session-optimization-summary-2026-07-15.md
?? docs/compose/plans/2026-07-21-weekly-stability-closure.md
?? docs/compose/reports/2026-07-21-stability-baseline.md
?? docs/compose/specs/2026-07-21-weekly-stability-closure-design.md
?? docs/session-optimization-handoff-2026-07-15.md
?? tests/desktop/test_plugin_manager_dialog.py
?? tests/desktop/test_settings_dialog.py
```

### Final `git diff --name-only`

```text
AssetsManager/dialogs/plugin_manager_dialog.py
AssetsManager/dialogs/settings_dialog.py
AssetsManager/dialogs/tabbed_dialog.py
AssetsManager/dialogs/tag_editor_dialog.py
AssetsManager/i18n/en.json
AssetsManager/i18n/ja.json
AssetsManager/i18n/zh.json
tests/desktop/test_tag_editor_dialog.py
```

### Final `git ls-files --others --exclude-standard`

```text
.mimocode/plans/1784045171846-playful-orchid.md
docs/Suggestions/session-optimization-summary-2026-07-15.md
docs/compose/plans/2026-07-21-weekly-stability-closure.md
docs/compose/reports/2026-07-21-stability-baseline.md
docs/compose/specs/2026-07-21-weekly-stability-closure-design.md
docs/session-optimization-handoff-2026-07-15.md
tests/desktop/test_plugin_manager_dialog.py
tests/desktop/test_settings_dialog.py
```

`git status --short -- "Project"` produced no output. Compared with the initial snapshot, the tracked modified paths are unchanged. The final snapshot contains `docs/compose/reports/2026-07-21-stability-baseline.md`; the initial snapshot already contained the listed plan/spec documents and other untracked paths.

## Follow-Up Boundaries

- Day 2 candidates must be chosen only from reproducible symptoms or existing failing tests. The grid zoom failure qualifies.
- Do not use historical test totals as an implementation target.
- Day 3 and Day 4 LAN and SPA acceptance work remains unexecuted in this Day 1 baseline.
