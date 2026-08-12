// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import StorefrontProductPage from './StorefrontProductPage';
import { ApiError } from '../api/errors';

const { catalogState, buyerState, shopApi, toStorefrontProduct } = vi.hoisted(() => ({
  catalogState: {
    products: [] as Array<Record<string, unknown>>,
    loading: true,
    error: null as unknown,
    refresh: vi.fn(),
  },
  buyerState: {
    addToCart: vi.fn(),
    addToWishlist: vi.fn(),
    removeFromWishlist: vi.fn(),
    isWishlisted: vi.fn(() => false),
  },
  shopApi: {
    createOrder: vi.fn(),
    getItem: vi.fn(),
    getItemByPath: vi.fn(),
  },
  toStorefrontProduct: vi.fn((item: any) => ({
    id: String(item.id),
    slug: String(item.path ?? item.id),
    name: String(item.title ?? item.id),
    description: String(item.description ?? ''),
    imageUrl: '',
    gallery: [],
    category: 'Asset',
    price: Number(item.price_cents ?? 0) / 100,
    currency: String(item.currency ?? 'USD'),
    downloads: 0,
    status: 'active' as const,
  })),
}));

const api = { buildUrl: (path: string) => '/api/' + path };

vi.mock('../hooks/useCommerce', () => ({ useCommerceCatalog: () => catalogState, toStorefrontProduct, canonicalizeShopPath: (value: unknown) => {
  if (typeof value !== 'string') return null;
  const raw = value.trim().replace(/\\/g, '/');
  if (!raw || raw.startsWith('/') || /^[A-Za-z]:($|\/)/.test(raw)) return null;
  const parts: string[] = [];
  for (const part of raw.split('/')) {
    if (!part || part === '.') continue;
    if (part === '..') return null;
    parts.push(part);
  }
  return parts.length ? parts.join('/') : null;
} }));
vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ api }) }));
vi.mock('../api/shop', () => ({ createShopApi: () => shopApi }));
vi.mock('../stores/ShopBuyerContext', () => ({ useShopBuyer: () => buyerState }));
vi.mock('../components/storefront/StorefrontShell', () => ({
  StorefrontShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('../components/viewer/ImageViewer', () => ({ ImageViewer: () => null }));
vi.mock('../components/ui/Modal', () => ({ Modal: () => null }));
vi.mock('../components/ui/Toast', () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock('../hooks/useI18n', () => ({
  useI18n: () => ({
    t: (key: string, ...args: unknown[]) => ({
      'commerce.store': 'Storefront',
      'commerce.back_to_store': 'Back to store',
      'commerce.product_loading': 'Loading product...',
      'commerce.product_load_failed': 'Could not load product',
      'commerce.product_load_failed_description': 'Try again or return to the store.',
      'commerce.product_not_found': 'Product not found',
      'commerce.product_not_found_description': 'This product is unavailable.',
      'commerce.digital_asset': 'Digital asset',
      'commerce.product_description_fallback': 'Description',
      'commerce.standard_license': 'Standard license',
      'commerce.free': 'Free',
      'commerce.buy_now': 'Buy now',
      'commerce.add_to_cart': 'Add to cart',
      'commerce.save': 'Save',
      'commerce.secure_checkout': 'Secure checkout',
      'commerce.instant_access': 'Instant access',
      'commerce.downloads_count': '{0} downloads',
      'commerce.confirm_purchase': 'Confirm purchase',
      'commerce.purchase_summary': 'Purchase {0} for {1}',
      'commerce.continue': 'Continue',
      'action.cancel': 'Cancel',
      'gallery.retry': 'Retry',
      'browse.loading': 'Loading...',
      'detail.images': 'Images',
    }[key] ?? (args.length ? key + ' ' + args.join(' ') : key)),
  }),
}));

const product = {
  id: '7',
  slug: 'assets/example.zip',
  name: 'Example asset',
  description: 'A downloadable asset',
  price: 12,
  currency: 'USD',
  imageUrl: undefined,
  gallery: [],
  category: 'Reference',
  license: 'Standard license',
  downloads: 3,
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/storefront/product/7']}>
      <Routes>
        <Route path="/storefront/product/:id" element={<StorefrontProductPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>(resolvePromise => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function detailResponse(id: number, title: string) {
  return {
    item: {
      id,
      path: 'assets/' + id + '.zip',
      title,
      description: 'A downloadable asset',
      price_cents: 1200,
      currency: 'USD',
      cover_path: null,
      gallery_paths: [],
      enabled: true,
      metadata: {},
      status: 'active' as const,
      created_at: 1,
      updated_at: 1,
    },
  };
}

function NavigableProductPage() {
  const navigate = useNavigate();
  return <>
    <button type="button" onClick={() => navigate('/storefront/product/8')}>Navigate</button>
    <StorefrontProductPage />
  </>;
}

function renderPathPage(path = 'packs/example.zip') {
  return render(
    <MemoryRouter initialEntries={[`/storefront/product/path/${path}`]}>
      <Routes>
        <Route path="/storefront/product/path/*" element={<StorefrontProductPage />} />
      </Routes>
    </MemoryRouter>,
  );
}
function renderNavigablePage() {
  return render(
    <MemoryRouter initialEntries={['/storefront/product/7']}>
      <Routes>
        <Route path="/storefront/product/:id" element={<NavigableProductPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('StorefrontProductPage catalog lifecycle', () => {
  beforeEach(() => {
    catalogState.products = [];
    catalogState.loading = true;
    catalogState.error = null;
    catalogState.refresh.mockReset();
    buyerState.addToCart.mockReset();
    buyerState.addToWishlist.mockReset();
    buyerState.removeFromWishlist.mockReset();
    buyerState.isWishlisted.mockReset().mockReturnValue(false);
    shopApi.createOrder.mockReset();
    shopApi.getItem.mockReset().mockRejectedValue(new ApiError('Not found', 404));
    shopApi.getItemByPath.mockReset().mockRejectedValue(new ApiError('Not found', 404));
  });

  afterEach(() => {
    cleanup();
  });

  it('does not report a missing product while the catalog is loading', () => {
    renderPage();

    expect(screen.getByRole('status').textContent).toContain('Loading product...');
    expect(screen.queryByText('Product not found')).toBeNull();
  });

  it('shows a retryable error instead of treating catalog failure as not found', () => {
    catalogState.loading = false;
    catalogState.error = new Error('network failure');
    renderPage();

    expect(screen.getByRole('alert').textContent).toContain('Could not load product');
    expect(screen.queryByText('Product not found')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(catalogState.refresh).toHaveBeenCalledTimes(1);
  });

  it('renders the matching product after the catalog settles', () => {
    catalogState.loading = false;
    catalogState.products = [product];
    renderPage();

    expect(screen.getByRole('heading', { name: 'Example asset' })).toBeDefined();
    expect(screen.queryByText('Product not found')).toBeNull();
  });

  it('loads an active product detail when it is outside the catalog response', async () => {
    catalogState.loading = false;
    catalogState.products = [];
    shopApi.getItem.mockResolvedValue({
      item: {
        id: 7,
        path: 'assets/example.zip',
        title: 'Example asset',
        description: 'A downloadable asset',
        price_cents: 1200,
        currency: 'USD',
        cover_path: null,
        gallery_paths: [],
        enabled: true,
        metadata: {},
        status: 'active',
        created_at: 1,
        updated_at: 1,
      },
    });
    renderPage();

    expect(await screen.findByRole('heading', { name: 'Example asset' })).toBeDefined();
    expect(shopApi.getItem).toHaveBeenCalledWith('7');
  });

  it('ignores a stale detail response after the route changes', async () => {
    catalogState.loading = false;
    const first = deferred<ReturnType<typeof detailResponse>>();
    const second = deferred<ReturnType<typeof detailResponse>>();
    shopApi.getItem.mockImplementation((itemId: string) => itemId === '7' ? first.promise : second.promise);
    renderNavigablePage();

    await waitFor(() => expect(shopApi.getItem).toHaveBeenCalledWith('7'));
    fireEvent.click(screen.getByRole('button', { name: 'Navigate' }));
    await waitFor(() => expect(shopApi.getItem).toHaveBeenCalledWith('8'));

    await act(async () => {
      first.resolve(detailResponse(7, 'Stale asset'));
    });
    expect(screen.queryByRole('heading', { name: 'Stale asset' })).toBeNull();

    await act(async () => {
      second.resolve(detailResponse(8, 'Current asset'));
    });
    expect(await screen.findByRole('heading', { name: 'Current asset' })).toBeDefined();
  });

  it('loads a wildcard path through the by-path endpoint after the catalog settles', async () => {
    catalogState.loading = false;
    shopApi.getItemByPath.mockResolvedValue({
      item: {
        id: 17,
        path: 'packs/example.zip',
        title: 'Path asset',
        description: 'A path addressed asset',
        price_cents: 1200,
        currency: 'USD',
        cover_path: null,
        gallery_paths: [],
        enabled: true,
        metadata: {},
        status: 'active',
        created_at: 1,
        updated_at: 1,
      },
    });
    renderPathPage();

    expect(await screen.findByRole('heading', { name: 'Path asset' })).toBeDefined();
    expect(shopApi.getItemByPath).toHaveBeenCalledWith('packs/example.zip');
    expect(shopApi.getItem).not.toHaveBeenCalled();
  });

  it('canonicalizes a valid path route before lookup and comparison', async () => {
    catalogState.loading = false;
    shopApi.getItemByPath.mockResolvedValue({
      item: {
        id: 17,
        path: 'packs/example.zip',
        title: 'Canonical path asset',
        description: 'A normalized path asset',
        price_cents: 1200,
        currency: 'USD',
        cover_path: null,
        gallery_paths: [],
        enabled: true,
        metadata: {},
        status: 'active',
        created_at: 1,
        updated_at: 1,
      },
    });
    renderPathPage('packs//./example.zip');

    expect(await screen.findByRole('heading', { name: 'Canonical path asset' })).toBeDefined();
    expect(shopApi.getItemByPath).toHaveBeenCalledWith('packs/example.zip');
  });

  it('does not request an unsafe parent path', async () => {
    catalogState.loading = false;
    renderPathPage('packs/../example.zip');

    expect(await screen.findByText('Product not found')).toBeDefined();
    expect(shopApi.getItemByPath).not.toHaveBeenCalled();
  });

  it('ignores a stale wildcard path response after the route changes', async () => {
    catalogState.loading = false;
    const first = deferred<ReturnType<typeof detailResponse>>();
    const second = deferred<ReturnType<typeof detailResponse>>();
    shopApi.getItemByPath.mockImplementation((path: string) => path === 'packs/first.zip' ? first.promise : second.promise);
    function NavigablePathPage() {
      const navigate = useNavigate();
      return <>
        <button type="button" onClick={() => navigate('/storefront/product/path/packs/second.zip')}>Navigate path</button>
        <StorefrontProductPage />
      </>;
    }
    render(
      <MemoryRouter initialEntries={['/storefront/product/path/packs/first.zip']}>
        <Routes><Route path="/storefront/product/path/*" element={<NavigablePathPage />} /></Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(shopApi.getItemByPath).toHaveBeenCalledWith('packs/first.zip'));
    fireEvent.click(screen.getByRole('button', { name: 'Navigate path' }));
    await waitFor(() => expect(shopApi.getItemByPath).toHaveBeenCalledWith('packs/second.zip'));

    await act(async () => { first.resolve(detailResponse(17, 'Stale path asset')); });
    expect(screen.queryByRole('heading', { name: 'Stale path asset' })).toBeNull();
    await act(async () => { second.resolve({ ...detailResponse(18, 'Current path asset'), item: { ...detailResponse(18, 'Current path asset').item, path: 'packs/second.zip' } }); });
    expect(await screen.findByRole('heading', { name: 'Current path asset' })).toBeDefined();
  });
  it('only shows not found after a settled catalog has no matching product', async () => {
    catalogState.loading = false;
    renderPage();

    expect(await screen.findByText('Product not found')).toBeDefined();
  });
});
