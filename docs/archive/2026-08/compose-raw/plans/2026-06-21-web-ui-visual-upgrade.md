# Web UI Visual Upgrade Implementation Plan
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the LAN web UI with Lucide SVG icons, Inter font, micro-interactions, and improved accessibility while keeping the existing dark theme and layout.

**Architecture:** CSS-first approach — update variables and add animation keyframes in style.css, add Lucide CDN to HTML, then replace emoji icons in HTML/JS. No layout changes.

**Tech Stack:** HTML, CSS, JavaScript, Lucide Icons (CDN), Inter font (Google Fonts)

---

### Task 1: CSS Foundation — Font, Variables, Animations

**Covers:** S2, S3

**Files:**
- Modify: `AssetsManager/lan/static/style.css`
- Modify: `AssetsManager/lan/static/index.html`
- Modify: `AssetsManager/lan/static/share.html`
- Modify: `AssetsManager/lan/static/login.html`
- Modify: `AssetsManager/lan/static/detail.html`

- [ ] **Step 1: Add Inter font to all HTML files**

In each HTML `<head>`, add before the CSS link:
```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
```

- [ ] **Step 2: Update CSS variables in style.css**

Replace the `:root` block with updated values:
```css
:root {
    --bg-base:       #0a0a0f;
    --bg-surface:    #12121a;
    --bg-card:       #1e1e2e;
    --bg-card-hover: #282840;
    --bg-elevated:   #2a2a3e;
    --bg-input:      #14141e;
    --border:        #2a2a3a;
    --border-hover:  #3a3a4f;
    --text-primary:  #e2e8f0;
    --text-secondary:#94a3b8;
    --text-muted:    #64748b;
    --accent:        #818cf8;
    --accent-hover:  #a5b4fc;
    --accent-subtle: rgba(129, 140, 248, 0.08);
    --accent-glow:   rgba(129, 140, 248, 0.20);
    --success:       #22c55e;
    --warning:       #f59e0b;
    --danger:        #ef4444;
    --radius-xs:     4px;
    --radius-sm:     6px;
    --radius-md:     10px;
    --radius-lg:     14px;
    --radius-xl:     20px;
    --shadow-card:   0 2px 12px rgba(0,0,0,0.25);
    --shadow-hover:  0 8px 30px rgba(0,0,0,0.35);
    --shadow-popup:  0 12px 40px rgba(0,0,0,0.45);
    --ease-out:      cubic-bezier(0.16, 1, 0.3, 1);
    --duration-fast: 150ms;
    --duration-normal: 200ms;
    --duration-slow: 300ms;
    --transition:    0.2s var(--ease-out);
    --sidebar-w:     260px;
    --info-w:        320px;
    --header-h:      56px;
    --grabber-w:     5px;
}
```

- [ ] **Step 3: Update body font**

```css
body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    font-size: 16px;
    /* ... rest unchanged ... */
}
```

- [ ] **Step 4: Add animation keyframes**

Add after the scrollbar styles:
```css
/* ── Animations ─────────────────────────────────────────────── */
@keyframes fadeUp {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
}
@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}
@keyframes shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
}
@keyframes scaleIn {
    from { opacity: 0; transform: scale(0.95); }
    to { opacity: 1; transform: scale(1); }
}

/* Reduced motion */
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: 0.01ms !important;
        transition-duration: 0.01ms !important;
    }
}
```

- [ ] **Step 5: Add focus ring styles**

```css
:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
}
button:focus-visible, a:focus-visible, input:focus-visible, select:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
}
```

- [ ] **Step 6: Add card animation class**

```css
.card-animate { animation: fadeUp var(--duration-slow) var(--ease-out) both; }
.skeleton {
    background: linear-gradient(90deg, var(--bg-card) 25%, var(--bg-elevated) 50%, var(--bg-card) 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
    border-radius: var(--radius-md);
}
```

---

### Task 2: Lucide Icons Integration

**Covers:** S4

**Files:**
- Modify: `AssetsManager/lan/static/index.html`
- Modify: `AssetsManager/lan/static/share.html`
- Modify: `AssetsManager/lan/static/login.html`
- Modify: `AssetsManager/lan/static/detail.html`
- Modify: `AssetsManager/lan/static/app.js`

- [ ] **Step 1: Add Lucide CDN to all HTML files**

Before the closing `</body>` tag, add:
```html
<script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>
```

- [ ] **Step 2: Create icon helper function in app.js**

Add at the top of app.js (after state declaration):
```javascript
function icon(name, cls = '') {
    return `<i data-lucide="${name}" class="${cls}"></i>`;
}
function initIcons() {
    if (typeof lucide !== 'undefined') lucide.createIcons();
}
```

