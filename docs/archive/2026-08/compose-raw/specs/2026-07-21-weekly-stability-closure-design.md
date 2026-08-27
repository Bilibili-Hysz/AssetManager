# Weekly Stability Closure Design

## [S1] Objective

Deliver a one-week stability closure for AssetsManager that produces current, reproducible evidence for desktop library-session behavior, LAN/WebUI delivery, and release-critical user journeys. The work prioritizes verified defects and targeted fixes over product expansion or architectural redesign.

## [S2] Product Boundary

AssetsManager remains a local-first asset workspace. The desktop application is the source of management and mutation workflows; LAN is the controlled browsing, review, sharing, and download surface. React SPA is the active WebUI; `AssetsManager/lan/static/` remains only a necessary fallback.

## [S3] Scope

The week is divided into four independently reviewable batches:

1. Baseline and risk ledger.
2. Targeted Python regression closure.
3. React SPA build and API-contract closure.
4. Real LAN release acceptance and evidence report.

Each batch must produce a dated artifact under `docs/compose/reports/`, focused test evidence, and a clear pass, fail, or blocked outcome.

## [S4] Non-Goals

- No new end-user feature work.
- No UI visual redesign or component-system replacement.
- No broad DatabaseManager, LibrarySession, or LAN service-container rewrite.
- No parallel feature implementation in React SPA and legacy static UI.
- No dependency upgrade or `npm audit fix --force` without a separate impact review.
- No plugin sandbox or permission-model work.

## [S5] Batch 1: Baseline and Risk Ledger

Establish the actual working-tree and quality baseline before modifying source.

Required evidence:

- Git working-tree status recorded without reverting unrelated changes.
- Python gate attempted in this order: ruff, pyright, compileall, pytest.
- WebUI environment and lockfile state recorded; run `npm ci`, `npm run typecheck`, `npm test`, and `npm run build` when Node tooling is available.
- Existing documented counts are treated as historical only; the report records the current observed result.
- A risk ledger ranks every discovered issue as P0, P1, P2, or deferred, with reproduction command or manual observation.

Success criteria:

- No source changes are made solely to make a historical test count match documentation.
- Every issue selected for later batches has a reproducible symptom or an existing failing test.

## [S6] Batch 2: Python Session and Desktop Regression Closure

Protect the highest-risk desktop and session boundaries with focused, behavior-oriented regression tests. Fix only failures reproduced in Batch 1 or independently confirmed during focused review.

Required coverage areas:

- Library switch stops or invalidates panel-owned work before the old session closes.
- Old session events and asynchronous completions cannot refresh the new active library.
- Session close rejects new work and drains admitted operations without same-thread reentrant close.
- File mutation projection occurs before the scoped `FileSystemChanged` event is consumed.
- Undo/Redo remains isolated to the canonical session.
- Runtime language and scale refresh preserves dialog state for already migrated dialogs.

Preferred test locations:

- `tests/integration/test_library_service.py`
- `tests/integration/test_file_operation_service.py`
- `tests/integration/test_undo_service.py`
- `tests/desktop/test_settings_dialog.py`
- `tests/desktop/test_tag_editor_dialog.py`
- `tests/desktop/test_plugin_manager_dialog.py`
- `tests/unit/test_architecture_boundaries.py`

Success criteria:

- Every production change has a focused regression that fails before the fix and passes after it.
- Focused tests pass before the full Python gate is rerun.
- No new direct presentation DB/store access, unscoped mutation service, or legacy-session fallback is introduced.

## [S7] Batch 3: React SPA and LAN Contract Closure

Validate the WebUI build pipeline and preserve browser/server contracts that are essential to secure LAN sharing.

Required coverage areas:

- `npm ci`, typecheck, tests, and production build complete from `webui/`.
- aiohttp serves the built SPA assets when `webui/dist/assets` exists.
- API client remains same-origin and sends `credentials: "same-origin"`.
- Browser auth restoration uses the HttpOnly cookie plus `/api/auth/me`; JavaScript does not need the credential value.
- Download endpoints preserve JSON/Blob response behavior.
- WebSocket uses same-origin `ws`/`wss`, has bounded reconnect, and does not use query tokens.
- Legacy static fallback rejects backup artifacts and remains a fallback rather than a second feature surface.

