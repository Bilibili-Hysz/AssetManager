# LAN No-Auth Login Redirect Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure an explicitly selected LAN `none` authentication mode does not redirect the WebUI to Login merely because the library contains historical active users.

**Architecture:** Carry the persisted `lan_auth_mode` into the LAN server. The server remains backward-compatible when the mode is omitted, but an explicit `none` mode disables user-based authentication admission and reports a guest/no-auth principal consistently through `/api/info`, `/api/auth/me`, and protected request middleware.

**Tech Stack:** Python, aiohttp, pytest, existing LAN service/runtime wiring, React WebUI authentication contract.

## Global Constraints

- Keep the change limited to the persisted LAN authentication-mode contract and its regression coverage.
- Preserve existing password/key authentication and legacy constructor behavior when no explicit mode is supplied.
- Do not expose credentials in logs, test output, or the final report.
- Follow TDD: the new regression must fail before the production change and pass after it.

---

### Task 1: Propagate and enforce explicit no-auth mode

**Files:**
- Modify: `AssetsManager/widgets/lan_sharing.py` at `_toggle_sharing` option construction.
- Modify: `AssetsManager/lan/__init__.py` and/or `AssetsManager/lan/server.py` at the public/server implementation constructor and authentication properties.
- Modify: `AssetsManager/lan/routes/system.py` at `handle_info`.
- Test: `tests/lan/test_lan_api.py` or the closest existing LAN server middleware test module.

**Interfaces:**
- Consumes: `AppSettings.get("lan_auth_mode", "none")` from the desktop sharing lifecycle.
- Produces: an optional `auth_mode` constructor value, with explicit `"none"` disabling active-user admission and legacy omitted mode retaining current behavior.

- [ ] **Step 1: Write the failing regression test**

  Construct a LAN server with an active user in its auth database, no password/key, and `auth_mode="none"`. Assert that `/api/info` reports `auth_enabled is False` and `auth_mode == "none"`, and that `/api/auth/me` returns a guest principal rather than HTTP 401. Assert the same middleware policy for a normal API request that should be reachable in no-auth mode.

- [ ] **Step 2: Run the focused test and verify it fails for the current reason**

  Run:

  ```powershell
  python -m pytest tests/lan/test_lan_api.py -k "explicit_none_auth_mode" -q
  ```

  Expected: FAIL because the current server does not accept/use `auth_mode`, or still derives authentication from active users.

- [ ] **Step 3: Implement the smallest production change**

  Add optional `auth_mode` plumbing from `LanSharingMixin._toggle_sharing` into `LanServer`. In the server authentication policy, treat explicit `auth_mode == "none"` as no-auth for active-user detection while retaining password/key checks. Make `/api/info` use the same effective policy rather than independently deriving `auth_mode` from active users. Keep the existing behavior when `auth_mode` is omitted.

- [ ] **Step 4: Run the regression and adjacent LAN tests**

  Run:

  ```powershell
  python -m pytest tests/lan/test_lan_api.py -k "explicit_none_auth_mode" -q
  python -m pytest tests/lan/test_lan_api.py tests/lan/test_runtime_realtime.py tests/e2e/test_webui_realtime_acceptance.py -q
  python -m ruff check AssetsManager/lan/server.py AssetsManager/lan/routes/system.py AssetsManager/widgets/lan_sharing.py tests/lan/test_lan_api.py
  ```

  Expected: all selected tests pass, including the no-auth regression and browser LAN acceptance.

- [ ] **Step 5: Verify the desktop setting propagation**

  Run the existing sharing tests plus a focused assertion that `_toggle_sharing` passes the persisted `lan_auth_mode` value to the server constructor. Confirm both `none` and `password` values are preserved.

- [ ] **Step 6: Review the final diff and test output**

  Run:

  ```powershell
  git diff --check
  git status --short
  ```

  Confirm only the planned authentication files and regression tests changed, with no unrelated edits or credential material.
