# C6-C10 Hardening 回归证据（2026-08-21）

## 1. Snapshot Metadata

| Field | Value |
|---|---|
| Report ID | `c6-c10-hardening-evidence-2026-08-21` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; baseline captured before this report and manifest were added |
| Status fingerprint | `ab85a7680579a43ef79ba1ac38b659f24632c696665c60921d9631182f6519f6` |
| Binary diff fingerprint | `b6fc339fb51971ec71bca26c1a8de17dfcf49b34b4e58db5be8980155c553589` |
| Tracked / untracked changes | 97 / 42 before this report and manifest were added |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This is a new dated snapshot after the batch-download quota and WebSocket offload test hardening. Earlier dated reports remain unchanged. The machine-readable companion is [audit-manifest-c6-c10-hardening-evidence-2026-08-21.json](audit-manifest-c6-c10-hardening-evidence-2026-08-21.json).

## 2. Hardening Changes

- Batch download quota denial now returns the canonical JSON 429 response, applies the quota identity cookie, removes the prepared ZIP, and records status 429 instead of raising a `web.Response` as an exception.
- The batch quota regression test covers response status/code/details and temporary ZIP cleanup.
- The WebSocket password-auth test now patches the underlying synchronous verifier and asserts that the exact verifier is passed through `asyncio.to_thread`.
- Existing single-download recorder status propagation, WebSocket admission waits, lifecycle fixture roots, and architecture-boundary signature coverage remain in the regression set.

## 3. Parallel Verification

### Focused hardening suite

Command:

```text
python -m pytest -n 0 --basetemp=.zcode/pytest-hardening-focused --durations=0 tests/lan/test_free_download_quota.py tests/lan/test_websocket_auth_offload.py tests/lan/test_lan_api.py::test_download_route_failure_is_pathless_and_recorder_safe tests/unit/test_architecture_boundaries.py::test_file_operation_service_delegates_deleted_projection_cleanup tests/lan/test_runtime_realtime.py::test_real_library_close_session_stops_lan_server_and_websocket tests/integration/test_window_lifecycle_lan_failure.py::test_window_switch_drains_session_after_explicit_lan_stop_failure tests/integration/test_window_lifecycle_lan_failure.py::test_window_exit_drains_session_after_explicit_lan_stop_failure
```

Result: **16 passed, 0 failed, 0 skipped**, exit code 0, 119.72 seconds.

### Full Python suite

Command:

```text
python -m pytest --basetemp=.zcode/pytest-hardening-full -n 0
```

Result: **3904 collected, 17 deselected, 3887 selected, 3880 passed, 0 failed, 7 skipped, 2 warnings**, exit code 0, 600.32 seconds.

The seven skips are platform-limited: four symlink/reparse privilege cases report `WinError 1314`, two directory-symlink cases are unavailable on Windows, and one abrupt Windows spawn termination/queue finalization case is nondeterministic. Warnings were a Qt signal disconnect warning and a duplicate ZIP entry warning for `data/assetmanager.db`.

### Static and governance gates

The independent static-gate agent ran all requested checks successfully:

- `check_audit_reports.py`: 17 manifests valid.
- `check_doc_stats.py`: README stats current.
- Boundaries, style sources, route capabilities, frontend data-fetch, and layers: all passed.
- `compileall`: passed.
- Full Ruff: passed.
- `git diff --check`: passed, with expected LF/CRLF conversion warnings only.

These static results are recorded as an execution summary. The corresponding final raw audit/Ruff logs are captured separately under `artifacts/evidence/2026-08-21/c6-c10-hardening-final/`.

## 4. Remaining Boundaries

- The seven platform-limited skips do not establish privileged Windows symlink/reparse or independent lifecycle coverage.
- Browser E2E, real-backend LAN acceptance, dependency/CVE, performance, package/release, clean-checkout, power-loss, and independent Windows lifecycle CI remain unexecuted.
- Full import copy replay, durable outbox, exactly-once event dispatch, thumbnail snapshot evolution, watcher cursor, and cross-system filesystem/SQLite atomicity remain outside scope.
- All C6-C10 findings remain `fixed-unverified`; no finding is promoted by this report.
