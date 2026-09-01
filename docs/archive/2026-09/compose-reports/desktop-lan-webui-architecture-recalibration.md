---
feature: desktop-lan-webui-architecture-recalibration
status: delivered
specs:
  - docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-recalibration-design.md
plans:
  - docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-recalibration.md
branch: master
commits: 77492fe2b3ee9e4bb26e17b982d421993d545136, 945fd1e51a85ce2384f277c1bb9e89396b8fbe7d
evidence_state: tested against the then-current working tree; product baseline captured separately
---

# Desktop–LAN–WebUI Architecture Recalibration — Final Report

## What Was Built

Task E executed the final Windows and Linux release gates for the recalibrated
Desktop–LAN–WebUI architecture. Fresh evidence now covers real Chromium
mutation refresh, WebSocket revision-gap recovery, same-port restart,
same-root reopen, cookie logout, 401 identity teardown, LAN-to-Desktop
projection refresh, authorization and path guards, failed-stop retry, and
session close with an active WebSocket.

The WebUI logout journey exposed a real stacking defect: the account menu was
visible but the browse toolbar intercepted pointer events over its Logout item.
The Header wrapper now establishes an explicit `relative z-20` stacking
boundary in `webui/src/components/layout/AppLayout.tsx`, and the real
Chromium logout test covers the regression.

The final release decision is `delivered`. All executable Windows gates passed,
and the directory-symlink case passed in the Ubuntu WSL Linux environment with
an isolated RuntimeData root.

## Architecture

The verified cross-surface path is:

```text
Desktop or LAN mutation
  → session-scoped domain event
  → RuntimeEventRouter / Qt domain-event bridge
  → authenticated WebSocket invalidation or Desktop panel refresh
  → authoritative HTTP/SQLite/filesystem projection
```

Runtime ownership remains canonical:

```text
LibrarySession
  → ApplicationBootstrap.runtime_for(session)
  → LibraryRuntime.services
  → Desktop panels and LanServer adapters
```

Browser identity remains cookie-only. Logout and 401 both advance the identity
generation, clear the guest projection, replace the realtime transport, and
leave no active WebSocket connection. LAN contract tests cover password,
access-key, user, guest and share authorization; the real browser acceptance
uses the local-UI cookie path.

## Design Decisions

- We record `delivered` because the required Linux directory-symlink gate passed
  with the project's supported PySide6 dependency range and isolated test data.
- We keep the real Chromium tests in the existing realtime acceptance harness;
  it already owns server startup, cookie setup, WebSocket connection counts,
  and same-root restart fixtures.
- We use a real LAN tag mutation for LAN→Desktop acceptance because it crosses
  the HTTP route, Runtime-bound service, domain EventBus, Qt bridge and Desktop
  projection in one journey.
- We fixed the Header/AppLayout stacking boundary after the browser test
  demonstrated that a visible logout control was not pointer-reachable.

## Usage

Run the complete current verification baseline:

```powershell
python -m pytest -q
npm --prefix webui test -- --run
npm --prefix webui run typecheck
npm --prefix webui run build
python -m pytest tests/core/test_packaging_entrypoints.py tests/core/test_package_contents.py -q
```

Run the Task E cross-surface slice:

```powershell
python -m pytest tests/e2e/test_webui_realtime_acceptance.py tests/desktop/test_file_list_shim.py tests/desktop/test_file_event_session_routing.py tests/desktop/test_tag_event_session_routing.py tests/lan/test_runtime_realtime.py tests/lan/test_server_lifecycle.py tests/integration/test_window_lifecycle_lan_failure.py -q
```

The Linux platform gate was executed in Ubuntu WSL with system PySide6 6.10.2,
the remaining Python dependencies in a temporary virtual environment, and an
isolated RuntimeData root:

```powershell
python -m pytest tests/integration/test_project_service.py -k symlink -q
```

Result: `1 passed, 23 deselected`. The Windows full-suite skip remains expected
because Windows does not expose directory symlink support in this test setup;
the Linux execution closes that platform-specific gate.

## Verification

| Gate | Result |
|---|---|
| Python full suite | `1590 passed, 1 skipped`; skip is the Windows directory-symlink case |
| WebUI full suite | `37 files / 289 tests passed` |
| WebUI typecheck | Passed |
| WebUI production build | Passed; `1632 modules transformed` |
| Packaging gates | `8 passed` |
| Task E cross-surface focused slice | `186 passed` |
| LAN lifecycle/realtime slice | `71 passed` |
| LAN auth/path/share contracts | `222 passed` |
| Linux directory-symlink gate | Ubuntu WSL, temporary venv, isolated RuntimeData; `-k symlink`: `1 passed, 23 deselected` |
| Compatibility residue scan | No production `for_library(` or `cleanup_library(` residue; the retained `migrate_path_metadata_for_library()` remains intentional |

The Chromium acceptance tests passed for Desktop mutation → Browser refresh,
revision-gap recovery, same-port restart, same-root epoch replacement,
logout/WebSocket teardown and 401 identity reset. Desktop acceptance passed for
real LAN tag mutation and same-session filesystem-event refresh. Residue
assertions cover Runtime subscriptions, EventBus handlers, lifecycle adapters,
WebSocket clients, server threads, closed-session behavior, stale identity
responses and session-filtered invalidation.

No standalone flaky startup rollback was reproduced during the serial Task E
run. The Windows platform skip is now covered by the successful Linux
directory-symlink execution, so no release gate remains open.

## Journey Log

> Brief notes on what informed the final state.

- [dead end] The first browser identity assertions used English labels while
  Chromium inherited the machine's Chinese locale; the harness now fixes the
  locale to `en-US` and waits on the password input instead of a nonexistent
  heading.
- [dead end] The Logout control was visible but pointer-inaccessible because
  the browse content painted above the Header menu; the E2E failure identified
  the missing layout stacking boundary.
- [lesson] A LAN→Desktop test must observe the real HTTP route and EventBus;
  directly invoking a panel callback does not prove cross-surface delivery.
- [lesson] Windows green aggregate tests do not satisfy the cross-platform
  release rule until the directory-symlink gate runs on a platform that
  supports directory symlinks; Ubuntu WSL supplied that missing evidence here.
- [pivot] Direct PyPI installation could not provide PySide6 for Ubuntu's
  Python 3.14, so the test used Ubuntu's matching system PySide6 package and a
  temporary virtual environment for the remaining dependencies.

## Source Materials

| File | Role |
|---|---|
| `docs/compose/specs/2026-07-21-desktop-lan-webui-architecture-recalibration-design.md` | Recalibration specification and S1/S6 rules |
| `docs/compose/plans/2026-07-21-desktop-lan-webui-architecture-recalibration.md` | Current ordered task chain |
| `tests/e2e/test_webui_realtime_acceptance.py` | Chromium realtime, logout and 401 acceptance |
| `tests/desktop/test_file_list_shim.py` | LAN-to-Desktop projection and teardown acceptance |
| `tests/lan/test_runtime_realtime.py` | Cursor, authorization and connected-session cleanup |
| `tests/lan/test_server_lifecycle.py` | Restart, failed-stop retry and thread/loop ownership |
| `webui/src/components/layout/AppLayout.tsx` | Header stacking-boundary fix |
| `docs/archive/2026-09/compose-reports/desktop-lan-webui-architecture-migration.md` | Parent migration status and release ledger |
