# Auth / Plugin / WebSocket 边界实施证据（2026-08-22）

## 1. Snapshot metadata

| Field | Value |
|---|---|
| Report ID | `auth-plugin-websocket-implementation-evidence-2026-08-22` |
| Source commit | `5fbf93059e2a2926ffb6b4fb940981736fd7050f` |
| Branch | `feat/quality-audit-2026-08-17` |
| Source kind | Dirty worktree; baseline captured before this report and manifest were added |
| Baseline status SHA-256 | `305b7f416579655a9bb9b5659ff7f45e79048e04` |
| Baseline diff SHA-256 | `1da774d6ed5646e1e5e19c2021f2c46517683daa` |
| Baseline tracked / untracked entries | `118 / 52` |
| Runtime | Windows 10.0.26220 x64, Python 3.14.3, pytest 9.0.2, Ruff 0.15.16 |

This is an append-only dated snapshot. Earlier reports and manifests remain unchanged. The machine-readable companion is [audit-manifest-auth-plugin-websocket-implementation-evidence-2026-08-22.json](audit-manifest-auth-plugin-websocket-implementation-evidence-2026-08-22.json).

## 2. Implemented scope

### AUTH-REV-01 — durable token revocation and session lease

- Revocation writes are durable-first; persistence failure installs an immediate in-process deny entry and returns a typed retryable failure rather than claiming durable logout (`AssetsManager/lan/token_revocations.py:37-65`).
- Initial durable loading remains retryable and fails closed while the production AuthService source is unavailable (`AssetsManager/lan/token_revocations.py:96-118`).
- Revocation repository operations are session-leased (`AssetsManager/application/auth_service.py:307-327`), and the repository lazily creates the v27 table without committing a caller-owned transaction (`AssetsManager/repositories/revoked_token_repository.py:20-47`).
- LAN logout performs durable work off the event loop, evicts matching existing WebSockets, and preserves the cookie on a 503 persistence failure so the client can retry (`AssetsManager/lan/routes/auth.py:104-139`).

### PLUGIN-OWN-01 — contribution ownership and lifecycle

Source register: `PLUGIN-V2` (Plugin API v2 handover and contribution contract).

- Category contributions are rebuilt from built-in baselines with normalized extensions, owner-aware collision handling, live extension lookup, and restoration after unload (`AssetsManager/application/asset_filters.py:13-65`, `AssetsManager/panels/file_list/_common.py:16-60`).
- Grid labels and directory classification consume the live canonical category registry instead of import-time or display-label snapshots (`AssetsManager/panels/file_list/_grid_widget_render.py:640-667`, `AssetsManager/controllers/info_controller.py:497-520`).
- Menu, command, tool-window, v2 command/parser, theme, and category registrations retain owner identity; duplicate IDs and failed v2 registration are rejected atomically (`AssetsManager/core/plugins/host_context.py:586-651`, `AssetsManager/core/plugins/host_context.py:839-926`).
- Plugin enable/load is idempotent with rollback, failed host bindings are released, and bulk unload attempts every loaded plugin (`AssetsManager/core/plugins/manager.py:125-359`).

### WS-REV-01 — existing WebSocket authority

- WebSocket authorization checks revocation asynchronously during admission and periodic reauthorization (`AssetsManager/lan/routes/websocket.py:23-113`).
- Connections retain only a SHA-256 token digest; logout evicts the matching token without evicting other tokens sharing an authority (`AssetsManager/lan/ws.py:65-180`, `AssetsManager/lan/ws.py:461-486`).
- Password/access-key verification remains offloaded through `asyncio.to_thread`; runtime and focused tests assert the exact verifier function and arguments (`AssetsManager/lan/routes/websocket.py:74-90`, `tests/lan/test_websocket_auth_offload.py:18-101`).

## 3. Executed verification

### Focused cross-module suite

```text
python -m pytest -n 0 --basetemp=.zcode/pytest-auth-plugin-focused -q tests/lan/test_l2_rate_input_cpu.py tests/lan/test_public_commerce_auth.py tests/lan/test_runtime_realtime.py tests/lan/test_websocket_auth_offload.py tests/lan/test_token_revocations.py tests/unit/test_revoked_token_repository.py tests/unit/test_auth_service_revocations.py tests/plugins tests/core/test_plugins.py tests/integration/test_plugin_service.py tests/unit/test_asset_filters.py tests/unit/test_info_controller.py
```

Result: **284 passed, 0 failed**, exit code 0, 49.31 seconds.

### Full Python suite

```text
python -m pytest --basetemp=.zcode/pytest-auth-plugin-full-2 -n 0 -q
```

Result: **3907 passed, 12 skipped, 17 deselected, 0 failed, 2 warnings**, exit code 0, 631.17 seconds. Windows-limited skips include symlink/reparse privilege, POSIX flock, and nondeterministic process-termination cases. Existing warnings were the Qt signal disconnect warning and duplicate ZIP entry warning.

### Static and governance gates

The following commands all exited 0 and their stdout/stderr are stored under `artifacts/evidence/2026-08-22/auth-plugin-websocket-final/`:

- `python scripts/check_audit_reports.py` — 18 pre-existing manifests valid before this report was indexed.
- `python scripts/check_doc_stats.py` — README structural statistics current (`python_test_files=270`).
- `python scripts/check_boundaries.py`
- `python scripts/check_style_sources.py`
- `python scripts/check_route_capabilities.py`
- `python scripts/check_frontend_data_fetch.py`
- `python scripts/check_layers.py`
- `python -m ruff check AssetsManager tests scripts run.py`
- `python -m compileall AssetsManager -q`
- `git diff --check`

Raw artifact SHA-256 values are recorded in the companion manifest. The full-suite output is a local raw artifact; no agent-reported output was substituted.

## 4. Status and remaining limits

The findings in this dated batch remain **`fixed-unverified`**. Local Windows tests do not prove:

- independent POSIX multi-process lock/revocation behavior;
- Windows symlink/junction/reparse privilege coverage;
- browser E2E or real-backend LAN acceptance;
- cross-process revocation propagation under concurrent writers;
- GitHub Actions/package/release execution;
- dependency/CVE status, performance benchmarks, clean-checkout reproducibility, power-loss recovery, or subprocess termination behavior;
- descriptor-backed final-open atomicity. Existing downloads, shares, thumbnails, and ZIP paths retain the separately tracked path-based final-open/TOCTOU limitation;
- plugin discovery concurrency, UI combo refresh across already-open panels, and full external plugin ecosystem compatibility.

No finding is promoted to `verified-fixed` by this report. No commit, push, release, revert, reset, clean, or worktree overwrite was performed.
