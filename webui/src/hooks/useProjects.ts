import { useCallback, useMemo, useRef, useState } from 'react';
import { useAuth } from './useAuth';
import { createFilesApi } from '../api/files';
import { useCachedQuery } from './useCachedQuery';
import type { FilesResponse } from '../types/api';

export interface SortConfig {
  sort: string;
  order: 'asc' | 'desc';
}

/** First-page / load-more page size (backend clamps 1-1000). */
const PAGE_SIZE = 500;

interface UseProjectsReturn {
  data: FilesResponse | null;
  isLoading: boolean;
  error: string | null;
  currentPath: string;
  sort: SortConfig;
  navigateTo: (path: string) => void;
  setSort: (config: SortConfig) => void;
  refresh: () => void;
  listingGeneration: number;
  hydrateDirectories: (paths: string[], signal: AbortSignal, generation: number) => Promise<void>;
  /** True when the server reported more items than are currently loaded. */
  canLoadMore: boolean;
  isLoadingMore: boolean;
  loadMore: () => Promise<void>;
}

export function useProjects(initialPath = ''): UseProjectsReturn {
  const { api } = useAuth();
  const filesApi = useMemo(() => createFilesApi(api), [api]);

  const [currentPath, setCurrentPath] = useState(initialPath);
  const [sort, setSortState] = useState<SortConfig>({ sort: 'name', order: 'asc' });
  // Bumped on every real listing request; directory summaries are correlated
  // against it so a superseded hydration cannot clobber a newer listing.
  const [listingGeneration, setListingGeneration] = useState(0);
  const generationRef = useRef(0);

  // The listing lives in the shared cache keyed by path + sort; identity
  // flips reset it via the provider-level cache clear, and a failed fetch
  // keeps the last good listing visible (same as the pre-cache behavior).
  // The first page requests a bounded limit; loadMore appends further pages
  // into the same cached entry via setData.
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const loadMoreInFlightRef = useRef(false);
  const { data, error, isLoading, refresh, setData } = useCachedQuery<FilesResponse>({
    key: ['projects', currentPath || '', sort.sort, sort.order],
    queryFn: signal => filesApi.list(
      {
        path: currentPath || undefined,
        sort: sort.sort,
        order: sort.order,
        summaries: false,
        limit: PAGE_SIZE,
      },
      signal,
    ),
    onFetchStart: () => {
      generationRef.current += 1;
      setListingGeneration(current => current + 1);
    },
  });

  const canLoadMore = Boolean(
    data
    && typeof data.total === 'number'
    && data.items.length < data.total,
  );

  const loadMore = useCallback(async () => {
    if (loadMoreInFlightRef.current || !data) return;
    if (typeof data.total !== 'number' || data.items.length >= data.total) return;
    loadMoreInFlightRef.current = true;
    setIsLoadingMore(true);
    const requestedPath = currentPath;
    const requestedSort = sort;
    const generation = generationRef.current;
    const offset = data.items.length;
    try {
      const page = await filesApi.list(
        {
          path: requestedPath || undefined,
          sort: requestedSort.sort,
          order: requestedSort.order,
          summaries: false,
          limit: PAGE_SIZE,
          offset,
        },
      );
      // Same guard as hydrateDirectories: a listing request that started in
      // the meantime (navigate / sort change / refresh) supersedes this page.
      if (generation !== generationRef.current) return;
      setData(previous => {
        if (!previous || previous.current_path !== requestedPath) return previous;
        const seen = new Set(previous.items.map(item => item.path));
        const fresh = page.items.filter(item => !seen.has(item.path));
        return {
          ...previous,
          items: [...previous.items, ...fresh],
          total: page.total,
          offset: page.offset,
          limit: page.limit,
        };
      });
    } catch {
      // Fail-open like useCachedQuery: the loaded listing stays visible and
      // the button remains for a retry.
    } finally {
      loadMoreInFlightRef.current = false;
      setIsLoadingMore(false);
    }
  }, [currentPath, data, filesApi, setData, sort]);

  const navigateTo = useCallback((path: string) => {
    setCurrentPath(path);
  }, []);

  const setSort = useCallback((config: SortConfig) => {
    setSortState(config);
  }, []);

  const hydrateDirectories = useCallback(async (
    paths: string[],
    signal: AbortSignal,
    generation: number,
  ) => {
    if (paths.length === 0) return;
    const response = await filesApi.summaries(currentPath, paths, signal);
    if (signal.aborted || generation !== generationRef.current) return;
    setData(previous => {
      if (!previous || previous.current_path !== currentPath) return previous;
      const summaries = new Map(response.items.map(item => [item.path, item]));
      return {
        ...previous,
        items: previous.items.map(item => {
          const summary = item.type === 'dir' ? summaries.get(item.path) : undefined;
          return summary
            ? { ...item, size_fmt: summary.size_fmt, thumbnail_url: summary.thumbnail_url ?? undefined }
            : item;
        }),
      };
    });
  }, [currentPath, filesApi, setData]);

  const errorMessage = error instanceof Error
    ? error.message
    : error ? String(error) : null;

  return {
    data: data ?? null,
    isLoading,
    error: errorMessage,
    currentPath,
    sort,
    navigateTo,
    setSort,
    refresh,
    listingGeneration,
    hydrateDirectories,
    canLoadMore,
    isLoadingMore,
    loadMore,
  };
}
