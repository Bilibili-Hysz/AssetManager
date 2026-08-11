import { test, expect, type Page } from '@playwright/test';

const ONE_PIXEL_PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=', 'base64');

const item = {
  id: 7,
  path: 'assets/hero.png',
  title: 'Hero Pack',
  description: 'A polished pack.',
  price_cents: 1200,
  currency: 'CNY',
  cover_path: 'assets/hero.png',
  gallery_paths: ['assets/hero-detail.png'],
  enabled: true,
  metadata: {},
  status: 'active',
  created_at: 1_700_000_000,
  updated_at: 1_700_000_000,
};

type MockCommerceOptions = {
  catalogItems?: typeof item[];
};

async function mockCommerceApis(page: Page, options: MockCommerceOptions = {}) {
  let cart = {
    id: 1,
    owner_type: 'anonymous',
    status: 'active',
    version: 1,
    expires_at: null,
    created_at: 1_700_000_000,
    updated_at: 1_700_000_000,
    items: [],
  };
  let wishlist: unknown[] = [];
  const catalogItems = options.catalogItems ?? [item];
  const mediaRequests: string[] = [];
  const catalogRequests: URL[] = [];
  let itemListRequests = 0;
  await page.route('**/api/info', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      version: 'test',
      share_name: 'Test Library',
      library_root: '/library',
      auth_enabled: false,
      auth_mode: 'none',
      theme_color: '#6366f1',
      welcome_msg: '',
      footer_text: '',
      feature_flags: { commerce: true, seller: false, quota: false },
      principal: {
        kind: 'guest', authenticated: false, role: 'guest', display_name: 'Guest',
        capabilities: { browse: true, preview: true, download: true, upload: false, manage_links: false, manage_users: false, settings: false, realtime: false },
      },
    }),
  }));
  await page.route('**/api/shop/catalog**', async route => {
    const url = new URL(route.request().url());
    catalogRequests.push(url);
    const search = url.searchParams.get('q')?.trim().toLowerCase();
    const filtered = search
      ? catalogItems.filter(candidate => `${candidate.title} ${candidate.description}`.toLowerCase().includes(search))
      : catalogItems;
    const requestedPage = Math.max(Number(url.searchParams.get('page') ?? '1') || 1, 1);
    const requestedPageSize = Math.min(Math.max(Number(url.searchParams.get('page_size') ?? '24') || 24, 1), 100);
    const offset = (requestedPage - 1) * requestedPageSize;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: filtered.slice(offset, offset + requestedPageSize),
        page: requestedPage,
        page_size: requestedPageSize,
        total: filtered.length,
      }),
    });
  });
  await page.route('**/api/shop/items**', async route => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname.includes('/items/') && pathname.includes('/media/')) {
      mediaRequests.push(pathname);
      await route.fulfill({ status: 200, contentType: 'image/png', body: ONE_PIXEL_PNG });
      return;
    }
    if (pathname.endsWith('/items')) {
      itemListRequests += 1;
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: catalogItems }) });
      return;
    }
    await route.continue();
  });
  await page.route('**/api/thumbnails/**', route => route.fulfill({ status: 200, contentType: 'image/png', body: ONE_PIXEL_PNG }));
  await page.route('**/api/shop/profile', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ profile: { store_name: 'Test Store', description: 'Test', accept_orders: true } }) }));
  await page.route('**/api/shop/analytics/store-view', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) }));
  await page.route('**/api/shop/cart', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ cart }) }));
  await page.route('**/api/shop/cart/items', async route => {
    if (route.request().method() === 'POST') {
      cart = { ...cart, version: cart.version + 1, items: [{ id: 9, item_id: 7, quantity: 1, unit_price_cents: 1200, currency: 'CNY', path: item.path, title: item.title, line_status: 'active', created_at: 1_700_000_000, updated_at: 1_700_000_000 }] };
    }
    await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ cart }) });
  });
  await page.route('**/api/shop/wishlist/items/**', async route => {
    if (route.request().method() === 'PUT') {
      wishlist = [{ item_id: 7, added_at: 1_700_000_000, path: item.path, title: item.title, price_cents: 1200, currency: 'CNY', availability: 'available' }];
    } else if (route.request().method() === 'DELETE') {
      wishlist = [];
    }
    await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ items: wishlist }) });
  });
  await page.route('**/api/shop/wishlist', async route => {
    if (route.request().method() === 'DELETE') wishlist = [];
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: wishlist }) });
  });
  return { mediaRequests, catalogRequests, getItemListRequests: () => itemListRequests };
}

