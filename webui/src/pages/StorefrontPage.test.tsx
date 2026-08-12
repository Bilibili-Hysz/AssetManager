// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { StorefrontData, StorefrontProduct } from '../components/storefront/types';

const { shopApiMock, catalogMock, i18nMock, authMock } = vi.hoisted(() => ({
  shopApiMock: {
    recordStorefrontView: vi.fn(async () => ({ ok: true })),
    getPublicProfile: vi.fn(async () => ({ profile: { store_name: 'My Store', description: 'Nice assets' } })),
  },
  catalogMock: { products: [] as StorefrontProduct[], loading: false, error: null, refresh: vi.fn() },
  i18nMock: { t: (key: string) => key },
  authMock: { api: {} },
}));

vi.mock('../hooks/useAuth', () => ({ useAuth: () => authMock }));
vi.mock('../api/shop', () => ({ createShopApi: () => shopApiMock }));
vi.mock('../hooks/useCommerce', () => ({ useCommerceCatalog: () => catalogMock }));
vi.mock('../hooks/useI18n', () => ({ useI18n: () => i18nMock }));
vi.mock('../components/storefront/StorefrontShell', () => ({
  StorefrontShell: ({ storeName, children }: { storeName: string; children: React.ReactNode }) => (
    <div data-testid="shell">{storeName}{children}</div>
  ),
}));

import StorefrontPage from './StorefrontPage';

const product: StorefrontProduct = {
  id: '7', slug: 'packs/hero.zip', name: 'Hero Pack', description: '',
  imageUrl: '/api/thumbnails/packs/hero.png', gallery: [], category: 'Packs', tags: [],
  price: 12.5, currency: 'CNY', downloads: 3, featured: true, status: 'active',
};

const storefrontData: StorefrontData = {
  name: 'Injected Store', description: 'Injected description', tagline: 'Tagline',
  products: [product], categories: [{ id: 'Packs', name: 'Packs', count: 1 }],
};

describe('StorefrontPage', () => {
  beforeEach(() => {
    shopApiMock.recordStorefrontView.mockClear();
    shopApiMock.getPublicProfile.mockClear();
    catalogMock.products = [];
  });

  afterEach(() => cleanup());

  it('renders the injected storefront data without depending on the network', () => {
    render(<MemoryRouter><StorefrontPage storefront={storefrontData} /></MemoryRouter>);
    expect(screen.getByText('Injected Store')).toBeDefined();
    expect(screen.getByRole('heading', { name: 'Tagline' })).toBeDefined();
    expect(screen.getByText('Hero Pack')).toBeDefined();
  });

  it('records the store view once on mount', async () => {
    render(<MemoryRouter><StorefrontPage storefront={storefrontData} /></MemoryRouter>);
    await vi.waitFor(() => expect(shopApiMock.recordStorefrontView).toHaveBeenCalledTimes(1));
  });

  it('loads the seller profile for the store name when not injected', async () => {
    render(<MemoryRouter><StorefrontPage /></MemoryRouter>);
    await vi.waitFor(() => expect(shopApiMock.getPublicProfile).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(screen.getByTestId('shell').textContent).toContain('My Store'));
  });

  it('shows the empty state when the catalog has no products', () => {
    render(<MemoryRouter><StorefrontPage /></MemoryRouter>);
    expect(screen.getByText('commerce.no_products_title')).toBeDefined();
  });
});
