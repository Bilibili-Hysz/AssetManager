# Desktop–LAN–WebUI Architecture Migration — Final Report

**Status:** Phase 5 complete through Task 17

**Plan:** `docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-migration.md`

**Spec:** `docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-design.md`

## Outcome

The migration now has one canonical `LibrarySession`/`LibraryRuntime` ownership
path across Desktop and LAN. LAN construction is runtime-only, routes consume
`SessionPrincipal` and explicit capabilities, public responses use DTO
contracts, and React realtime recovery is driven by `epoch + revision` followed
by authoritative HTTP refetches.

Migration factories and request-user dictionary adapters were removed from
production. LAN server shutdown closes its own WebSocket/site/scanner resources
without closing the injected runtime; session/runtime teardown remains owned by
`ApplicationBootstrap` and `LibraryService`.

## Verification evidence

| Gate | Command | Result |
|---|---|---|
| Full Python | `python -m pytest -q` | `1427 passed, 1 skipped` |
| WebUI typecheck | `npm --prefix webui run typecheck` | Passed |
| WebUI tests | `npm --prefix webui test -- --run` | `34 files, 251 passed` |
| WebUI production build | `npm --prefix webui run build` | Vite build passed; 1626 modules transformed |
| Packaging | `python -m pytest tests/core/test_packaging_entrypoints.py tests/core/test_package_contents.py -q` | `8 passed` |
| LAN/browser acceptance | `python -m pytest tests/lan/test_runtime_realtime.py tests/e2e/test_webui_realtime_acceptance.py -q` | `18 passed` |
| Focused contract repair | `python -m pytest tests/lan/test_t2_t4_contracts.py::test_websocket_valid_query_key_does_not_authenticate_a_connection tests/lan/test_t2_t4_contracts.py::test_lan_preview_and_download_require_their_explicit_permissions tests/lan/test_t2_t4_contracts.py::test_lan_server_rejects_connection_for_a_different_library_root -q` | `3 passed` |

The single skipped Python test requires directory symlinks, which are
unavailable on this Windows environment. No test failure remains.

## Cross-surface acceptance

The real Chromium harness served the production `webui/dist` artifact through
the real aiohttp HTTP and WebSocket routes and verified:

- Desktop-created folders become visible in the browser without a reload.
- A real WebSocket/server interruption followed by same-port restart recovers
  the revision gap and displays mutations made while disconnected.
- Closing and reopening the same library root creates a new runtime epoch; the
  browser receives the new authoritative state after reconnect.
- The LAN server restarts cleanly on the same port and its background thread is
  no longer alive after teardown.
- Query-string token/key credentials do not authenticate WebSocket connections.
- Preview/download permissions are enforced by canonical principal
  capabilities, while path traversal is rejected at the LAN boundary.

## Teardown and isolation evidence

- Runtime realtime tests cover subscription replacement, server shutdown,
  missed-event recovery, library switching, and closed-session rejection.
- `LanServer.stop()` waits for the server thread and closes WebSocket/site and
  scanner resources; it does not close the injected runtime.
- Runtime providers are checked against their owning `LibrarySession`.
- Wrong-root connection requests fail before a route can use a mismatched
  database connection.
- Architecture gates reject production LAN legacy factories, route-level
  service construction, legacy request-user adapters, and page-level direct
  WebSocket consumption.

## Documentation and packaging

Updated architecture truth is recorded in:

- `docs/architecture.md`
- `docs/architecture-diagram.md`
- `docs/adr/0003-library-runtime.md`
- `AssetManager.spec`

The PyInstaller manifest explicitly includes the canonical runtime, runtime
event router, LAN DTO, and LAN principal modules.

## Residual risks and rollback notes

- The Windows test environment cannot execute the directory-symlink integration
  case; Linux CI should retain that case as a required platform gate.
- React Router emits existing v7 future-flag warnings in some tests; they do
  not fail typecheck, tests, or the production build.
- The system remains a modular monolith. Independent-service extraction should
  not begin until runtime ownership, session teardown, DTO contracts, and
  authoritative HTTP projection recovery remain stable across a production
  release.
- Roll back the migration if a release shows an authorization bypass, wrong-root
  response, stale-session mutation, unrecoverable reconnect loop, leaked
  runtime subscription, fabricated telemetry, or a packaging import failure.

## Completion decision

All executable Task 17 gates passed with fresh evidence. No commit or release
operation was performed because the workspace contains unrelated user changes
and explicit commit authorization was not provided.