test('storefront product exposes gallery, cart, and wishlist controls', async ({ page }) => {
  const { mediaRequests } = await mockCommerceApis(page);
  await page.goto('/storefront/product/7');
  await expect(page.getByRole('heading', { name: 'Hero Pack' })).toBeVisible();
  await expect.poll(() => mediaRequests).toEqual(expect.arrayContaining([
    '/api/shop/items/7/media/cover',
    '/api/shop/items/7/media/gallery-0',
  ]));
  await expect(page.getByRole('button', { name: 'Hero Pack 2' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Add to cart' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save' })).toBeVisible();
  await page.getByRole('button', { name: 'Add to cart' }).click();
  await expect(page.getByRole('status')).toContainText('Added to cart');
  await page.getByRole('link', { name: 'Cart' }).last().click();
  await expect(page.getByRole('heading', { name: 'Your cart' })).toBeVisible();
  await expect(page.getByText('Hero Pack')).toBeVisible();
});

test('storefront products uses server Catalog pagination and preserves response order', async ({ page }) => {
  const secondItem = {
    ...item,
    id: 8,
    path: 'assets/second.png',
    title: 'Second Pack',
    cover_path: 'assets/second.png',
    created_at: 1_700_000_001,
    updated_at: 1_700_000_001,
  };
  const { catalogRequests, getItemListRequests } = await mockCommerceApis(page, {
    catalogItems: [item, secondItem],
  });

  await page.goto('/storefront/products?page=2&page_size=1');
  await expect(page.getByRole('link', { name: 'Second Pack' })).toBeVisible();
  await expect(page.getByText('2 results')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Previous page' })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Next page' })).toBeDisabled();

  expect(catalogRequests).toHaveLength(1);
  expect(catalogRequests[0].searchParams.get('page')).toBe('2');
  expect(catalogRequests[0].searchParams.get('page_size')).toBe('1');
  expect(catalogRequests[0].searchParams.get('sort')).toBe('newest');
  expect(catalogRequests[0].searchParams.get('category')).toBeNull();
  expect(getItemListRequests()).toBe(0);
});

test('cart checkout opens the whole checkout group receipt', async ({ page }) => {
  await mockCommerceApis(page);
  await page.route('**/api/shop/cart/checkout', async route => {
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        checkout_group_id: 'checkout-group-test',
        idempotent: false,
        status: 'converted',
        orders: [{
          id: 101,
          item_id: 7,
          item_title: item.title,
          amount_cents: 2400,
          currency: 'CNY',
          status: 'pending',
          delivery_available: false,
          quantity: 2,
          unit_price_cents: 1200,
          created_at: 1_700_000_000,
          updated_at: 1_700_000_000,
        }],
        cart: {
          id: 1,
          owner_type: 'anonymous',
          status: 'converted',
          version: 3,
          expires_at: null,
          created_at: 1_700_000_000,
          updated_at: 1_700_000_000,
          items: [],
        },
      }),
    });
  });
  await page.route('**/api/shop/cart/checkout/checkout-group-test', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        checkout_group_id: 'checkout-group-test',
        idempotent: true,
        status: 'converted',
        created_at: 1_700_000_000,
        orders: [{
          id: 101,
          item_id: 7,
          item_title: item.title,
          amount_cents: 2400,
          currency: 'CNY',
          status: 'pending',
          delivery_available: false,
          quantity: 2,
          unit_price_cents: 1200,
          created_at: 1_700_000_000,
          updated_at: 1_700_000_000,
        }],
        cart: {
          id: 1,
          owner_type: 'anonymous',
          status: 'converted',
          version: 3,
          expires_at: null,
          created_at: 1_700_000_000,
          updated_at: 1_700_000_000,
          items: [],
        },
      }),
    });
  });

  await page.goto('/storefront/product/7');
  await page.getByRole('button', { name: 'Add to cart' }).click();
  await page.getByRole('link', { name: 'Cart' }).last().click();
  await expect(page.getByRole('heading', { name: 'Your cart' })).toBeVisible();
  await page.getByRole('button', { name: 'Checkout' }).click();

  await expect(page).toHaveURL(/\/storefront\/checkout\/group\?group=checkout-group-test$/);
  await expect(page.getByRole('heading', { name: 'Checkout complete' })).toBeVisible();
  await expect(page.getByText('Hero Pack')).toBeVisible();
  await expect(page.getByRole('cell', { name: '2', exact: true })).toBeVisible();
});


