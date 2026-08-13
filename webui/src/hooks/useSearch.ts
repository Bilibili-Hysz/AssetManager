import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useAuth } from './useAuth';
import { useCachedQuery } from './useCachedQuery';
import { createQuickSearchApi } from '../api/quicksearch';
import type { SearchResult } from '../types/api';

interface UseSearchReturn {
  query: string;
  results: SearchResult[];
  isSearching: boolean;
  setQuery: (q: string) => void;
  clear: () => void;
}

/**
 * Debounced quick-search backed by the shared query cache. The header and
 * the command palette each mount their own instance; instances with the same
 * debounced query share one cache entry, so typing once still fires a single
 * quick-search request, and the dedup also covers invalidation refetches.
 */
export function useSearch(): UseSearchReturn {
  const { api, identityGeneration } = useAuth();
  const quickSearchApi = useMemo(() => createQuickSearchApi(api), [api]);
  const [query, setQueryState] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [pendingDebounce, setPendingDebounce] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const identityGenerationRef = useRef(identityGeneration);

  const activeQuery = debouncedQuery.trim();

  const { data, error, isFetching } = useCachedQuery<SearchResult[]>({
    key: ['quicksearch', activeQuery],
    queryFn: async signal => {
      const response = await quickSearchApi.search(activeQuery, 20, signal);
      return response.results ?? [];
    },
    enabled: activeQuery !== '',
    domains: ['files', 'metadata'],
  });

  const setQuery = useCallback((q: string) => {
    setQueryState(q);
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!q.trim()) {
      setPendingDebounce(false);
      setDebouncedQuery('');
      return;
    }
    setPendingDebounce(true);
    timerRef.current = setTimeout(() => {
      setPendingDebounce(false);
      setDebouncedQuery(q);
    }, 200);
  }, []);

  const clear = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setPendingDebounce(false);
    setQueryState('');
    setDebouncedQuery('');
  }, []);

  useEffect(() => {
    if (identityGenerationRef.current === identityGeneration) return;
    identityGenerationRef.current = identityGeneration;
    if (timerRef.current) clearTimeout(timerRef.current);
    setPendingDebounce(false);
    setQueryState('');
    setDebouncedQuery('');
  }, [identityGeneration]);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  // A failed search shows no results (the stale list from the previous query
  // is never surfaced), matching the pre-cache behavior.
  const results = error ? [] : (data ?? []);
  const isSearching = query.trim() !== '' && (pendingDebounce || isFetching);

  return { query, results, isSearching, setQuery, clear };
}
