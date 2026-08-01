---
feature: task-14-browser-realtime-acceptance
status: delivered
specs:
  - docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-design.md
plans:
  - docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-migration.md
branch: master
evidence_state: pre-baseline working tree; baseline captured in repository-baseline-2026-08-01.md
---

# Task 14 — Browser Realtime Acceptance Final Report

## What Was Built

Task 14 provides a real Chromium acceptance harness for the React LAN WebUI. It starts the production LAN server against the canonical `LibraryRuntime`, authenticates through the same-origin cookie boundary, opens the built SPA, and performs mutations through the Desktop-side `file_operation_service`.

The harness proves three recovery paths: normal mutation refresh without a browser reload, revision-gap recovery after a real LAN stop/restart on the same port, and epoch recovery after closing and reopening the same library root with a new canonical session/runtime.

## Architecture

`tests/e2e/test_webui_realtime_acceptance.py` owns the browser fixture, runtime/server lifecycle, cookie bootstrap, and three end-to-end scenarios. The browser consumes the production `webui/dist` artifact through the real aiohttp HTTP and WebSocket routes. Runtime invalidations remain projections; the browser re-reads authoritative HTTP snapshots.

The LAN lifecycle now waits for the shutdown coroutine and background server thread to finish naturally. Each restart builds a fresh aiohttp application for the new event loop, while the runtime realtime bridge closes and recreates its single subscription during cleanup/startup.

### Design Decisions

- We use real server shutdown/restart as the disconnect control because the Python Playwright WebSocket observer is observational and does not expose an active close operation.
- We reuse the browser origin and port for replacement servers so recovery exercises the same transport and SPA state.
- We keep authentication cookie-only in acceptance tests; query credentials are not used for realtime admission.

## Usage

Run the focused browser and realtime gate from the repository root:

```powershell
python -m pytest tests/lan/test_runtime_realtime.py tests/e2e/test_webui_realtime_acceptance.py -q
```

The suite requires Python Playwright/Chromium and a current production build in `webui/dist`.

## Verification

Fresh verification completed in this workspace:

| Gate | Result |
|---|---|
| `python -m pytest tests/lan/test_runtime_realtime.py tests/e2e/test_webui_realtime_acceptance.py -q` | **18 passed** |
| `npm test -- --run` from `webui` | **34 files, 251 tests passed** |
| `npm run typecheck` from `webui` | **passed** |
| `npm run build` from `webui` | **passed**, 1626 modules transformed |
| Focused LAN Ruff gate | **All checks passed** |
| Scoped `git diff --check` | **passed** |

The broader WebUI suite still prints pre-existing React Router future-flag warnings; they do not fail the tests.

## Journey Log

- [dead end] An initial stop implementation stopped the event loop while `_startup()` was still unwinding, producing `Event loop stopped before Future completed`.
- [pivot] Shutdown now waits for natural thread exit, and restart creates a new aiohttp application bound to the new event loop.
- [lesson] Browser realtime acceptance must verify visible authoritative state after mutation, transport interruption, and runtime epoch replacement; a successful socket connection alone is insufficient.

## Source Materials

| File | Role | Notes |
|---|---|---|
| `docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-design.md` | Architecture specification | Runtime, cursor, and realtime boundaries |
| `docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-migration.md` | Implementation plan | Task 14 acceptance requirements |
| `tests/e2e/test_webui_realtime_acceptance.py` | Browser harness | Real Chromium scenarios |
| `tests/lan/test_runtime_realtime.py` | Runtime bridge tests | Isolation and lifecycle coverage |
| `AssetsManager/lan/server.py` | Server lifecycle | Shutdown and restart behavior |
| `AssetsManager/lan/api.py` | Realtime bridge | Subscription and cleanup lifecycle |
