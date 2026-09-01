# Day 4 Real LAN Browser Acceptance

## Status

Partial. The available real-browser journeys, including controlled same-instance server restart and browser session recovery, passed after the lifecycle repair. Physical-client and desktop-GUI journeys were not available and are explicitly blocked below.

## Scope And Safety

- Worktree: `.worktrees/grid-zoom-interpolation-fix`.
- This acceptance created no application, frontend, test, dependency, lockfile, or existing Day 2/3 documentation changes.
- The only intended repository artifact is this report.
- The harness used a unique OS-assigned port, a temporary library, temporary thumbnail directory, and temporary SQLite database under the system temporary directory. It deleted those temporary files after every run.
- The report intentionally omits passwords, credentials, tokens, share credentials, and private absolute paths.
- `webui npm run build` passed before SPA-browser acceptance. It produced the existing ignored production asset output; no tracked source, dependency, or lockfile was changed.

## Available Environment

| Capability | Observed result | Classification |
| --- | --- | --- |
| Host network | One active WLAN IPv4 interface was present; the harness bound `0.0.0.0` and Edge navigated through that WLAN address. | Available |
| Browser automation | Python Playwright was installed. Microsoft Edge was installed and launched as headless Chromium. | Available |
| Browser clients | Two isolated, real Edge browser contexts were available. They are independent browser sessions, not two physical LAN devices. | Available |
| Mobile browser | Playwright mobile viewport/touch emulation was available. | Available as emulation only |
| Second physical LAN client | No discoverable or controllable second physical client was available. | Blocked |
| Physical mobile device/browser | No discoverable or controllable physical mobile device was available. | Blocked |
| Host sleep/wake | Not attempted; the acceptance constraint prohibits sleeping the host. | Blocked |
| Desktop GUI controls | The real desktop share toggle, workspace switch, and full Qt close were not driven. | Blocked |

## Procedure And Evidence

The browser harness started temporary instances through the public `LanServer` facade, which constructs the real `_LanServerImpl`. It bound each instance to `0.0.0.0` on an OS-assigned unique port. All browser navigation used the WLAN address rather than loopback.

### Evidence Boundaries

- **Automated real-browser evidence:** all browse, login, reload, download, share, WebSocket, offline/online, mobile-viewport, and legacy fallback observations in this report were exercised through Microsoft Edge browser contexts over the WLAN address.
- **Controlled server-lifecycle evidence:** start, stop, and same-instance restart observations were made through the public `LanServer` facade in the temporary harness. They are not desktop-GUI share-toggle evidence.
- **Standalone HTTP-harness evidence:** none was used as an acceptance result in this report. Browser `fetch` calls remain automated browser evidence, and aiohttp unit/contract tests remain Day 3 evidence rather than Day 4 acceptance evidence.
- **Physical/manual evidence:** no second physical client, physical mobile device, host sleep/wake, or desktop GUI workflow was available; those journeys remain blocked in the matrix.

The first browser run established these automated real-browser results:

- SPA root loaded over the WLAN address: HTTP 200.
- A separate unauthenticated server instance allowed the configured guest root browse journey: `/api/files` returned the temporary nested directory.
- On the password-protected instance, password login set an HttpOnly `lan_token` cookie. Cookie-authenticated `/api/auth/me` succeeded before and after a browser reload.
- The authenticated browser exercised root and nested browsing, detail metadata, tags, search, and an image thumbnail endpoint. Each returned HTTP 200.
- An actual browser download was initiated for one file. A batch POST returned a nonempty ZIP Blob with a ZIP content type.

The follow-up browser runs established these automated real-browser results:

- A registered non-admin account was returned with the server's `viewer` role and received HTTP 403 when attempting share management. The harness does not rename that actual server role to `user`.
- An admin/password context created a password-protected share limited to the nested directory. The returned share URL had no query string. In the independent context, download was HTTP 401 before password verification, the verify JSON did not include a token, the scoped nested file downloaded successfully afterward, and an in-library file outside scope returned HTTP 403. The working post-verification download is browser evidence that the scoped share cookie was sent. The cookie is configured HttpOnly and is not exposed to JavaScript.
- Two isolated browser contexts each authenticated through cookies and opened `/ws` successfully without query credentials.
- Playwright's browser-context offline mode made `fetch('/api/files')` reject; after online restoration, the same request returned HTTP 200. This is browser network emulation, not a physical LAN interruption.
- A `390x844` touch/mobile browser context loaded the SPA successfully. This is viewport emulation, not a physical mobile device.
- With `pages.SPA_DIR` temporarily redirected only in the in-memory Python harness to a missing location, real Edge loaded `/` from the legacy static fallback with HTTP 200. No repository file was renamed or modified.

The post-repair rerun established these automated real-browser results:

- The temporary unauthenticated instance served guest root browsing over the host WLAN address.
- A password-authenticated Edge context retained its HttpOnly session through reload, then remained authenticated after the same `LanServer` instance was stopped and restarted on the same port.
- The same rerun revalidated nested browsing, metadata, tags, search, thumbnails, browser download, ZIP download, viewer share-management denial, password-share scope, two cookie-authenticated WebSockets, offline/online emulation, and mobile viewport emulation.

