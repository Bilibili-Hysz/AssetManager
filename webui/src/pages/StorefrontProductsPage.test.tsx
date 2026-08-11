// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import StorefrontProductsPage from './StorefrontProductsPage';

const catalogMocks = vi.hoisted(() => ({
  calls: [] as Array<Record<string, unknown>>,
  state: {
    products: [
      { id: 'zeta', name: 'Zeta', description: 'Server order', price: 1, currency: 'USD', imageUrl: '', gallery: [], status: 'active' },
      { id: 'alpha', name: 'Alpha', description: 'Server order', price: 99, currency: 'USD', imageUrl: '', gallery: [], status: 'active' },
      { id: 'beta', name: 'Beta', description: 'Server order', price: 2, currency: 'USD', imageUrl: '', gallery: [], status: 'active' },
    ],
    page: 2,
    pageSize: 10,
    total: 31,
    loading: false,
    error: null as unknown,
    refresh: vi.fn(),
  },
}));

vi.mock('../hooks/useCommerce', () => ({
  useCommerceCatalogPage: (params: Record<string, unknown>) => {
    catalogMocks.calls.push(params);
    return catalogMocks.state;
  },
}));

vi.mock('../hooks/useI18n', () => ({
  useI18n: () => ({
    t: (key: string, ...args: Array<string | number>) => ({
      'commerce.search': 'Search',
      'commerce.marketplace_label': 'Marketplace',
      'commerce.browse_assets': 'Browse assets',
      'commerce.browse_assets_description': 'Browse',
      'commerce.sell_yours': 'Sell yours',
      'commerce.results_count': `${args[0]} results`,
      'commerce.sort_by': 'Sort by',
      'commerce.sort_newest': 'Newest',
      'commerce.page_size': 'Per page',
      'commerce.pagination': 'Catalog pagination',
      'commerce.previous_page': 'Previous page',
      'commerce.next_page': 'Next page',
      'commerce.page_of': `Page ${args[0]} of ${args[1]}`,
      'commerce.no_search_results': 'No matching assets',
      'commerce.no_search_results_description': 'Try another keyword.',
      'commerce.no_products_title': 'No assets',
      'commerce.no_products_description': 'No products.',
      'commerce.clear_search': 'Clear search',
      'browse.loading': 'Loading...',
      'browse.error': 'Failed to load files',
      'landing.retry': 'Retry',
      'commerce.product_load_failed_description': 'Could not load catalog.',
    }[key] ?? key),
  }),
}));

vi.mock('../components/storefront/StorefrontShell', () => ({
  StorefrontShell: ({ children, searchValue, onSearch }: { children: React.ReactNode; searchValue?: string; onSearch?: (value: string) => void }) => (
    <div>
      <form role="search" onSubmit={event => { event.preventDefault(); onSearch?.((event.currentTarget.elements.namedItem('search') as HTMLInputElement).value); }}>
        <input name="search" aria-label="Search" defaultValue={searchValue ?? ''} />
      </form>
      {children}
    </div>
  ),
}));

vi.mock('../components/storefront/ProductCard', () => ({
  ProductCard: ({ product }: { product: { name: string } }) => <article data-testid="product-card">{product.name}</article>,
  EmptyState: ({ title, description, action }: { title: string; description: string; action?: React.ReactNode }) => <div data-testid="empty-state"><h2>{title}</h2><p>{description}</p>{action}</div>,
}));

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}

function renderPage(initialEntry = '/storefront/products?q=alpha&page=2&page_size=10') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <LocationProbe />
      <StorefrontProductsPage />
    </MemoryRouter>,
  );
}

describe('StorefrontProductsPage server Catalog integration', () => {
  beforeEach(() => {
    catalogMocks.calls = [];
    catalogMocks.state.products = [
      { id: 'zeta', name: 'Zeta', description: 'Server order', price: 1, currency: 'USD', imageUrl: '', gallery: [], status: 'active' },
      { id: 'alpha', name: 'Alpha', description: 'Server order', price: 99, currency: 'USD', imageUrl: '', gallery: [], status: 'active' },
      { id: 'beta', name: 'Beta', description: 'Server order', price: 2, currency: 'USD', imageUrl: '', gallery: [], status: 'active' },
    ];
    catalogMocks.state.page = 2;
    catalogMocks.state.pageSize = 10;
    catalogMocks.state.total = 31;
    catalogMocks.state.loading = false;
    catalogMocks.state.error = null;
    catalogMocks.state.refresh.mockReset();
  });

  afterEach(() => cleanup());

  it('passes URL state to the server hook and preserves server order/total without local filtering', () => {
    renderPage();

    expect(catalogMocks.calls[0]).toEqual({ q: 'alpha', page: 2, page_size: 10, sort: 'newest' });
    expect(screen.getByText('31 results')).toBeDefined();
    expect(screen.getAllByTestId('product-card').map(node => node.textContent)).toEqual(['Zeta', 'Alpha', 'Beta']);
    expect(screen.queryByRole('combobox')).toBeDefined();
    expect(screen.queryByText('Featured')).toBeNull();
  });

  it('changes URL page and re-requests instead of slicing the current products', () => {
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
    expect(screen.getByTestId('location').textContent).toBe('/storefront/products?q=alpha&page=3&page_size=10');
    expect(catalogMocks.calls[catalogMocks.calls.length - 1]).toEqual({ q: 'alpha', page: 3, page_size: 10, sort: 'newest' });
  });

  it('resets page to one when the Header search changes', () => {
    renderPage();

    const input = screen.getByRole('textbox', { name: 'Search' });
    fireEvent.change(input, { target: { value: 'beta' } });
    fireEvent.submit(screen.getByRole('search'));

    expect(screen.getByTestId('location').textContent).toBe('/storefront/products?q=beta&page_size=10');
    expect(catalogMocks.calls[catalogMocks.calls.length - 1]).toEqual({ q: 'beta', page: 1, page_size: 10, sort: 'newest' });
  });

  it('renders loading and retryable error states from the server hook', () => {
    catalogMocks.state.loading = true;
    catalogMocks.state.products = [];
    renderPage('/storefront/products');
    expect(screen.getByText('Loading...')).toBeDefined();
    cleanup();

    catalogMocks.state.loading = false;
    catalogMocks.state.error = new Error('catalog failed');
    renderPage('/storefront/products');
    expect(screen.getByText('Failed to load files')).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(catalogMocks.state.refresh).toHaveBeenCalledTimes(1);
  });
});