# AssetManager WebUI Design

## 1. Objective

AssetManager is a private resource-library application for people who need to
inspect and organize visual project assets. The home page has one job: confirm
the library is available and offer a confident path into browsing it.

## 2. Product Context

The Gate home screen is an expressive entry surface inside an otherwise
utilitarian asset-management product. Browse, detail, sharing, and admin
surfaces remain operational and information-dense; Gate can use a quieter,
immersive visual composition because it is a transition state.

## 3. Visual Foundations

- `--gate-bg-deepest: #07070d`: dark archive backdrop.
- `--gate-bg-surface: #111122`: identity and control surfaces.
- `--gate-accent: #6366f1`: server-configurable indigo action color.
- `--gate-violet: #a78bfa`: restrained secondary visual energy.
- `--gate-text-primary: #f1f5f9`, `--gate-text-secondary: #94a3b8`, and
  `--gate-text-muted: #64748b`: reading hierarchy.
- Display/body: `'Avenir Next', 'Segoe UI', system-ui, sans-serif`; utility
  values use the browser monospace fallback only where tabular alignment helps.
- The signature element is the blurred library-preview wall behind a centered
  identity stack. It uses actual library thumbnails, never stock imagery.

## 4. Accessibility

All actions have visible focus states and at least 44px hit targets. The
status region is live, background imagery is decorative, and reduced motion
disables rotation, sweeps, particles, and ripples without hiding controls or
content. The layout remains single-column and scrollable at 375px width.

## 5. Voice & Tone

Use direct operational language: `Enter Library`, `Background tuning`, and
`Library unavailable`. Status text describes current state without marketing
copy or implementation jargon.

## 6. Implementation Practices

Use `/api/info`, `/api/home`, and returned `thumbnail_url` values as the only
home-page data sources. Keep visual tokens scoped beneath `.gate`; do not
change browse-page layout or authentication behavior. Persist only voluntary
theme/background preferences in browser storage.

## 7. Anti-Patterns

Do not add a feature-card grid, a second CTA, external images, fake metrics,
unbounded animated DOM nodes, or decorative text that competes with library
identity. Do not turn the identity stack into a floating card.

## 8. Decision-Making

The Gate page favors a single centered reading path over dashboard density.
Its visual treatment may be expressive because it is an entry transition;
operational screens continue to use conventional compact layouts.

## 9. Workflow

Before changing Gate, verify the real data states (loading, unavailable,
empty, broken thumbnail), focus/reduced-motion behavior, and both desktop and
375px viewports. Keep screenshot evidence or state the reason a render check
could not run.

## Decision Trace

```json
[
  {
    "decision": "Use a blurred wall of actual library thumbnail URLs as the Gate signature.",
    "reason": "AssetManager is about visual library inspection, so the entry surface should reveal the user's own material rather than a generic illustration.",
    "alternatives": ["static abstract background", "external stock photography"],
    "tradeoff": "The wall must handle empty and broken-thumbnail states explicitly."
  },
  {
    "decision": "Keep one centered entry action and compact status pills.",
    "reason": "The page's job is to orient and enter the library, not duplicate Browse controls before navigation.",
    "alternatives": ["dashboard-style quick actions", "feature-card grid"],
    "tradeoff": "Secondary home actions remain one navigation step away."
  },
  {
    "decision": "Scope the expressive Gate language to the landing page.",
    "reason": "The browsing and admin workflows need fast scanning more than visual ceremony.",
    "alternatives": ["apply Gate styling application-wide", "make the landing page entirely conventional"],
    "tradeoff": "The product deliberately has two visual intensities."
  }
]
```
