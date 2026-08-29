// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SellerProductsPage from './SellerProductsPage';

const { update, create, remove, list, refresh, showToast, catalogState, api, sellerApi, sellerRefresh } = vi.hoisted(() => ({
  update: vi.fn(),
  create: vi.fn(),
  remove: vi.fn(),
  list: vi.fn(),
  refresh: vi.fn(),
  showToast: vi.fn(),
  api: { buildUrl: (path: string) => `/api/${path}` },
  // Stable identities: the page re-runs its load effect whenever the seller
  // shop api object changes, mirroring the memoized production hook.
  sellerApi: {},
  sellerRefresh: vi.fn(),
  catalogState: {
    loading: false,
    error: null as unknown,
    products: [{ id: 'item-123', slug: 'projects/original', name: 'Original product', price: 12.5, status: 'active' as const, imageUrl: '' }],
  },
}));

vi.mock('../hooks/useCommerce', () => ({
  useSellerCommerceCatalog: () => ({ ...catalogState, refresh }),
  assetThumbnailUrl: (path: string, size: number, buildUrl: (value: string) => string) => buildUrl(`thumbnails/${encodeURIComponent(path)}?size=${size}`),
}));
vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ api }) }));
vi.mock('../stores/SellerAuthContext', () => ({ useSellerAuth: () => ({ sellerApi, refresh: sellerRefresh }) }));
vi.mock('../api/shop', () => ({ createShopApi: () => ({ update, create, remove, list }) }));
vi.mock('../components/ui/Toast', () => ({ useToast: () => ({ showToast }) }));
vi.mock('../hooks/useI18n', () => ({ useI18n: () => ({
  t: (key: string, ...args: Array<string | number>) => {
    const value = ({
      'seller.edit': 'Edit',
      'seller.add_product': 'Add product',
      'seller.portal': 'Seller Studio',
      'seller.catalog': 'Catalog',
      'seller.products_subtitle': 'Manage products',
      'seller.product': 'Product',
      'seller.amount': 'Amount',
      'seller.products_title': 'Products',
      'seller.settings_saved': 'Saved',
      'seller.product_updated': 'Product saved.',
      'seller.product_removed': 'Product removed.',
      'seller.archive_product': 'Archive',
      'seller.restore_product': 'Restore',
      'seller.delete_product_confirmation': 'Delete {0}? This cannot be undone.',
      'seller.actions': 'Actions',
      'seller.gallery_paths': 'Gallery paths',
      'seller.gallery_cover': 'Cover',
      'seller.gallery': 'Gallery',
      'seller.cover_path': 'Cover path',
      'seller.gallery_image_path': 'Gallery image path {0}',
      'seller.new_gallery_image_path': 'New gallery image path',
      'seller.gallery_paths_help': 'Manage cover and gallery paths.',
      'seller.gallery_paths_note': 'Cover and gallery paths are managed separately.',
      'seller.gallery_paths_placeholder': 'Relative image path',
      'seller.gallery_path_required': 'Path is required.',
      'seller.gallery_path_relative': 'Enter a relative image path inside the library.',
      'seller.gallery_path_duplicate_cover': 'Gallery path must differ from the cover path.',
      'seller.gallery_path_duplicate': 'Path is duplicated. Use a different image path.',
      'seller.gallery_path_duplicate_item': 'Path is duplicated. Remove the duplicate item.',
      'seller.field_path_required': 'Enter a product path.',
      'seller.field_title_required': 'Enter a product title.',
      'seller.field_price_invalid': 'Enter a price of zero or more.',
      'seller.field_gallery_limit': 'Use at most 20 gallery images.',
      'seller.gallery_preview': 'Gallery images',
      'seller.move_gallery_image_up': 'Move gallery image {0} up',
      'seller.move_gallery_image_down': 'Move gallery image {0} down',
      'seller.delete_gallery_image': 'Delete gallery image {0}',
      'info.path': 'Path',
      'info.add_tag': 'Add tag',
      'action.cancel': 'Cancel',
      'action.delete': 'Delete',
      'browse.loading': 'Loading',
      'commerce.product_not_found': 'Product not found',
      'commerce.product_not_found_description': 'This product could not be found.',
    }[key] ?? key);
    return args.reduce((result, arg, index) => String(result).replace(`{${index}}`, String(arg)), String(value));
  },
}) }));
vi.mock('../components/storefront/StorefrontShell', () => ({ StorefrontShell: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock('../components/storefront/ProductCard', () => ({
  ProductCard: ({ product, onArchive, onRestore, onRemove }: { product: { name: string; status?: string }; onArchive?: (product: { name: string; status?: string }) => void; onRestore?: (product: { name: string; status?: string }) => void; onRemove?: (product: { name: string; status?: string }) => void }) => (
    <div>
      <span>{product.name}</span>
      {product.status === 'archived' ? <button type="button" onClick={() => onRestore?.(product)}>Restore</button> : <button type="button" onClick={() => onArchive?.(product)}>Archive</button>}
      <button type="button" onClick={() => onRemove?.(product)}>Delete</button>
    </div>
  ),
  EmptyState: ({ title }: { title: string }) => <div>{title}</div>,
}));

afterEach(() => { cleanup(); });

function renderAt(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><Routes><Route path="/seller/products/:id" element={<SellerProductsPage />} /><Route path="/seller/products/new" element={<SellerProductsPage />} /><Route path="/seller/products" element={<SellerProductsPage />} /></Routes></MemoryRouter>);
}

describe('SellerProductsPage edit mode', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    catalogState.loading = false;
    catalogState.error = null;
    catalogState.products = [{ id: 'item-123', slug: 'projects/original', name: 'Original product', price: 12.5, status: 'active', imageUrl: '' }];
    update.mockResolvedValue({ item: {} });
    create.mockResolvedValue({ item: {} });
    remove.mockResolvedValue({ ok: true });
    list.mockResolvedValue({ items: [{ id: 123, path: 'projects/original', title: 'Original product', description: 'Original description', price_cents: 1250, currency: 'USD', cover_path: null, enabled: true, metadata: {}, status: 'active', created_at: 0, updated_at: 0 }] });
    refresh.mockResolvedValue(undefined);
    vi.stubGlobal('confirm', vi.fn(() => true));
  });

  it('loads the catalog asynchronously before showing an edit form', async () => {
    catalogState.loading = true;
    renderAt('/seller/products/item-123');
    expect(screen.getByText('Loading')).toBeDefined();
  });

  it('prefills and updates the product addressed by the route id', async () => {
    renderAt('/seller/products/item-123');
    expect(screen.getByDisplayValue('projects/original')).toBeDefined();
    expect(screen.getByDisplayValue('Original product')).toBeDefined();
    await waitFor(() => expect(screen.getByDisplayValue('Original description')).toBeDefined());
    expect(screen.getByDisplayValue('12.5')).toBeDefined();

    fireEvent.change(screen.getByDisplayValue('Original product'), { target: { value: 'Updated product' } });
    fireEvent.change(screen.getByDisplayValue('Original description'), { target: { value: 'Updated description' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Edit' }).closest('form')!);

    await waitFor(() => expect(update).toHaveBeenCalledWith('item-123', {
      path: 'projects/original',
      title: 'Updated product',
      description: 'Updated description',
      price_cents: 1250,
      status: 'active',
    }));
    expect(create).not.toHaveBeenCalled();
  });

  it('archives a visible active product through the real update API', async () => {
    renderAt('/seller/products');
    fireEvent.click(screen.getByRole('button', { name: 'Archive' }));

    await waitFor(() => expect(update).toHaveBeenCalledWith('item-123', { status: 'archived' }));
    expect(refresh).toHaveBeenCalled();
  });

  it('loads seller management fields with disabled products included', async () => {
    renderAt('/seller/products');

    await waitFor(() => expect(list).toHaveBeenCalledWith(undefined, true));
  });

  it('does not submit a blank title even when the submit handler is invoked directly', async () => {
    renderAt('/seller/products/new');
    fireEvent.change(screen.getByLabelText('Product'), { target: { value: '   ' } });
    fireEvent.change(screen.getByLabelText('Path'), { target: { value: 'projects/new' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Add product' }).closest('form')!);

    await waitFor(() => expect(create).not.toHaveBeenCalled());
  });

  it('shows inline field errors with aria wiring when validation fails', async () => {
    renderAt('/seller/products/new');
    // Capture the inputs before submitting: once the inline error renders
    // inside the <label>, the label text no longer equals 'Path' exactly.
    const pathInput = screen.getByLabelText('Path');
    const titleInput = screen.getByLabelText('Product');
    fireEvent.change(pathInput, { target: { value: '   ' } });
    fireEvent.change(titleInput, { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '-3' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Add product' }).closest('form')!);

    expect(await screen.findByText('Enter a product path.')).toBeDefined();
    expect(screen.getByText('Enter a product title.')).toBeDefined();
    expect(screen.getByText('Enter a price of zero or more.')).toBeDefined();
    expect(pathInput.getAttribute('aria-invalid')).toBe('true');
    expect(pathInput.getAttribute('aria-describedby')).toBe('seller-path-error');
    await waitFor(() => expect(create).not.toHaveBeenCalled());

    // Correcting a field clears its inline error immediately.
    fireEvent.change(pathInput, { target: { value: 'projects/new' } });
    expect(screen.queryByText('Enter a product path.')).toBeNull();
  });

  it('passes the backend error message through for an update failure', async () => {
    update.mockRejectedValueOnce(new Error('title must not be empty'));
    renderAt('/seller/products/item-123');
    fireEvent.submit(screen.getByRole('button', { name: 'Edit' }).closest('form')!);

    await waitFor(() => expect(showToast).toHaveBeenCalledWith('title must not be empty', 'error'));
  });

  it('converts a decimal amount to cents when creating a product', async () => {
    renderAt('/seller/products/new');
    fireEvent.change(screen.getByLabelText('Path'), { target: { value: 'projects/new' } });
    fireEvent.change(screen.getByLabelText('Product'), { target: { value: 'New product' } });
    fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '12.00' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Add product' }).closest('form')!);

    await waitFor(() => expect(create).toHaveBeenCalledWith({
      path: 'projects/new',
      title: 'New product',
      description: '',
      price_cents: 1200,
      status: 'active',
    }));
  });

  it('passes the backend error message through for a delete failure', async () => {
    remove.mockRejectedValueOnce(new Error('item is referenced by an order'));
    renderAt('/seller/products');
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    await waitFor(() => expect(showToast).toHaveBeenCalledWith('item is referenced by an order', 'error'));
  });
  it('confirms and removes a product through the real delete API', async () => {
    renderAt('/seller/products');
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    await waitFor(() => expect(remove).toHaveBeenCalledWith('item-123'));
    expect(window.confirm).toHaveBeenCalled();
    expect(refresh).toHaveBeenCalled();
  });


  it('edits cover and gallery separately, preserves order, and removes one image', async () => {
    list.mockResolvedValueOnce({ items: [{ id: 123, path: 'projects/original', title: 'Original product', description: 'Original description', price_cents: 1250, currency: 'USD', cover_path: 'projects/cover.png', gallery_paths: ['projects/one.png', 'projects/two.png'], enabled: true, metadata: {}, status: 'active', created_at: 0, updated_at: 0 }] });
    renderAt('/seller/products/item-123');

    await waitFor(() => expect(screen.getByDisplayValue('projects/cover.png')).toBeDefined());
    expect(screen.getByDisplayValue('projects/one.png')).toBeDefined();
    expect(screen.getByDisplayValue('projects/two.png')).toBeDefined();
    expect(screen.getByRole('img', { name: 'Cover: projects/cover.png' }).getAttribute('src')).toBe('/api/thumbnails/projects%2Fcover.png?size=256');

    fireEvent.click(screen.getByRole('button', { name: 'Move gallery image 2 up' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete gallery image 2' }));
    fireEvent.change(screen.getByDisplayValue('projects/cover.png'), { target: { value: 'projects/new-cover.png' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Edit' }).closest('form')!);

    await waitFor(() => expect(update).toHaveBeenCalledWith('item-123', expect.objectContaining({
      cover_path: 'projects/new-cover.png',
      gallery_paths: ['projects/two.png'],
    })));
  });

  it('supports adding a gallery path from the keyboard and rejects duplicates', async () => {
    renderAt('/seller/products/new');
    fireEvent.change(screen.getByLabelText('Path'), { target: { value: 'projects/new' } });
    fireEvent.change(screen.getByLabelText('Product'), { target: { value: 'New product' } });
    const input = screen.getByLabelText('New gallery image path');
    fireEvent.change(input, { target: { value: 'projects/preview.png' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(screen.getByDisplayValue('projects/preview.png')).toBeDefined();

    fireEvent.change(screen.getByLabelText('New gallery image path'), { target: { value: 'projects/preview.png' } });
    expect(screen.getByRole('alert').textContent).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Add tag' }) as HTMLButtonElement).disabled).toBe(true);
  });


  it('shows invalid path feedback and requires confirmation before saving', async () => {
    renderAt('/seller/products/new');
    fireEvent.change(screen.getByLabelText('Path'), { target: { value: 'projects/new' } });
    fireEvent.change(screen.getByLabelText('Product'), { target: { value: 'New product' } });
    const input = screen.getByLabelText('New gallery image path');
    fireEvent.change(input, { target: { value: '../outside.png' } });
    expect(screen.getByRole('alert').textContent).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Add tag' }) as HTMLButtonElement).disabled).toBe(true);

    vi.mocked(window.confirm).mockReturnValueOnce(false);
    fireEvent.submit(screen.getByRole('button', { name: 'Add product' }).closest('form')!);
    expect(create).not.toHaveBeenCalled();
  });

  it('shows graceful preview fallback when a thumbnail cannot be loaded', async () => {
    renderAt('/seller/products/new');
    const input = screen.getByLabelText('New gallery image path');
    fireEvent.change(input, { target: { value: 'projects/missing.png' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add tag' }));
    const image = screen.getByRole('img', { name: 'Gallery 1: projects/missing.png' });
    fireEvent.error(image);
    expect(screen.getByLabelText('Gallery 1 preview unavailable')).toBeDefined();
  });

  it('shows a graceful not-found state after catalog loading completes', () => {
    catalogState.products = [];
    renderAt('/seller/products/missing');
    expect(screen.getByText('Product not found')).toBeDefined();
    expect(screen.getByText('This product could not be found.')).toBeDefined();
  });
});
