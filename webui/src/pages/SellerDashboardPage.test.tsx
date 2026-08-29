// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SellerDashboardPage, { deliveryQuotaBarColor, deliveryQuotaRatio } from './SellerDashboardPage';

const { catalogState, orderState, quotaState } = vi.hoisted(() => ({
  catalogState: {
    products: [] as Array<{ id: string; name: string; price: number; imageUrl: string; status?: 'active' | 'draft' | 'archived' }>,
  },
  orderState: {
    orders: [] as Array<{ id: string; productName: string; amount: number; currency?: string; status: 'paid' | 'pending' | 'refunded' | 'failed'; createdAt: string }>,
    stats: { revenue: 0, orders: 0, products: 0, views: undefined as number | undefined },
  },
  quotaState: {
    quota: undefined as
      | { enabled: boolean; used: number; limit: number; delivery_tokens: number; download_limit: number; downloads_used: number; downloads_remaining: number; period: string; remaining: number; reset_at: number | null; min_interval_seconds: number }
      | undefined,
  },
}));

vi.mock('../hooks/useCommerce', () => ({
  useSellerCommerceCatalog: () => ({ ...catalogState, loading: false, error: null, refresh: vi.fn() }),
  useSellerCommerceOrders: () => ({ ...orderState, loading: false, refresh: vi.fn() }),
  useSellerDeliveryQuota: () => ({ quota: quotaState.quota, loading: false, refresh: vi.fn() }),
}));
vi.mock('../components/storefront/StorefrontShell', () => ({
  StorefrontShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('../components/storefront/ProductCard', () => ({
  ProductCard: ({ product }: { product: { id: string; name: string } }) => (
    <article>
      <a href={`/seller/products/${product.id}`}>{product.name}</a>
    </article>
  ),
  EmptyState: ({ title, description, action }: { title: string; description: string; action?: React.ReactNode }) => (
    <div role="status"><h3>{title}</h3><p>{description}</p>{action}</div>
  ),
}));
vi.mock('../hooks/useI18n', () => ({
  useI18n: () => ({
    t: (key: string) => ({
      'seller.portal': 'Seller Studio',
      'seller.workspace': 'Seller workspace',
      'seller.dashboard_title': 'Good to see you.',
      'seller.dashboard_subtitle': 'Keep your catalog sharp and your store moving.',
      'seller.view_store': 'View store',
      'seller.add_product': 'Add product',
      'seller.overview': 'Store overview',
      'seller.total_revenue': 'Total revenue',
      'seller.orders': 'Orders',
      'seller.active_products': 'Active products',
      'seller.store_views': 'Store views',
      'seller.delivery_quota': 'Delivery quota',
      'seller.analytics_unavailable': 'Not tracked by the current backend.',
      'seller.recent_products': 'Recent products',
      'seller.recent_activity': 'Recent activity',
      'seller.no_products_title': 'Your catalog is empty',
      'seller.no_products_description': 'Add your first product to start building your storefront.',
      'seller.no_activity': 'No recent activity yet.',
      'commerce.view_all': 'View all',
      'seller.status_paid': 'Paid',
      'seller.status_pending': 'Pending',
      'seller.status_refunded': 'Refunded',
      'seller.status_failed': 'Failed',
    }[key] ?? key),
  }),
}));

afterEach(() => cleanup());

describe('SellerDashboardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    quotaState.quota = undefined;
    catalogState.products = [
      { id: 'product-1', name: 'First asset', price: 12.5, imageUrl: '', status: 'active' },
      { id: 'product-2', name: 'Second asset', price: 8, imageUrl: '', status: 'draft' },
      { id: 'product-3', name: 'Third asset', price: 4, imageUrl: '', status: 'active' },
      { id: 'product-4', name: 'Fourth asset', price: 2, imageUrl: '', status: 'archived' },
      { id: 'product-5', name: 'Fifth asset', price: 1, imageUrl: '', status: 'active' },
    ];
    orderState.orders = [
      { id: 'order-1', productName: 'First asset', amount: 12.5, currency: 'USD', status: 'paid', createdAt: 'today' },
      { id: 'order-2', productName: 'Second asset', amount: 8, currency: 'USD', status: 'pending', createdAt: 'yesterday' },
      { id: 'order-3', productName: 'Third asset', amount: 4, currency: 'USD', status: 'refunded', createdAt: 'Monday' },
      { id: 'order-4', productName: 'Fourth asset', amount: 2, currency: 'USD', status: 'failed', createdAt: 'Sunday' },
      { id: 'order-5', productName: 'Fifth asset', amount: 1, currency: 'USD', status: 'paid', createdAt: 'Saturday' },
    ];
    orderState.stats = { revenue: 26.5, orders: 5, products: 0, views: 1234 };
  });

  it('renders overview stats and only the four most recent products and orders', () => {
    render(<MemoryRouter><SellerDashboardPage seller={{ displayName: 'Seller', storeName: 'North Studio' }} /></MemoryRouter>);

    expect(screen.getByRole('heading', { name: 'Good to see you.' })).toBeDefined();
    expect(screen.getByText('Total revenue').parentElement?.textContent).toContain('$26.50');
    expect(screen.getByText('Orders').parentElement?.textContent).toContain('5');
    expect(screen.getByText('Active products').parentElement?.textContent).toContain('3');
    expect(screen.getByText('Store views').parentElement?.textContent).toContain('1,234');

    expect(screen.getAllByText('First asset')).toHaveLength(2);
    expect(screen.getAllByText('Fourth asset')).toHaveLength(2);
    expect(screen.queryByText('Fifth asset')).toBeNull();
    expect(screen.getAllByText(/asset/).length).toBe(8);
    expect(screen.getAllByText(/Paid/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Pending/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Refunded/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Failed/).length).toBeGreaterThan(0);
  });

  it('uses explicit page data and exposes dashboard navigation targets', () => {
    const onNavigate = vi.fn();
    render(
      <MemoryRouter>
        <SellerDashboardPage
          seller={{ displayName: 'Seller' }}
          products={[{ id: 'explicit-product', name: 'Explicit asset', price: 3, imageUrl: '', status: 'active' }]}
          orders={[{ id: 'explicit-order', productName: 'Explicit asset', amount: 3, status: 'paid', createdAt: 'now' }]}
          stats={{ revenue: 3, orders: 1, products: 1, views: undefined }}
          onNavigate={onNavigate}
        />
      </MemoryRouter>,
    );

    expect(screen.getAllByText('Explicit asset')).toHaveLength(2);
    expect(screen.queryByText('First asset')).toBeNull();
    expect(screen.getByRole('link', { name: 'View store' }).getAttribute('href')).toBe('/storefront');
    expect(screen.getByRole('link', { name: 'View all' }).getAttribute('href')).toBe('/seller/products');
    const addProduct = screen.getByRole('link', { name: 'Add product' });
    expect(addProduct.getAttribute('href')).toBe('/seller/products/new');
    fireEvent.click(addProduct);
    expect(onNavigate).toHaveBeenCalledWith('/seller/products/new');
    expect(screen.getByText('Store views').parentElement?.textContent).toContain('—');
    expect(screen.getByText('—').getAttribute('title')).toBe('Not tracked by the current backend.');
  });

  it('renders the delivery quota card with used/limit and a progress bar when quota is enabled', () => {
    quotaState.quota = {
      enabled: true, used: 12, limit: 20, delivery_tokens: 3, download_limit: 20,
      downloads_used: 12, downloads_remaining: 8, period: 'daily', remaining: 8,
      reset_at: null, min_interval_seconds: 0,
    };
    render(<MemoryRouter><SellerDashboardPage /></MemoryRouter>);

    expect(screen.getByText('Delivery quota')).toBeDefined();
    expect(screen.getByText('12 / 20')).toBeDefined();
    const bar = screen.getByRole('progressbar', { name: 'Delivery quota' });
    expect(bar.getAttribute('aria-valuemax')).toBe('20');
    expect(bar.getAttribute('aria-valuenow')).toBe('12');
    const fill = bar.firstElementChild as HTMLElement | null;
    expect(fill?.style.width).toBe('60%');
  });

  it('hides the delivery quota card when the quota is disabled or unavailable', () => {
    quotaState.quota = {
      enabled: false, used: 0, limit: 0, delivery_tokens: 0, download_limit: 0,
      downloads_used: 0, downloads_remaining: 0, period: 'daily', remaining: 0,
      reset_at: null, min_interval_seconds: 0,
    };
    render(<MemoryRouter><SellerDashboardPage /></MemoryRouter>);
    expect(screen.queryByRole('progressbar')).toBeNull();
    expect(screen.queryByText('Delivery quota')).toBeNull();

    cleanup();
    quotaState.quota = undefined;
    render(<MemoryRouter><SellerDashboardPage /></MemoryRouter>);
    expect(screen.queryByRole('progressbar')).toBeNull();
    expect(screen.queryByText('Delivery quota')).toBeNull();
  });

  it('renders empty states for a catalog and activity feed with no data', () => {
    catalogState.products = [];
    orderState.orders = [];
    orderState.stats = { revenue: 0, orders: 0, products: 0, views: undefined };
    render(<MemoryRouter><SellerDashboardPage /></MemoryRouter>);

    expect(screen.getByRole('heading', { name: 'Recent products' })).toBeDefined();
    expect(screen.getByRole('heading', { name: 'Your catalog is empty' })).toBeDefined();
    expect(screen.getByText('Add your first product to start building your storefront.')).toBeDefined();
    expect(screen.getByText('No recent activity yet.')).toBeDefined();
    expect(screen.getAllByRole('link', { name: 'Add product' }).length).toBe(2);
  });

  it('colors the quota bar with semantic tokens as usage approaches the limit', () => {
    expect(deliveryQuotaRatio(12, 20)).toBeCloseTo(0.6);
    expect(deliveryQuotaRatio(0, 0)).toBe(0);
    expect(deliveryQuotaRatio(5, 0)).toBe(0);
    expect(deliveryQuotaRatio(30, 20)).toBe(1);
    expect(deliveryQuotaBarColor(0.5)).toBe('var(--color-accent)');
    expect(deliveryQuotaBarColor(0.8)).toBe('var(--color-warning)');
    expect(deliveryQuotaBarColor(0.95)).toBe('var(--color-danger)');
  });
});