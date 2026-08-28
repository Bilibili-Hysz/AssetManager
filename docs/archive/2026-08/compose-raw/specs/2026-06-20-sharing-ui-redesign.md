# Sharing Module UI/UX Redesign
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

Date: 2026-06-20
Scope: Desktop (PySide6) + Web (browser) sharing UI/UX overhaul

## [S1] Desktop: Quick Share Entry

**Interaction flow:**
1. File list → right-click → "Quick Share"
2. Floating card appears (not full dialog):
   - Shows: filename, file count, total size
   - Buttons: "Generate Link" + "Copy Link" + "QR Code"
   - Toggles: password protection, download limit, expiry (collapsed by default)
3. Click "Generate Link" → link auto-copied to clipboard + toast notification
4. System tray icon shows share status (green=active, gray=stopped)

**Entry points:** Right-click menu + toolbar button + shortcut `Ctrl+Shift+S`

## [S2] Desktop: Share Management Dialog

**Entry:** Menu → "Share Manager" or `Ctrl+Shift+M`

**4 Tabs:**

### Tab 1 — Overview
- Server status card (IP/port/online users/traffic stats)
- Quick share button (large, centered)
- Recent activity list (last 10 entries: who downloaded what, when)
- Tunnel status (Cloudflare tunnel toggle + public URL)

### Tab 2 — Share Links
- Table view: Name | Path | Permissions | Expiry | Downloads | Actions
- Per-row actions: Copy link | Edit | Disable | Delete
- Top bar: search + filter (active/expired/all)
- Batch operations: select multiple → batch delete/disable

### Tab 3 — User Management
- Admin list (current logged-in user)
- Invite code management: generate/copy/revoke
- Online users list: username | IP | login time | actions (kick/ban)
- Guest permission defaults

### Tab 4 — Settings
- Network: port, bind address, SSL cert
- Security: password policy, rate limiting, IP blacklist
- Branding: server name, logo, welcome message
- Advanced: Cloudflare tunnel, WebDAV (future)

## [S3] Web: Visual Optimization + Permission System

**Unchanged:**
- Dark theme + existing CSS variable system
- Three-column layout (sidebar + file grid + detail panel)
- Grid/list view toggle

**New/Enhanced:**

### Login Page (new)
- Centered card: Logo + server name + username/password input
- "Browse as guest" button (if anonymous allowed)
- Remember login (cookie)

### Permission Badges (new)
- File card corner: lock icon = password required, download icon = downloadable
- Top status bar shows current permission level: Admin/User/Guest

### Mobile Optimization (enhanced)
- Bottom fixed action bar: Back | View toggle | Download | Share
- Sidebar → fullscreen drawer
- File cards → single-column layout
- Image preview → fullscreen gesture browsing

### Interaction Enhancements (enhanced)
- Download progress bar (instead of direct jump)
- Batch selection mode (long press or checkboxes)
- Drag-to-download (desktop browsers)
- Copy share link button (per file card)

## [S4] Permission Model

### User Roles
| Role | Browse | Download | Upload | Manage Links | Manage Users | Settings |
|------|--------|----------|--------|--------------|--------------|----------|
| Admin | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Registered User | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Guest | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |

### Share Link Permissions
- **View only**: preview only (images/video/text)
- **Downloadable**: preview + download
- **Password protected**: requires password to access
- **Time limited**: auto-expire after set time
- **Download limited**: auto-expire after N downloads

### Authentication
- Admin: username + password → JWT token (httpOnly cookie)
- Registered user: username + password → JWT token
- Guest: no auth required, browse only
- Share links: token in URL (`/s/{share_id}?token=xxx`)

## Execution Order

1. Desktop: Quick share entry (right-click + floating card)
2. Desktop: Share management dialog (4 tabs)
3. Web: Login page + auth flow
4. Web: Permission badges + role-based UI
5. Web: Mobile optimization
6. Web: Interaction enhancements (progress bar, batch select, drag download)
7. Backend: User management API + invite codes
8. Backend: Role-based middleware + permission checks

## Quality Gate

```powershell
python -m ruff check . --exclude ".Cython&Noikta" && python -m pyright && python -m pytest -q
```
