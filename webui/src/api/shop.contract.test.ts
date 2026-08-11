import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from './client';
import type { ShopCatalogResponse } from '../types/api';
import { createShopApi } from './shop';

function setup() {
  const api = {
    get: vi.fn(),
    getBlob: vi.fn(),
    getBlobWithMetadata: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    deleteWithBody: vi.fn(),
    buildUrl: vi.fn((path: string) => `/api/${path}`),
  } as unknown as ApiClient;
  return { api, shop: createShopApi(api) };
}

describe('shop API contract', () => {
  it('lists items with an optional status filter', () => {
    const { shop, api } = setup();
    shop.list('active');
    expect(api.get).toHaveBeenCalledWith('shop/items', { status: 'active' });
    shop.list();
    expect(api.get).toHaveBeenCalledWith('shop/items', undefined);
  });

  it('requests disabled seller items when management mode is enabled', () => {
    const { shop, api } = setup();
    shop.list(undefined, true);
    shop.list('archived', true);
    expect(api.get).toHaveBeenNthCalledWith(1, 'shop/items', { include_disabled: true });
    expect(api.get).toHaveBeenNthCalledWith(2, 'shop/items', { status: 'archived', include_disabled: true });
  });

  it('requests the independent catalog with only provided snake_case query parameters', () => {
    const { shop, api } = setup();
    const response: Promise<ShopCatalogResponse> = shop.catalog({
      q: 'hero',
      page: 2,
      page_size: 24,
      sort: 'newest',
    });
    shop.catalog();

    expect(response).toBeUndefined();
    expect(api.get).toHaveBeenNthCalledWith(1, 'shop/catalog', {
      q: 'hero',
      page: 2,
      page_size: 24,
      sort: 'newest',
    });
    expect(api.get).toHaveBeenNthCalledWith(2, 'shop/catalog', undefined);
  });

  it('normalizes empty and surrounding-whitespace q values before requesting the catalog', () => {
    const { shop, api } = setup();
    shop.catalog({ q: "  hero  " });
    shop.catalog({ q: "   " });

    expect(api.get).toHaveBeenNthCalledWith(1, 'shop/catalog', { q: 'hero' });
    expect(api.get).toHaveBeenNthCalledWith(2, 'shop/catalog', undefined);
  });

  it('gets an item by its canonical path without putting the path in the URL path', () => {
    const { shop, api } = setup();
    shop.getItemByPath('packs/hero pack.zip');
    expect(api.get).toHaveBeenCalledWith('shop/items/by-path', { path: 'packs/hero pack.zip' });
  });

  it('encodes item, order, and delivery identifiers', () => {
    const { shop, api } = setup();
    shop.update('item/a', { title: 'Updated' });
    shop.getItem('item/a');
    shop.getOrder('order/a');
    shop.getDelivery('token/a');
    expect(api.put).toHaveBeenCalledWith('shop/items/item%2Fa', { title: 'Updated' });
    expect(api.get).toHaveBeenCalledWith('shop/items/item%2Fa');
    expect(api.get).toHaveBeenCalledWith('shop/order/order%2Fa');
    expect(api.get).toHaveBeenCalledWith('shop/delivery/token%2Fa');
  });

  it('lists buyer-safe order history with optional status and limit', () => {
    const { shop, api } = setup();
    shop.listBuyerOrders();
    shop.listBuyerOrders('fulfilled', 25);
    expect(api.get).toHaveBeenNthCalledWith(1, 'shop/buyer/orders', { limit: 50 });
    expect(api.get).toHaveBeenNthCalledWith(2, 'shop/buyer/orders', { status: 'fulfilled', limit: 25 });
  });

  it('maps receipt recovery to the owner-scoped buyer route', () => {
    const { shop, api } = setup();
    shop.recoverOrderReceipt('order/a');
    expect(api.post).toHaveBeenCalledWith('shop/order/order%2Fa/receipt/recover', {});
  });

  it('maps buyer delivery downloads to the receipt route with an idempotency header', () => {
    const { shop, api } = setup();
    shop.downloadOrderDelivery('order/a', 'delivery-attempt-1');

    expect(api.getBlobWithMetadata).toHaveBeenCalledWith(
      'shop/order/order%2Fa/delivery',
      { 'Idempotency-Key': 'delivery-attempt-1' },
      undefined,
    );
  });

  it('maps delivery recovery to the seller-scoped rotate route', () => {
    const { shop, api } = setup();
    shop.rotateDelivery('order/a', { max_downloads: 5, expires_in: 3600 });
    expect(api.post).toHaveBeenCalledWith(
      'shop/order/order%2Fa/delivery/rotate',
      { max_downloads: 5, expires_in: 3600 },
    );
  });

  it('maps one-time share claims to the delivery claim route with the claim in the body', () => {
    const { shop, api } = setup();
    shop.claimDelivery('order/a', 'claim-code-123');
    expect(api.post).toHaveBeenCalledWith('shop/delivery/order%2Fa/claim', { claim: 'claim-code-123' });
  });

  it('encodes numeric order ids in the share claim route', () => {
    const { shop, api } = setup();
    shop.claimDelivery(42, 'claim-code-123');
    expect(api.post).toHaveBeenCalledWith('shop/delivery/42/claim', { claim: 'claim-code-123' });
  });

  it('maps seller order mutations and buyer order creation to the documented routes', () => {
    const { shop, api } = setup();
    shop.createOrder('item-1');
    shop.confirmOrder('order-1');
    shop.fulfillOrder('order-1');
    shop.revokeOrder('order-1');
    expect(api.post).toHaveBeenNthCalledWith(1, 'shop/order', { item_id: 'item-1' });
    expect(api.post).toHaveBeenNthCalledWith(2, 'shop/order/order-1/confirm');
    expect(api.post).toHaveBeenNthCalledWith(3, 'shop/order/order-1/fulfill');
    expect(api.post).toHaveBeenNthCalledWith(4, 'shop/order/order-1/revoke');
  });

  it('builds export and delivery download URLs with encoded query values', () => {
    const { shop, api } = setup();
    shop.exportOrdersUrl('pending review');
    shop.deliveryDownloadUrl('token/a');
    shop.orderDeliveryUrl('order/a');
    expect(api.buildUrl).toHaveBeenNthCalledWith(1, 'shop/orders/export?status=pending%20review');
    expect(api.buildUrl).toHaveBeenNthCalledWith(2, 'shop/delivery/token%2Fa/download');
    expect(api.buildUrl).toHaveBeenNthCalledWith(3, 'shop/order/order%2Fa/delivery');
  });

  it('maps seller profile persistence and anonymous storefront analytics to documented routes', () => {
    const { shop, api } = setup();
    const profile = { store_name: 'North Studio', contact_email: 'hello@example.com', description: 'Art', accept_orders: false };
    shop.getPublicProfile();
    shop.getSellerProfile();
    shop.updateSellerProfile(profile);
    shop.recordStorefrontView();
    expect(api.get).toHaveBeenNthCalledWith(1, 'shop/profile');
    expect(api.get).toHaveBeenNthCalledWith(2, 'shop/seller-profile');
    expect(api.put).toHaveBeenCalledWith('shop/seller-profile', profile);
    expect(api.post).toHaveBeenCalledWith('shop/analytics/store-view', {});
  });
  it('maps cart and wishlist operations to the versioned buyer routes', () => {
    const { shop, api } = setup();
    shop.getCart();
    shop.addCartItem('item/a', 2, 4);
    shop.updateCartItem('line/a', 3, 5);
    shop.removeCartItem('line/a', 6);
    shop.clearCart();
    shop.checkoutCart({ idempotency_key: 'checkout-1', accept_price_changes: true });
    shop.getCheckoutGroup('group/a');
    shop.mergeBuyerState();
    shop.getWishlist();
    shop.addWishlistItem('item/a');
    shop.removeWishlistItem('item/a');
    shop.clearWishlist();
    expect(api.get).toHaveBeenCalledWith('shop/cart');
    expect(api.post).toHaveBeenCalledWith('shop/cart/items', { item_id: 'item/a', quantity: 2, version: 4 });
    expect(api.patch).toHaveBeenCalledWith('shop/cart/items/line%2Fa', { quantity: 3, version: 5 });
    expect(api.deleteWithBody).toHaveBeenCalledWith('shop/cart/items/line%2Fa', { version: 6 });
    expect(api.delete).toHaveBeenCalledWith('shop/cart/items');
    expect(api.post).toHaveBeenCalledWith('shop/cart/checkout', { idempotency_key: 'checkout-1', accept_price_changes: true });
    expect(api.get).toHaveBeenCalledWith('shop/cart/checkout/group%2Fa');
    expect(api.post).toHaveBeenCalledWith('shop/buyer/merge', {});
    expect(api.get).toHaveBeenCalledWith('shop/wishlist');
    expect(api.put).toHaveBeenCalledWith('shop/wishlist/items/item%2Fa', {});
    expect(api.delete).toHaveBeenCalledWith('shop/wishlist/items/item%2Fa');
    expect(api.delete).toHaveBeenCalledWith('shop/wishlist');
  });

});
