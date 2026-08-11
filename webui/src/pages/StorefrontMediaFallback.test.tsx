// @vitest-environment jsdom
import { cleanup, render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SellerGalleryEditor from '../components/storefront/SellerGalleryEditor';
import StorefrontCartPage from './StorefrontCartPage';
import StorefrontWishlistPage from './StorefrontWishlistPage';

const { buildUrl, buyerState, showToast } = vi.hoisted(() => ({
  buildUrl: vi.fn((path: string) => `/library/api/${path}`),
  buyerState: { current: {} as Record<string, unknown> },
  showToast: vi.fn(),
}));

vi.mock('../hooks/useAuth', () => ({ useAuth: () => ({ api: { buildUrl } }) }));
vi.mock('../components/storefront/ShopBuyerContext', () => ({
  useShopBuyer: () => buyerState.current,
}));
vi.mock('../components/storefront/StorefrontShell', () => ({
  StorefrontShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock('../hooks/useI18n', () => ({
  useI18n: () => ({
    t: (key: string, ...args: Array<string | number>) => {
      const value = ({
        'seller.gallery_paths': 'Gallery paths',
        'seller.gallery_cover': 'Cover',
        'seller.gallery': 'Gallery',
        'seller.cover_path': 'Cover path',
        'seller.gallery_image_path': 'Gallery image path {0}',
        'seller.new_gallery_image_path': 'New gallery image path',
        'seller.gallery_paths_help': 'Manage cover and gallery paths.',
        'seller.gallery_paths_note': 'Cover and gallery paths are managed separately.',
        'seller.gallery_preview': 'Gallery images',
        'info.path': 'Path',
      }[key] ?? key);
      return args.reduce((result, arg, index) => String(result).replace(`{${index}}`, String(arg)), String(value));
    },
  }),
}));
vi.mock('../components/ui/Toast', () => ({ useToast: () => ({ showToast }) }));

function buyerContext(overrides: Record<string, unknown>) {
  return {
    cart: null,
    wishlist: [],
    cartLoading: false,
    wishlistLoading: false,
    refreshCart: vi.fn().mockResolvedValue(null),
    refreshWishlist: vi.fn().mockResolvedValue([]),
    updateCartItem: vi.fn(),
    removeCartItem: vi.fn(),
    clearCart: vi.fn(),
    checkout: vi.fn(),
    removeFromWishlist: vi.fn(),
    clearWishlist: vi.fn(),
    ...overrides,
  };
}

describe('storefront non-image thumbnail fallbacks', () => {
  beforeEach(() => {
    buildUrl.mockClear();
    showToast.mockClear();
  });

  afterEach(() => cleanup());

  it('renders a cart placeholder without requesting a thumbnail for an archive', () => {
    buyerState.current = buyerContext({
      cart: {
        id: 1,
        owner_type: 'anonymous',
        status: 'active',
        version: 1,
        expires_at: null,
        created_at: 1,
        updated_at: 1,
        items: [{
          id: 11,
          item_id: 7,
          quantity: 1,
          unit_price_cents: 1200,
          currency: 'CNY',
          path: 'shop/sales/archive.zip',
          title: 'Archive asset',
          line_status: 'active',
          created_at: 1,
          updated_at: 1,
        }],
      },
    });

    const { container } = render(<MemoryRouter><StorefrontCartPage /></MemoryRouter>);

    expect(container.querySelector('.storefront-cart-line-image img')).toBeNull();
    expect(container.querySelector('.storefront-cart-line-image .storefront-line-image-placeholder')).not.toBeNull();
    expect(buildUrl).not.toHaveBeenCalled();
  });

  it('renders a wishlist placeholder without requesting a thumbnail for a text asset', () => {
    buyerState.current = buyerContext({
      wishlist: [{
        item_id: 8,
        added_at: 1,
        path: 'shop/sales/readme.txt',
        title: 'Readme asset',
        price_cents: 0,
        currency: 'CNY',
        availability: 'available',
      }],
    });

    const { container } = render(<MemoryRouter><StorefrontWishlistPage /></MemoryRouter>);

    expect(container.querySelector('.storefront-wishlist-image img')).toBeNull();
    expect(container.querySelector('.storefront-wishlist-image .storefront-line-image-placeholder')).not.toBeNull();
    expect(buildUrl).not.toHaveBeenCalled();
  });

  it('shows an unavailable seller preview without requesting a thumbnail for a PSD', () => {
    const { container } = render(
      <SellerGalleryEditor
        coverPath="shop/sales/source.psd"
        galleryPaths={[]}
        buildUrl={buildUrl}
        onChange={vi.fn()}
      />,
    );

    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('[aria-label="Cover preview unavailable"]')).not.toBeNull();
    expect(buildUrl).not.toHaveBeenCalled();
  });
});
