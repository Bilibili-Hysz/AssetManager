import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createFavoritesApi } from '../api/favorites';
import { useToast } from '../components/ui/Toast';
import type { GalleryEntry, SessionPrincipal } from '../types/api';
import { useAuth } from './useAuth';
import { useI18n } from './useI18n';
import { useInvalidation } from './useInvalidation';

const STORAGE_KEY = 'am_favorites_cache:v2';
const FAVORITES_DOMAINS = ['favorites'] as const;

function normalizePaths(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const paths: string[] = [];
  for (const candidate of value) {
    if (typeof candidate !== 'string') continue;
    const path = candidate.trim();
    if (!path || seen.has(path)) continue;
    seen.add(path);
    paths.push(path);
  }
  return paths;
}

function normalizeEntries(value: unknown): GalleryEntry[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const entries: GalleryEntry[] = [];
  for (const candidate of value) {
    if (!candidate || typeof candidate !== 'object') continue;
    const entry = candidate as GalleryEntry;
    if (typeof entry.path !== 'string' || !entry.path.trim() || seen.has(entry.path)) continue;
    seen.add(entry.path);
    entries.push(entry);
  }
  return entries;
}

function readCache(storageKey: string): string[] {
  try {
    const raw = localStorage.getItem(storageKey);
    return raw ? normalizePaths(JSON.parse(raw)) : [];
  } catch {
    return [];
  }
}

function writeCache(storageKey: string, paths: string[]) {
  try {
    localStorage.setItem(storageKey, JSON.stringify(normalizePaths(paths)));
  } catch {
    // Favorites remain usable when storage is unavailable.
  }
}

function isAbortError(error: unknown): boolean {
  return typeof error === 'object'
    && error !== null
    && 'name' in error
    && (error as { name?: unknown }).name === 'AbortError';
}

function principalIdentity(principal?: SessionPrincipal): string {
  if (!principal) return 'principal:unknown';
  if (principal.kind === 'user' && principal.user_profile?.id != null) {
    return `user:${principal.user_profile.id}`;
  }
  return `principal:${principal.kind}`;
}

