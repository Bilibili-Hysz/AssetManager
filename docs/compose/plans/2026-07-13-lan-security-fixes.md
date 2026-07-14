# LAN Security Fixes Implementation Plan

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/lan-security-fixes.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make LAN authorization, share management, ZIP limits, and security settings match the existing UI and permission model.

**Architecture:** Keep the current aiohttp route structure. Add small helper functions in `AssetsManager/lan/routes/_helpers.py`, then call them from affected route handlers. Avoid redesigning authentication or the desktop sharing UI.

**Tech Stack:** Python, aiohttp, PySide6 settings UI, pytest/anyio.

## Global Constraints

Only fix reviewed LAN issues; do not refactor the whole LAN server.
Use the existing role/permission model in `get_user_permissions()`.
Every behavioral change needs a focused pytest regression test.

---

### Task 1: Route-Level Permissions

**Covers:** High-risk unauthorized browse/download/preview/share creation.

**Files:**
- Modify: `AssetsManager/lan/routes/_helpers.py`
- Modify: `AssetsManager/lan/routes/files.py`
- Modify: `AssetsManager/lan/routes/downloads.py`
- Modify: `AssetsManager/lan/routes/thumbnails.py`
- Modify: `AssetsManager/lan/routes/shares.py`
- Test: `tests/lan/test_lan_api.py`

**Interfaces:**
- Produces: `require_permission(request, permission: str) -> dict | None` returning the request user when allowed, otherwise `None`.
- Consumes: existing `get_request_user()` and `get_user_permissions()`.

- [ ] **Step 1: Write failing tests**

Add tests that a registered `user` cannot create shares, that a guest blocked by settings cannot browse/download/preview, and that an admin/local UI token still can.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `python -m pytest tests/lan/test_lan_api.py -q`
Expected: new permission tests fail before implementation.

- [ ] **Step 3: Implement minimal permission gates**

Add `require_permission()` in `_helpers.py`; call it at the top of file listing, direct download, batch download, thumbnail, thumbnail batch, and share creation/list/delete as appropriate.

- [ ] **Step 4: Run focused tests and confirm pass**

Run: `python -m pytest tests/lan/test_lan_api.py tests/lan/test_role_permissions.py -q`
Expected: all selected LAN tests pass.

### Task 2: ZIP Size Accounting

**Covers:** Directory and batch ZIP resource exhaustion.

**Files:**
- Modify: `AssetsManager/lan/routes/downloads.py`
- Test: `tests/lan/test_lan_api.py`

**Interfaces:**
- Produces: `_estimate_download_size(targets: list[Path]) -> int` for files and recursive directories.

- [ ] **Step 1: Write failing tests**

Add tests proving a directory larger than `MAX_BATCH_DOWNLOAD_BYTES` is rejected for direct directory download and batch download.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `python -m pytest tests/lan/test_lan_api.py -q`
Expected: directory size tests fail before implementation.

- [ ] **Step 3: Implement recursive size check**

Count files recursively, skip hidden entries consistently with ZIP building, and reject before creating a temp ZIP.

- [ ] **Step 4: Run focused tests and confirm pass**

Run: `python -m pytest tests/lan/test_lan_api.py -q`
Expected: LAN API tests pass.

### Task 3: Security Settings Application

**Covers:** Whitelist and restart-required security settings.

**Files:**
- Modify: `AssetsManager/lan/security.py`
- Modify: `AssetsManager/lan/server.py`
- Modify: `AssetsManager/widgets/lan_sharing.py`
- Test: `tests/lan/test_lan_api.py`
- Test: `tests/unit/test_lan_sharing.py`

**Interfaces:**
- Produces: whitelist support in security middleware.
- Produces: restart detection for auth, rate limit, blacklist, whitelist, SSL settings.

- [ ] **Step 1: Write failing tests**

Add middleware tests for whitelist allow/deny and unit tests that `_apply_sharing_settings()` restarts when security settings differ.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `python -m pytest tests/lan/test_lan_api.py tests/unit/test_lan_sharing.py -q`
Expected: new settings tests fail before implementation.

- [ ] **Step 3: Implement whitelist and restart detection**

Pass `lan_ip_whitelist` into `LanServer`, enforce it in `security.py`, and compare restart-required settings in `LanSharingMixin`.

- [ ] **Step 4: Run focused tests and confirm pass**

Run: `python -m pytest tests/lan/test_lan_api.py tests/unit/test_lan_sharing.py -q`
Expected: selected tests pass.

### Task 4: Final Verification

**Covers:** End-to-end confidence for LAN fixes.

**Files:**
- No new files expected.

**Interfaces:**
- Consumes: all previous tasks.

- [ ] **Step 1: Run LAN test suite**

Run: `python -m pytest tests/lan tests/unit/test_lan_sharing.py -q`
Expected: pass.

- [ ] **Step 2: Run static checks for touched package**

Run: `python -m compileall AssetsManager/lan AssetsManager/widgets -q`
Expected: pass.
