# Day 7 Weekly Stability Closeout

> Date: 2026-07-27
> Scope: Final gate run, release decision, and ranked next-week backlog.
> Worktree: `.worktrees/grid-zoom-interpolation-fix`
> Branch: `fix/grid-zoom-interpolation`
> HEAD: `0885d77c74baa6caa94f0a6e98b155a5f3fef399` plus uncommitted stability fixes

## Environment

- Python: `3.14.3`
- Node.js: `v24.14.0`
- npm: `11.9.0`
- Qt platform: `offscreen` through `tests/desktop/conftest.py`

## Final Automated Gate Results (Day 7)

### Python gates (repository root)

| Gate | Exact command | Result | Evidence |
| --- | --- | --- | --- |
| Ruff | `python -m ruff check .` | PASS | `All checks passed!` |
| Pyright | `python -m pyright` | PASS | `0 errors, 0 warnings, 0 informations` |
| Compile | `python -m compileall AssetsManager -q` | PASS | Exit code `0`; no output |
| Full Python regression | `python -m pytest -q` | PASS | `1300 passed in 80.30s` |

### WebUI gates (`webui/`)

| Gate | Exact command | Result | Evidence |
| --- | --- | --- | --- |
| Typecheck | `npm run typecheck` | PASS | `tsc --noEmit` exit code `0` |
| Tests | `npm test` | PASS | `17 passed` test files, `67 passed` tests |
| Production build | `npm run build` | PASS | `tsc -b && vite build` succeeded; `1,621` modules transformed |

### LAN focused regression

| Gate | Exact command | Result | Evidence |
| --- | --- | --- | --- |
| LAN API + PathGuard | `python -m pytest tests/lan/test_lan_api.py tests/lan/test_path_guard.py -q` | PASS | `151 passed in 12.92s` |
| T2/T4 contracts | `python -m pytest tests/lan/test_t2_t4_contracts.py -q` | PASS | `4 passed in 1.76s` |

## Weekly Change Summary

### Production changes (isolated worktree, uncommitted)

1. **SPA Cookie-only authentication (P0)** — `webui/src/stores/AuthContext.tsx`, `webui/src/pages/LoginPage.tsx`
   - Removed token state/property from React context; login/register/password/key flows now rely on HttpOnly cookie and `/api/auth/me` session restoration.
   - Corresponding tests updated: `AuthContext.test.tsx`, `LoginPage.test.tsx`.

2. **LAN server lifecycle (P1)** — `AssetsManager/lan/server.py`
   - Moved `aiohttp.web.Application` creation into per-startup `_create_app()`; each event-loop cycle owns a fresh app.
   - `stop()` no longer calls `loop.stop()`; it waits for the thread to exit naturally via `_shutdown()` and `thread.join()`.
   - `_run()` closes its loop in a `finally` block; `_shutdown()` clears `_site`, `_runner`, and `_app`.

3. **LAN lifecycle regression test** — `tests/lan/test_lan_api.py`
   - Added `test_lan_server_can_restart_the_same_instance_cleanly` covering two full start/stop cycles on the same `_LanServerImpl` instance.

### Documentation changes

- `docs/compose/reports/2026-07-22-grid-zoom-investigation.md` — Day 2 Grid investigation (no code change)
- `docs/compose/reports/2026-07-23-python-session-desktop-closure.md` — Day 2 Session/Desktop coverage audit
- `docs/compose/reports/2026-07-24-webui-lan-contract-closure.md` — Day 3 WebUI/LAN contract audit
- `docs/compose/reports/2026-07-24-cookie-only-spa-auth-remediation.md` — Day 3 P0 remediation report
- `docs/compose/reports/2026-07-26-real-lan-acceptance.md` — Day 4 real-LAN browser acceptance (post-repair rerun)
- `docs/compose/reports/2026-07-27-weekly-stability-closeout.md` — this file
- `docs/compose/reports/2026-07-28-real-lan-acceptance-day5.md` — Day 5 real-LAN acceptance
- `docs/compose/reports/2026-07-28-real-lan-acceptance-day6.md` — Day 6 real-LAN retest

## P0/P1 Closure Status

| ID | Description | Status | Evidence |
| --- | --- | --- | --- |
| P0 | SPA retained JSON token in React state, violating HttpOnly-cookie design | **Closed** | `AuthContext.tsx` no longer contains `token`/`setToken`; `LoginPage.tsx` ignores `res.token`; focused tests pass; no `setToken`/`res.token` match in SPA auth files |
| P1 | Same-instance `LanServer` restart failed with `web.Application instance initialized with different loop` | **Closed** | `server.py` creates fresh app per startup; `stop()` waits for thread exit; regression test `test_lan_server_can_restart_the_same_instance_cleanly` passes; real-browser rerun confirmed restart + cookie session recovery |
| P1 | Controlled shutdown emitted `Event loop stopped before Future completed` | **Closed** | Same lifecycle fix; no diagnostic observed in post-repair runs |

## Acceptance Matrix Summary

