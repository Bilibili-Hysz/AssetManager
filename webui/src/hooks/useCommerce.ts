import { useMemo } from 'react';
import { useAuth } from './useAuth';
import { useSellerShopApi } from './usePageApis';
import { useSellerAuth } from '../stores/SellerAuthContext';
import { useCachedQuery } from './useCachedQuery';
import { createShopApi, type ShopApi } from '../api/shop';
import type { QueryKey } from '../cache/queryCache';
import type {
  ShopCatalogQuery, ShopCatalogResponse, ShopItem, ShopItemsResponse, ShopOrder, ShopStats,
  ShopSellerDeliveryQuota,
} from '../types/api';
import type { StorefrontOrder, StorefrontProduct, StorefrontStats } from '../components/storefront/types';

/**
 * Input shape accepted by the presentation adapters. The shop domain methods
 * (shop.ts) return the typed ShopItem/ShopOrder DTOs; these widened forms keep
 * the defensive reads for fields the backend may omit from some responses.
 */
type ShopItemInput = Partial<ShopItem> & {
  id?: string | number;
  path?: string;
  downloads?: number;
  download_count?: number;
  category?: string;
  tags?: unknown[];
  featured?: boolean;
};
type ShopOrderInput = Omit<Partial<ShopOrder>, 'id'> & {
  id?: string | number;
  title?: string;
  cover_path?: string | null;
  price_cents?: number;
};

