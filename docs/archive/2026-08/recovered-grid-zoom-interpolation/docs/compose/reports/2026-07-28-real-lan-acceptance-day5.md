# Day 5 Real LAN Browser Acceptance

> Date: 2026-07-27
> Scope: Task 4 Step 2–5 from the weekly stability plan: browser/share/mobile journeys, WebSocket recovery, lifecycle, and legacy fallback.
> Worktree: `.worktrees/grid-zoom-interpolation-fix`
> Branch: `fix/grid-zoom-interpolation`

## Status

Partial. All automatable journeys passed. Physical-client, desktop-GUI, and sleep/wake journeys remain blocked.

## Available Environment

| Capability | Observed result | Classification |
| --- | --- | --- |
| Host network | One active WLAN IPv4 interface; harness bound `0.0.0.0` and Edge navigated through WLAN address. | Available |
| Browser automation | Python Playwright installed; Microsoft Edge launched as headless Chromium. | Available |
| Browser clients | Two isolated Edge browser contexts available. | Available |
| Mobile browser | Playwright mobile viewport/touch emulation available. | Available as emulation only |
| Second physical LAN client | No controllable second physical device. | **Blocked** |
| Physical mobile device/browser | No controllable physical mobile device. | **Blocked** |
| Host sleep/wake | Not attempted. | **Blocked** |
| Desktop GUI controls | Real desktop share toggle, workspace switch, and full Qt close not driven. | **Blocked** |

## Procedure and Evidence

The harness used a temporary library, temporary thumbnail directory, temporary SQLite database, and OS-assigned unique port under the system temporary directory. All temporary files were deleted after each run.

### Step 2: Browser and permission journeys

| # | Journey | Result | Evidence |
| --- | --- | --- | --- |
| 1 | Start sharing from the active desktop library | **PASS** | `LanServer` facade started on `0.0.0.0` with random port; `is_running() == true` |
| 2 | Open the LAN URL from a second client | **Blocked** | No second physical device; two isolated browser contexts on one host were used instead |
| 3 | Login and refresh the page to restore the Cookie-authenticated session | **PASS** | Password login set HttpOnly `lan_token`; `/api/auth/me` returned 200 before and after reload |
| 4 | Browse root and nested project; open detail; load tags, metadata, and thumbnail | **PASS** | `/api/files`, `/api/files?path=nested`, `/api/meta/nested/detail.txt`, `/api/tags`, `/api/search?q=detail`, `/api/thumbnails/nested/preview.png?size=32` all returned HTTP 200 |
| 5 | Search a known sample file | **PASS** | Search query returned matching results |
| 6 | Download one file | **PASS** | Playwright captured a real browser download |
| 7 | Download two files as a ZIP | **PASS** | Batch POST returned nonempty ZIP Blob with `application/zip` content type |
| 8 | Verify guest, registered-user, and admin permissions | **PASS** | Guest browse 200; registered `viewer` received 403 on share management; admin created password share successfully |

### Step 3: Password-share and mobile journeys

| # | Journey | Result | Evidence |
| --- | --- | --- | --- |
| 1 | Create a password-protected share for nested/project | **PASS** | Share creation returned 200; URL had no query credential |
| 2 | Open the copied URL from a separate browser/mobile device | **Blocked** | No second physical device; opened in independent browser context instead |
| 3 | Enter the share password | **PASS** | Verify POST returned 200 |
| 4 | Confirm only the scoped project is visible | **PASS** | Scoped file downloaded (200); out-of-scope file returned 403 |
| 5 | Preview and download an allowed file | **PASS** | Download succeeded after verification |
| 6 | Confirm an out-of-scope path cannot be reached | **PASS** | Out-of-scope path returned 403 |

### Step 4: WebSocket recovery and lifecycle journeys

| # | Journey | Result | Evidence |
| --- | --- | --- | --- |
| 1 | Open two authenticated browser clients | **PASS** | Two isolated contexts both authenticated via cookie |
| 2 | Trigger a benign server event or navigate on both clients | **PASS** | Both clients navigated and fetched successfully |
| 3 | Disable and restore one client's network for less than 30 seconds | **PASS** | Playwright offline mode rejected fetch; online restoration returned 200 |
| 4 | Observe bounded reconnect behavior | **PASS** | WebSocket reconnect capped at one attempt; no unbounded retry observed |
| 5 | Stop sharing from the desktop app | **Blocked** | No desktop GUI; controlled harness `stop()` returned and `is_running() == false` |
| 6 | Start sharing again, switch to another library, then close the desktop app | **Blocked** | No desktop GUI; same-instance restart passed in controlled harness with browser recovery |

### Step 5: Legacy fallback

| Journey | Result | Evidence |
| --- | --- | --- |
| Browse -> login when configured -> open share -> download | **PASS** | Legacy static fallback served `/` with HTTP 200 when SPA build was temporarily absent; no `.bak`/`.bak2` resources exposed |

## Journey Matrix

| Journey | Result | Evidence / limitation |
| --- | --- | --- |
| Start a temporary LAN share | PASS | Real `LanServer` facade; unique port; `0.0.0.0` bind |
| Guest browse root | PASS | Separate no-auth instance; real browser `/api/files` returned root contents |
| Password login and cookie refresh | PASS | Real browser login, HttpOnly auth cookie, `/api/auth/me`, reload restoration |
| Root/nested/detail/metadata/tags/search/thumbnail | PASS | Browser fetches all returned HTTP 200 |
| Single-file download | PASS | Playwright received real browser download |
| Batch Blob/ZIP download | PASS | Browser POST received nonempty ZIP Blob |
| Password share URL and scope | PASS | No query string on URL; 401 before verify; scoped 200 after; out-of-scope 403 |
| QR rendering/scanning | **BLOCKED** | URL contract checked; no QR visual assertion or physical scanner |
| Guest, viewer/user, admin roles | PASS | Guest browse, viewer share-management 403, admin share creation |
| Two browser clients and WebSocket | PASS | Two independent Edge contexts opened cookie-authenticated WebSockets |
| Brief network interruption | PASS | Offline/online browser-context emulation |
| Physical second LAN client | **BLOCKED** | No controllable second physical device |
| Physical mobile browser | **BLOCKED** | Mobile viewport is emulation only |
| Sleep/wake | **BLOCKED** | Not attempted |
| Stop share | PASS (harness) | Controlled harness `stop()` returned; not desktop GUI |
| Restart same server instance | PASS | Same-instance restart with browser recovery |
| Desktop share toggle/workspace switch/full Qt close | **BLOCKED** | No real desktop GUI driven |
| Legacy fallback | PASS | Real Edge received legacy static fallback |

## Findings

### P0

- None observed.

### P1

- None observed. The lifecycle repair resolved the former same-instance restart failure.

### P2

- Real-browser coverage uses two isolated contexts on one host, not a second physical device.
- Mobile coverage is `390x844` touch emulation only.
- QR rendering and scanning were not visually asserted.

### Blocked

- Physical second LAN client and physical mobile browser require available devices.
- Sleep/wake requires an explicitly approved environment.
- Desktop share toggle, workspace switch, and full Qt close require an actual GUI acceptance session.

## Release Impact

All automatable journeys pass, including the previously failing same-instance server restart with browser recovery. The blocked journeys are explicitly environmental limitations, not product defects. However, they remain required for a complete release-ready conclusion.

## Changed Files

- `docs/compose/reports/2026-07-27-weekly-stability-closeout.md` (updated)
- This report: `docs/compose/reports/2026-07-28-real-lan-acceptance-day5.md`
