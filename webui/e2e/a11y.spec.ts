import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

/**
 * Automated WCAG 2.1 AA gate: every route below renders against mocked APIs
 * (same pattern as webui-shell.spec.ts) and must produce zero axe-core
 * violations for the A/AA rule tags. Fixes to flagged issues belong in the
 * source, not in this file — the curated tag set is the contract.
 */

async function mockApis(page: Page) {
  const json = (body: unknown) => ({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
  await page.route('**/api/info', route => route.fulfill(json({
    version: 'test',
    share_name: 'Test Library',
    library_root: '/library',
    auth_enabled: true,
    auth_mode: 'password',
    theme_color: '#6366f1',
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

for (const route of ROUTES) {
  for (const theme of ['dark', 'light'] as const) {
    test(`axe scan is clean: ${route} (${theme})`, async ({ page }) => {
      await mockApis(page);
      await page.addInitScript(value => localStorage.setItem('am_theme', value), theme);
      await page.goto(route);
      // Let route-level lazy content settle before scanning.
      await page.waitForTimeout(1000);
      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
        .analyze();
      expect(
        results.violations.map(v => ({
          id: v.id, impact: v.impact, help: v.help,
          nodes: v.nodes.map(n => ({ target: n.target, summary: n.failureSummary })),
        })),
        `axe violations on ${route} (${theme})`,
      ).toEqual([]);
    });
  }
}
