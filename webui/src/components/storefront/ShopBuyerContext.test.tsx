// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ShopBuyerProvider, useShopBuyer } from './ShopBuyerContext';

const mocks = vi.hoisted(() => {
  const cart = {
    id: 7,
    owner_type: 'user' as const,
    status: 'active' as const,
    version: 2,
    expires_at: null,
    created_at: 1,
    updated_at: 2,
    items: [],
  };
  const wishlist = [{
    item_id: 11,
    added_at: 1,
    path: 'images/one.png',
    title: 'One',
    price_cents: 100,
    currency: 'CNY',
    availability: 'available' as const,
  }];
  return {
    api: {},
    shop: {
      getCart: vi.fn().mockResolvedValue({ cart }),
      getWishlist: vi.fn().mockResolvedValue({ items: [] }),
      mergeBuyerState: vi.fn().mockResolvedValue({ merged: true, cart, wishlist }),
      addCartItem: vi.fn(),
      updateCartItem: vi.fn(),
      removeCartItem: vi.fn(),
      clearCart: vi.fn(),
      checkoutCart: vi.fn(),
      addWishlistItem: vi.fn(),
      removeWishlistItem: vi.fn(),
      clearWishlist: vi.fn(),
    },
    auth: {
      identityGeneration: 1,
      isAuthenticated: true,
      isLoading: false,
      principal: { kind: 'user' },
    },
  };
});

vi.mock('../../hooks/useAuth', () => ({ useAuth: () => ({ api: mocks.api, ...mocks.auth }) }));
vi.mock('../../api/shop', () => ({ createShopApi: () => mocks.shop }));

