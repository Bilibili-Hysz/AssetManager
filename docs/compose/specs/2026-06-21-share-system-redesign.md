# Share System Dialog Redesign

Date: 2026-06-21
Scope: PySide6 SharingSettingsDialog — interaction, layout, real-time refresh, feedback

## [S1] Overview Tab — Dashboard Card Layout

Replace stacked layout with 2×N grid cards:

```
┌─────────────────┬─────────────────┐
│ Server Status    │ Online Users    │
│ Running · 8080   │ 3 users         │
│ [Stop] [Copy]    │ UserA · 192.168 │
├─────────────────┼─────────────────┤
│ Traffic Stats    │ Quick Share     │
│ 12.5MB · 45 req  │ [Share] [Copy]  │
├─────────────────┴─────────────────┤
│ Recent Activity (live scroll)      │
│ • UserA downloaded file.psd 2s ago│
├───────────────────────────────────┤
│ Cloudflare Tunnel                  │
│ Status: Disconnected  [Start]      │
└───────────────────────────────────┘
```

- Each card refreshes independently
- Status changes trigger border color animation (green=ok, red=fail)
- Activity list auto-scrolls with fade-in for new entries

## [S2] Real-Time Refresh System

| Action | Current | Improved |
|--------|---------|----------|
| Create share link | Manual refresh | Auto-refresh list + toast |
| Delete share link | Silent | Fade-out animation + undo toast |
| Start/stop server | Close/reopen | Instant card update |
| User online/offline | 6s delay | 2s poll + status animation |
| Tunnel connect | Wait | Progress bar + live status |

Implementation:
1. All write operations emit `data_changed` signal on completion
2. Each tab listens to `data_changed` → auto-refresh
3. Activity list: 2s polling (was 6s), new entries fade-in
4. Status card border transitions: 300ms color animation

## [S3] Interaction Feedback System

| Action | Feedback |
|--------|----------|
| Start sharing | Button → spinner → success/fail state |
| Copy link | Button text "Copy" → "Copied ✓" (1.5s) |
| Create share | Form submit → loading → result area expands + QR |
| Delete share | Confirm dialog → fade-out → toast |
| Start tunnel | Button disabled + "Connecting..." → success/fail |
| API error | Red toast (5s auto-dismiss) |
| Data loading | Skeleton shimmer (not blank) |

Toast system (new):
- Success: green, 3s auto-dismiss
- Error: red, 5s auto-dismiss, manual close
- Info: blue, 3s auto-dismiss

## [S4] Settings Tab — Progressive Disclosure

Collapsible panels with contextual help:

```
▼ Network
  Server Name: [AssetManager    ]
  Port:        [8080]
  Bind:        [0.0.0.0 ▾]

▼ Security
  Auth Mode:   [None ▾]
  Rate Limit:  [100]

▶ Branding (collapsed)
▶ Advanced (collapsed)
▶ Tunnel (collapsed)
```

- Default: Network + Security expanded, rest collapsed
- Each panel has description text
- Changes save instantly (no Apply button needed)
- Sensitive fields (passwords, certs) have show/hide toggle

## [S5] Cross-Tab Data Flow

```
Overview Tab ──data_changed──> Share Links Tab (auto-refresh)
     │                              │
     └──data_changed──> Users Tab (auto-refresh)
```

- Create share in Quick Share → Share Links tab auto-refreshes
- Delete share in Share Links → Overview stats auto-update
- User connects → Users tab + Overview card both update

## Execution Order

1. Refactor Overview Tab to dashboard card layout
2. Add toast notification system
3. Add data_changed signal + cross-tab refresh
4. Add skeleton loading states
5. Refactor Settings Tab to collapsible panels
6. Add interaction feedback (loading, animations)
7. Test all flows