## Journey Matrix

| Journey | Result | Evidence / limitation |
| --- | --- | --- |
| Start a temporary LAN share | PASS | Real `LanServer` facade and `_LanServerImpl`; unique port; `0.0.0.0` bind; Edge used WLAN address. |
| Guest browse root | PASS | Separate no-auth temporary server; real browser `/api/files` returned root contents. |
| Password login and cookie refresh | PASS | Real browser login, HttpOnly auth cookie observation, `/api/auth/me`, and reload restoration succeeded. |
| Root/nested/detail/metadata/tags/search/thumbnail | PASS | Browser fetches all returned HTTP 200. |
| Single-file download | PASS | Playwright received a real browser download. |
| Batch Blob/ZIP download | PASS | Browser POST received a nonempty ZIP Blob. |
| Password share URL and scope | PASS | No query string on returned URL; 401 before verify; scoped download 200 after verify; outside-scope file 403. |
| QR rendering/scanning | BLOCKED | URL contract was checked, but no QR visual assertion or physical scanner was available. |
| Guest, viewer/user, admin roles | PASS | Guest browse, server-returned `viewer` share-management denial, and password-admin share creation were browser-verified. |
| Two browser clients and WebSocket | PASS | Two independent Edge contexts opened cookie-authenticated WebSockets. They are not physical clients. |
| Brief network interruption | PASS | Offline/online browser-context emulation rejected then recovered `fetch`; not a physical LAN outage. |
| Physical second LAN client | BLOCKED | No controllable second physical device was available. |
| Physical mobile browser | BLOCKED | Mobile viewport result is emulation only; no physical mobile device was available. |
| Sleep/wake | BLOCKED | Host sleep was intentionally not driven. |
| Stop share | PASS | Controlled harness `stop()` returned and `is_running()` became false. |
| Restart same server instance | PASS | Controlled real-browser rerun stopped and restarted the same `LanServer` facade instance on the same port; the existing browser context reloaded successfully and `/api/auth/me` returned HTTP 200. |
| Desktop share toggle/workspace switch/full Qt close | BLOCKED | No real desktop GUI was driven. |
| Legacy fallback | PASS | Real Edge received legacy static root fallback after in-memory-only SPA-path override. |

## Server And Browser Logs

### Automated Browser Evidence

- `guest_root_browse_over_wlan`: PASS.
- `password_login_httpOnly_cookie_refresh_reload`: PASS.
- `root_nested_detail_metadata_tags_thumbnail_search`: PASS.
- `single_and_zip_download`: PASS.
- `viewer_role_share_management_restricted`: PASS.
- `password_share_url_scope_and_httpOnly_cookie`: PASS; QR visual rendering unasserted.
- `two_isolated_browser_contexts_cookie_websocket`: PASS.
- `short_network_interruption`: PASS; Playwright offline/online emulation.
- `mobile_viewport`: PASS; browser emulation only.
- `legacy_browser_fallback`: PASS.
- `same_instance_restart_browser_recovery`: PASS after lifecycle repair; the existing Cookie-authenticated Edge context reloaded and restored `/api/auth/me` over the WLAN address.

### Controlled Lifecycle Log

The post-repair rerun stopped the protected `LanServer` facade, confirmed `is_running() == false`, restarted that same object on the same OS-assigned port, and navigated the original authenticated Edge context back to the WLAN URL. Root navigation and Cookie-authenticated `/api/auth/me` both returned HTTP 200. No `web.Application instance initialized with different loop` or `Event loop stopped before Future completed` diagnostic was emitted during this run.

The port number and all temporary filesystem locations are intentionally redacted or omitted.

## Findings

### P0

- None observed in this Day 4 real-browser acceptance.

### P1

- No P1 issue was observed in the post-repair controlled lifecycle or real-browser rerun. The former same-instance restart and forced-event-loop-stop failures are resolved by the current lifecycle implementation and covered by the rerun evidence above.

### P2

- The real-browser browser-client coverage uses two isolated contexts on one host. It proves cookie isolation and WebSocket behavior but does not establish behavior from a second physical LAN device.
- Mobile coverage is a `390x844` touch emulation only. QR rendering and scanning were not visually asserted.

### Deferred / Blocked

- Physical second LAN client and physical mobile browser acceptance require available devices.
- Sleep/wake requires an explicitly approved environment that can suspend and resume the host.
- Desktop share toggle, workspace switch, and full Qt close require an actual GUI acceptance session; they were deliberately not automated here.

## Release Impact

The browser-facing LAN flows that were executable in a safe temporary environment have substantial real-browser evidence, including real WLAN navigation, HttpOnly-cookie session restoration, downloads, scoped password share behavior, legacy fallback, cookie-authenticated WebSockets, and same-instance restart with browser recovery. This does **not** support a fully release-ready conclusion: physical/manual required journeys remain blocked rather than inferred as pass. Complete those journeys before release sign-off.

## Final Repository Checks

The following checks were run after acceptance:

```powershell
git diff --check
```

`git diff --check` completed without whitespace errors. The worktree retains pre-existing frontend and Day 2/3 documentation changes; this Day 4 report is the only file created by this acceptance.
