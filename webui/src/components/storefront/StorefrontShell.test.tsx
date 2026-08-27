// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { StorefrontShell } from './StorefrontShell';

const { refreshCart, refreshWishlist, sellerLogout } = vi.hoisted(() => ({
  refreshCart: vi.fn().mockResolvedValue(undefined),
  refreshWishlist: vi.fn().mockResolvedValue(undefined),
  sellerLogout: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('../../stores/AuthContext', () => ({
  useAuthContext: () => ({ isAuthenticated: false, user: null }),
}));
vi.mock('../../stores/SellerAuthContext', () => ({
  useOptionalSellerAuth: () => ({ authenticated: true, logout: sellerLogout }),
}));
vi.mock('../../stores/ShopBuyerContext', () => ({
  useShopBuyer: () => ({ cart: null, wishlist: [], refreshCart, refreshWishlist }),
}));
vi.mock('../../hooks/useI18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}));

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}

describe('StorefrontShell search', () => {
  afterEach(() => {
    cleanup();
    sellerLogout.mockClear();
  });

  it('uses seller logout for an authenticated seller shell', async () => {
    render(
      <MemoryRouter initialEntries={['/seller']}>
        <StorefrontShell sellerMode><LocationProbe /></StorefrontShell>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'header.logout' }));
    expect(sellerLogout).toHaveBeenCalledTimes(1);
  });
  it('navigates to the products search when no custom handler is provided', () => {
    render(
      <MemoryRouter initialEntries={['/storefront']}>
        <StorefrontShell><LocationProbe /></StorefrontShell>
      </MemoryRouter>,
    );

    expect(screen.getByRole('link', { name: 'commerce.buyer_orders' }).getAttribute('href')).toBe('/storefront/orders');

    fireEvent.change(screen.getByRole('textbox', { name: 'commerce.search' }), { target: { value: '  neon icons  ' } });
    fireEvent.submit(screen.getByRole('search'));

    expect(screen.getByTestId('location').textContent).toBe('/storefront/products?q=neon%20icons');

    fireEvent.change(screen.getByLabelText('commerce.search'), { target: { value: '   ' } });
    fireEvent.submit(screen.getByRole('search'));
    expect(screen.getByTestId('location').textContent).toBe('/storefront/products');
  });

  it('syncs a parent-provided URL search value into the Header input', () => {
    render(
      <MemoryRouter initialEntries={['/storefront/products?q=alpha']}>
        <StorefrontShell searchValue="alpha"><LocationProbe /></StorefrontShell>
      </MemoryRouter>,
    );

    expect((screen.getByRole('textbox', { name: 'commerce.search' }) as HTMLInputElement).value).toBe('alpha');
  });

  it('keeps custom search behavior instead of navigating', () => {
    const onSearch = vi.fn();
    render(
      <MemoryRouter initialEntries={['/storefront/products']}>
        <StorefrontShell onSearch={onSearch}><LocationProbe /></StorefrontShell>
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByRole('textbox', { name: 'commerce.search' }), { target: { value: '  brushes ' } });
    fireEvent.submit(screen.getByRole('search'));

    expect(onSearch).toHaveBeenCalledWith('brushes');
    expect(screen.getByTestId('location').textContent).toBe('/storefront/products');
  });
});
