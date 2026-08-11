import { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { useAuth } from './useAuth';
import { createThumbnailsApi } from '../api/thumbnails';

const MAX_CACHE = 300;
export const THUMBNAIL_CACHE_STORAGE_KEY = 'lan_thumb_cache';

interface ThumbnailCache {
  [path: string]: string; // base64 data
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
  const { api, identityGeneration } = useAuth();
  const thumbApi = useMemo(() => createThumbnailsApi(api), [api]);
  const [cache, setCache] = useState<ThumbnailCache>({});
  const cacheRef = useRef<Map<string, string>>(new Map());
  const pendingRef = useRef(new Set<string>());
  const identityGenerationRef = useRef(identityGeneration);
  identityGenerationRef.current = identityGeneration;

  useEffect(() => {
    cacheRef.current = new Map();
    pendingRef.current.clear();
    setCache({});
    try {
      sessionStorage.removeItem(THUMBNAIL_CACHE_STORAGE_KEY);
    } catch { /* ignore storage failures */ }
  }, [identityGeneration]);

  useEffect(() => {
    try {
      const stored = window.sessionStorage.getItem(THUMBNAIL_CACHE_STORAGE_KEY);
      if (stored) {
        const restoredCache = JSON.parse(stored) as ThumbnailCache;
        const restoredMap = trimCache(new Map(Object.entries(restoredCache)));
        cacheRef.current = restoredMap;
        setCache(Object.fromEntries(restoredMap));
      }
    } catch { /* ignore */ }
  }, []);

  const persist = useCallback((nextCache: Map<string, string>) => {
    // Trim regardless of whether storage succeeds so a full quota failure
    // cannot leave an unbounded memory cache behind.
    const retained = trimCache(nextCache);
    try {
      sessionStorage.setItem(THUMBNAIL_CACHE_STORAGE_KEY, JSON.stringify(Object.fromEntries(retained)));
    } catch { /* quota exceeded */ }
    return retained;
  }, []);

  const loadThumbnails = useCallback(async (paths: string[]) => {
    const generation = identityGeneration;
    const pending = pendingRef.current;
    const uncached = paths.filter(path => path && !cacheRef.current.has(path) && !pending.has(path));
    if (uncached.length === 0) return;
    for (const path of uncached) pending.add(path);

    try {
      const res = await thumbApi.batch(uncached, 256);
      if (generation !== identityGenerationRef.current) return;
      const nextCache = new Map(cacheRef.current);
      for (const [path, encoded] of Object.entries(res.thumbnails)) {
        nextCache.delete(path); // refresh access order
        nextCache.set(path, encoded);
      }
      const retainedCache = persist(nextCache);
      cacheRef.current = retainedCache;
      setCache(Object.fromEntries(retainedCache));
    } catch { /* ignore */ } finally {
      for (const path of uncached) pending.delete(path);
    }
  }, [identityGeneration, persist, thumbApi]);

  const getThumbnail = useCallback((path: string): string | undefined => {
    const current = cacheRef.current;
    if (!current.has(path)) return undefined;
    const encoded = current.get(path) as string;
    // Move the key to the end so insertion order doubles as LRU access order.
    current.delete(path);
    current.set(path, encoded);
    return encoded;
  }, []);

  return { loadThumbnails, getThumbnail, revision: cache };
}