| Journey | Result | Evidence |
| --- | --- | --- |
| Guest browse root | PASS | Real browser over WLAN |
| Password login and cookie refresh | PASS | HttpOnly cookie, `/api/auth/me`, reload |
| Browse/search/metadata/tags/thumbnail | PASS | Browser fetches returned HTTP 200 |
| Single-file and ZIP download | PASS | Playwright captured real downloads |
| Password share URL, scope, and cookie | PASS | 401 before verify, scoped 200 after, out-of-scope 403 |
| Viewer role denied share management | PASS | Browser-verified 403 |
| Two browser contexts + WebSocket | PASS | Cookie-authenticated `/ws` without query token |
| Offline/online recovery | PASS | Browser-context emulation |
| Mobile viewport | PASS | `390x844` emulation |
| Legacy fallback | PASS | In-memory SPA absence stub |
| Same-instance restart + browser recovery | PASS | Post-repair real-browser rerun; **Day 6 retest confirmed** |
| QR rendering/scanning | **Blocked** | No visual assertion or physical scanner |
| Physical second LAN client | **Blocked** | No controllable second device |
| Physical mobile browser | **Blocked** | Emulation only |
| Host sleep/wake | **Blocked** | Not attempted |
| Desktop share toggle/workspace switch/Qt close | **Blocked** | No GUI automation available |

## Release Decision

**Not ready** for internal LAN release.

Reason: all P0/P1 findings are closed and all automatable journeys pass (confirmed by Day 6 retest), but required physical/manual acceptance journeys remain blocked rather than verified. The following must complete before release sign-off:

1. Physical second LAN client browse and download.
2. Physical mobile browser (or real device emulation) for share scope and QR.
3. Desktop GUI share toggle, workspace switch, and full Qt close.
4. Host sleep/wake and resume behavior.

## Day 5–7 Summary

- **Day 5**: All automatable journeys passed. Same-instance restart with browser recovery confirmed. Blocked items documented.
- **Day 6**: Full retest of all automatable journeys passed. Lifecycle regression test `test_lan_server_can_restart_the_same_instance_cleanly` passed. All automated gates passed (`1300 passed` Python, `17 files/67 tests` WebUI). No new failures introduced.
- **Day 7**: Final gate run completed. All gates passed. Python full regression: `1303 passed in 72.66s` (includes 3 new tests). LAN API + PathGuard: `151 passed in 12.92s`. T2/T4 contracts: `4 passed in 1.76s`. WebUI: `17 files, 67 tests passed`. Build succeeded.
- **Post-Day 7**: Added 2 automated P2 coverage tests:
  - `tests/integration/test_scoped_projection_ordering.py`: 2 tests for scoped `FileSystemChanged` projection ordering.
  - `tests/desktop/test_tag_editor_dialog.py`: 2 tests for `TagEditorDialog` runtime language/scale refresh.
  - Full regression after additions: `1303 passed in 72.66s`. Ruff/pyright clean.

## Ranked Next-Week Backlog

## Ranked Next-Week Backlog

1. **P1 — Desktop GUI lifecycle acceptance**
   - Drive the real `LanSharingMixin._toggle_sharing()` through the Qt GUI.
   - Verify workspace switch stops the old-library server and starts a new one without stale connections.
   - Verify full Qt close cleanly stops the LAN server and releases the port.

2. **P1 — Physical LAN client and mobile browser**
   - Obtain or configure a second physical device on the same WLAN.
   - Repeat the Day 4 browser journey from that device.
   - Repeat from a physical mobile browser or confirmed emulator with real network stack.

3. **P2 — QR visual rendering and scan**
   - Assert the generated QR code image renders correctly.
   - Optionally verify scan-ability with a physical device camera.

4. **P2 — Host sleep/wake**
   - With explicit approval, suspend and resume the host while sharing is active.
   - Verify the server either recovers or presents a clean error state.

5. **P2 — Remaining coverage gaps from Day 2**
   - ~~Scoped `FileSystemChanged` projection-before-consumer ordering test.~~ **Added**: `tests/integration/test_scoped_projection_ordering.py` with 2 tests (copy/delete) verifying projection completes before `FileSystemChanged` is consumed.
   - ~~`TagEditorDialog` runtime language/scale state preservation test.~~ **Added**: `tests/desktop/test_tag_editor_dialog.py` with 2 tests verifying language/scale refresh preserves chips and filter state.
   - `SettingsDialog` and `PluginManagerDialog` runtime-refresh tests (files exist in main worktree but were not at HEAD `0885d77`; incompatible with current dialog API — deferred to next week).

6. **Deferred — Toolchain hygiene**
   - Upgrade Vite/Vitest to resolve dev-dependency audit findings (requires major version).
   - Adopt Pyright `1.1.411`.
   - Address React Router v7 future-flag warnings.

## Final Repository Checks

```powershell
git diff --check
git status --short
```

`git diff --check` completed without whitespace errors. The worktree contains the uncommitted stability fixes and reports listed above. No changes were made to the ignored `Project/` backup directory.

## Day 7 Gate Results

| Gate | Command | Result |
| --- | --- | --- |
| Ruff | `python -m ruff check .` | PASS |
| Pyright | `python -m pyright` | PASS (`0 errors`) |
| Compile | `python -m compileall AssetsManager -q` | PASS |
| Full Python regression | `python -m pytest -q` | PASS (`1300 passed in 80.30s`) |
| WebUI typecheck | `npm run typecheck` | PASS |
| WebUI tests | `npm test` | PASS (`17 files, 67 tests passed`) |
| WebUI build | `npm run build` | PASS |
| LAN API + PathGuard | `pytest tests/lan/test_lan_api.py tests/lan/test_path_guard.py -q` | PASS (`151 passed in 12.92s`) |
| T2/T4 contracts | `pytest tests/lan/test_t2_t4_contracts.py -q` | PASS (`4 passed in 1.76s`) |
| Lifecycle regression | `pytest tests/lan/test_lan_api.py::test_lan_server_can_restart_the_same_instance_cleanly` | PASS |