export function useFavorites() {
  const { api, serverInfo, principal, identityGeneration } = useAuth();
  const { showToast } = useToast();
  const { t } = useI18n();
  const showToastRef = useRef(showToast);
  const tRef = useRef(t);
  showToastRef.current = showToast;
  tRef.current = t;
  const favoritesApi = useMemo(() => createFavoritesApi(api), [api]);
  const libraryIdentity = [
    serverInfo?.asset_root_id?.trim(),
    serverInfo?.library_root?.trim() || serverInfo?.share_name?.trim(),
  ].filter(Boolean).join('|') || 'unknown-library';
  const cacheKey = `${STORAGE_KEY}:${encodeURIComponent([
    window.location.origin,
    libraryIdentity,
    principalIdentity(principal),
  ].join('|'))}`;

  const [paths, setPaths] = useState<string[]>(() => readCache(cacheKey));
  const [items, setItems] = useState<GalleryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pathsRef = useRef(paths);
  const itemsRef = useRef(items);
  const cacheKeyRef = useRef(cacheKey);
  const refreshGenerationRef = useRef(0);
  const refreshControllerRef = useRef<AbortController | null>(null);
  const mutationGenerationRef = useRef(0);
  const pathMutationGenerationRef = useRef(new Map<string, number>());
  const pendingMutationsRef = useRef(new Set<number>());
  const mutationQueueRef = useRef(Promise.resolve());
  const mutationControllersRef = useRef(new Set<AbortController>());
  const contextGenerationRef = useRef(0);

  const updatePaths = useCallback((nextPaths: string[]) => {
    const normalized = normalizePaths(nextPaths);
    pathsRef.current = normalized;
    setPaths(normalized);
    writeCache(cacheKeyRef.current, normalized);
  }, []);

  const updateItems = useCallback((nextItems: GalleryEntry[]) => {
    itemsRef.current = nextItems;
    setItems(nextItems);
  }, []);

  const refresh = useCallback(async () => {
    const generation = ++refreshGenerationRef.current;
    const mutationGeneration = mutationGenerationRef.current;
    const contextGeneration = contextGenerationRef.current;
    const requestCacheKey = cacheKeyRef.current;
    refreshControllerRef.current?.abort();
    const controller = new AbortController();
    refreshControllerRef.current = controller;
    setLoading(true);
    setError(null);

    try {
      const response = await favoritesApi.list(controller.signal);
      if (controller.signal.aborted
        || generation !== refreshGenerationRef.current
        || mutationGeneration !== mutationGenerationRef.current
        || pendingMutationsRef.current.size > 0
        || contextGeneration !== contextGenerationRef.current
        || requestCacheKey !== cacheKeyRef.current) return;
      const favorites = normalizeEntries(response.favorites);
      updatePaths(favorites.map(item => item.path));
      updateItems(favorites);
      setError(null);
    } catch (caught) {
      if (controller.signal.aborted
        || isAbortError(caught)
        || generation !== refreshGenerationRef.current
        || contextGeneration !== contextGenerationRef.current) return;
      const message = tRef.current('gallery.favorites_load_failed');
      setError(message);
      showToastRef.current(message, 'error');
    } finally {
      if (!controller.signal.aborted
        && generation === refreshGenerationRef.current
        && contextGeneration === contextGenerationRef.current) {
        setLoading(false);
      }
    }
  }, [favoritesApi, updateItems, updatePaths]);

  useEffect(() => {
    contextGenerationRef.current += 1;
    refreshGenerationRef.current += 1;
    mutationGenerationRef.current += 1;
    refreshControllerRef.current?.abort();
    for (const controller of mutationControllersRef.current) controller.abort();
    mutationControllersRef.current.clear();
    cacheKeyRef.current = cacheKey;
    pendingMutationsRef.current.clear();
    pathMutationGenerationRef.current.clear();
    mutationQueueRef.current = Promise.resolve();
    updatePaths(readCache(cacheKey));
    updateItems([]);
    void refresh();

    return () => {
      contextGenerationRef.current += 1;
      refreshGenerationRef.current += 1;
      refreshControllerRef.current?.abort();
      for (const controller of mutationControllersRef.current) controller.abort();
      mutationControllersRef.current.clear();
    };
  }, [cacheKey, identityGeneration, refresh, updateItems, updatePaths]);

  useInvalidation(FAVORITES_DOMAINS, () => {
    void refresh();
  });

  const setFavorite = useCallback((favoritePath: string, favorite: boolean) => {
    const path = favoritePath.trim();
    if (!path) return Promise.resolve();
    const wasFavorite = pathsRef.current.includes(path);
    if (wasFavorite === favorite) return Promise.resolve();

    const generation = ++mutationGenerationRef.current;
    const contextGeneration = contextGenerationRef.current;
    const removedItem = favorite
      ? undefined
      : itemsRef.current.find(item => item.path === path);
    const removedIndex = favorite
      ? -1
      : itemsRef.current.findIndex(item => item.path === path);
    pathMutationGenerationRef.current.set(path, generation);
    pendingMutationsRef.current.add(generation);
    refreshGenerationRef.current += 1;
    refreshControllerRef.current?.abort();
    setLoading(false);
    setError(null);
    updatePaths(favorite
      ? [...pathsRef.current, path]
      : pathsRef.current.filter(candidate => candidate !== path));
    if (!favorite) {
      updateItems(itemsRef.current.filter(item => item.path !== path));
    }

    const operation = mutationQueueRef.current.then(async () => {
      if (contextGeneration !== contextGenerationRef.current) return;
      const controller = new AbortController();
      mutationControllersRef.current.add(controller);
      try {
        if (favorite) await favoritesApi.add(path, controller.signal);
        else await favoritesApi.remove(path, controller.signal);
      } catch (caught) {
        if (isAbortError(caught) || contextGeneration !== contextGenerationRef.current) return;
        if (pathMutationGenerationRef.current.get(path) === generation) {
          if (wasFavorite) {
            // Remove failed — restore the path at its original position.
            const restoredPaths = pathsRef.current.filter(candidate => candidate !== path);
            restoredPaths.splice(Math.min(removedIndex, restoredPaths.length), 0, path);
            updatePaths(restoredPaths);
          } else {
            // Add failed — drop the optimistically added path.
            updatePaths(pathsRef.current.filter(candidate => candidate !== path));
          }
          if (wasFavorite
            && removedItem
            && !itemsRef.current.some(item => item.path === path)) {
            const restoredItems = [...itemsRef.current];
            restoredItems.splice(Math.min(removedIndex, restoredItems.length), 0, removedItem);
            updateItems(restoredItems);
          }
        }
        showToastRef.current(
          favorite
            ? tRef.current('gallery.favorite_save_failed')
            : tRef.current('gallery.favorite_remove_failed'),
          'error',
        );
      } finally {
        mutationControllersRef.current.delete(controller);
        pendingMutationsRef.current.delete(generation);
        if (pathMutationGenerationRef.current.get(path) === generation) {
          pathMutationGenerationRef.current.delete(path);
        }
        if (contextGeneration === contextGenerationRef.current
          && pendingMutationsRef.current.size === 0
          && mutationGenerationRef.current === generation) {
          await refresh();
        }
      }
    });
    mutationQueueRef.current = operation;
    return operation;
  }, [favoritesApi, refresh, updateItems, updatePaths]);

  const addFavorite = useCallback(
    (path: string) => setFavorite(path, true),
    [setFavorite],
  );
  const removeFavorite = useCallback(
    (path: string) => setFavorite(path, false),
    [setFavorite],
  );
  const toggleFavorite = useCallback(
    (path: string) => setFavorite(path, !pathsRef.current.includes(path)),
    [setFavorite],
  );
  const isFavorite = useCallback(
    (path: string) => paths.includes(path),
    [paths],
  );

  return {
    favorites: paths,
    items,
    loading,
    error,
    addFavorite,
    removeFavorite,
    toggleFavorite,
    isFavorite,
    refresh,
  };
}