- [ ] **Step 3: Replace emoji icons in index.html**

Replace context menu emojis:
- `&#128194;` → `icon('folder-open')`
- `&#11015;` → `icon('download')`
- `&#128230;` → `icon('package')`
- `&#128279;` → `icon('link')`
- `&#128203;` → `icon('clipboard')`
- `&#128196;` → `icon('file-text')`

Replace toolbar emojis:
- `&#9776;` (menu) → `icon('menu')`
- `&#9638;` (grid) → `icon('layout-grid')`
- `&#9432;` (info) → `icon('info')`
- `&#8593;` (sort) → `icon('arrow-up-down')`
- `&#10005;` (clear) → `icon('x')`
- `&#9745;` (select) → `icon('check-square')`

Replace landing page icon:
- `A` text → `icon('hard-drive')` (or keep as styled text)

- [ ] **Step 4: Call initIcons() after DOM updates**

In app.js, after every `innerHTML` assignment that includes icons, call `initIcons()`. Key locations:
- After `renderProjects()` — grid cards
- After `renderBreadcrumb()` 
- After context menu show
- After login/register overlay show

- [ ] **Step 5: Replace emojis in share.html and login.html**

Share page:
- `&#128274;` → `icon('lock')`
- `&#9888;` → `icon('alert-triangle')`

Login page: no emojis to replace (uses text).

---

### Task 3: Button Hover/Press States + Card Animations

**Covers:** S3, S6

**Files:**
- Modify: `AssetsManager/lan/static/style.css`

- [ ] **Step 1: Add button interaction states**

```css
.btn {
    transition: all var(--duration-fast) var(--ease-out);
    cursor: pointer;
}
.btn:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
}
.btn:active {
    transform: scale(0.97);
    box-shadow: none;
}
.btn--primary {
    background: var(--accent);
    color: #fff;
}
.btn--primary:hover {
    background: var(--accent-hover);
}
```

- [ ] **Step 2: Add card hover transitions**

```css
.project-card {
    transition: all var(--duration-normal) var(--ease-out);
    cursor: pointer;
}
.project-card:hover {
    background: var(--bg-card-hover);
    transform: translateY(-2px);
    box-shadow: var(--shadow-hover);
}
```

- [ ] **Step 3: Add sidebar item transitions**

```css
.sidebar__item {
    transition: background var(--duration-fast) var(--ease-out);
}
.sidebar__item:hover {
    background: var(--bg-card);
}
.sidebar__item.active {
    background: var(--accent-subtle);
    border-left: 3px solid var(--accent);
}
```

- [ ] **Step 4: Add toolbar button states**

```css
.toolbar__btn {
    transition: all var(--duration-fast) var(--ease-out);
}
.toolbar__btn:hover {
    background: var(--bg-card);
    color: var(--text-primary);
}
.toolbar__btn.active {
    background: var(--accent-subtle);
    color: var(--accent);
}
```

---

### Task 4: Skeleton Loading States

**Covers:** S3

**Files:**
- Modify: `AssetsManager/lan/static/app.js`
- Modify: `AssetsManager/lan/static/style.css`

- [ ] **Step 1: Update skeleton function in app.js**

```javascript
function skeleton(count = 6) {
    let html = '';
    for (let i = 0; i < count; i++) {
        html += `<div class="project-card skeleton-card" style="animation-delay: ${i * 50}ms">
            <div class="skeleton" style="height: 140px; border-radius: var(--radius-md) var(--radius-md) 0 0;"></div>
            <div style="padding: 12px;">
                <div class="skeleton" style="height: 16px; width: 70%; margin-bottom: 8px; border-radius: 4px;"></div>
                <div class="skeleton" style="height: 12px; width: 40%; border-radius: 4px;"></div>
            </div>
        </div>`;
    }
    return html;
}
```

- [ ] **Step 2: Add skeleton card CSS**

```css
.skeleton-card {
    padding: 0;
    overflow: hidden;
    animation: fadeUp var(--duration-slow) var(--ease-out) both;
}
```

---

### Task 5: Test and Verify

**Covers:** S1-S6

- [ ] **Step 1: Run quality gate**

```bash
python -m ruff check . --exclude ".Cython&Noikta" && python -m pyright && python -m pytest -q
```

- [ ] **Step 2: Manual verification checklist**

- [ ] Icons render as SVG (not emoji)
- [ ] Inter font loads correctly
- [ ] Card hover animations smooth (150-300ms)
- [ ] Skeleton shimmer visible during load
- [ ] Focus rings visible on Tab navigation
- [ ] Button press feedback (scale 0.97)
- [ ] Reduced-motion disables animations
- [ ] Mobile responsive still works
- [ ] i18n still works

