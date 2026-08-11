// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import StorefrontWishlistPage from './StorefrontWishlistPage';

const { buyerState } = vi.hoisted(() => ({
  buyerState: {
    wishlist: [] as Array<Record<string, unknown>>,
    wishlistLoading: false,
    refreshWishlist: vi.fn(),
    removeFromWishlist: vi.fn(),
    clearWishlist: vi.fn(),
  },
}));

const api = { buildUrl: (path: string) => '/api/' + path };

vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ api }) }));
vi.mock('../components/storefront/ShopBuyerContext', () => ({ useShopBuyer: () => buyerState }));
vi.mock('../components/storefront/StorefrontShell', () => ({
  StorefrontShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('../components/ui/Toast', () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock('../hooks/useI18n', () => ({
  useI18n: () => ({
    t: (key: string) => ({
      'commerce.store': 'Storefront',
      'commerce.back_to_store': 'Back to store',
      'commerce.wishlist': 'Wishlist',
      'commerce.wishlist_title': 'Saved assets',
      'commerce.wishlist_description': 'Keep products here.',
      'commerce.clear_wishlist': 'Clear wishlist',
      'commerce.wishlist_empty': 'Nothing saved yet',
      'commerce.wishlist_empty_description': 'Save products to revisit.',
      'commerce.browse_assets': 'Browse assets',
      'commerce.remove_from_wishlist': 'Remove from wishlist',
      'commerce.product_not_found': 'Product not found',
      'commerce.item_unavailable': 'Item unavailable',
      'commerce.available': 'Available',
      'commerce.unavailable': 'Unavailable',
      'browse.loading': 'Loading...',
    }[key] ?? key),
  }),
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/storefront/wishlist']}>
      <StorefrontWishlistPage />
    </MemoryRouter>,
  );
}

describe('StorefrontWishlistPage', () => {
  beforeEach(() => {
    buyerState.wishlist = [];
    buyerState.wishlistLoading = false;
    buyerState.refreshWishlist.mockReset().mockResolvedValue([]);
    buyerState.removeFromWishlist.mockReset().mockResolvedValue([]);
    buyerState.clearWishlist.mockReset().mockResolvedValue([]);
  });

  afterEach(() => cleanup());

  it('refreshes and shows a loading state for an empty wishlist', () => {
    buyerState.wishlistLoading = true;
    renderPage();

    expect(screen.getByText('Loading...')).toBeDefined();
    expect(buyerState.refreshWishlist).toHaveBeenCalledTimes(1);
  });

  it('renders available and unavailable entries and supports remove/clear actions', () => {
    buyerState.wishlist = [
      {
        item_id: 7,
        added_at: 1,
        path: 'assets/cover.png',
        title: 'Available asset',
        price_cents: 1200,
        currency: 'USD',
        availability: 'available',
      },
      {
        item_id: 8,
        added_at: 2,
        path: null,
        title: 'Unavailable asset',
        price_cents: null,
        currency: null,
        availability: 'unavailable',
      },
    ];
    renderPage();

    expect(screen.getByRole('link', { name: 'Available asset' })).toBeDefined();
    expect(screen.getByText('Unavailable asset')).toBeDefined();
    expect(screen.queryByRole('link', { name: 'Unavailable asset' })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Remove from wishlist Available asset' }));
    expect(buyerState.removeFromWishlist).toHaveBeenCalledWith(7);
    fireEvent.click(screen.getByRole('button', { name: 'Clear wishlist' }));
    expect(buyerState.clearWishlist).toHaveBeenCalledTimes(1);
  });
});
