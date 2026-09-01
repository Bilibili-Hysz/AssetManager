# Desktop UI visual closure — August 1, 2026

## Scope

This report records the final UI-07 audit for the Desktop visual/performance
track. The implementation stayed inside the existing Qt widgets, theme token
pipeline, SVG icon registry, scaled geometry helpers, and current async data
flow.

## Completed in this batch

- Removed user-facing emoji and platform glyphs from FileList state controls,
  legacy Details rows, InfoPanel summaries/empty state, Sidebar favorites
  choices, LAN sharing status/buttons, plugin menu text, and sharing labels.
- Completed the residual cleanup in the legacy FileList Details path, the
  default VS Code tool definition, LAN status toolbar state, and all three
  locale resources; semantic SVG icons now carry those visual states without
  changing the underlying commands or persisted data.
- Kept legacy favorite JSON values readable through the existing compatibility
  map; new favorite values use semantic icon names.
- Added the InfoPanel empty state as separate semantic icon and text widgets so
  it does not overload the preview QLabel with mixed pixmap/text state.
- Retained `reduce_motion` behavior for dialog fade-in and the existing Grid
  and InfoPanel animation paths.
- Fixed stateful FileList controls so sorting and hidden-file changes keep
  semantic SVG icons instead of reintroducing Unicode glyphs.
- Fixed live UI-scale relayout by including the measured item hint in the
  GridLayout cache key.
- Added 500 ms filesystem refresh debounce and coalesced scoped domain events
  with QFileSystemWatcher notifications to avoid duplicate model resets.
- Added semantic icon cache invalidation for theme and scale changes.

## Theme contrast audit

The audit scanned 22 theme JSON assets (21 selectable themes plus the Default
fallback) after applying the same token fallback rules used by
`AssetsManager.core.themes`.

Thresholds used:

- `body` and `heading`: 4.5:1 against `base` and `panel`.
- `muted`: 3.0:1 against `base` and `panel` (secondary text threshold).
- `on_accent`: 4.5:1 against `accent` for normal button text.

All `body`, `heading`, `muted`, and `on_accent` pairs now meet the listed
thresholds for the 21 selectable themes. Accent foregrounds were changed to a
high-contrast dark token where necessary; Midnight and Nord muted tokens were
raised slightly. The new contract is enforced by
`tests/core/test_themes.py`.

## Verification

- Targeted Desktop/UI regression: 148 passed.
- Desktop suite after the preceding UI-06 batch: 326 passed.
- Final affected-module regression after quality remediation: 229 passed.
- Full project regression: 1590 passed, 1 platform-dependent test skipped
  (directory symlinks are unavailable on Windows).
- Python compile check and Ruff passed for all touched Desktop modules.
- All three locale JSON files parse successfully after the visual text cleanup.
- Runtime UI controls no longer use literal emoji/platform glyphs for their
  icons; compatibility mappings for legacy favorite JSON values remain intact.
