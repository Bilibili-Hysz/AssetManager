import { useState, useCallback, useRef } from 'react';
import { useAuth } from './useAuth';
import { createThumbnailsApi } from '../api/thumbnails';

const MAX_CACHE = 300;

interface ThumbnailCache {
  [path: string]: string; // base64 data
}

export function useThumbnailCache() {
  const { api } = useAuth();
  const thumbApi = createThumbnailsApi(api);
  const cache = useRef<ThumbnailCache>({});

  // Load from sessionStorage on init
  useState(() => {
    try {
      const stored = sessionStorage.getItem('lan_thumb_cache');
      if (stored) cache.current = JSON.parse(stored);
    } catch { /* ignore */ }
  });

  const persist = useCallback(() => {
    try {
      const entries = Object.entries(cache.current);
      if (entries.length > MAX_CACHE) {
        // LRU eviction: remove oldest entries
        const newCache: ThumbnailCache = {};
        entries.slice(-MAX_CACHE).forEach(([k, v]) => { newCache[k] = v; });
        cache.current = newCache;
      }
      sessionStorage.setItem('lan_thumb_cache', JSON.stringify(cache.current));
    } catch { /* quota exceeded */ }
  }, []);

  const loadThumbnails = useCallback(async (paths: string[]) => {
    const uncached = paths.filter(p => !cache.current[p] && p);
    if (uncached.length === 0) return;

    try {
      const res = await thumbApi.batch(uncached, 256);
      Object.assign(cache.current, res.thumbnails);
      persist();
    } catch { /* ignore */ }
  }, [thumbApi, persist]);

  const getThumbnail = useCallback((path: string): string | undefined => {
    return cache.current[path];
  }, []);

  return { loadThumbnails, getThumbnail };
}