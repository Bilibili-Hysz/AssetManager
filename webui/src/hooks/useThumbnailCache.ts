import { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { useAuth } from './useAuth';
import { createThumbnailsApi } from '../api/thumbnails';

const MAX_CACHE = 300;
const THUMBNAIL_CACHE_STORAGE_PREFIX = 'lan_thumb_cache:';
const LEGACY_THUMBNAIL_CACHE_STORAGE_KEY = 'lan_thumb_cache';
export const THUMBNAIL_CACHE_STORAGE_KEY = LEGACY_THUMBNAIL_CACHE_STORAGE_KEY;

interface ThumbnailCache {
  [path: string]: string; // base64 data
}

export function thumbnailCacheStorageKey(namespace: string): string {
  return `${THUMBNAIL_CACHE_STORAGE_PREFIX}${encodeURIComponent(namespace || 'legacy')}`;
}

/**
 * Cap the memory cache at MAX_CACHE entries, evicting the least recently
 * accessed paths. The Map preserves insertion order; a cache read (or write)
 * moves a key to the end via delete+set, so iteration order tracks recency.
 */
function trimCache(cache: Map<string, string>): Map<string, string> {
  if (cache.size <= MAX_CACHE) return cache;
  const entries = Array.from(cache.entries());
  return new Map(entries.slice(entries.length - MAX_CACHE));
}

export function useThumbnailCache() {
  const { api, identityGeneration, thumbnailCacheNamespace } = useAuth();
  const namespace = thumbnailCacheNamespace || 'legacy';
  const storageKey = useMemo(() => thumbnailCacheStorageKey(namespace), [namespace]);
  const thumbApi = useMemo(() => createThumbnailsApi(api), [api]);
  const [cache, setCache] = useState<ThumbnailCache>({});
  const cacheRef = useRef<Map<string, string>>(new Map());
  const pendingRef = useRef(new Set<string>());
  const namespaceRef = useRef(namespace);
  const identityGenerationRef = useRef(identityGeneration);
  const previousIdentityGenerationRef = useRef(identityGeneration);
  namespaceRef.current = namespace;
  identityGenerationRef.current = identityGeneration;

  useEffect(() => {
    const generationChanged = previousIdentityGenerationRef.current !== identityGeneration;
    previousIdentityGenerationRef.current = identityGeneration;
    cacheRef.current = new Map();
    pendingRef.current.clear();
    setCache({});
    try {
      window.sessionStorage.removeItem(LEGACY_THUMBNAIL_CACHE_STORAGE_KEY);
      if (generationChanged) {
        window.sessionStorage.removeItem(storageKey);
        return;
      }
      const stored = window.sessionStorage.getItem(storageKey);
      if (stored) {
        const restoredCache = JSON.parse(stored) as ThumbnailCache;
        if (restoredCache && typeof restoredCache === 'object' && !Array.isArray(restoredCache)) {
          const restoredMap = trimCache(new Map(Object.entries(restoredCache)));
          cacheRef.current = restoredMap;
          setCache(Object.fromEntries(restoredMap));
        }
      }
    } catch { /* ignore */ }
  }, [identityGeneration, namespace, storageKey]);

  const persist = useCallback((nextCache: Map<string, string>) => {
    const retained = trimCache(nextCache);
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(Object.fromEntries(retained)));
    } catch { /* quota exceeded */ }
    return retained;
  }, [storageKey]);

  const loadThumbnails = useCallback(async (paths: string[]) => {
    const generation = identityGeneration;
    const requestNamespace = namespace;
    const pending = pendingRef.current;
    const uncached = paths.filter(path => path && !cacheRef.current.has(path) && !pending.has(path));
    if (uncached.length === 0) return;
    for (const path of uncached) pending.add(path);

    try {
      const res = await thumbApi.batch(uncached, 256);
      if (generation !== identityGenerationRef.current || requestNamespace !== namespaceRef.current) return;
      const nextCache = new Map(cacheRef.current);
      for (const [path, encoded] of Object.entries(res.thumbnails)) {
        nextCache.delete(path);
        nextCache.set(path, encoded);
      }
      const retainedCache = persist(nextCache);
      cacheRef.current = retainedCache;
      setCache(Object.fromEntries(retainedCache));
    } catch { /* ignore */ } finally {
      for (const path of uncached) pending.delete(path);
    }
  }, [identityGeneration, namespace, persist, thumbApi]);

  const getThumbnail = useCallback((path: string): string | undefined => {
    const current = cacheRef.current;
    if (!current.has(path)) return undefined;
    const encoded = current.get(path) as string;
    current.delete(path);
    current.set(path, encoded);
    return encoded;
  }, []);

  return { loadThumbnails, getThumbnail, revision: cache };
}