Preferred test locations:

- `webui/src/api/contracts.test.ts`
- `webui/src/api/files-shares.contract.test.ts`
- `webui/src/stores/AuthContext.test.tsx`
- `webui/src/hooks/useWebSocket.test.tsx`
- `tests/lan/test_lan_api.py`
- `tests/lan/test_path_guard.py`

Success criteria:

- Any contract defect has a focused frontend or LAN regression test.
- The production WebUI bundle can be served by the existing aiohttp route configuration without changing API origin semantics.

## [S8] Batch 4: Real LAN Release Acceptance

Run a manual acceptance matrix against a real library on at least one additional LAN client and one mobile browser when available. Record environment details, observed outcomes, logs, and blockers without exposing credentials or private absolute paths.

Required journeys:

1. Start sharing from an active desktop library and open the LAN URL from a second client.
2. Login and restore browser session through refresh.
3. Browse root, nested project, detail page, metadata, tags, thumbnail, and search.
4. Download one file and execute one batch ZIP download.
5. Create and consume a password-protected share from a QR code or copied URL.
6. Confirm expected guest, registered-user, and admin permissions.
7. Connect two browser clients, observe WebSocket behavior, and verify bounded recovery after a brief network interruption.
8. Stop sharing, switch library, and close the desktop app; confirm no stale LAN service or errors remain.
9. Open forced legacy fallback only for its documented browse/login/share/download safety path.

Success criteria:

- All required journeys have a pass/fail/blocked result with reproduction conditions.
- Any P0 or P1 failure blocks release and becomes a focused follow-up task.
- No credential, token, share password, or private filesystem path is placed in the report.

## [S9] Day-by-Day Delivery Goals

| Day | Batch | Daily goal | Completion evidence |
| --- | --- | --- | --- |
| Day 1 | Batch 1 | Establish current Python/WebUI baseline and ranked risk ledger. | Baseline report with exact commands and observed outcomes. |
| Day 2 | Batch 2A | Reproduce and close the highest-priority session or file-operation regression. | Focused test, minimal fix if needed, focused gate. |
| Day 3 | Batch 2B | Validate Desktop dialog lifecycle and architecture boundaries; close only confirmed regressions. | Desktop and boundary test evidence. |
| Day 4 | Batch 3 | Validate WebUI install, typecheck, tests, build, and LAN contracts. | WebUI/LAN contract report and build artifact result. |
| Day 5 | Batch 4A | Execute real-LAN acceptance with second client and mobile browser. | Filled manual journey matrix. |
| Day 6 | Batch 4B | Retest defects found in real-LAN acceptance and execute final focused gates. | Retest evidence or documented blockers. |
| Day 7 | Closeout | Run full gates, publish final readiness report, and create next-week backlog from unresolved findings. | Final report with pass/fail decision and ranked follow-ups. |

## [S10] Global Engineering Constraints

- Preserve unrelated working-tree changes; never edit the ignored `Project/` backup directory.
- Use `LibrarySession` and scoped services for new opened-library code.
- Use `PathGuard`, `validate_path()`, or `validated_existing_key()` for every user-supplied LAN path.
- Keep application mutation facts on session-scoped domain events; use `core.signal_bus` only for presentation coordination.
- Use `scaled_px()` or `scaled_pt()` for new desktop dimensions and theme tokens for colors.
- Do not rebuild visible dialogs during runtime language or UI-scale refresh; preserve user state and running work.
- Run focused checks first. Before weekly closeout, run `python -m ruff check .`, `python -m pyright`, `python -m compileall AssetsManager -q`, and `python -m pytest -q`.
- Do not claim a release-ready result if any required command or manual journey is blocked or unexecuted.

## [S11] Reporting and Decision Rule

Each batch report must state:

- Scope and environment.
- Exact commands or manual procedure.
- Observed results.
- Changed files, if any.
- Regressions added, if any.
- Remaining risks, classified P0/P1/P2/deferred.

The final weekly report chooses one outcome:

- **Ready for internal LAN release:** all P0/P1 items pass and all required acceptance journeys are complete.
- **Conditionally ready:** no P0 issue, but a non-critical manual environment is unavailable; the report names the missing evidence.
- **Not ready:** any P0/P1 failure, unresolved security concern, or incomplete critical journey.
