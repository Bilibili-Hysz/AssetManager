// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SellerDashboardPage from './SellerDashboardPage';

const { catalogState, orderState } = vi.hoisted(() => ({
  catalogState: {
    products: [] as Array<{ id: string; name: string; price: number; imageUrl: string; status?: 'active' | 'draft' | 'archived' }>,
  },
  orderState: {
    orders: [] as Array<{ id: string; productName: string; amount: number; currency?: string; status: 'paid' | 'pending' | 'refunded' | 'failed'; createdAt: string }>,
    stats: { revenue: 0, orders: 0, products: 0, views: undefined as number | undefined },
  },
}));

vi.mock('../hooks/useCommerce', () => ({
  useCommerceCatalog: () => ({ ...catalogState, loading: false, error: null, refresh: vi.fn() }),
  useCommerceOrders: () => ({ ...orderState, loading: false, refresh: vi.fn() }),
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
});