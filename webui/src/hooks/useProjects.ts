import { useState, useCallback, useEffect, useMemo } from 'react';
import { useAuth } from './useAuth';
import { createFilesApi } from '../api/files';
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
}

export function useProjects(initialPath = ''): UseProjectsReturn {
  const { api } = useAuth();
  const filesApi = useMemo(() => createFilesApi(api), [api]);

  const [currentPath, setCurrentPath] = useState(initialPath);
  const [data, setData] = useState<FilesResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSortState] = useState<SortConfig>({ sort: 'name', order: 'asc' });
  const [refreshVersion, setRefreshVersion] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setIsLoading(true);
    setError(null);
    filesApi.list(
      { path: currentPath || undefined, sort: sort.sort, order: sort.order },
      controller.signal,
    )
      .then(response => {
        if (!controller.signal.aborted) setData(response);
      })
      .catch(err => {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Failed to load files');
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false);
      });
    return () => controller.abort();
  }, [currentPath, filesApi, refreshVersion, sort]);

  const navigateTo = useCallback((path: string) => {
    setCurrentPath(path);
  }, []);

  const setSort = useCallback((config: SortConfig) => {
    setSortState(config);
  }, []);

  const refresh = useCallback(() => {
    setRefreshVersion(version => version + 1);
  }, []);

  return { data, isLoading, error, currentPath, sort, navigateTo, setSort, refresh };
}
