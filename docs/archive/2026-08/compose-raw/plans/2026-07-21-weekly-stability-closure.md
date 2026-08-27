# Weekly Stability Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a defensible internal-LAN release decision by validating the current desktop session boundary, WebUI delivery contracts, and real-client sharing journeys during one focused week, without expanding product scope.

**Architecture:** This is a verification-first plan. Batches first establish current behavior, then make only a minimal tested correction for a reproduced defect, validate the separately built React SPA against the aiohttp LAN API, and finally execute real-client acceptance. The desktop session boundary remains `LibrarySession -> ApplicationBootstrap.for_library() -> LibraryScopedServices`; LAN paths remain `PathGuard`-validated and browser authentication remains Cookie-based.

**Tech Stack:** Python 3.12+, PySide6, SQLite, pytest, ruff, pyright, aiohttp, React 18, TypeScript, Vite, Vitest, Node.js.

## Global Constraints

- Preserve unrelated working-tree changes; never edit the ignored `Project/` backup directory.
- Use `LibrarySession` and scoped services for new opened-library code.
- Use `PathGuard`, `validate_path()`, or `validated_existing_key()` for every user-supplied LAN path.
- Keep application mutation facts on session-scoped domain events; use `core.signal_bus` only for presentation coordination.
- Use `scaled_px()` or `scaled_pt()` for new desktop dimensions and theme tokens for colors.
- Do not rebuild visible dialogs during runtime language or UI-scale refresh; preserve user state and running work.
- Run focused checks first. Before weekly closeout, run `python -m ruff check .`, `python -m pyright`, `python -m compileall AssetsManager -q`, and `python -m pytest -q`.
- Do not claim a release-ready result if any required command or manual journey is blocked or unexecuted.
- Do not run `npm audit fix --force`, replace DatabaseManager, or add product features in this plan.

---

## Weekly Objectives

| Objective | Target | Evidence |
| --- | --- | --- |
| O1: Current baseline | Establish actual Python and WebUI health without relying on historical pass counts. | Day-1 report records exact command, environment, exit status, duration, and failures. |
| O2: Session integrity | Confirm old library work cannot affect a newly opened session and file mutations publish after projections update. | Focused integration/desktop regressions pass; each correction has a failing-before/passing-after test. |
| O3: Browser delivery | Confirm built React SPA, Cookie authentication, Blob download, and WebSocket contracts remain compatible with aiohttp. | WebUI typecheck/test/build plus focused Python LAN tests pass. |
| O4: Real LAN release evidence | Confirm critical user journeys from a second client and mobile browser, including recovery and shutdown. | Completed acceptance matrix with no P0/P1 failure. |

## Report Format

Every report created by this plan uses exactly this structure:

```markdown
# Batch Report

## Environment
- Date/time:
- Git revision:
- Python / Node / npm:
- Desktop host:
- LAN clients:

## Procedure
1. Run the command or complete the manual journey listed in the owning plan task.

## Results
| Check | Result | Evidence |
| --- | --- | --- |

## Findings
| Priority | Reproduction | Decision |
| --- | --- | --- |

## Changed Files
- (none) or exact paths

## Release Impact
Ready / Conditionally ready / Not ready, with reason.
```

### Task 1: Establish Baseline and Risk Ledger

**Covers:** [S3, S5, S9, S10, S11]

**Files:**
- Create: `docs/compose/reports/2026-07-21-stability-baseline.md`
- Read: `docs/agent-quick-map.md`
- Read: `docs/agent-architecture-map-deep.md`
- Read: `docs/testing.md`
- Read: `pytest.ini`, `pyrightconfig.json`, `webui/package.json`, `webui/package-lock.json`
- Do not modify: `AssetsManager/`, `webui/src/`, `tests/`

**Interfaces:**
- Consumes: Existing Python quality commands and WebUI package scripts.
- Produces: A current baseline report and ranked ledger used to decide whether Tasks 2 and 3 require code changes.

- [ ] **Step 1: Record the repository state without modifying it**

Run:

```powershell
git status --short
git rev-parse --short HEAD
```

Expected: The report lists every pre-existing modified or untracked path as observed state; no path is reverted, staged, deleted, or reformatted.

- [ ] **Step 2: Run the Python static and syntax gates in isolation**

Run:

```powershell
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
```

Expected: Each command has an exit code and output summary recorded independently. Continue to the next command even when an earlier command fails so the risk ledger is complete.

- [ ] **Step 3: Run the focused high-risk Python regression baseline**

Run:

