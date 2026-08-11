import { expect, test, type Page, type Route } from '@playwright/test';

const sellerInfo = {
  version: 'e2e',
  share_name: 'Seller E2E',
  library_root: '/tmp/library',
  auth_enabled: false,
  auth_mode: 'none',
  theme_color: '#7c3aed',
  welcome_msg: 'Seller E2E',
  footer_text: 'Seller E2E',
  library_stats: { total_projects: 1, total_size: 0, total_size_fmt: '0 B' },
  feature_flags: { commerce: true, seller: true, quota: true },
  principal: {
    kind: 'guest', authenticated: false, role: 'guest', display_name: 'Guest',
    capabilities: { browse: true, preview: true, download: true, upload: false, manage_links: false, manage_users: false, settings: false, realtime: false },
  },
};

const products = [
  { id: 101, path: 'packs/aurora-ui.zip', title: 'Aurora UI Pack', description: 'A seller-managed UI asset pack.', price_cents: 12900, currency: 'USD', cover_path: 'packs/aurora-cover.png', gallery_paths: [], enabled: true, status: 'active', downloads: 42, created_at: 1_754_600_000, updated_at: 1_754_600_000 },
  { id: 102, path: 'drafts/launch-icons.zip', title: 'Launch Icons Draft', description: 'A draft product.', price_cents: 4900, currency: 'USD', cover_path: null, gallery_paths: [], enabled: true, status: 'draft', downloads: 0, created_at: 1_754_600_000, updated_at: 1_754_600_000 },
];

const orders = [{ id: 501, item_title: 'Aurora UI Pack', item_path: 'packs/aurora-ui.zip', amount_cents: 12900, currency: 'USD', status: 'confirmed', created_at: 1_754_600_000 }];
const emptyCart = { cart: { id: 1, owner_type: 'anonymous', status: 'active', version: 1, items: [], subtotal_cents: 0, currency: 'USD' } };
const emptyWishlist = { items: [] };

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

async function installSellerMocks(page: Page, options: { catalogStatus?: number } = {}) {
  let authenticated = false;

  await page.route('**/api/**', route => json(route, { error: 'Unmocked seller E2E API request' }, 404));
  await page.route('**/api/info', route => json(route, sellerInfo));
  await page.route('**/api/auth/seller-status', route => json(route, { enabled: true, authenticated }));
  await page.route('**/api/auth/seller-login', async route => { authenticated = true; await json(route, { ok: true }); });
  await page.route('**/api/auth/seller-logout', async route => { authenticated = false; await json(route, { ok: true }); });
  await page.route('**/api/shop/items**', route => json(route, { items: products }, options.catalogStatus ?? 200));
  await page.route('**/api/shop/orders**', route => json(route, { orders }));
  await page.route('**/api/shop/stats**', route => json(route, { stats: { total_orders: 7, gross_cents: 98765, store_views: 1234 } }));
  await page.route('**/api/shop/seller-profile**', route => json(route, { profile: { store_name: 'Seller E2E Store', contact_email: 'seller@example.test', description: 'Seller E2E profile', accept_orders: true } }));
  await page.route('**/api/shop/cart**', route => json(route, emptyCart));
  await page.route('**/api/shop/wishlist**', route => json(route, emptyWishlist));
}

test.describe('Seller portal', () => {
  test('seller can log in and reach the dashboard with stats and recent activity', async ({ page }) => {
    await installSellerMocks(page);
    await page.goto('/seller');
    await expect(page).toHaveURL(/\/seller$/);
    await expect(page.getByRole('heading', { name: 'Login' })).toBeVisible();

    await page.locator('#seller-username').fill('seller-admin');
    await page.locator('#seller-password').fill('seller-secret');
    await page.getByRole('button', { name: 'Login' }).click();

    await expect(page.getByRole('heading', { name: 'Good to see you.' })).toBeVisible();
    await expect(page.getByText('Total revenue')).toBeVisible();
    await expect(page.getByText('$987.65')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Recent activity' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Aurora UI Pack' })).toBeVisible();
  });

  test('dashboard navigation opens the seller products catalog', async ({ page }) => {
    await installSellerMocks(page);
    await page.goto('/seller');
    await page.getByRole('heading', { name: 'Login' }).waitFor();
    await page.locator('#seller-password').fill('seller-secret');
    await page.getByRole('button', { name: 'Login' }).click();
    await expect(page.getByRole('heading', { name: 'Good to see you.' })).toBeVisible();

    await page.getByRole('link', { name: 'Products', exact: true }).click();
    await expect(page).toHaveURL(/\/seller\/products$/);
    await expect(page.getByRole('heading', { name: 'Products' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Aurora UI Pack' })).toBeVisible();
    await expect(page.getByText('Launch Icons Draft')).toBeVisible();
  });

  test('catalog API failure does not blank the seller dashboard', async ({ page }) => {
    await installSellerMocks(page, { catalogStatus: 503 });
    await page.goto('/seller');
    await page.getByRole('heading', { name: 'Login' }).waitFor();
    await page.locator('#seller-password').fill('seller-secret');
    await page.getByRole('button', { name: 'Login' }).click();

    await expect(page.getByRole('heading', { name: 'Good to see you.' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Recent activity' })).toBeVisible();
    await expect(page.getByText('Your catalog is empty')).toBeVisible();
    await expect(page.locator('text=Uncaught Error')).toHaveCount(0);
  });
});


