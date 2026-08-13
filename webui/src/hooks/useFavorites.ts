import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createFavoritesApi } from '../api/favorites';
import { useToast } from '../components/ui/Toast';
import type { GalleryEntry, SessionPrincipal } from '../types/api';
import { useAuth } from './useAuth';
import { useCachedQuery } from './useCachedQuery';
import { useI18n } from './useI18n';

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
  const { api, serverInfo, principal } = useAuth();
  const { showToast } = useToast();
  const { t } = useI18n();
  const showToastRef = useRef(showToast);
  const tRef = useRef(t);
  showToastRef.current = showToast;
  tRef.current = t;
  const favoritesApi = useMemo(() => createFavoritesApi(api), [api]);
  const libraryIdentity = serverInfo?.library_root?.trim()
    || serverInfo?.share_name?.trim()
    || 'unknown-library';
  const cacheKey = `${STORAGE_KEY}:${encodeURIComponent([
    window.location.origin,
    libraryIdentity,
    principalIdentity(principal),
  ].join('|'))}`;

  // The network read path lives in the shared cache: the sidebar and the
  // gallery pages mount their own instance but share one GET /api/favorites
  // per library + principal (the key swap and the provider-level identity
  // clear handle user switches). In-flight dedup replaces the old
  // module-level sharedFavoritesRequest.
  const { data, error, isLoading, refresh } = useCachedQuery<GalleryEntry[]>({
    key: ['favorites', cacheKey],
    queryFn: () => favoritesApi.list().then(response => normalizeEntries(response.favorites)),
    domains: FAVORITES_DOMAINS,
  });

  const [paths, setPaths] = useState<string[]>(() => readCache(cacheKey));
  const [items, setItems] = useState<GalleryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const pathsRef = useRef(paths);
  const itemsRef = useRef(items);
  const cacheKeyRef = useRef(cacheKey);
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

  // Library/identity switch: drop every local trace of the previous context.
  // The cache entry swaps by key (and the provider clears the whole cache on
  // identity changes), so the fetch itself is driven by useCachedQuery.
  useEffect(() => {
    contextGenerationRef.current += 1;
    mutationGenerationRef.current += 1;
    for (const controller of mutationControllersRef.current) controller.abort();
    mutationControllersRef.current.clear();
    cacheKeyRef.current = cacheKey;
    pendingMutationsRef.current.clear();
    pathMutationGenerationRef.current.clear();
    mutationQueueRef.current = Promise.resolve();
    updatePaths(readCache(cacheKey));
    updateItems([]);
  }, [cacheKey, updateItems, updatePaths]);

  // The server list is the source of truth once a response lands; responses
  // arriving while optimistic mutations are pending are skipped so they
  // cannot clobber optimistic state (the pre-cache guard, unchanged).
  useEffect(() => {
    if (data === undefined) return;
    if (pendingMutationsRef.current.size > 0) return;
    updateItems(data);
    updatePaths(data.map(item => item.path));
  }, [data, updateItems, updatePaths]);

  useEffect(() => {
    setLoading(isLoading);
  }, [isLoading]);

  // One toast per load failure (the entry keeps the last good list visible).
  useEffect(() => {
    if (error != null) {
      const message = tRef.current('gallery.favorites_load_failed');
      showToastRef.current(message, 'error');
    }
  }, [error]);

  // Other tabs write the same localStorage key; 'storage' events fire only
  // cross-tab, so each mounted instance stays in sync with the latest
  // favorites without another network round-trip.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== cacheKeyRef.current) return;
      const latest = readCache(cacheKeyRef.current);
      const current = pathsRef.current;
      if (current.length === latest.length && current.every((path, index) => path === latest[index])) return;
      updatePaths(latest);
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [updatePaths]);

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
    setLoading(false);
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
          // Queue drained: pull the confirmed server list once.
          refresh();
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

  const errorMessage = error != null ? t('gallery.favorites_load_failed') : null;

  return {
    favorites: paths,
    items,
    loading,
    error: errorMessage,
    addFavorite,
    removeFavorite,
    toggleFavorite,
    isFavorite,
    refresh,
  };
}
