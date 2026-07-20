# Share System Desktop Redesign

## Implementation Status

Implemented on 2026-07-15. The staged desktop work is complete; the LAN WebUI remains outside this scope.

| Phase | Commit | Delivered |
| --- | --- | --- |
| F0 | `a92a202` | Shared asynchronous desktop share request boundary and stable setting keys. |
| F1 | `06654c3` | Endpoint-first publishing shell with distinct local and public exposure actions. |
| F2 | `f753c75` | One canonical `ShareLinkDialog` creator and the Links management page. |
| F3 | `4bd14bf` | Access page with immediate guest-policy persistence and localized invite feedback. |
| F4 | `6355510` | Consequence-sectioned Configuration with live, restart, and next-start impact summaries. |
| F5 | `23b8eb6` | Retired unused legacy entry points plus lifecycle, accessibility, and theme-refresh regression coverage. |

### Canonical runtime contracts

- `LanSharingMixin` remains the sole desktop LAN lifecycle owner. The Share System dialog delegates start, stop, and restart decisions through it.
- `SharingSettingsDialog` is the management shell with `Endpoint`, `Links`, `Access`, and `Configuration` pages. Its Links page is the only management surface; selected FileList paths open the same `ShareLinkDialog` creator.
- Guest access controls persist immediately because LAN routes read their AppSettings values for each guest request. They are intentionally not Configuration dirty-state changes.
- The Configuration footer classifies settings from the same declarations used by the lifecycle owner: hot settings reload on the running server; port, bind, credentials, rate-limit, IP-rule, and TLS changes restart it; unrelated persisted diagnostics controls apply on the next start.
- Final validation: `python -m ruff check .`, `python -m pyright`, `python -m compileall AssetsManager -q`, and `python -m pytest -q` completed with `1290 passed`.

## Scope

This redesign covers the desktop Share System entry points and excludes the LAN WebUI. It preserves current server, share-link, invite-code, and tunnel capabilities while consolidating their presentation and explicitly exposing safety state.

## Pre-Implementation Audit Findings

### Critical workflow fragmentation

1. **The same link can be created through three different products.** `SharingSettingsDialog._create_quick_share()` (`AssetsManager/dialogs/sharing_settings_dialog.py:1081`), `ShareLinkDialog._create_link()` (`AssetsManager/dialogs/share_link_dialog.py:156`), and `LanSharingMixin._quick_share()` (`AssetsManager/widgets/lan_sharing.py:244`) differ in defaults and options. For example, the mixin always enables preview while the standalone dialog exposes it. Keep contextual entry points, but route all of them to one create-link sheet.
2. **Link management is duplicated.** The Share Links tab (`sharing_settings_dialog.py:441`) and `ShareLinkManager` (`AssetsManager/dialogs/share_link_manager.py:68`) both list, copy, and delete the same records. Retire the standalone manager after callers move to the canonical Links page.
3. **Transport code is repeated in three dialogs.** Each dialog recreates QRunnable request classes with different error behavior. This makes UI state inconsistent and will impede a unified loading/error model.

### High-impact UI design issues

1. **The Overview is a dashboard where users need a control surface.** At the 700px minimum dialog width (`sharing_settings_dialog.py:122`), six cards, a 200px QR code, activity, tunnel state, and endpoint data compete in a two-column grid (`:256-423`). The service endpoint and current share action should be the visual anchor; metrics are supporting information.
2. **High-risk and low-frequency controls have the same hierarchy.** Network and Security open by default while logging, file filters, branding, and tunnel configuration share the same stacked settings treatment (`:632-841`). Port, bind mode, password, and public exposure need their own decision-oriented screens and clear live/restart semantics.
3. **The table's repeated filled Copy/Delete controls overload every row.** The inline button widgets (`:1167-1193`) are visually noisy, do not match the shared factory styling, and create accessibility traversal issues. Use selection-driven actions plus a context menu.
4. **Quick Share is a separate dark-styled popover.** `QuickShareCard` hard-codes fallback colors and does not refresh on theme changes (`AssetsManager/dialogs/quick_share_card.py:43-129`). It reads as a different product rather than a prefilled version of link creation.

### State and trust gaps to resolve with the redesign

