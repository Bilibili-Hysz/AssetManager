/**
 * D10 (dialect unification P3, 2026-09-04): the shared E2E LAN API mock
 * fixtures.
 *
 * The three Playwright specs each carried a hand-rolled `page.route`
 * fulfillment for the same endpoints, with drifting shapes (theme_color,
 * feature_flags, principal presence). This module is the single mock
 * vocabulary for `page.route`-based specs; field shapes follow the live
 * runtime DTOs (`AssetsManager/lan/dto.py`, mirrored by
 * `src/types/contracts.ts`).
 *
 * Generation (`gen_web_mocks.py`) was evaluated and deliberately deferred:
 * the backend golden (`tests/contracts/lan_public_contracts.json`) covers
 * the ServerInfo DTO subset without the `principal` envelope the runtime
 * `/api/info` actually returns — a generated factory needs a runtime-shape
 * export that does not exist yet. Until that lands, hand-maintained shapes
 * live HERE (one place) instead of in three specs (three places).
 */
import type { Page, Route } from '@playwright/test';

/** Minimal guest principal shared by every auth-disabled mock. */
export const guestPrincipal = {
  kind: 'guest',
  authenticated: false,
  role: 'guest',
  display_name: 'Guest',
  capabilities: {
    browse: true,
    preview: true,
    download: true,
    upload: false,
    manage_links: false,
    manage_users: false,
    settings: false,
    realtime: false,
  },
} as const;

/** Full runtime `/api/info` envelope (DTO fields + principal). */
export function infoBody(overrides: Record<string, unknown> = {}) {
  return {
    version: 'test',
    share_name: 'Test Library',
    library_root: '/library',
    auth_enabled: false,
    auth_mode: 'none',
    // Shipped dark default (Assets/Themes/D_Navy.json) — exercises the
    // follow-the-owner theme identity.
    theme_color: '#5b7ff5',
    theme_name: 'Navy',
    welcome_msg: '',
    footer_text: '',
    feature_flags: { quota: true },
    library_stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' },
    principal: guestPrincipal,
    ...overrides,
  };
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

/**
 * Install the standard guest-workspace mock set used by the shell/a11y
 * specs: info, quota, home, gallery home, favorites, files, tags, search,
 * project detail, meta, auth/me, gallery collection, stats, tree.
 *
 * ``authEnabled`` flips the info envelope to the password mode the /login
 * scans need (ProtectedRoute then renders the real login UI instead of the
 * workspace).
 */
export async function mockGuestWorkspaceApis(
  page: Page,
  options: { authEnabled?: boolean } = {},
) {
  const authEnabled = options.authEnabled ?? false;
  await page.route('**/api/info', route => json(route, infoBody({
    // Auth disabled by default: ProtectedRoute renders the real workspace
    // pages for the guest principal instead of redirecting to /login.
    auth_enabled: authEnabled,
    auth_mode: authEnabled ? 'password' : 'none',
  })));
  await page.route('**/api/quota', route => json(route, { enabled: false }));
  await page.route('**/api/home', route => json(route, {
    recent_projects: [], preview_pool: [], popular_tags: [],
    stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' },
  }));
  await page.route('**/api/gallery/home', route => json(route, {
    featured: null, collections: [], projects: [], recent: [],
    stats: { collections: 0, projects: 0, artworks: 0, total_size_fmt: '0 B' },
  }));
  await page.route('**/api/favorites', route => json(route, { favorites: [] }));
  await page.route('**/api/files**', route => json(route, { current_path: '', items: [] }));
  await page.route('**/api/tags**', route => json(route, { tags: [] }));
  await page.route('**/api/search**', route => json(route, { results: [], count: 0 }));
  await page.route('**/api/projects/**', route => json(route, {
    name: 'asset', path: 'asset', tags: [], notes: '', urls: [], total_size: 0,
    total_size_fmt: '0 B', file_count: 0, files: [], images: [], thumbnail_url: null, modified: 0,
  }));
  await page.route('**/api/meta/**', route => json(route, {
    path: 'asset', tags: [], notes: '', urls: [],
  }));
  await page.route('**/api/auth/me', route => json(route, {
    principal: guestPrincipal,
    user: null,
  }));
  await page.route('**/api/gallery/collection**', route => json(route, {
    items: [], total: 0, page: 1, page_size: 24,
  }));
  await page.route('**/api/stats', route => json(route, {}));
  await page.route('**/api/tree**', route => json(route, {
    tree: [], depth_config: { global: 3, branches: {} },
  }));
}
