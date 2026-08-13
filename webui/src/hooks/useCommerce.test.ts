// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react';
import { createElement, type ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryCacheProvider } from '../cache/QueryCacheContext';
import { assetThumbnailUrl, canonicalizeShopPath, toStorefrontOrder, toStorefrontProduct, useCommerceCatalog, useCommerceCatalogPage } from './useCommerce';

const commerceMocks = vi.hoisted(() => ({
  api: {
    buildUrl: (path: string) => `/api/${path}`,
    get: vi.fn(),
  },
}));

vi.mock('./useAuth', () => ({ useAuth: () => ({ api: commerceMocks.api, identityGeneration: 0 }) }));
vi.mock('./useInvalidation', () => ({
  useInvalidation: () => ({}),
}));

function wrapper({ children }: { children: ReactNode }) {
  return createElement(QueryCacheProvider, null, children);
}

function setupBuildUrl() {
  return vi.fn((path: string) => `/library/api/${path}`);
}

describe('commerce resource URL mapping', () => {
  beforeEach(() => {
    commerceMocks.api.get.mockReset();
  });

  it('canonicalizes shop paths like the backend and rejects unsafe paths', () => {
    expect(canonicalizeShopPath('  packs//./nested\\asset.zip  ')).toBe('packs/nested/asset.zip');
    expect(canonicalizeShopPath('../asset.zip')).toBeNull();
    expect(canonicalizeShopPath('/packs/asset.zip')).toBeNull();
    expect(canonicalizeShopPath('C:/packs/asset.zip')).toBeNull();
  });

  it('does not let an older catalog refresh overwrite the latest response', async () => {
    let resolveFirst!: (value: { items: Array<Record<string, unknown>> }) => void;
    let resolveSecond!: (value: { items: Array<Record<string, unknown>> }) => void;
    commerceMocks.api.get
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve; }));

    const { result } = renderHook(() => useCommerceCatalog(), { wrapper });
    await waitFor(() => expect(commerceMocks.api.get).toHaveBeenCalledTimes(1));
    const latestRefresh = result.current.refresh();
    await act(async () => {
      resolveSecond({ items: [{ id: 2, path: 'latest.zip', title: 'Latest', enabled: true }] });
      await latestRefresh;
    });
    expect(result.current.products[0]?.name).toBe('Latest');

    await act(async () => {
      resolveFirst({ items: [{ id: 1, path: 'stale.zip', title: 'Stale', enabled: true }] });
      await Promise.resolve();
    });
    expect(result.current.products[0]?.name).toBe('Latest');
    expect(result.current.loading).toBe(false);
  });
  it('loads a catalog page through shop/catalog and forwards query parameters', async () => {
    commerceMocks.api.get.mockResolvedValueOnce({
      items: [{ id: 12, path: 'packs/alpha.zip', title: 'Alpha', cover_path: 'packs/alpha.png', enabled: true }],
      page: 2,
      page_size: 10,
      total: 31,
    });

    const { result } = renderHook(() => useCommerceCatalogPage({
      q: 'alpha',
      page: 2,
      page_size: 10,
      sort: 'newest',
    }), { wrapper });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(commerceMocks.api.get).toHaveBeenCalledWith(
      'shop/catalog',
      { q: 'alpha', page: 2, page_size: 10, sort: 'newest' },
      expect.any(AbortSignal),
    );
    expect(result.current.products[0]?.name).toBe('Alpha');
    expect(result.current.page).toBe(2);
    expect(result.current.pageSize).toBe(10);
    expect(result.current.total).toBe(31);
    expect(result.current.error).toBeNull();
  });

  it('uses catalog defaults and exposes request errors', async () => {
    const reason = new Error('catalog unavailable');
    commerceMocks.api.get.mockRejectedValueOnce(reason);

    const { result } = renderHook(() => useCommerceCatalogPage(), { wrapper });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(commerceMocks.api.get).toHaveBeenCalledWith(
      'shop/catalog',
      { page: 1, page_size: 24, sort: 'newest' },
      expect.any(AbortSignal),
    );
    expect(result.current.page).toBe(1);
    expect(result.current.pageSize).toBe(24);
    expect(result.current.products).toEqual([]);
    expect(result.current.total).toBe(0);
    expect(result.current.error).toBe(reason);
  });

  it('lets the newest catalog request win and ignores stale responses', async () => {
    let resolveFirst!: (value: { items: Array<Record<string, unknown>>; page: number; page_size: number; total: number }) => void;
    let resolveSecond!: (value: { items: Array<Record<string, unknown>>; page: number; page_size: number; total: number }) => void;
    commerceMocks.api.get
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve; }));

    const { result } = renderHook(() => useCommerceCatalogPage({ q: 'asset' }), { wrapper });
    await waitFor(() => expect(commerceMocks.api.get).toHaveBeenCalledTimes(1));

    const latestRefresh = result.current.refresh();
    await act(async () => {
      resolveSecond({
        items: [{ id: 2, path: 'latest.zip', title: 'Latest', enabled: true }],
        page: 1,
        page_size: 24,
        total: 1,
      });
      await latestRefresh;
    });
    expect(result.current.products[0]?.name).toBe('Latest');

    await act(async () => {
      resolveFirst({
        items: [{ id: 1, path: 'stale.zip', title: 'Stale', enabled: true }],
        page: 1,
        page_size: 24,
        total: 1,
      });
      await Promise.resolve();
    });
    expect(result.current.products[0]?.name).toBe('Latest');
    expect(result.current.loading).toBe(false);
  });

  it('builds product thumbnails through the configured API base path', () => {
    const buildUrl = setupBuildUrl();

    const product = toStorefrontProduct({
      id: 7,
      path: 'projects/alpha',
      title: 'Alpha',
      cover_path: 'projects/alpha/cover image.png',
      price_cents: 1250,
      currency: 'CNY',
      enabled: true,
    }, buildUrl);

    expect(product.imageUrl).toBe('/library/api/shop/items/7/media/cover?size=512');
    expect(buildUrl).toHaveBeenCalledWith('shop/items/7/media/cover?size=512');
  });

  it('builds seller order cover thumbnails through the configured API base path', () => {
    const buildUrl = setupBuildUrl();

    const order = toStorefrontOrder({
      id: 'order-1',
      status: 'confirmed',
      item_title: 'Alpha',
      cover_path: 'projects/alpha/cover.png',
      amount_cents: 500,
      currency: 'CNY',
      created_at: 1_700_000_000,
    }, buildUrl);

    expect(order.productImageUrl).toBe('/library/api/thumbnails/projects%2Falpha%2Fcover.png?size=512');
    expect(buildUrl).toHaveBeenCalledWith('thumbnails/projects%2Falpha%2Fcover.png?size=512');
  });

  it('keeps fully qualified external thumbnail URLs unchanged', () => {
    const buildUrl = setupBuildUrl();

    expect(assetThumbnailUrl('https://cdn.example.test/cover.png', 512, buildUrl))
      .toBe('https://cdn.example.test/cover.png');
    expect(buildUrl).not.toHaveBeenCalled();
  });

  it('does not build thumbnail URLs for non-image assets', () => {
    const buildUrl = setupBuildUrl();

    expect(assetThumbnailUrl('shop/sales/archive.zip', 512, buildUrl)).toBe('');
    expect(assetThumbnailUrl('shop/sales/document.txt', 512, buildUrl)).toBe('');
    expect(buildUrl).not.toHaveBeenCalled();
  });

  it('maps gallery_paths into additional configured thumbnail URLs', () => {
    const buildUrl = setupBuildUrl();
    const product = toStorefrontProduct({
      id: 8,
      path: 'projects/alpha',
      title: 'Alpha',
      cover_path: 'projects/alpha/cover.png',
      gallery_paths: ['projects/alpha/detail.png', 'projects/alpha/cover.png'],
      price_cents: 1250,
      currency: 'CNY',
      enabled: true,
    }, buildUrl);
    expect(product.gallery).toEqual([
      '/library/api/shop/items/8/media/gallery-0?size=512',
    ]);
    expect(buildUrl).toHaveBeenCalledWith('shop/items/8/media/cover?size=512');
    expect(buildUrl).toHaveBeenCalledWith('shop/items/8/media/gallery-0?size=512');
  });

  it('uses stable cover/gallery media slots while preserving order and deduplication', () => {
    const buildUrl = setupBuildUrl();
    const product = toStorefrontProduct({
      id: 17,
      path: 'packs/asset.zip',
      title: 'Asset pack',
      cover_path: 'packs/cover.png',
      gallery_paths: ['packs/one.png', 'packs/cover.png', 'packs/two.jpg', 'packs/one.png'],
      enabled: true,
    }, buildUrl);

    expect(product.imageUrl).toBe('/library/api/shop/items/17/media/cover?size=512');
    expect(product.gallery).toEqual([
      '/library/api/shop/items/17/media/gallery-0?size=512',
      '/library/api/shop/items/17/media/gallery-2?size=512',
    ]);
    expect(buildUrl).toHaveBeenCalledWith('shop/items/17/media/gallery-0?size=512');
    expect(buildUrl).toHaveBeenCalledWith('shop/items/17/media/gallery-2?size=512');
  });

  it('falls back to ordinary thumbnails without a numeric item id', () => {
    const buildUrl = setupBuildUrl();
    const product = toStorefrontProduct({
      path: 'packs/asset.zip',
      cover_path: 'packs/cover.png',
      gallery_paths: ['packs/detail.png'],
      enabled: true,
    }, buildUrl);

    expect(product.imageUrl).toBe('/library/api/thumbnails/packs%2Fcover.png?size=512');
    expect(product.gallery).toEqual(['/library/api/thumbnails/packs%2Fdetail.png?size=512']);
    expect(buildUrl).toHaveBeenCalledWith('thumbnails/packs%2Fcover.png?size=512');
    expect(buildUrl).toHaveBeenCalledWith('thumbnails/packs%2Fdetail.png?size=512');
  });

  it('keeps external product media URLs unchanged', () => {
    const buildUrl = setupBuildUrl();
    const product = toStorefrontProduct({
      id: 19,
      path: 'packs/asset.zip',
      cover_path: 'https://cdn.example.test/cover.png',
      gallery_paths: ['/images/detail.jpg'],
      enabled: true,
    }, buildUrl);

    expect(product.imageUrl).toBe('https://cdn.example.test/cover.png');
    expect(product.gallery).toEqual(['/images/detail.jpg']);
    expect(buildUrl).not.toHaveBeenCalled();
  });

  it('does not request thumbnails for non-image product files', () => {
    const buildUrl = setupBuildUrl();

    const product = toStorefrontProduct({
      id: 9,
      path: 'shop/sales/hero.txt',
      title: 'Text asset',
      price_cents: 1200,
      currency: 'CNY',
      enabled: true,
    }, buildUrl);

    expect(product.imageUrl).toBe('');
    expect(product.gallery).toEqual([]);
    expect(buildUrl).not.toHaveBeenCalled();
  });

  it('keeps an image cover when the downloadable product path is non-image', () => {
    const buildUrl = setupBuildUrl();

    const product = toStorefrontProduct({
      id: 10,
      path: 'shop/sales/hero.zip',
      title: 'Archive asset',
      cover_path: 'shop/sales/cover.png',
      price_cents: 1200,
      currency: 'CNY',
      enabled: true,
    }, buildUrl);

    expect(product.imageUrl).toBe('/library/api/shop/items/10/media/cover?size=512');
    expect(buildUrl).toHaveBeenCalledTimes(1);
  });
});
