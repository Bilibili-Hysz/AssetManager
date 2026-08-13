import { useCallback, useMemo, useRef, useState } from 'react';
import { useAuth } from './useAuth';
import { createFilesApi } from '../api/files';
import { useCachedQuery } from './useCachedQuery';
import type { FilesResponse } from '../types/api';

export interface SortConfig {
  sort: string;
  order: 'asc' | 'desc';
}

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
  const { data, error, isLoading, refresh, setData } = useCachedQuery<FilesResponse>({
    key: ['projects', currentPath || '', sort.sort, sort.order],
    queryFn: signal => filesApi.list(
      { path: currentPath || undefined, sort: sort.sort, order: sort.order, summaries: false },
      signal,
    ),
    onFetchStart: () => {
      generationRef.current += 1;
      setListingGeneration(current => current + 1);
    },
  });

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
  };
}