```powershell
python -m pytest tests/unit/test_architecture_boundaries.py tests/integration/test_library_service.py tests/integration/test_file_operation_service.py tests/integration/test_undo_service.py tests/desktop/test_settings_dialog.py tests/desktop/test_tag_editor_dialog.py tests/desktop/test_plugin_manager_dialog.py tests/lan/test_lan_api.py tests/lan/test_path_guard.py -q
```

Expected: A single recorded pass/fail summary. For each failure, capture the failing test node, assertion output, and minimal reproduction command.

- [ ] **Step 4: Run the full Python test baseline**

Run:

```powershell
python -m pytest -q
```

Expected: Record observed pass/fail/skipped counts and elapsed time. Do not edit documentation merely to synchronize historical test counts.

- [ ] **Step 5: Establish the WebUI reproducibility baseline**

Run from `webui/`:

```powershell
npm ci
npm run typecheck
npm test
npm run build
```

Expected: `dist/` is created only by `npm run build`; record each command result. If `npm ci` cannot access the registry, classify it as an environment blocker rather than changing lockfiles or dependencies.

- [ ] **Step 6: Create the risk ledger**

Write `docs/compose/reports/2026-07-21-stability-baseline.md` using the Report Format above. Classify findings exactly as:

```text
P0: authentication bypass, path traversal, data loss, stale cross-library write, or release-blocking crash
P1: broken critical desktop/LAN journey, incorrect authorization, or reproducible WebUI build/contract failure
P2: non-critical regression with a clear workaround
Deferred: historical count drift, unavailable external environment, or a non-reproduced hypothesis
```

Expected: Every proposed source change in Task 2 or Task 3 references a failing test or a repeatable manual reproduction.

### Task 2: Validate Python Session and Desktop Regression Boundaries

**Covers:** [S3, S6, S9, S10, S11]

**Files:**
- Read: `AssetsManager/application/context.py`, `AssetsManager/application/library_service.py`, `AssetsManager/application/bootstrap.py`, `AssetsManager/application/file_operation_service.py`, `AssetsManager/application/undo_service.py`, `AssetsManager/window_lifecycle_coordinator.py`.
- Test: `tests/unit/test_architecture_boundaries.py`, `tests/integration/test_library_service.py`, `tests/integration/test_file_operation_service.py`, `tests/integration/test_undo_service.py`, `tests/desktop/test_settings_dialog.py`, `tests/desktop/test_tag_editor_dialog.py`, `tests/desktop/test_plugin_manager_dialog.py`.
- Create: `docs/compose/reports/2026-07-23-python-session-desktop-closure.md`

**Interfaces:**
- Consumes: Task 1 risk ledger and the existing `LibrarySession.operation()`, `LibraryService.close_session()`, `ApplicationBootstrap.for_library()`, `FileOperationService._publish_file_change()`, and migrated-dialog runtime refresh contracts.
- Produces: Passing regression evidence, or a bounded repair task for each reproduced P0/P1 failure.

- [ ] **Step 1: Run the session and desktop boundary suite**

```powershell
python -m pytest tests/unit/test_architecture_boundaries.py tests/integration/test_library_service.py tests/integration/test_file_operation_service.py tests/integration/test_undo_service.py tests/desktop/test_settings_dialog.py tests/desktop/test_tag_editor_dialog.py tests/desktop/test_plugin_manager_dialog.py -q
```

Expected: Record every failing node and assertion output. If the suite passes, record a no-change result and do not edit source.

- [ ] **Step 2: Create a bounded repair record for every P0/P1 failure**

Copy this exact record into the report for each failed node:

```text
Title: Fix the literal failing test node copied from this report
Reproducer: the exact `python -m pytest` command formed from that copied node
Expected failing behavior: the literal assertion output copied from the test run
Allowed production files: only modules named in the copied failure traceback
Required regression file: the existing file containing the copied failing node
Required gates: owning test file, architecture boundaries, and this Task 2 suite
```

Expected: Do not edit source during this weekly planning run. Every repair begins later as a separate TDD/bugfix task.

- [ ] **Step 3: Confirm the existing suite covers required invariants**

Record the exact existing test node covering each item:

```text
old-session events are rejected by session token
session close rejects new work and drains admitted work
FileSystemChanged follows projection updates
Undo/Redo history is session-isolated
migrated dialog refresh preserves user state
architecture boundaries reject new presentation DB/store access
```

Expected: A missing invariant becomes a standalone test-coverage task. It does not justify speculative production code.

- [ ] **Step 4: Publish the Python closure report**

Write `docs/compose/reports/2026-07-23-python-session-desktop-closure.md` using the Report Format. List each bounded repair record, or state that all selected session/desktop regressions passed with no source changes.

### Task 3: Validate React SPA and LAN Contract Boundaries

