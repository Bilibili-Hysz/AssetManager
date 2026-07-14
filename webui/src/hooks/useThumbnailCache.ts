import { useState, useCallback, useEffect, useMemo } from 'react';
import { useAuth } from './useAuth';
import { createThumbnailsApi } from '../api/thumbnails';

const MAX_CACHE = 300;

interface ThumbnailCache {
  [path: string]: string; // base64 data
}

export function useThumbnailCache() {
  const { api } = useAuth();
  const thumbApi = useMemo(() => createThumbnailsApi(api), [api]);
  const [cache, setCache] = useState<ThumbnailCache>({});

  useEffect(() => {
    try {
      const stored = window.sessionStorage.getItem('lan_thumb_cache');
      if (stored) {
        setCache(JSON.parse(stored));
      }
    } catch { /* ignore */ }
  }, []);

  const persist = useCallback((nextCache: ThumbnailCache) => {
    try {
      const entries = Object.entries(nextCache);
      const retained = entries.length > MAX_CACHE ? Object.fromEntries(entries.slice(-MAX_CACHE)) : nextCache;
      sessionStorage.setItem('lan_thumb_cache', JSON.stringify(retained));
      return retained;
    } catch { /* quota exceeded */ }
  }, []);

  const loadThumbnails = useCallback(async (paths: string[]) => {
    const uncached = paths.filter(p => !cache[p] && p);
    if (uncached.length === 0) return;

    try {
      const res = await thumbApi.batch(uncached, 256);
      setCache(current => {
        const nextCache = { ...current, ...res.thumbnails };
        return persist(nextCache) ?? nextCache;
      });
    } catch { /* ignore */ }
  }, [cache, thumbApi, persist]);

  const getThumbnail = useCallback((path: string): string | undefined => {
    return cache[path];
  }, [cache]);

  return { loadThumbnails, getThumbnail, revision: cache };
}