function wrapper({ children }: { children: React.ReactNode }) {
  return <ShopBuyerProvider>{children}</ShopBuyerProvider>;
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe('ShopBuyerProvider', () => {
  beforeEach(() => {
    mocks.shop.getCart.mockClear();
    mocks.shop.getWishlist.mockClear();
    mocks.shop.mergeBuyerState.mockClear();
    mocks.shop.mergeBuyerState.mockResolvedValue({
      merged: true,
      cart: { ...mocks.shop.getCart.mock.results[0]?.value?.cart },
      wishlist: [],
    });
    mocks.auth.identityGeneration = 1;
    mocks.auth.isAuthenticated = true;
    mocks.auth.isLoading = false;
    mocks.auth.principal = { kind: 'user' };
  });

  it('merges anonymous buyer state when a user identity becomes active', async () => {
    const cart = {
      id: 7,
      owner_type: 'user' as const,
      status: 'active' as const,
      version: 2,
      expires_at: null,
      created_at: 1,
      updated_at: 2,
      items: [],
    };
    const wishlist = [{
      item_id: 11,
      added_at: 1,
      path: 'images/one.png',
      title: 'One',
      price_cents: 100,
      currency: 'CNY',
      availability: 'available' as const,
    }];
    mocks.shop.mergeBuyerState.mockResolvedValue({ merged: true, cart, wishlist });

    const { result } = renderHook(() => useShopBuyer(), { wrapper });

    await waitFor(() => expect(mocks.shop.mergeBuyerState).toHaveBeenCalledTimes(1));
    expect(result.current.cart).toEqual(cart);
    expect(result.current.wishlist).toEqual(wishlist);
  });

  it('clears private state and reloads guest state after logout', async () => {
    const { result, rerender } = renderHook(() => useShopBuyer(), { wrapper });
    await waitFor(() => expect(mocks.shop.mergeBuyerState).toHaveBeenCalledTimes(1));

    mocks.auth.identityGeneration = 2;
    mocks.auth.isAuthenticated = false;
    mocks.auth.principal = { kind: 'guest' };
    mocks.shop.getCart.mockResolvedValueOnce({ cart: { ...mocks.shop.getCart.mock.results[0]?.value?.cart, owner_type: 'anonymous' } });
    mocks.shop.getWishlist.mockResolvedValueOnce({ items: [] });
    rerender();

    await waitFor(() => expect(mocks.shop.getCart).toHaveBeenCalled());
    expect(result.current.wishlist).toEqual([]);
  });
  it('ignores stale cart refresh responses after the buyer identity changes', async () => {
    const userCart = {
      id: 7,
      owner_type: 'user' as const,
      status: 'active' as const,
      version: 2,
      expires_at: null,
      created_at: 1,
      updated_at: 2,
      items: [],
    };
    const staleCart = { ...userCart, version: 99 };
    const guestCart = { ...userCart, owner_type: 'anonymous' as const, version: 3 };
    const staleRequest = deferred<{ cart: typeof staleCart }>();
    const guestRequest = deferred<{ cart: typeof guestCart }>();

    mocks.shop.mergeBuyerState.mockResolvedValue({ merged: true, cart: userCart, wishlist: [] });
    mocks.shop.getCart
      .mockImplementationOnce(() => staleRequest.promise)
      .mockImplementationOnce(() => guestRequest.promise);
    mocks.shop.getWishlist.mockResolvedValue({ items: [] });

    const { result, rerender } = renderHook(() => useShopBuyer(), { wrapper });
    await waitFor(() => expect(mocks.shop.mergeBuyerState).toHaveBeenCalledTimes(1));

    let staleRefresh!: Promise<unknown>;
    await act(async () => {
      staleRefresh = result.current.refreshCart();
    });

    mocks.auth.identityGeneration = 2;
    mocks.auth.isAuthenticated = false;
    mocks.auth.principal = { kind: 'guest' };
    await act(async () => {
      rerender();
    });
    await waitFor(() => expect(mocks.shop.getCart).toHaveBeenCalledTimes(2));
    expect(result.current.cartLoading).toBe(true);

    await act(async () => {
      staleRequest.resolve({ cart: staleCart });
      await staleRefresh;
    });
    expect(result.current.cart).toBeNull();

    await act(async () => {
      guestRequest.resolve({ cart: guestCart });
    });
    await waitFor(() => expect(result.current.cart).toEqual(guestCart));
    expect(result.current.cartLoading).toBe(false);
  });

  it('serializes cart mutations and forwards the latest cart version', async () => {
    const initialCart = {
      id: 7,
      owner_type: 'user' as const,
      status: 'active' as const,
      version: 2,
      expires_at: null,
      created_at: 1,
      updated_at: 2,
      items: [],
    };
    const firstCart = { ...initialCart, version: 3 };
    const secondCart = { ...initialCart, version: 4 };
    const firstRequest = deferred<{ cart: typeof firstCart }>();
    const secondRequest = deferred<{ cart: typeof secondCart }>();

    mocks.shop.mergeBuyerState.mockResolvedValue({ merged: true, cart: initialCart, wishlist: [] });
    mocks.shop.addCartItem.mockReset();
    mocks.shop.addCartItem
      .mockImplementationOnce(() => firstRequest.promise)
      .mockImplementationOnce(() => secondRequest.promise);

    const { result } = renderHook(() => useShopBuyer(), { wrapper });
    await waitFor(() => expect(mocks.shop.mergeBuyerState).toHaveBeenCalledTimes(1));

    const firstMutation = result.current.addToCart(12);
    const secondMutation = result.current.addToCart(13);
    await waitFor(() => expect(mocks.shop.addCartItem).toHaveBeenCalledTimes(1));
    expect(mocks.shop.addCartItem).toHaveBeenNthCalledWith(1, 12, 1, 2);

    await act(async () => {
      firstRequest.resolve({ cart: firstCart });
      await firstMutation;
    });
    await waitFor(() => expect(mocks.shop.addCartItem).toHaveBeenCalledTimes(2));
    expect(mocks.shop.addCartItem).toHaveBeenNthCalledWith(2, 13, 1, 3);

    await act(async () => {
      secondRequest.resolve({ cart: secondCart });
      await secondMutation;
    });
    expect(result.current.cart).toEqual(secondCart);
  });
});
