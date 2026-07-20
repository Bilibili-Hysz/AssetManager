# DESIGN.md - AssetsManager Share System Desktop

## Implementation Status

This design was implemented in staged commits `a92a202`, `06654c3`, `f753c75`, `4bd14bf`, `6355510`, and `23b8eb6` on 2026-07-15. The production desktop surface now uses the Endpoint / Links / Access / Configuration shell, canonical link creation, sectioned configuration impact feedback, and theme/accessibility regression coverage. The LAN WebUI remains out of scope.

## 1. Objective

Make local and internet sharing understandable as one controlled workflow: start the service, create or copy a link, then verify and manage its access. The desktop surface should read as an operational console, not a dashboard: the active address and exposure state are always obvious, destructive actions stay quiet until selected, and advanced configuration never competes with the next safe action.

## 2. Product Context

- **What the product does:** AssetsManager exposes an open asset library to local-network or tunnel-connected recipients and lets its owner create time- and access-bounded share links.
- **Who it's for:** A desktop asset-library owner who needs to share selected files quickly, but must still understand whether access is local, public, protected, or expired.
- **Adjacent brands (feel like these):** Linear for operational density, Tailscale for clear network posture, Raycast for compact action language.
- **Distant brand (do not feel like this):** Consumer cloud-storage marketing UI, because the owner needs operational certainty rather than promotional reassurance.
- **Cultural register:** Technical and calm. Security-relevant facts are direct; the interface does not dramatize ordinary local sharing.

## 3. Visual Foundations

### 3a. Color

- **Neutral scale:** `[--surface: theme.panel, --surface-raised: theme.input_bg, --surface-hover: theme.hover_overlay, --rule: theme.border, --text: theme.body, --text-strong: theme.heading, --text-muted: theme.muted]`.
- **Accent(s):** `[--accent-primary: theme.accent, --accent-on: theme.on_accent]`.
- **Semantic:** `[--status-local: #2F8F68, --status-public: #C77818, --status-offline: theme.muted, --danger: theme.danger]`. These values must be mapped through the existing theme token system before implementation rather than hard-coded into dialogs.
- **Usage rules:** Accent marks exactly one default action per view. Green means an active local endpoint, amber means internet exposure or restart required, and danger is reserved for irreversible removal or stopping a currently active service.

### 3b. Typography

- **Display face:** Existing application UI face at 18px semibold for page title and 20px semibold for an active endpoint label; no decorative display face is introduced.
- **Body face:** Existing application UI face at 13px regular, 13px medium for key facts, 11px for metadata.
- **Fallback stack:** Application-default Qt system font, preserving the host operating system's CJK fallback behavior.
- **Type scale:** `11 / 13 / 15 / 18 / 20 px`.
- **Weight discipline:** Regular for labels and descriptions; medium only for selected row names and endpoint state; semibold only for the page title and the current endpoint. Do not use bold as a substitute for semantic color.

### 3c. Spacing & rhythm

- **Base unit:** `4 px` through `scaled_px`.
- **Spacing scale:** `4, 8, 12, 16, 24, 32 px`.
- **What generous whitespace means in numbers:** The management shell uses 16px outer padding, 12px between control groups, and 8px table-row padding. No dashboard card grid is used.

### 3d. Component seeds

- **Button:** Three variants only: one filled primary action, outlined secondary actions, and quiet icon/text actions. Every icon-only action has a tooltip and accessible name.
- **Card / container:** Use bordered `QFrame` sections with 6px radius and no shadow only when they group a distinct operational state. Tables, lists, and forms remain flat on the base surface.
- **Iconography:** Use a consistent Qt-compatible line-icon set or simple vector glyphs. Status is encoded by a colored dot plus adjacent text, never emoji alone.
- **Status strip:** A compact, full-width endpoint strip holds state, address, exposure badge, and the one contextually correct service action.
- **Row actions:** Use a selected-row action bar or context menu. Do not place filled Copy and Delete buttons inside every table row.