function asNumber(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function isAbsoluteUrl(value: string): boolean {
  return value.startsWith('/') || value.startsWith('http://') || value.startsWith('https://');
}

const WINDOWS_ABSOLUTE_PATH = /^[A-Za-z]:($|\/)/;

/** Keep shop paths aligned with the backend's normalize_relative_shop_path. */
export function canonicalizeShopPath(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const raw = value.trim().replace(/\\/g, '/');
  if (!raw || raw.startsWith('/') || WINDOWS_ABSOLUTE_PATH.test(raw)) return null;
  const parts: string[] = [];
  for (const part of raw.split('/')) {
    if (!part || part === '.') continue;
    if (part === '..') return null;
    parts.push(part);
  }
  return parts.length > 0 ? parts.join('/') : null;
}

// Keep this list aligned with AssetsManager.domain.asset.IMAGE_EXTS and the
// thumbnail service: a product can be any downloadable file, but only image
// paths should be sent to /api/thumbnails.
const THUMBNAIL_EXTENSIONS = new Set([
  '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tiff', '.ico', '.svg',
]);

export function isThumbnailPath(value: string): boolean {
  if (!value) return false;
  if (isAbsoluteUrl(value)) return true;
  // Only the final path segment matters: a dot in a parent directory must not
  // be mistaken for a file extension.
  const lastSegment = value.slice(value.lastIndexOf('/') + 1);
  const dotIndex = lastSegment.lastIndexOf('.');
  const extension = dotIndex >= 0 ? lastSegment.slice(dotIndex + 1).toLowerCase() : '';
  // Paths without an extension may still be image-backed library aliases.
  // THUMBNAIL_EXTENSIONS stores entries with a leading dot to stay aligned
  // with the backend's IMAGE_EXTS list.
  return !extension || THUMBNAIL_EXTENSIONS.has(`.${extension}`);
}
export function assetThumbnailUrl(path: string, size: number, buildUrl: (path: string) => string): string {
  if (!path || !isThumbnailPath(path)) return '';
  if (isAbsoluteUrl(path)) return path;
  return buildUrl(`thumbnails/${encodeURIComponent(path)}?size=${size}`);
}

function numericItemId(value: unknown): string | null {
  if (typeof value === 'number') {
    return Number.isSafeInteger(value) && value >= 0 ? String(value) : null;
  }
  if (typeof value !== 'string' || !/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? value : null;
}

function storefrontMediaUrl(
  path: string,
  slot: string,
  itemId: string | null,
  size: number,
  buildUrl: (path: string) => string,
): string {
  if (!path || !isThumbnailPath(path)) return '';
  // External/root URLs and products without a numeric id retain the existing
  // safe fallback behavior. Only image paths can use the item media route.
  if (!itemId || isAbsoluteUrl(path)) return assetThumbnailUrl(path, size, buildUrl);
  return buildUrl(`shop/items/${encodeURIComponent(itemId)}/media/${slot}?size=${size}`);
}

export function toStorefrontProduct(item: ShopItemInput, buildUrl: (path: string) => string): StorefrontProduct {
  const path = String(item.path ?? '');
  const coverPath = typeof item.cover_path === 'string' ? item.cover_path : '';
  const galleryPaths = Array.isArray(item.gallery_paths)
    ? item.gallery_paths.filter((value): value is string => typeof value === 'string' && value.length > 0)
    : [];
  const seenMediaPaths = new Set<string>();
  const mediaEntries = [
    { path: coverPath || path, slot: 'cover' },
    ...galleryPaths.map((value, index) => ({ path: value, slot: `gallery-${index}` })),
  ].filter(entry => {
    if (!entry.path || seenMediaPaths.has(entry.path)) return false;
    seenMediaPaths.add(entry.path);
    return isThumbnailPath(entry.path);
  });
  const itemId = numericItemId(item.id);
  const mediaUrls = mediaEntries.map(entry => storefrontMediaUrl(entry.path, entry.slot, itemId, 512, buildUrl));
  const rawDownloads = item.downloads ?? item.download_count;
  const downloads = rawDownloads == null ? undefined : asNumber(rawDownloads);
  const rawStatus = String(item.status ?? '');
  const status: StorefrontProduct['status'] = rawStatus === 'draft' || rawStatus === 'archived'
    ? rawStatus
    : item.enabled === false ? 'archived' : 'active';
  return {
    id: String(item.id ?? path),
    slug: path,
    name: String(item.title ?? path.split('/').filter(Boolean).pop() ?? 'Asset'),
    description: String(item.description ?? ''),
    imageUrl: mediaUrls[0] ?? '',
    gallery: mediaUrls.slice(1),
    category: typeof item.category === 'string' ? item.category : 'Asset',
    tags: Array.isArray(item.tags) ? item.tags.map(String) : [],
    price: asNumber(item.price_cents) / 100,
    currency: String(item.currency ?? 'CNY'),
    downloads,
    featured: Boolean(item.featured),
    status,
    updatedAt: item.updated_at == null ? undefined : new Date(asNumber(item.updated_at) * 1000).toISOString(),
  };
}

export function toStorefrontOrder(order: ShopOrderInput, buildUrl: (path: string) => string): StorefrontOrder {
  const rawStatus = String(order.status ?? 'pending');
  const status: StorefrontOrder['status'] = rawStatus === 'revoked' ? 'refunded'
    : rawStatus === 'confirmed' || rawStatus === 'fulfilled' ? 'paid'
      : rawStatus === 'failed' ? 'failed' : 'pending';
  const created = asNumber(order.created_at);
  return {
    id: String(order.id ?? ''),
    productName: String(order.item_title ?? order.title ?? order.item_path ?? 'Asset'),
    productImageUrl: typeof order.cover_path === 'string' && isThumbnailPath(order.cover_path) ? assetThumbnailUrl(order.cover_path, 512, buildUrl) : undefined,
    amount: asNumber(order.amount_cents ?? order.price_cents) / 100,
    currency: String(order.currency ?? 'CNY'),
    status,
    sourceStatus: rawStatus === 'pending' || rawStatus === 'confirmed' || rawStatus === 'fulfilled' || rawStatus === 'revoked' ? rawStatus : undefined,
    createdAt: created > 0 ? new Date(created * 1000).toLocaleString() : '',
  };
}


export interface CommerceCatalogPageState {
  products: StorefrontProduct[];
  page: number;
  pageSize: number;
  total: number;
  loading: boolean;
  error: unknown;
  refresh: () => void;
}

/**
 * Paginated public Commerce catalog hook. This is intentionally separate from
 * useCommerceCatalog so the legacy shop/items contract remains untouched.
 * Fetches through the shared query cache keyed by the catalog query.
 */
export function useCommerceCatalogPage(params: ShopCatalogQuery = {}): CommerceCatalogPageState {
  const { api } = useAuth();
  const shopApi = useMemo(() => createShopApi(api), [api]);
  const query = useMemo(() => ({
    ...(params.q !== undefined ? { q: params.q } : {}),
    page: params.page ?? 1,
    page_size: params.page_size ?? 24,
    sort: params.sort ?? 'newest',
  }), [params.page, params.page_size, params.q, params.sort]);

  const { data, error, isLoading, refresh } = useCachedQuery<ShopCatalogResponse>({
    key: ['shop-catalog-page', query.q ?? null, query.page, query.page_size, query.sort],
    queryFn: signal => shopApi.catalog(query, signal),
    domains: ['shop'],
  });

  const products = useMemo(
    () => (data?.items ?? []).map(item => toStorefrontProduct(item, api.buildUrl)),
    [api.buildUrl, data],
  );
  const page = data?.page ?? query.page;
  const pageSize = data?.page_size ?? query.page_size;
  const total = data?.total ?? 0;

  return useMemo(
    () => ({ products, page, pageSize, total, loading: isLoading, error: error ?? null, refresh }),
    [error, isLoading, page, pageSize, products, refresh, total],
  );
}

function useCommerceCatalogState(shopApi: ShopApi, buildUrl: (path: string) => string, key: QueryKey, includeDisabled: boolean) {
  const { data, error, isLoading, refresh } = useCachedQuery<ShopItemsResponse>({
    key,
    queryFn: signal => shopApi.list(includeDisabled ? undefined : 'active', includeDisabled, signal),
    domains: ['shop'],
  });

  const products = useMemo(
    () => (data?.items ?? []).map(item => toStorefrontProduct(item, buildUrl)),
    [buildUrl, data],
  );

  return useMemo(
    () => ({ products, loading: isLoading, error: error ?? null, refresh }),
    [error, isLoading, products, refresh],
  );
}

export function useCommerceCatalog(includeDisabled = false) {
  const { api } = useAuth();
  const shopApi = useMemo(() => createShopApi(api), [api]);

  return useCommerceCatalogState(shopApi, api.buildUrl, ['shop-catalog', includeDisabled], includeDisabled);
}

/**
 * Seller-surface catalog: identical query shape, but routed through the
 * dedicated seller session client (useSellerShopApi) and a seller-scoped cache
 * key, so a seller cookie expiry never surfaces as a main-session failure.
 * Buyer-mode callers keep using useCommerceCatalog with the main client.
 */
export function useSellerCommerceCatalog(includeDisabled = false) {
  const shopApi = useSellerShopApi();
  const { sellerApi } = useSellerAuth();

  return useCommerceCatalogState(shopApi, sellerApi.buildUrl, ['shop-catalog', 'seller', includeDisabled], includeDisabled);
}

function useCommerceOrdersState(shopApi: ShopApi, buildUrl: (path: string) => string, key: QueryKey) {
  const { data, isLoading, refresh } = useCachedQuery<{ orders: StorefrontOrder[]; stats: StorefrontStats }>({
    key,
    queryFn: async signal => {
      const [orderResponse, statsResponse] = await Promise.all([
        shopApi.listOrders(undefined, signal),
        shopApi.getStats(signal),
      ]);
      const orders = orderResponse.orders.map(order => toStorefrontOrder(order, buildUrl));
      const rawStats: Partial<ShopStats> = statsResponse.stats ?? {};
      return {
        orders,
        stats: {
          revenue: asNumber(rawStats.gross_cents) / 100,
          orders: asNumber(rawStats.total_orders, orders.length),
          products: 0,
          views: rawStats.store_views == null ? undefined : asNumber(rawStats.store_views),
        },
      };
    },
    domains: ['orders', 'quota'],
  });

  const orders = data?.orders ?? [];
  const stats = data?.stats ?? { revenue: 0, orders: 0, products: 0 };

  return useMemo(
    () => ({ orders, stats, loading: isLoading, refresh }),
    [isLoading, orders, refresh, stats],
  );
}

export function useCommerceOrders() {
  const { api } = useAuth();
  const shopApi = useMemo(() => createShopApi(api), [api]);

  return useCommerceOrdersState(shopApi, api.buildUrl, ['shop-orders']);
}

/**
 * Seller-surface orders: same shape as useCommerceOrders, but fetched through
 * the dedicated seller session client and a seller-scoped cache key.
 */
export function useSellerCommerceOrders() {
  const shopApi = useSellerShopApi();
  const { sellerApi } = useSellerAuth();

  return useCommerceOrdersState(shopApi, sellerApi.buildUrl, ['shop-orders', 'seller']);
}

/**
 * Seller-side delivery-token quota (GET shop/quota). Fetched through the
 * dedicated seller session client with a seller-scoped cache key; `quota` is
 * undefined while loading, after a failure, and on backends that omit the
 * optional aggregate — callers hide the quota surface in those cases.
 */
export function useSellerDeliveryQuota(): { quota: ShopSellerDeliveryQuota | undefined; loading: boolean; refresh: () => void } {
  const shopApi = useSellerShopApi();
  const { data, isLoading, refresh } = useCachedQuery<ShopSellerDeliveryQuota>({
    key: ['shop-quota', 'seller'],
    queryFn: async signal => (await shopApi.sellerQuota(signal)).quota,
    domains: ['quota'],
  });
  return useMemo(
    () => ({ quota: data, loading: isLoading, refresh }),
    [data, isLoading, refresh],
  );
}
