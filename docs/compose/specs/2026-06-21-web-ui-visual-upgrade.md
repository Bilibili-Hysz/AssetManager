# Web UI Visual Upgrade Design
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

Date: 2026-06-21
Scope: LAN web UI visual upgrade — dark theme, SVG icons, Inter font, micro-interactions

## [S1] Overview

Keep existing three-column layout and dark theme. Upgrade visual quality:
- Replace emoji icons with Lucide SVG
- Switch to Inter font (Google Fonts)
- Increase base font size 14px → 16px
- Add micro-interaction animations (150-300ms)
- Add skeleton loading states
- Add visible focus rings
- Add hover/press button feedback

## [S2] Color Palette (refined)

```css
--accent:        #818cf8;  /* brighter indigo for dark bg */
--accent-hover:  #a5b4fc;
--bg-card:       #1e1e2e;  /* softer */
--text-primary:  #e2e8f0;  /* slate-200 */
--text-secondary:#94a3b8;  /* slate-400 */
```

## [S3] Animation System

Unified tokens:
```css
--ease-out: cubic-bezier(0.16, 1, 0.3, 1);
--duration-fast: 150ms;
--duration-normal: 200ms;
--duration-slow: 300ms;
```

Card entrance: fadeUp 0.3s
Skeleton shimmer: 1.5s infinite gradient
Button hover: bg color 150ms
Press feedback: scale(0.97) 100ms

## [S4] SVG Icons (Lucide)

CDN: `<script src="https://unpkg.com/lucide@latest"></script>`
Init: `lucide.createIcons()` after DOM render

Replacements:
- folder → folder icon
- download → download icon
- package → package icon
- link → link icon
- clipboard → clipboard icon
- file → file icon
- alert-triangle → alert-triangle icon
- x → x icon
- plus → plus icon
- chevron-down → chevron-down icon
- menu → menu icon
- grid → layout-grid icon
- list → list icon
- search → search icon
- settings → settings icon
- info → info icon
- copy → copy icon
- external-link → external-link icon
- eye → eye icon (preview)
- clock → clock icon (expiry)
- lock → lock icon (password)
- user → user icon
- logout → log-out icon
- upload → upload icon
- trash → trash-2 icon
- edit → pencil icon
- check → check icon

## [S5] Font

```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
```
```css
font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
```
Base: 16px (mobile compliant)

## [S6] Accessibility

- Focus rings: `outline: 2px solid var(--accent); outline-offset: 2px;`
- Aria labels on icon-only buttons
- Keyboard navigation preserved
- prefers-reduced-motion respected

## Execution Order

1. Add Inter font + update CSS variables
2. Add Lucide CDN + create icon helper
3. Replace all emoji icons in HTML/JS
4. Add animation CSS (fadeUp, shimmer, transitions)
5. Add skeleton loading states
6. Add focus rings + hover/press states
7. Test responsive + accessibility

