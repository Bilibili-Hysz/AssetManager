---
feature: lan-security-fixes
status: delivered
specs: []
plans:
  - docs/compose/plans/2026-07-13-lan-security-fixes.md
branch: master
commits: 12c400e866eba8ccf4d01cf738397bc2d10b1059..working-tree
---

# LAN Security Fixes - Final Report

## What Was Built

The LAN sharing server now applies the existing role and guest-permission model across browsing, preview, download, metadata, project, tag, and share-management routes. Guest settings such as `lan_guest_list`, `lan_guest_download`, and `lan_guest_preview` now affect the corresponding API routes instead of only existing in the desktop settings UI.

Share-link public access is now narrowly scoped. Public share endpoints still allow recipients to open share pages, verify passwords, preview allowed images, and download shared files, but management endpoints such as share deletion now go through normal authentication and `manage_links` checks.

Directory ZIP downloads now estimate recursive content size before creating temporary ZIP files, and LAN security settings such as IP whitelist, blocked IPs, rate limit, credentials, SSL paths, port, and bind address trigger a server restart when changed while sharing is running.

## Architecture

Authorization stays centralized in `AssetsManager/lan/routes/_helpers.py` through the existing `get_user_permissions()` role model plus `require_permission(request, permission)`. Route handlers perform permission checks at the top before path validation, filesystem reads, thumbnail generation, or ZIP creation.

The aiohttp authentication middleware in `AssetsManager/lan/server.py` now treats share-public APIs as explicit method/path cases instead of using a broad `/api/shares/` prefix. This preserves public share consumption while allowing management endpoints to populate request auth context.

Security filtering remains in `AssetsManager/lan/security.py`. The middleware checks blacklist first, then optional exact-match whitelist, then auth/general rate limits. The desktop startup path continues to construct servers through `AssetsManager.lan.LanServer`, which now forwards `ip_whitelist` to `_LanServerImpl`.

### Design Decisions

We reused the existing role matrix because tests and UI already depended on it, and adding a second permission system would have increased drift.

We chose restart-on-security-setting-change instead of hot reload because credentials, SSL, rate limits, blacklists, and whitelists are captured when the aiohttp app and middleware are built.

We kept whitelist matching as exact IP string comparison because the current UI stores plain lines and no existing code defines CIDR or proxy-header semantics.

## Usage

LAN settings continue to be managed from the existing desktop sharing settings dialog. Security-related changes now take effect after the running server is stopped and restarted by `_apply_sharing_settings()`.

Relevant settings include:

- `lan_guest_list` controls browse-style routes.
- `lan_guest_download` controls direct and batch downloads.
- `lan_guest_preview` controls thumbnail preview routes.
- `lan_ip_whitelist` restricts requests to exact matching client IPs when non-empty.
- `lan_blocked_ips` still rejects matching IPs before whitelist/rate-limit handling.

## Verification

Final verification commands run in the current `master` working tree:

```bash
python -m pytest tests/lan tests/unit/test_lan_sharing.py -q
```

Result: `108 passed in 4.79s`.

```bash
python -m compileall AssetsManager/lan AssetsManager/widgets -q
```

Result: passed with no error output.

## Journey Log

- [pivot] Worktree creation was skipped because many project files were untracked; a new worktree from `HEAD` would have been incomplete.
- [lesson] Public share routes need method/path-specific middleware rules, not broad prefix exemptions, because management endpoints share the same URL prefix.
- [lesson] Route permission audits should follow the full `api.py` route table; protecting only primary file routes left metadata, project, and tag routes exposed.

## Source Materials

| File | Role | Notes |
|------|------|-------|
| `docs/compose/plans/2026-07-13-lan-security-fixes.md` | Implementation plan | Tracks the staged task breakdown used for this fix |