test('wishlist save and remove actions update the buyer wishlist', async ({ page }) => {
  await mockCommerceApis(page);
  await page.goto('/storefront/product/7');
  await page.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByRole('status')).toContainText('Saved to your wishlist');

  await page.goto('/storefront/wishlist');
  await expect(page.getByRole('heading', { name: 'Saved assets' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Hero Pack' })).toBeVisible();
  await page.getByRole('button', { name: 'Remove from wishlist Hero Pack' }).click();
  await expect(page.getByRole('heading', { name: 'Nothing saved yet' })).toBeVisible();
});

test('fulfilled checkout group downloads buyer delivery from the real receipt UI', async ({ page }) => {
  await mockCommerceApis(page);
  let deliveryRequestKey = '';
  await page.route('**/api/shop/cart/checkout/checkout-group-delivery', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        checkout_group_id: 'checkout-group-delivery',
        idempotent: true,
        status: 'converted',
        created_at: 1_700_000_000,
        orders: [{
          id: 202,
          item_id: 7,
          item_title: item.title,
          amount_cents: 1200,
          currency: 'CNY',
          status: 'fulfilled',
          delivery_available: true,
          quantity: 1,
          unit_price_cents: 1200,
          created_at: 1_700_000_000,
          updated_at: 1_700_000_000,
        }],
        cart: {
          id: 1,
          owner_type: 'anonymous',
          status: 'converted',
          version: 3,
          expires_at: null,
          created_at: 1_700_000_000,
          updated_at: 1_700_000_000,
          items: [],
        },
      }),
    });
  });
  await page.route('**/api/shop/order/202/delivery', async route => {
    deliveryRequestKey = route.request().headers()['idempotency-key'] ?? '';
    await route.fulfill({
      status: 200,
      contentType: 'application/zip',
      headers: { 'Content-Disposition': 'attachment; filename="hero-pack.zip"' },
      body: 'mock zip payload',
    });
  });

  await page.goto('/storefront/checkout/group?group=checkout-group-delivery');
  await expect(page.getByRole('heading', { name: 'Checkout complete' })).toBeVisible();
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Delivery' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('hero-pack.zip');
  expect(deliveryRequestKey).toMatch(/^buyer-delivery-202-/);
});

test('canonical path product deep-link resolves through the by-path endpoint', async ({ page }) => {
  await mockCommerceApis(page, { catalogItems: [] });
  let requestedPath = '';
  await page.route('**/api/shop/items/by-path**', async route => {
    requestedPath = new URL(route.request().url()).searchParams.get('path') ?? '';
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ item }) });
  });

  await page.goto('/storefront/product/path/assets/hero.png');
  await expect(page).toHaveURL(/\/storefront\/product\/path\/assets\/hero\.png$/);
  await expect(page.getByRole('heading', { name: 'Hero Pack' })).toBeVisible();
  expect(requestedPath).toBe('assets/hero.png');
});
test('numeric product detail falls back to the item endpoint when catalog omits it', async ({ page }) => {
  await mockCommerceApis(page, { catalogItems: [] });
  let detailRequests = 0;
  await page.route('**/api/shop/items/7', async route => {
    detailRequests += 1;
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ item }) });
  });

  await page.goto('/storefront/product/7');
  await expect(page.getByRole('heading', { name: 'Hero Pack' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Add to cart' })).toBeVisible();
  expect(detailRequests).toBeGreaterThan(0);
});


