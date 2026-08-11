import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useAuth } from './useAuth';
import { useRealtimeContext } from '../stores/RealtimeContext';
import type { ShopCatalogQuery, ShopItem } from '../types/api';
import type { StorefrontOrder, StorefrontProduct, StorefrontStats } from '../components/storefront/types';

type RawShopItem = Partial<ShopItem> & {
  id?: string | number;
  path?: string;
  downloads?: number;
  download_count?: number;
  category?: string;
  tags?: unknown[];
  featured?: boolean;
};
type RawShopOrder = Record<string, unknown> & { id?: string | number; status?: string };
type RawShopStats = Record<string, unknown>;

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

export function toStorefrontProduct(item: RawShopItem, buildUrl: (path: string) => string): StorefrontProduct {
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

export function toStorefrontOrder(order: RawShopOrder, buildUrl: (path: string) => string): StorefrontOrder {
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


function isAbortError(reason: unknown): boolean {
  return typeof reason === 'object'
    && reason !== null
    && 'name' in reason
    && (reason as { name?: unknown }).name === 'AbortError';
}

export interface CommerceCatalogPageState {
  products: StorefrontProduct[];
  page: number;
  pageSize: number;
  total: number;
  loading: boolean;
  error: unknown;
  refresh: () => Promise<void>;
}

/**
 * Paginated public Commerce catalog hook. This is intentionally separate from
 * useCommerceCatalog so the legacy shop/items contract remains untouched.
 */
export function useCommerceCatalogPage(params: ShopCatalogQuery = {}): CommerceCatalogPageState {
  const { api } = useAuth();
  const { registerInvalidation } = useRealtimeContext();
  const [products, setProducts] = useState<StorefrontProduct[]>([]);
  const [page, setPage] = useState(params.page ?? 1);
  const [pageSize, setPageSize] = useState(params.page_size ?? 24);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const requestSequenceRef = useRef(0);
  const requestControllerRef = useRef<AbortController | null>(null);
  const query = useMemo(() => ({
    ...(params.q !== undefined ? { q: params.q } : {}),
    page: params.page ?? 1,
    page_size: params.page_size ?? 24,
    sort: params.sort ?? 'newest',
  }), [params.page, params.page_size, params.q, params.sort]);

  const refresh = useCallback(async () => {
    const requestSequence = ++requestSequenceRef.current;
    requestControllerRef.current?.abort();
    const controller = new AbortController();
    requestControllerRef.current = controller;
    setLoading(true);
    try {
      const response = await api.get<{
        items?: RawShopItem[];
        page?: number;
        page_size?: number;
        total?: number;
      }>('shop/catalog', query, controller.signal);
      if (controller.signal.aborted || requestSequence !== requestSequenceRef.current) return;
      setProducts((response.items ?? []).map(item => toStorefrontProduct(item, api.buildUrl)));
      setPage(asNumber(response.page, query.page));
      setPageSize(asNumber(response.page_size, query.page_size));
      setTotal(asNumber(response.total));
      setError(null);
    } catch (reason) {
      if (controller.signal.aborted || isAbortError(reason) || requestSequence !== requestSequenceRef.current) return;
      setProducts([]);
      setTotal(0);
      setError(reason);
    } finally {
      if (!controller.signal.aborted && requestSequence === requestSequenceRef.current) setLoading(false);
    }
  }, [api, query]);

  useEffect(() => {
    void refresh();
    const unregister = registerInvalidation(['shop'], () => { void refresh(); });
    return () => {
      requestSequenceRef.current += 1;
      requestControllerRef.current?.abort();
      requestControllerRef.current = null;
      unregister();
    };
  }, [refresh, registerInvalidation]);

  return useMemo(() => ({ products, page, pageSize, total, loading, error, refresh }), [error, loading, page, pageSize, products, refresh, total]);
}

export function useCommerceCatalog(includeDisabled = false) {
  const { api } = useAuth();
  const { registerInvalidation } = useRealtimeContext();
  const [products, setProducts] = useState<StorefrontProduct[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const requestSequenceRef = useRef(0);
  const requestControllerRef = useRef<AbortController | null>(null);
  const query = useMemo((): Record<string, string | boolean> => {
    if (includeDisabled) return { include_disabled: true };
    return { status: 'active' };
  }, [includeDisabled]);

  const refresh = useCallback(async () => {
    const requestSequence = ++requestSequenceRef.current;
    requestControllerRef.current?.abort();
    const controller = new AbortController();
    requestControllerRef.current = controller;
    setLoading(true);
    try {
      const response = await api.get<{ items: RawShopItem[] }>('shop/items', query, controller.signal);
      if (controller.signal.aborted || requestSequence !== requestSequenceRef.current) return;
      setProducts((response.items ?? []).map(item => toStorefrontProduct(item, api.buildUrl)));
      setError(null);
    } catch (reason) {
      if (controller.signal.aborted || isAbortError(reason) || requestSequence !== requestSequenceRef.current) return;
      setProducts([]);
      setError(reason);
    } finally {
      if (!controller.signal.aborted && requestSequence === requestSequenceRef.current) setLoading(false);
    }
  }, [api, query]);

  useEffect(() => {
    void refresh();
    const unregister = registerInvalidation(['shop'], () => { void refresh(); });
    return () => {
      requestSequenceRef.current += 1;
      requestControllerRef.current?.abort();
      requestControllerRef.current = null;
      unregister();
    };
  }, [refresh, registerInvalidation]);

  return useMemo(() => ({ products, loading, error, refresh }), [error, loading, products, refresh]);
}

export function useCommerceOrders() {
  const { api } = useAuth();
  const { registerInvalidation } = useRealtimeContext();
  const [orders, setOrders] = useState<StorefrontOrder[]>([]);
  const [stats, setStats] = useState<StorefrontStats>({ revenue: 0, orders: 0, products: 0 });
  const [loading, setLoading] = useState(true);
  const requestSequenceRef = useRef(0);

  const refresh = useCallback(async () => {
    const requestSequence = ++requestSequenceRef.current;
    setLoading(true);
    try {
      const [orderResponse, statsResponse] = await Promise.all([
        api.get<{ orders: RawShopOrder[] }>('shop/orders'),
        api.get<{ stats?: RawShopStats }>('shop/stats'),
      ]);
      if (requestSequence !== requestSequenceRef.current) return;
      const nextOrders = (orderResponse.orders ?? []).map(order => toStorefrontOrder(order, api.buildUrl));
      const rawStats = statsResponse.stats ?? {};
      setOrders(nextOrders);
      setStats({
        revenue: asNumber(rawStats.gross_cents) / 100,
        orders: asNumber(rawStats.total_orders, nextOrders.length),
        products: 0,
        views: rawStats.store_views == null ? undefined : asNumber(rawStats.store_views),
      });
    } catch {
      if (requestSequence !== requestSequenceRef.current) return;
      setOrders([]);
      setStats({ revenue: 0, orders: 0, products: 0 });
    } finally {
      if (requestSequence === requestSequenceRef.current) setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void refresh();
    const unregister = registerInvalidation(['orders', 'quota'], () => { void refresh(); });
    return () => {
      requestSequenceRef.current += 1;
      unregister();
    };
  }, [refresh, registerInvalidation]);

  return useMemo(() => ({ orders, stats, loading, refresh }), [loading, orders, refresh, stats]);
}
