import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

/**
 * Automated WCAG 2.1 AA gate: every route below renders against mocked APIs
 * (same pattern as webui-shell.spec.ts) and must produce zero axe-core
 * violations for the A/AA rule tags. Fixes to flagged issues belong in the
 * source, not in this file — the curated tag set is the contract.
 */

async function mockApis(page: Page, options: { authEnabled?: boolean } = {}) {
  const authEnabled = options.authEnabled ?? false;
  const json = (body: unknown) => ({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
  await page.route('**/api/info', route => route.fulfill(json({
    version: 'test',
    share_name: 'Test Library',
    library_root: '/library',
    // Auth disabled by default: ProtectedRoute renders the real workspace
    // pages for the guest principal instead of redirecting to /login (which
    // would make the /browse, /detail and /gallery scans silently scan the
    // login page). The /login scan opts back in to render the real login UI.
    auth_enabled: authEnabled,
    auth_mode: authEnabled ? 'password' : 'none',
    // Shipped server default: AssetsManager/core/constants.py
    // DEFAULT_LAN_THEME_COLOR. Text usages bind to the contrast-safe
    // --color-accent-text token, so any server accent stays decorative.
    theme_color: '#5b7ff5',
    welcome_msg: '',
    footer_text: '',
    feature_flags: { commerce: true, seller: true, quota: true },
    library_stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' },
    principal: {
      kind: 'guest', authenticated: false, role: 'guest', display_name: 'Guest',
      capabilities: { browse: true, preview: true, download: true, upload: false,
        manage_links: false, manage_users: false, settings: false, realtime: false },
    },
  })));
  await page.route('**/api/quota', route => route.fulfill(json({ enabled: false })));
  await page.route('**/api/home', route => route.fulfill(json({
    recent_projects: [], preview_pool: [], popular_tags: [],
    stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' },
  })));
  await page.route('**/api/gallery/home', route => route.fulfill(json({
    featured: null, collections: [], projects: [], recent: [],
    stats: { collections: 0, projects: 0, artworks: 0, total_size_fmt: '0 B' },
  })));
  await page.route('**/api/favorites', route => route.fulfill(json({ favorites: [] })));
  await page.route('**/api/files**', route => route.fulfill(json({ current_path: '', items: [] })));
  await page.route('**/api/tags**', route => route.fulfill(json({ tags: [] })));
  await page.route('**/api/search**', route => route.fulfill(json({ results: [], count: 0 })));
  await page.route('**/api/projects/**', route => route.fulfill(json({
    name: 'asset', path: 'asset', tags: [], notes: '', urls: [], total_size: 0,
    total_size_fmt: '0 B', file_count: 0, files: [], images: [], thumbnail_url: null, modified: 0,
  })));
  await page.route('**/api/meta/**', route => route.fulfill(json({
    path: 'asset', tags: [], notes: '', urls: [],
  })));
  await page.route('**/api/shop/catalog**', route => route.fulfill(json({
    items: [], page: 1, page_size: 24, total: 0,
  })));
  await page.route('**/api/shop/items**', route => route.fulfill(json({ items: [] })));
  await page.route('**/api/shop/profile**', route => route.fulfill(json({ profile: { name: 'Test Shop', description: '', accepts_orders: true } })));
  await page.route('**/api/shop/seller-profile**', route => route.fulfill(json({ profile: { name: 'Test Shop' } })));
  await page.route('**/api/shop/stats**', route => route.fulfill(json({ stats: {} })));
  await page.route('**/api/shop/orders**', route => route.fulfill(json({ orders: [] })));
  await page.route('**/api/auth/seller-status', route => route.fulfill(json({ enabled: true, authenticated: true })));
  await page.route('**/api/shop/analytics/**', route => route.fulfill(json({ ok: true })));
  // API coverage that drifted from the workspace pages (proxy would otherwise
  // hit the real LAN server at 127.0.0.1:8080 and fail the scans).
  await page.route('**/api/auth/me', route => route.fulfill(json({
    principal: {
      kind: 'guest', authenticated: false, role: 'guest', display_name: 'Guest',
      capabilities: { browse: true, preview: true, download: true, upload: false,
        manage_links: false, manage_users: false, settings: false, realtime: false },
    },
    user: null,
  })));
  await page.route('**/api/gallery/collection**', route => route.fulfill(json({
    items: [], total: 0, page: 1, page_size: 24,
  })));
  await page.route('**/api/shop/cart', route => route.fulfill(json({ items: [], total_cents: 0 })));
  await page.route('**/api/shop/wishlist', route => route.fulfill(json({ items: [] })));
  await page.route('**/api/stats', route => route.fulfill(json({})));
  await page.route('**/api/tree**', route => route.fulfill(json({
    tree: [], depth_config: { global: 3, branches: {} },
  })));
}

const ROUTES = [
  '/',
  '/login',
  '/browse',
  '/gallery',
  '/gallery/collection',
  '/gallery/favorites',
  '/storefront',
  '/storefront/products',
  '/detail?path=asset.png',
  '/seller/products',
];

/** Wait for the React shell, then one bounded task-turn for lazy effects. */
async function settleApp(page: Page) {
  await page.waitForFunction(() => (document.querySelector('#root')?.childElementCount ?? 0) > 0);
  // Mocked APIs resolve in microtasks; give effects one extra turn to commit
  // route-level lazy content before the scan.
  await page.waitForTimeout(300);
}

async function expectCleanScan(page: Page, label: string) {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
  expect(
    results.violations.map(v => ({
      id: v.id, impact: v.impact, help: v.help,
      nodes: v.nodes.map(n => ({ target: n.target, summary: n.failureSummary })),
    })),
    `axe violations on ${label}`,
  ).toEqual([]);
}

for (const route of ROUTES) {
  for (const theme of ['dark', 'light'] as const) {
    test(`axe scan is clean: ${route} (${theme})`, async ({ page }) => {
      await mockApis(page, { authEnabled: route === '/login' });
      await page.addInitScript(value => localStorage.setItem('am_theme', value), theme);
      await page.goto(route);
      await settleApp(page);
      await expectCleanScan(page, `${route} (${theme})`);
    });
  }
}

// Interaction states the initial-render scans cannot see. Keep this list
// deliberately short: every entry needs an interaction step and must be
// deterministic in the mocked-app environment.
test('axe scan is clean: tuning panel open (dark)', async ({ page }) => {
  await mockApis(page);
  await page.addInitScript(value => localStorage.setItem('am_theme', value), 'dark');
  await page.goto('/');
  await settleApp(page);
  await page.getByRole('button', { name: 'Background tuning' }).click();
  await expect(page.getByRole('dialog', { name: 'Background tuning' })).toBeVisible();
  await expectCleanScan(page, 'tuning panel open (dark)');
});

test('axe scan is clean: language menu open (dark)', async ({ page }) => {
  await mockApis(page);
  await page.addInitScript(value => localStorage.setItem('am_theme', value), 'dark');
  await page.goto('/browse');
  await settleApp(page);
  await page.getByRole('button', { name: 'Language' }).click();
  await expect(page.getByRole('menu')).toBeVisible();
  await expectCleanScan(page, 'language menu open (dark)');
});

test('axe scan is clean: command palette open (dark)', async ({ page }) => {
  await mockApis(page);
  await page.addInitScript(value => localStorage.setItem('am_theme', value), 'dark');
  await page.goto('/gallery');
  await settleApp(page);
  await page.keyboard.press('Control+K');
  await expect(page.getByRole('dialog', { name: 'Command palette' })).toBeVisible();
  await expectCleanScan(page, 'command palette open (dark)');
});

// Modal open state: ShareDialog is the cheapest Modal.tsx surface to reach
// with the guest mocks (browse list → context menu → Share). Route-level
// scans cannot see a dialog, which is exactly how the transparent modal
// scrim (undefined --color-overlay token) previously slipped through.
test('axe scan is clean: share dialog open (dark)', async ({ page }) => {
  await mockApis(page);
  // One file row so the context menu has a target; list view keeps the row
  // layout deterministic across viewport sizes. (mockApis' json helper is
  // function-scoped, so this override spells the fulfillment out inline.)
  await page.route('**/api/files**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      current_path: 'assets',
      items: [{
        name: 'asset.png', path: 'assets/asset.png', type: 'file', size: 1024,
        size_fmt: '1 KB', modified: 0, extension: '.png', category: 'image', is_project: false,
      }],
    }),
  }));
  await page.addInitScript(value => localStorage.setItem('am_view', value), 'list');
  await page.addInitScript(value => localStorage.setItem('am_theme', value), 'dark');
  await page.goto('/browse');
  await settleApp(page);
  await page.getByText('asset.png').first().click({ button: 'right' });
  await page.getByRole('menuitem', { name: 'Share' }).click();
  await expect(page.getByRole('dialog', { name: 'Create Share Link' })).toBeVisible();
  await expectCleanScan(page, 'share dialog open (dark)');

  // Regression guard for the transparent-scrim bug: the Modal overlay element
  // (the dialog's fixed parent) must paint an actual background color.
  const overlayBackground = await page.evaluate(() => {
    const overlay = document.querySelector('[role="dialog"]')?.parentElement;
    return overlay ? getComputedStyle(overlay).backgroundColor : null;
  });
  expect(overlayBackground, 'modal overlay element not found').toBeTruthy();
  expect(
    overlayBackground === 'transparent' || overlayBackground === 'rgba(0, 0, 0, 0)',
    `modal overlay background is transparent: ${overlayBackground}`,
  ).toBe(false);
});