1. Invite creation and revoke silently fail (`sharing_settings_dialog.py:1403`, `:1424`).
2. Guest permissions are shown and persisted but are not included in hot reload state (`AssetsManager/widgets/lan_sharing.py:154-165`), so the UI can promise a behavior that the running server does not use.
3. The create-link button is re-enabled immediately after success (`share_link_dialog.py:190-206`), making duplicate links likely.
4. The UI uses emoji for semantic state and navigation, while translated labels also function as state keys (`sharing_settings_dialog.py:680`, `:773-777`). Both are fragile across platforms and locales.

## Target Information Architecture

Replace the four equal tabs with a small management shell. The shell is one dialog at 980x720 minimum, with a left navigation rail on desktop and a top strip below 800px.

```text
Share System
|-- Endpoint             service posture and the active address
|-- Links                create, inspect, copy, revoke share links
|-- Access               recipients, invitations, guest policy
`-- Configuration        network, security, appearance, content, diagnostics
```

`Endpoint` is not a dashboard. It answers: Is sharing reachable? Where? Who can access it? What should I do next?

`Links` is the only canonical link-management surface. File-list context menu, toolbar share, and Quick Share all open the same create-link sheet with the selected paths prefilled.

`Access` owns invite codes, connected recipients, and guest defaults. It states whether a setting applies immediately or after restart.

`Configuration` uses a second-level section list rather than several simultaneously expanded panels:

```text
Configuration
|-- Network             name, port, bind, TLS
|-- Protection          sign-in mode, password, rate limiting, IP rules
|-- Presentation        theme color, welcome message, footer
|-- Library scope       types, depth, hidden files, exclusions, blur tags
|-- Diagnostics         access log and rotation
`-- Internet access     Cloudflare tunnel, only if available
```

## Structure

### Shared shell

```text
+--------------------------------------------------------------------------------+
| Share System                                             [Apply] [Close]      |
|------------------------------------------------------------------------------|
| Endpoint     |  STATUS STRIP                                                 |
| Links        |  [green dot] Sharing on this network                         |
| Access       |  http://192.168.1.24:8080       [Copy] [Open] [Stop sharing] |
| Configuration|  Local network  |  Protected: password  |  2 recipients       |
|              |---------------------------------------------------------------|
|              |  Make a link                                                  |
|              |  Select files or folders from FileList, then choose access.  |
|              |  [Create link]                                                |
|              |---------------------------------------------------------------|
|              |  Recent activity                                              |
|              |  [time] Alice opened Character/hero.png                      |
+--------------------------------------------------------------------------------+
```

- The status strip changes by state:
  - **Off:** gray dot, `Sharing is off`, `Start sharing` primary action, an explanation that the current library will be exposed only after start.
  - **Local:** green dot, local URL, `Copy`, `Open`, and quiet `Stop sharing` action.
  - **Public:** amber `Internet access enabled` badge alongside the local address, public URL, and `Stop internet access` as the scoped safety action. Stopping the whole server remains separate.
  - **Starting / failed:** replace action with busy text or a direct failure sentence and `Try again`; do not use a modal for normal start failure.
- QR code is absent by default. `Show QR` reveals it in an anchored side sheet after an endpoint exists. Copy QR remains an export action, not the center of the primary screen.
- Traffic and recipient count live in the status strip's supporting metadata, not separate cards.

### Links page

```text
Links                                                    [+ Create link]
[Search links] [All links v]                                      12 active
-------------------------------------------------------------------------------
Name / shared items                 Access       Expires       Downloads
Project package (3 items)           Password     Tomorrow      1 / 10
Textures/                           Anyone       Never         24 / unlimited
-------------------------------------------------------------------------------
Selected: Project package     [Copy link] [Open] [Revoke...]      [More v]
```

- A selected row uses a 2px accent-leading rule and a muted surface fill, not a saturated selection block.
- Empty state: `No links yet` followed by `Create a link for files in this library. Links can expire, require a password, and limit downloads.` plus `Create link`.
- Revoke is the only danger action and opens a confirmation with the link name, recipient effect, and undo availability if the backend can support it. Do not label a link deletion as generic `Delete`.
- The table has an accessible row context menu with Copy, Open, and Revoke. The keyboard action bar mirrors this menu.

