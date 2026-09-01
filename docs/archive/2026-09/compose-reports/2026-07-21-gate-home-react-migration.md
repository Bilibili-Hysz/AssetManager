# Gate Home React Migration Verification

## Scope

The React `/` route retains the existing authentication and `/browse` navigation contracts while presenting the Gate home experience with AssetManager-owned `/api/info`, `/api/home`, and returned `thumbnail_url` values. No prototype endpoint or external image source is used.

## Verification

- Focused Gate suite: `npm test -- src/pages/LandingPage.test.tsx` passed with 28 tests.
- Full WebUI suite: `npm test` passed with 34 test files and 254 tests.
- TypeScript: `npm run typecheck` completed successfully (`tsc --noEmit`).
- Production build: `npm run build` completed successfully. Vite transformed 1,626 modules and emitted the production bundle.
- Diff hygiene: `git diff --check -- webui/src/pages/LandingPage.tsx webui/src/pages/LandingPage.css webui/src/pages/LandingPage.test.tsx webui/DESIGN.md` reported no whitespace errors. Git emitted only the existing LF-to-CRLF advisory for modified TypeScript files.

## Rendered QA

Controlled API responses were rendered in a local Vite session with authentication disabled and a six-image preview pool.

| Viewport | Evidence | Result |
| --- | --- | --- |
| `1440x900` desktop | `C:\Users\86177\AppData\Local\Temp\gate-qa\desktop.png` | Main content, image wall, identity, status area, CTA, theme control, and tuning control were present with `scrollWidth === clientWidth` (1440). |
| `390x844` mobile | `C:\Users\86177\AppData\Local\Temp\gate-qa\mobile.png` | Content remained reachable with `scrollWidth === clientWidth` (390); the tuning panel used internal vertical scrolling. |

The controlled browser check also confirmed that theme switching did not refetch home data, Escape closed the Background dialog, reduced motion suppressed pointer effects, and the entry action resolved to `/browse`. Loading, empty-library, unavailable-home, broken-thumbnail, hidden-page, rotation-preload, and unmount-cleanup states are covered by the focused LandingPage suite.

## Review Outcome

Local defect review found that hidden documents paused image rotation but not decorative animations or pointer effects. A regression test was added first, then the page was updated so hidden state blocks pointer effects and applies `gate-paused`, which pauses transient decoration, sweep, and rise animations. The focused regression test and the complete WebUI suite pass after that change.

## Residuals

The test runner prints pre-existing React Router v7 future-flag warnings; they do not fail tests. The independent reviewer actor was unavailable because its runtime returned `APIError`, so the review was completed locally with a red-green regression test and fresh full-suite verification.