**Covers:** [S3, S7, S9, S10, S11]

**Files:**
- Read: `webui/src/api/client.ts`, `webui/src/stores/AuthContext.tsx`, `webui/src/hooks/useWebSocket.ts`, `AssetsManager/lan/api.py`, `AssetsManager/lan/server.py`, `AssetsManager/lan/routes/_helpers.py`.
- Test: `webui/src/api/contracts.test.ts`, `webui/src/api/files-shares.contract.test.ts`, `webui/src/stores/AuthContext.test.tsx`, `webui/src/hooks/useWebSocket.test.tsx`, `tests/lan/test_lan_api.py`, `tests/lan/test_path_guard.py`.
- Create: `docs/compose/reports/2026-07-24-webui-lan-contract-closure.md`

**Interfaces:**
- Consumes: Task 1 WebUI baseline, aiohttp `setup_routes()`, `createApiClient()`, `AuthProvider`, `useWebSocket()`, and `PathGuard` helper contracts.
- Produces: Passing build and contract evidence, or a bounded repair task for each reproduced P0/P1 browser/server failure.

- [ ] **Step 1: Run the complete WebUI contract suite**

```powershell
cd webui
npm test
```

Expected: Record every frontend failure with its Vitest node and assertion output. If this suite passes, do not change WebUI source.

- [ ] **Step 2: Run the Python LAN contract suite**

Run from the repository root:

```powershell
python -m pytest tests/lan/test_lan_api.py tests/lan/test_path_guard.py -q
```

Expected: Record every failing Python test node and assertion output. If this suite passes, do not change LAN source.

- [ ] **Step 3: Confirm existing contract coverage**

Record the exact existing test node covering each item:

```text
same-origin Cookie transport
Cookie-based /api/auth/me session restoration
JSON versus Blob download behavior
ws/wss same-origin URL construction without query token
bounded WebSocket reconnect
PathGuard rejection of escape paths
SPA asset and legacy static delivery behavior
```

Expected: A missing contract becomes a standalone test-coverage task. It does not justify speculative production code.

- [ ] **Step 4: Run the production WebUI build and LAN focused suite**

Run from `webui/`:

```powershell
npm run typecheck
npm test
npm run build
```

Run from the repository root:

```powershell
python -m pytest tests/lan/test_lan_api.py tests/lan/test_path_guard.py -q
```

Expected: All commands pass. Record the built `webui/dist/assets` presence but do not commit generated distribution output unless the repository already tracks it.

- [ ] **Step 5: Create bounded repair records and publish the WebUI/LAN closure report**

For every P0/P1 failure, add the bounded repair record from Task 2, replacing the reproducer with the copied Vitest or pytest node. Then write `docs/compose/reports/2026-07-24-webui-lan-contract-closure.md` using the Report Format, with frontend/Python contract test results and build output.

### Task 4: Execute Real-LAN Acceptance and Release Decision

**Covers:** [S2, S3, S8, S9, S10, S11]

**Files:**
- Create: `docs/compose/reports/2026-07-26-real-lan-acceptance.md`
- Create: `docs/compose/reports/2026-07-27-weekly-stability-closeout.md`
- Modify only after a reproduced acceptance failure: the smallest source module and matching focused regression named by Task 2 or Task 3.

**Interfaces:**
- Consumes: Tasks 1-3 reports, an active desktop library, `LanSharingMixin._toggle_sharing()`, LAN routes, the SPA build, and one additional LAN client plus mobile browser when available.
- Produces: A complete manual acceptance matrix and a release verdict: ready for internal LAN release, conditionally ready, or not ready.

- [ ] **Step 1: Prepare a safe acceptance library and environment record**

Create a temporary, non-sensitive library containing:

```text
root/
  images/sample.png
  documents/sample.txt
  nested/project/sample.jpg
  nested/project/second.txt
```

Record desktop OS, Python version, Node/npm version, LAN bind address, browser versions, second-client device, mobile device, and whether sleep/wake testing is possible. Do not write passwords, tokens, QR payloads, or private absolute paths into the report.

- [ ] **Step 2: Execute browser and permission journeys from a second LAN client**

Perform and record pass/fail for this exact sequence:

```text
1. Start sharing from the active desktop library.
2. Open the LAN URL from a second client.
3. Login and refresh the page to restore the Cookie-authenticated session.
4. Browse root and nested project; open detail; load tags, metadata, and thumbnail.
5. Search a known sample file.
6. Download one file.
7. Download two files as a ZIP.
8. Verify guest, registered-user, and admin permissions against configured roles.
```

Expected: Every row has URL-independent evidence such as visible result, response status, downloaded filename, or observed permission denial.

