import { useState, useCallback } from 'react';
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
  const filesApi = createFilesApi(api);

  const [currentPath, setCurrentPath] = useState(initialPath);
  const [data, setData] = useState<FilesResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSortState] = useState<SortConfig>({ sort: 'name', order: 'asc' });

  const fetchFiles = useCallback((path: string, sortConfig: SortConfig) => {
    setIsLoading(true);
    setError(null);
    filesApi.list({ path: path || undefined, sort: sortConfig.sort, order: sortConfig.order })
      .then(setData)
      .catch(err => setError(err instanceof Error ? err.message : 'Failed to load files'))
      .finally(() => setIsLoading(false));
  }, [filesApi]);

  const navigateTo = useCallback((path: string) => {
    setCurrentPath(path);
    fetchFiles(path, sort);
  }, [fetchFiles, sort]);

  const setSort = useCallback((config: SortConfig) => {
    setSortState(config);
    fetchFiles(currentPath, config);
  }, [fetchFiles, currentPath]);

  const refresh = useCallback(() => {
    fetchFiles(currentPath, sort);
  }, [fetchFiles, currentPath, sort]);

  // Initial load
  useState(() => {
    fetchFiles(currentPath, sort);
  });

  return { data, isLoading, error, currentPath, sort, navigateTo, setSort, refresh };
}