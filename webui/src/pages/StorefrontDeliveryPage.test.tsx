// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import StorefrontDeliveryPage from './StorefrontDeliveryPage';
import { ApiError } from '../api/errors';

const { shopApi } = vi.hoisted(() => ({
  shopApi: {
    getDelivery: vi.fn(),
    deliveryDownloadUrl: vi.fn(),
    claimDelivery: vi.fn(),
    getOrder: vi.fn(),
    downloadOrderDelivery: vi.fn(),
  },
}));

const api = { buildUrl: (path: string) => '/api/' + path };

vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ api }) }));
vi.mock('../api/shop', () => ({ createShopApi: () => shopApi }));
vi.mock('../components/storefront/StorefrontShell', () => ({
  StorefrontShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('../components/ui/Toast', () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock('../hooks/useI18n', () => ({
  useI18n: () => ({
    t: (key: string) => ({
      'commerce.store': 'Storefront',
      'commerce.back_to_store': 'Back to store',
      'commerce.instant_access': 'Instant access',
      'commerce.digital_asset': 'Digital asset',
      'commerce.download_started': 'Download started',
      'commerce.product_not_found': 'Product not found',
      'commerce.product_not_found_description': 'This product is unavailable.',
      'commerce.delivery_claim_invalid': 'This delivery link is invalid or has already been used.',
      'commerce.delivery_claim_recover_hint': 'Restore access from your order history, or check out again.',
      'commerce.delivery_claim_recover_link': 'Restore from order history',
      'commerce.continue_shopping': 'Continue shopping',
      'error.rate_limited': 'Too many requests. Please wait.',
      'gallery.retry': 'Retry',
      'browse.loading': 'Loading...',
      'action.download': 'Download',
    }[key] ?? key),
  }),
}));

function renderPage(token = 'token-a') {
  return render(
    <MemoryRouter initialEntries={['/storefront/delivery/' + token]}>
      <Routes>
        <Route path="/storefront/delivery/:token" element={<StorefrontDeliveryPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('StorefrontDeliveryPage', () => {
  beforeEach(() => {
    shopApi.getDelivery.mockReset();
    shopApi.deliveryDownloadUrl.mockReset().mockReturnValue('/api/shop/delivery/token-a/download');
    shopApi.claimDelivery.mockReset();
    shopApi.getOrder.mockReset();
    shopApi.downloadOrderDelivery.mockReset();
  });

  afterEach(() => cleanup());

  it('shows loading and then renders a fulfilled delivery link', async () => {
    let resolve!: (value: unknown) => void;
    const pending = new Promise(resolvePromise => { resolve = resolvePromise; });
    shopApi.getDelivery.mockReturnValue(pending);
    renderPage();

    expect(screen.getByRole('heading', { name: 'Loading...' })).toBeDefined();
    expect(shopApi.deliveryDownloadUrl).toHaveBeenCalledWith('token-a');
    expect(shopApi.claimDelivery).not.toHaveBeenCalled();

    await act(async () => {
      resolve({
        filename: 'bundle.zip',
        is_directory: false,
        download_url: '/legacy/download',
        order: { download_count: 2, max_downloads: 5 },
      });
    });

    expect(await screen.findByRole('heading', { name: 'bundle.zip' })).toBeDefined();
    expect(screen.getByRole('link', { name: 'Download' }).getAttribute('href')).toBe('/api/shop/delivery/token-a/download');
    expect(screen.getByText('2 / 5')).toBeDefined();
  });

  it('renders an alert when the delivery token cannot be resolved', async () => {
    shopApi.getDelivery.mockRejectedValue(new Error('expired'));
    renderPage();

    await waitFor(() => expect(screen.getByRole('alert')).toBeDefined());
    expect(screen.getByRole('heading', { name: 'Product not found' })).toBeDefined();
  });

  it('exchanges a one-time share claim and shows the receipt-channel download', async () => {
    shopApi.claimDelivery.mockResolvedValue({ ok: true });
    shopApi.getOrder.mockResolvedValue({
      order: {
        id: 7,
        item_id: 1,
        item_title: 'bundle.zip',
        amount_cents: 1200,
        currency: 'USD',
        status: 'fulfilled',
        delivery_available: true,
        created_at: 0,
        updated_at: 0,
      },
    });
    renderPage('order-7?claim=abc123def456ghi789jkl012mno345');

    expect(shopApi.claimDelivery).toHaveBeenCalledWith('order-7', 'abc123def456ghi789jkl012mno345');
    expect(await screen.findByRole('heading', { name: 'bundle.zip' })).toBeDefined();
    expect(shopApi.getOrder).toHaveBeenCalledWith('order-7');
    expect(screen.getByRole('button', { name: 'Download' })).toBeDefined();
  });

  it('shows an invalid-claim notice with recovery guidance when the claim answers 404', async () => {
    shopApi.claimDelivery.mockRejectedValue(new ApiError('not found', 404));
    renderPage('order-7?claim=used-claim');

    await waitFor(() => expect(screen.getByRole('alert')).toBeDefined());
    expect(screen.getByRole('heading', { name: 'Product not found' })).toBeDefined();
    expect(screen.getByText('This delivery link is invalid or has already been used.')).toBeDefined();
    expect(screen.getByText('Restore access from your order history, or check out again.')).toBeDefined();
    expect(screen.getByRole('link', { name: 'Restore from order history' }).getAttribute('href')).toBe('/storefront/orders');
    expect(screen.getByRole('link', { name: 'Continue shopping' }).getAttribute('href')).toBe('/storefront/products');
  });

  it('shows the rate-limited notice instead of the invalid-claim copy when the claim answers 429', async () => {
    shopApi.claimDelivery.mockRejectedValue(new ApiError('rate limited', 429));
    renderPage('order-7?claim=throttled-claim');

    await waitFor(() => expect(screen.getByRole('alert')).toBeDefined());
    expect(screen.getByText('Too many requests. Please wait.')).toBeDefined();
    expect(screen.queryByText('This delivery link is invalid or has already been used.')).toBeNull();
    expect(screen.queryByText('Restore access from your order history, or check out again.')).toBeNull();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeDefined();
  });

  it('leaves the legacy flow untouched when a claim parameter is absent', async () => {
    shopApi.getDelivery.mockResolvedValue({
      filename: 'legacy.zip',
      is_directory: true,
      download_url: '/legacy/download',
      order: { download_count: 0, max_downloads: 3 },
    });
    renderPage('token-a');

    expect(await screen.findByRole('heading', { name: 'legacy.zip' })).toBeDefined();
    expect(shopApi.claimDelivery).not.toHaveBeenCalled();
    expect(shopApi.getOrder).not.toHaveBeenCalled();
  });
});