### Create-link sheet

Use a modal sheet, 560px wide, not a second tabbed dialog. It has two phases in the same stable layout.

```text
Create link
Shared items
Project package                           [Change selection]
3 items · 84 MB

Access
( ) Anyone with the link
( ) Require a password   [Password field]

Availability
Expires [24 hours v]       Download limit [Unlimited v]
[x] Let recipients preview supported files

                                      [Cancel] [Create link]
```

On success, replace the action area with an explicit output state without reflowing the whole sheet:

```text
Link created
https://192.168.1.24:8080/s/8Gk...
[Copy link] [Open] [Show QR]                         [Done]
```

- Default choices: 24-hour expiry, preview allowed, no download cap. Do not silently add a password. If sharing is public, show a compact exposure note before creation.
- A disabled `Create link` button must state the missing prerequisite beside it, such as `Start sharing to create a link`.
- A second create requires an explicit `Create another link` action, preventing duplicate submissions.

### Access page

```text
Access
Guest policy
People using a link can: [Preview x] [Download x] [Browse folders x]
Applies: [after server restart]                                   [Apply now]

Invitations                                               [Generate invite]
CODE            Status       Created                 [Copy] [Revoke]
NM4R-KQ7D       Active       Today, 10:42

Connected now
Name            Connection                   Last activity
Alice           192.168.1.18                 Viewing Textures/
```

- Avoid an `Admin Info` block containing only the current owner name and role. Put this in a compact identity line at the page top if it remains useful.
- Error states stay inside the affected section: `Could not create an invite. Check that sharing is running, then try again.`

### Configuration page

- Use a section navigator on the left of the content pane or a `QListWidget`-style subnavigation, never four expanded accordions in one scroll view.
- Each screen opens with a short consequence sentence:
  - Network: `These changes decide where the server listens. Port and bind changes restart sharing.`
  - Protection: `Password and IP rule changes apply after restart.`
  - Library scope: `These changes control what recipients can browse.`
- A sticky footer shows `No unsaved changes`, `3 changes apply now`, or `2 changes require restart`, with `Discard` and `Apply changes` actions.

## Interaction Rules

1. Starting sharing from any entry point opens no additional confirmation when a library is open and settings are valid. Invalid port, missing library, or TLS configuration errors appear beside the relevant field or in the endpoint strip.
2. Stopping the server requires confirmation only when active links or connected recipients exist. The confirmation names the impact: `12 active links will stop working until sharing starts again.`
3. Internet access is modeled separately from local sharing. Its amber posture label must remain visible while the tunnel runs.
4. Async refresh preserves the selected link by immutable ID, retains keyboard focus, and shows progress only in the changed region.
5. All state models use stable values (`none`, `password`, `images`, `models`, etc.); labels are localized at render time only.

## Delivery Sequence

1. Extract a canonical share API client/controller and stable UI view models. Keep server semantics unchanged; add focused error and lifecycle tests.
2. Build the new shell and Endpoint page behind the existing Share System menu entry. Preserve `LanSharingMixin` as the lifecycle owner.
3. Move link listing and creation into canonical Links page and Create-link sheet. Re-route contextual Quick Share and retire `ShareLinkManager` after behavioral parity tests pass.
4. Move invitations, online recipients, and guest policy to Access. Fix live/restart behavior before claiming controls apply.
5. Replace Settings tab with sectioned Configuration, add restart/live markers, and remove per-widget styling in favor of semantic themed primitives.
6. Add keyboard, accessibility-name, locale-switch, narrow-width, stopped-server, start-failure, empty, and async-refresh regression coverage.

## Acceptance Criteria

- A user can identify local versus public exposure, copy the correct endpoint, and stop only the intended exposure within two seconds of opening the dialog.
- Share creation has one implementation path and one result state; all contextual entry points prefill it.
- Links have one management view; removal is called `Revoke` and is never the visual default.
- Every remote operation has loading, success, empty, and failure feedback in the affected region.
- Theme changes affect all Share System controls, including row actions and the contextual creation surface.
- No persisted setting key is derived from translated display text, and no semantic status relies on emoji alone.
