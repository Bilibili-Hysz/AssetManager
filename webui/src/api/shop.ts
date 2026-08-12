import type { ApiClient } from './client';
import type {
  DeliveryInfo,
  FulfillOrderResponse,
  ShopItem,
  ShopItemPayload,
  ShopSellerProfile,
  ShopSellerProfilePayload,
  ShopPublicSellerProfile,
  ShopBuyerOrder,
  ShopBuyerOrdersResponse,
  ShopItemsResponse,
  ShopCatalogQuery,
  ShopCatalogResponse,
  ShopOrder,
  ShopOrdersResponse,
  ShopStats,
  ShopCartResponse,
  ShopCartCheckoutResponse,
  ShopCheckoutGroupResponse,
  ShopWishlistResponse,
  ShopBuyerMergeResponse,
  ReceiptRecoveryResponse,
} from '../types/api';

export function createShopApi(api: ApiClient) {
  return {
    list: (status?: 'active' | 'archived' | 'draft', includeDisabled = false, signal?: AbortSignal) => {
      const params = {
        ...(status ? { status } : {}),
        ...(includeDisabled ? { include_disabled: true } : {}),
      };
      return api.get<ShopItemsResponse>(
        'shop/items',
        Object.keys(params).length > 0 ? params : undefined,
        signal,
      );
    },
    catalog: (params?: ShopCatalogQuery, signal?: AbortSignal) => {
      const normalizedQ = params?.q?.trim();
      const query = {
        ...(normalizedQ ? { q: normalizedQ } : {}),
        ...(params?.page !== undefined ? { page: params.page } : {}),
        ...(params?.page_size !== undefined ? { page_size: params.page_size } : {}),
        ...(params?.sort !== undefined ? { sort: params.sort } : {}),
      };
      return api.get<ShopCatalogResponse>(
        'shop/catalog',
        Object.keys(query).length > 0 ? query : undefined,
        signal,
      );
    },
    getItem: (id: string | number) =>
      api.get<{ item: ShopItem }>(`shop/items/${encodeURIComponent(String(id))}`),
    getItemByPath: (path: string) =>
      api.get<{ item: ShopItem }>('shop/items/by-path', { path }),
    create: (payload: ShopItemPayload) =>
      api.post<{ item: ShopItem }>('shop/items', payload),
    update: (id: string | number, payload: ShopItemPayload) =>
      api.put<{ item: ShopItem }>(`shop/items/${encodeURIComponent(id)}`, payload),
    remove: (id: string | number) =>
      api.delete<{ ok: boolean }>(`shop/items/${encodeURIComponent(String(id))}`),

    getPublicProfile: () =>
      api.get<{ profile: ShopPublicSellerProfile }>('shop/profile'),
    getSellerProfile: () =>
      api.get<{ profile: ShopSellerProfile }>('shop/seller-profile'),
    updateSellerProfile: (payload: ShopSellerProfilePayload) =>
      api.put<{ profile: ShopSellerProfile }>('shop/seller-profile', payload),

    /** Public, cookie-deduplicated store visit. It returns no visitor data. */
    recordStorefrontView: () => api.post<{ ok: boolean }>('shop/analytics/store-view', {}),

    getCart: () => api.get<ShopCartResponse>('shop/cart'),
    addCartItem: (itemId: string | number, quantity = 1, version?: number) =>
      api.post<ShopCartResponse>('shop/cart/items', {
        item_id: itemId,
        quantity,
        ...(version == null ? {} : { version }),
      }),
    updateCartItem: (lineId: string | number, quantity: number, version?: number) =>
      api.patch<ShopCartResponse>('shop/cart/items/' + encodeURIComponent(String(lineId)), {
        quantity,
        ...(version == null ? {} : { version }),
      }),
    removeCartItem: (lineId: string | number, version?: number) => {
      const path = 'shop/cart/items/' + encodeURIComponent(String(lineId));
      return version == null
        ? api.delete<ShopCartResponse>(path)
        : api.deleteWithBody<ShopCartResponse>(path, { version });
    },
    clearCart: () => api.delete<ShopCartResponse>('shop/cart/items'),
    checkoutCart: (payload: {
      idempotency_key: string;
      accept_price_changes?: boolean;
      buyer_name?: string;
      buyer_email?: string;
    }) => api.post<ShopCartCheckoutResponse>('shop/cart/checkout', payload),
    getCheckoutGroup: (group: string | number) =>
      api.get<ShopCheckoutGroupResponse>(`shop/cart/checkout/${encodeURIComponent(String(group))}`),

    /** Merge anonymous buyer state into the authenticated user's state. */
    mergeBuyerState: () =>
      api.post<ShopBuyerMergeResponse>('shop/buyer/merge', {}),

    getWishlist: () => api.get<ShopWishlistResponse>('shop/wishlist'),
    addWishlistItem: (itemId: string | number) =>
      api.put<ShopWishlistResponse>('shop/wishlist/items/' + encodeURIComponent(String(itemId)), {}),
    removeWishlistItem: (itemId: string | number) =>
      api.delete<ShopWishlistResponse>('shop/wishlist/items/' + encodeURIComponent(String(itemId))),
    clearWishlist: () => api.delete<ShopWishlistResponse>('shop/wishlist'),

    listOrders: (status?: string, signal?: AbortSignal) =>
      api.get<ShopOrdersResponse>('shop/orders', status ? { status } : undefined, signal),
    listBuyerOrders: (status?: string, limit = 50, cursor?: string) =>
      api.get<ShopBuyerOrdersResponse>('shop/buyer/orders', {
        ...(status ? { status } : {}),
        limit,
        ...(cursor ? { cursor } : {}),
      }),
    createOrder: (itemId: string | number) =>
      api.post<{ order: ShopBuyerOrder }>('shop/order', { item_id: itemId }),
    getOrder: (id: string | number) =>
      api.get<{ order: ShopBuyerOrder }>(`shop/order/${encodeURIComponent(String(id))}`),
    confirmOrder: (id: string | number) =>
      api.post<{ order: ShopBuyerOrder }>(`shop/order/${encodeURIComponent(String(id))}/confirm`),
    fulfillOrder: (id: string | number) =>
      api.post<FulfillOrderResponse>(`shop/order/${encodeURIComponent(id)}/fulfill`),
    rotateDelivery: (
      id: string | number,
      payload?: { max_downloads?: number; expires_in?: number },
    ) => api.post<FulfillOrderResponse>(
      `shop/order/${encodeURIComponent(String(id))}/delivery/rotate`,
      payload ?? {},
    ),
    revokeOrder: (id: string | number) =>
      api.post<{ order: ShopOrder }>(`shop/order/${encodeURIComponent(id)}/revoke`),
    getStats: (signal?: AbortSignal) => api.get<{ stats: ShopStats }>('shop/stats', undefined, signal),
    exportOrdersUrl: (status?: string) =>
      api.buildUrl(`shop/orders/export${status ? `?status=${encodeURIComponent(status)}` : ''}`),

    /** Buyer delivery endpoint. The receipt cookie is sent by the browser. */
    orderDeliveryUrl: (id: string | number) =>
      api.buildUrl(`shop/order/${encodeURIComponent(String(id))}/delivery`),
    /** Fetch a buyer delivery with request-level retry idempotency. */
    downloadOrderDelivery: (id: string | number, requestKey: string, signal?: AbortSignal) =>
      api.getBlobWithMetadata(
        `shop/order/${encodeURIComponent(String(id))}/delivery`,
        { 'Idempotency-Key': requestKey },
        signal,
      ),
    recoverOrderReceipt: (id: string | number) =>
      api.post<ReceiptRecoveryResponse>(
        `shop/order/${encodeURIComponent(String(id))}/receipt/recover`,
        {},
      ),

    /**
     * Exchange a one-time share claim code for the order receipt cookie. After
     * a successful claim the buyer can use getOrder / downloadOrderDelivery
     * through the existing receipt channel.
     */
    claimDelivery: (orderId: string | number, claim: string) =>
      api.post<{ ok: boolean }>(
        `shop/delivery/${encodeURIComponent(String(orderId))}/claim`,
        { claim },
      ),

    // Legacy token-based delivery routes remain available for existing seller
    // links and older storefront URLs. New buyer checkout code must not use
    // these methods because delivery tokens are never exposed to the buyer.
    /**
     * @deprecated Legacy bearer-token delivery lookup. New share links use the
     * order id + one-time claim flow (claimDelivery + getOrder/downloadOrderDelivery).
     */
    getDelivery: (token: string) =>
      api.get<DeliveryInfo>(`shop/delivery/${encodeURIComponent(token)}`),
    /**
     * @deprecated Legacy bearer-token download URL. New share links download
     * through the receipt channel (downloadOrderDelivery).
     */
    deliveryDownloadUrl: (token: string) =>
      api.buildUrl(`shop/delivery/${encodeURIComponent(token)}/download`),
  };
}

export type ShopApi = ReturnType<typeof createShopApi>;