- [ ] **Step 3: Execute password-share and mobile journeys**

Perform and record:

```text
1. Create a password-protected share for nested/project.
2. Open the copied URL or generated QR code from a separate browser/mobile device.
3. Enter the share password.
4. Confirm only the scoped project is visible.
5. Preview and download an allowed file.
6. Confirm an out-of-scope path cannot be reached by URL manipulation.
```

Expected: The share Cookie remains scoped to the share API path; no credential value is copied into the report.

- [ ] **Step 4: Execute WebSocket recovery and lifecycle journeys**

Perform and record:

```text
1. Open two authenticated browser clients.
2. Trigger a benign server event or navigate on both clients.
3. Disable and restore one client's network for less than 30 seconds.
4. Observe at most the intended bounded reconnect behavior.
5. Stop sharing from the desktop app.
6. Start sharing again, switch to another library, then close the desktop app.
```

Expected: No stale server remains attached to the old library; no desktop traceback, hung shutdown, or old-library response is observed.

- [ ] **Step 5: Verify forced legacy fallback safety path**

Open the documented legacy fallback path and perform only:

```text
browse -> login when configured -> open share -> download
```

Expected: The fallback does not expose `.bak`/`.bak2` resources, accepts only documented functionality, and does not receive new feature work.

- [ ] **Step 6: Triage each failure before editing code**

Use this exact decision table:

```text
P0: auth bypass, path escape, cross-library data exposure, data loss, crash during critical journey
P1: login/browse/share/download/desktop shutdown journey is reproducibly broken
P2: non-critical visual issue or a documented workaround exists
Blocked: required device/network/sleep capability unavailable
```

Expected: For P0/P1, add a focused automated regression first and return to Task 2 or Task 3. For blocked journeys, report the missing environment and select `Conditionally ready` or `Not ready`; do not infer a pass.

- [ ] **Step 7: Run final automated gates**

Run from repository root:

```powershell
python -m ruff check .
python -m pyright
python -m compileall AssetsManager -q
python -m pytest -q
```

Run from `webui/`:

```powershell
npm run typecheck
npm test
npm run build
```

Expected: Record the exact observed output summaries. A failure causes `Not ready` until fixed and retested, unless it is proven unrelated pre-existing work with explicit owner and no release impact.

- [ ] **Step 8: Publish acceptance and closeout reports**

Write `docs/compose/reports/2026-07-26-real-lan-acceptance.md` using the Report Format and add a matrix containing every Task 4 journey. Then write `docs/compose/reports/2026-07-27-weekly-stability-closeout.md` with exactly one final decision:

```text
Ready for internal LAN release: all P0/P1 findings closed and required journeys complete.
Conditionally ready: no P0 finding, but a named non-critical acceptance environment is unavailable.
Not ready: unresolved P0/P1 finding, security concern, or incomplete critical journey.
```

Expected: The closeout includes a ranked next-week backlog and does not claim readiness without full evidence.

## Day Schedule

| Day | Work | End-of-day deliverable |
| --- | --- | --- |
| Day 1 | Task 1 | `2026-07-21-stability-baseline.md` with current gate results and risk ledger. |
| Day 2 | Task 2, session/Desktop boundary suite | Failing nodes classified into bounded repair tasks, or a no-change passing report section. |
| Day 3 | Task 2, invariant coverage review | `2026-07-23-python-session-desktop-closure.md`. |
| Day 4 | Task 3 | `2026-07-24-webui-lan-contract-closure.md` and production WebUI build outcome. |
| Day 5 | Task 4, browser/share/mobile journeys | First completed real-LAN acceptance matrix. |
| Day 6 | Task 4, recovery/lifecycle retest | Retested P0/P1 findings or explicit blockers. |
| Day 7 | Task 4 closeout | Full gates, release decision, and ranked follow-up backlog. |

## Plan Self-Review

- Spec coverage: Task 1 covers baseline/risk requirements; Task 2 covers desktop/session closure; Task 3 covers SPA/LAN contracts; Task 4 covers product boundary, manual acceptance, reporting, and final decision. All sections S1-S11 are covered.
- Placeholder scan: This is a verification plan, so all commands and journey steps are concrete. Repair-task records require copying actual failing nodes and assertions from observed output; source changes are deliberately deferred to those separately scoped repairs.
- Interface consistency: All named interfaces are existing project APIs: `LibrarySession.operation()`, `ApplicationBootstrap.for_library()`, `FileOperationService._publish_file_change()`, `createApiClient()`, `AuthProvider`, `useWebSocket()`, `setup_routes()`, `validate_path()`, and `validated_existing_key()`.
