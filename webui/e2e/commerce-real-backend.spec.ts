import { stat } from 'node:fs/promises';
import { test, expect } from '@playwright/test';

interface CommerceItem {
  id: string | number;
  title: string;
  path?: string;
  cover_path?: string | null;
  gallery_paths?: string[];
  enabled?: boolean;
  status?: string;
}

interface CommerceItemsResponse {
  items?: CommerceItem[];
}

const baseUrl = process.env.REAL_COMMERCE_BASE_URL?.replace(/\/+$/, '') ?? '';
const sellerUsername = process.env.REAL_COMMERCE_SELLER_USERNAME ?? 'admin';
const sellerPassword = process.env.REAL_COMMERCE_SELLER_PASSWORD ?? '';


function canonicalCommercePath(rawPath: string): string {
  return rawPath.replace(/\\/g, '/').split('/').filter(segment => segment && segment !== '.').join('/');
}

function encodeCommercePath(rawPath: string): string {
  return canonicalCommercePath(rawPath).split('/').map(segment => encodeURIComponent(segment)).join('/');
}

test.describe('real backend Commerce acceptance', () => {
  test('exposes read-only path detail and public media contracts', async ({ browser }) => {
    test.skip(!baseUrl, 'Set REAL_COMMERCE_BASE_URL to run the optional read-only real-backend contract check.');
    const context = await browser.newContext({ locale: 'en-US' });
    const buyer = await context.newPage();

    try {
      const catalogResponse = await buyer.request.get(`${baseUrl}/api/shop/items`);
      expect(catalogResponse.ok()).toBeTruthy();
      const catalog = await catalogResponse.json() as CommerceItemsResponse;
      const item = catalog.items?.find(candidate => candidate.enabled !== false && (candidate.status === undefined || candidate.status === 'active'));
      expect(item, 'the real backend must expose at least one active Commerce item').toBeDefined();
      if (!item) return;

      const directPath = canonicalCommercePath(item.path ?? '');
      if (directPath) {
        const byPathResponse = await buyer.request.get(`${baseUrl}/api/shop/items/by-path`, {
          params: { path: directPath },
        });
        expect(byPathResponse.ok()).toBeTruthy();
        const byPathPayload = await byPathResponse.json() as {
          item?: { id?: string | number; title?: string };
        };
        expect(String(byPathPayload.item?.id)).toBe(String(item.id));
        expect(byPathPayload.item?.title).toBe(item.title);

        const pageResponse = await buyer.goto(`${baseUrl}/storefront/product/path/${encodeCommercePath(directPath)}`, {
          waitUntil: 'domcontentloaded',
        });
        expect(pageResponse?.ok()).toBeTruthy();
        await expect(buyer.getByRole('heading', { name: item.title })).toBeVisible();
      }

      if (typeof item.cover_path === 'string' && item.cover_path.trim()) {
        const mediaResponse = await buyer.request.get(
          `${baseUrl}/api/shop/items/${encodeURIComponent(String(item.id))}/media/cover`,
          { params: { size: '64' } },
        );
        expect(mediaResponse.ok()).toBeTruthy();
        expect(mediaResponse.headers()['content-type'] ?? '').toMatch(/^image\//);
      }

      const galleryIndex = item.gallery_paths?.findIndex(path => typeof path === 'string' && path.trim()) ?? -1;
      if (galleryIndex >= 0) {
        const mediaResponse = await buyer.request.get(
          `${baseUrl}/api/shop/items/${encodeURIComponent(String(item.id))}/media/gallery-${galleryIndex}`,
          { params: { size: '64' } },
        );
        expect(mediaResponse.ok()).toBeTruthy();
        expect(mediaResponse.headers()['content-type'] ?? '').toMatch(/^image\//);
      }
    } finally {
      await context.close();
    }
  });

  test('completes buyer checkout, seller fulfillment, and buyer delivery', async ({ browser }) => {
    test.skip(
      !baseUrl || !sellerPassword,
      'Set REAL_COMMERCE_BASE_URL and REAL_COMMERCE_SELLER_PASSWORD to run the optional real-backend checkout flow.',
    );
    const buyerContext = await browser.newContext({ locale: 'en-US', acceptDownloads: true });
    const sellerContext = await browser.newContext({ locale: 'en-US' });
    const buyer = await buyerContext.newPage();
    const seller = await sellerContext.newPage();

    try {
      const catalogResponse = await buyer.request.get(`${baseUrl}/api/shop/items`);
      expect(catalogResponse.ok()).toBeTruthy();
      const catalog = await catalogResponse.json() as CommerceItemsResponse;
      const item = catalog.items?.find(candidate => candidate.enabled !== false && (candidate.status === undefined || candidate.status === 'active'));
      expect(item, 'the real backend must expose at least one active Commerce item').toBeDefined();
      if (!item) return;

      await buyer.goto(`${baseUrl}/storefront/product/${encodeURIComponent(String(item.id))}`, { waitUntil: 'networkidle' });
      await expect(buyer.getByRole('heading', { name: item.title })).toBeVisible();
      await buyer.getByRole('button', { name: 'Add to cart' }).click();
      await expect(buyer.getByRole('status')).toBeVisible();
      await buyer.getByRole('link', { name: 'Cart' }).last().click();
      await expect(buyer.getByRole('heading', { name: 'Your cart' })).toBeVisible();
      await buyer.getByRole('button', { name: 'Checkout' }).click();
      await buyer.waitForURL(/\/storefront\/checkout\/group\?group=/);

      const checkoutGroupUrl = buyer.url();
      await buyer.getByRole('link', { name: 'Order details' }).click();
      await buyer.waitForURL(/\/storefront\/checkout\/[^/]+$/);
      await buyer.getByRole('button', { name: 'Continue' }).click();
      await expect(buyer.getByText('confirmed', { exact: true })).toBeVisible();

      await seller.goto(`${baseUrl}/seller`, { waitUntil: 'networkidle' });
      await seller.locator('#seller-username').fill(sellerUsername);
      await seller.locator('#seller-password').fill(sellerPassword);
      await seller.getByRole('button', { name: 'Login' }).click();
      await expect(seller.getByRole('heading', { name: 'Good to see you.' })).toBeVisible();
      await seller.goto(`${baseUrl}/seller/orders`, { waitUntil: 'networkidle' });
      await expect(seller.getByText(item.title, { exact: true })).toBeVisible();
      await seller.getByRole('table').getByRole('button', { name: 'Paid', exact: true }).click();
      await expect(seller.getByRole('link', { name: 'Delivery link' })).toBeVisible();

      await buyer.goto(checkoutGroupUrl, { waitUntil: 'networkidle' });
      const deliveryButton = buyer.getByRole('button', { name: 'Delivery' });
      await expect(deliveryButton).toBeVisible();
      const downloadPromise = buyer.waitForEvent('download');
      await deliveryButton.click();
      const download = await downloadPromise;
      const downloadedPath = await download.path();
      expect(download.suggestedFilename()).toMatch(/\.zip$/i);
      expect(downloadedPath).not.toBeNull();
      if (downloadedPath) {
        expect((await stat(downloadedPath)).size).toBeGreaterThan(0);
      }
    } finally {
      await buyerContext.close();
      await sellerContext.close();
    }
  });
});

