import { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { useAuth } from './useAuth';
import { createThumbnailsApi } from '../api/thumbnails';

const MAX_CACHE = 300;
export const THUMBNAIL_CACHE_STORAGE_KEY = 'lan_thumb_cache';

interface ThumbnailCache {
  [path: string]: string; // base64 data
}

export function useThumbnailCache() {
  const { api, identityGeneration } = useAuth();
  const thumbApi = useMemo(() => createThumbnailsApi(api), [api]);
  const [cache, setCache] = useState<ThumbnailCache>({});
  const cacheRef = useRef<ThumbnailCache>({});
  const identityGenerationRef = useRef(identityGeneration);
  identityGenerationRef.current = identityGeneration;

  useEffect(() => {
    cacheRef.current = {};
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
        cacheRef.current = restoredCache;
        setCache(restoredCache);
      }
    } catch { /* ignore */ }
  }, []);

  const persist = useCallback((nextCache: ThumbnailCache) => {
    try {
      const entries = Object.entries(nextCache);
      const retained = entries.length > MAX_CACHE ? Object.fromEntries(entries.slice(-MAX_CACHE)) : nextCache;
      sessionStorage.setItem(THUMBNAIL_CACHE_STORAGE_KEY, JSON.stringify(retained));
      return retained;
    } catch { /* quota exceeded */ }
  }, []);

  const loadThumbnails = useCallback(async (paths: string[]) => {
    const generation = identityGeneration;
    const uncached = paths.filter(path => path && !cacheRef.current[path]);
    if (uncached.length === 0) return;

    try {
      const res = await thumbApi.batch(uncached, 256);
      if (generation !== identityGenerationRef.current) return;
      setCache(current => {
        const nextCache = { ...current, ...res.thumbnails };
        const retainedCache = persist(nextCache) ?? nextCache;
        cacheRef.current = retainedCache;
        return retainedCache;
      });
    } catch { /* ignore */ }
  }, [identityGeneration, persist, thumbApi]);

  const getThumbnail = useCallback((path: string): string | undefined => {
    return cache[path];
  }, [cache]);

  return { loadThumbnails, getThumbnail, revision: cache };
}
