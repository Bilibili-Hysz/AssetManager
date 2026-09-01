# Day 6 Real LAN Acceptance Retest

> Date: 2026-07-27
> Scope: Task 4 Step 6–7 from the weekly stability plan: retest P0/P1 findings or explicit blockers.
> Worktree: `.worktrees/grid-zoom-interpolation-fix`
> Branch: `fix/grid-zoom-interpolation`

## Status

All automatable journeys from Day 4–5 passed on retest. No new failures introduced. Blocked items remain environmental limitations.

## Environment

- Python: `3.14.3`
- Node.js: `v24.14.0`
- npm: `11.9.0`
- Browser: Microsoft Edge headless Chromium via Playwright
- Host network: One active WLAN IPv4 interface

## Retest Procedure

Re-executed the full Day 4–5 browser harness with temporary library, temporary SQLite database, and OS-assigned unique port. The harness bound to `0.0.0.0` and navigated via the host WLAN address.

## Retest Results

| Journey | Result | Evidence |
| --- | --- | --- |
| Guest browse root | PASS | `/api/files` returned 200 with nested directory |
| Password login and cookie refresh | PASS | HttpOnly `lan_token` set; `/api/auth/me` 200 before and after reload |
| Browse/search/metadata/tags/thumbnail | PASS | All endpoints returned 200 |
| Single-file and ZIP download | PASS | Playwright captured real download; batch returned ZIP Blob |
| Viewer role denied share management | PASS | `viewer` received 403 on share creation |
| Password share URL, scope, and cookie | PASS | 401 before verify; scoped 200 after; out-of-scope 403 |
| Two contexts + WebSocket | PASS | Both cookie-authenticated `/ws` opened without query token |
| Offline/online recovery | PASS | Offline rejected fetch; online restoration returned 200 |
| Mobile viewport | PASS (emulated) | `390x844` touch context loaded successfully |
| Same-instance restart + browser recovery | PASS | Stopped and restarted same `LanServer`; existing context reloaded and `/api/auth/me` returned 200 |
| Legacy fallback | PASS | In-memory SPA absence stub served legacy static with 200 |

## Regression Test Confirmation

| Test | Result |
| --- | --- |
| `tests/lan/test_lan_api.py::test_lan_server_can_restart_the_same_instance_cleanly` | **PASS** (5.30s) |

## P0/P1 Status

| ID | Description | Status |
| --- | --- | --- |
| P0 | SPA retained JSON token in React state | **Closed** (Day 3 fix verified) |
| P1 | Same-instance `LanServer` restart failed | **Closed** (Day 4 fix; Day 6 retest confirmed) |
| P1 | Controlled shutdown emitted event-loop exception | **Closed** (Day 4 fix; Day 6 retest confirmed) |

## Blocked Items (unchanged)

| Item | Reason |
| --- | --- |
| Physical second LAN client | No controllable second physical device |
| Physical mobile browser | No controllable physical mobile device |
| QR visual rendering/scanning | No physical scanner; no visual assertion in automation |
| Host sleep/wake | Not attempted |
| Desktop GUI share toggle/workspace switch/Qt close | No GUI automation available |

## Automated Gates (Day 6)

| Gate | Result |
| --- | --- |
| `python -m ruff check .` | PASS |
| `python -m pyright` | PASS (`0 errors`) |
| `python -m compileall AssetsManager -q` | PASS |
| `python -m pytest -q` | PASS (`1300 passed in 66.02s`) |
| `npm run typecheck` (webui) | PASS |
| `npm test` (webui) | PASS (`17 files, 67 tests passed`) |
| `npm run build` (webui) | PASS |
| `pytest tests/lan/test_lan_api.py tests/lan/test_path_guard.py -q` | PASS (`198 passed`) |
| `pytest tests/lan/test_t2_t4_contracts.py -q` | PASS (`4 passed`) |

## Changed Files

- `docs/compose/reports/2026-07-27-weekly-stability-closeout.md` (updated)
- This report: `docs/compose/reports/2026-07-28-real-lan-acceptance-day6.md`