## 4. Accessibility

- **Text contrast:** Body text remains at least 4.5:1; labels, rules, and inactive badges remain at least 3:1 against their immediate background.
- **Motion:** No decorative animation. State changes use immediate content replacement; progress uses a determinate or textual busy state.
- **Focus indicators:** A 2px accent outline with a 2px outer gap appears on keyboard focus for every input, table, toolbar action, and destructive confirmation.
- **Alt text policy:** Icons are decorative only when adjacent text gives the same meaning. Icon-only controls use `setAccessibleName` and `setToolTip` with the action verb.
- **Keyboard:** `Ctrl+L` copies the selected or active link, `Delete` opens revoke confirmation for selected links, `Ctrl+F` focuses link search, and `Ctrl+Enter` creates the configured link. All have discoverable labels in an overflow help affordance.

## 5. Voice & Tone

- **Register:** Plain operational language.
- **Sentence rhythm:** Short labels and one-sentence state explanations.
- **Words this brand uses:** `Local network`, `Internet link`, `Protected`, `Expires`, `Copy link`, `Restart required`.
- **Words this brand refuses:** `seamless`, `instant magic`, `securely share` without a concrete qualifier, `active` without naming what is active, `quick` for a flow that requires decisions.
- **Address:** The interface addresses the owner implicitly through direct action labels, not conversational second-person marketing copy.

## 6. Implementation Practices

- **Token format:** Existing `themes.get()` values and `scaled_px`/`scaled_pt`; add named Share System semantic helpers rather than per-widget style strings.
- **Component library convention:** Extend `TabbedDialog` only after extracting reusable status-strip, action-toolbar, and themed table primitives. The share manager itself becomes a dedicated dialog shell, not a generic settings dialog with more tabs.
- **Image treatment rules:** No illustrations, QR code only as a functional export artifact after an endpoint or link exists.
- **Grid system:** Desktop split view: fixed 216px navigation rail plus flexible content. At widths below 800px, use a top navigation strip and a single-column content pane.
- **Motion rules:** No animation except a 150ms opacity transition for non-blocking busy indicators when reduced motion is not requested.

## 7. Anti-Patterns

- **No dashboard card grid.** Six equal cards obscure the fact that service state and link creation are the dominant tasks.
- **No emoji navigation or status signals.** Emoji vary by platform, do not localize, and cannot carry the accessibility burden of state.
- **No duplicate creation or management dialogs.** A task has one canonical surface; contextual entry points only prefill it.
- **No primary button in every table row.** Repeated filled actions flatten priority and make dangerous operations visually noisy.
- **No translated display text as state keys.** Authentication modes, file categories, and permissions use stable domain values with localized labels.
- **No full URL as centered display text.** Long endpoints are left-aligned, selectable, elided visually, and always available through Copy and Open actions.

## 8. Decision-Making

1. **Exposure clarity over visual density.** If a user cannot tell whether a library is off, local, or public, expose that state before adding any metric or setting.
2. **One canonical workflow per job.** Contextual quick-share starts the same create-link flow with defaults; it does not create a parallel product surface.
3. **Safe default before advanced control.** The default local service and a 24-hour protected link are discoverable first; network, TLS, logging, and filtering are progressively disclosed.
4. **Live behavior over stored preference.** Controls show whether a change applies now, applies after restart, or is unavailable while the service is stopped.
5. **Theme coherence over local styling.** All controls reuse semantic theme tokens and refresh on theme change.

## 9. Workflow

1. Read the current server state and selected asset paths.
2. Render the endpoint strip before link data or configuration.
3. Route the user to the canonical page: Links, Access, or Configuration.
4. Present one primary action based on state and selection.
5. Show inline loading, empty, success, and failure states in the affected region.
6. Mark configuration changes as live, restart-required, or unsaved before Apply.
7. Preserve keyboard focus and selected link identity after any async refresh.
