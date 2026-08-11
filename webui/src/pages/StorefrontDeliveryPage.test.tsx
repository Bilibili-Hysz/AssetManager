// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import StorefrontDeliveryPage from './StorefrontDeliveryPage';

const { shopApi } = vi.hoisted(() => ({
  shopApi: {
    getDelivery: vi.fn(),
    deliveryDownloadUrl: vi.fn(),
  },
}));

const api = { buildUrl: (path: string) => '/api/' + path };

vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ api }) }));
vi.mock('../api/shop', () => ({ createShopApi: () => shopApi }));
vi.mock('../components/storefront/StorefrontShell', () => ({
  StorefrontShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
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
  });

  afterEach(() => cleanup());

  it('shows loading and then renders a fulfilled delivery link', async () => {
    let resolve!: (value: unknown) => void;
    const pending = new Promise(resolvePromise => { resolve = resolvePromise; });
    shopApi.getDelivery.mockReturnValue(pending);
    renderPage();

    expect(screen.getByRole('heading', { name: 'Loading...' })).toBeDefined();
    expect(shopApi.deliveryDownloadUrl).toHaveBeenCalledWith('token-a');

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
});
