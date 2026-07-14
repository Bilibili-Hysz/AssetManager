import { useState, useRef, useCallback, useEffect } from 'react';
import { useAuth } from './useAuth';
import { createMetadataApi } from '../api/metadata';
import type { SearchResult } from '../types/api';

interface UseSearchReturn {
  query: string;
  results: SearchResult[];
  isSearching: boolean;
  setQuery: (q: string) => void;
  clear: () => void;
}

export function useSearch(): UseSearchReturn {
  const { api } = useAuth();
  const metaApi = createMetadataApi(api);
  const [query, setQueryState] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  const setQuery = useCallback((q: string) => {
    setQueryState(q);
    if (timerRef.current) clearTimeout(timerRef.current);

    if (!q.trim()) {
      setResults([]);
      setIsSearching(false);
      return;
    }

    setIsSearching(true);
    timerRef.current = setTimeout(() => {
      metaApi.search(q.trim())
        .then(res => setResults(res.results ?? []))
        .catch(() => setResults([]))
        .finally(() => setIsSearching(false));
    }, 200);
  }, [metaApi]);

  const clear = useCallback(() => {
    setQueryState('');
    setResults([]);
    setIsSearching(false);
  }, []);

  useEffect(() => {
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, []);

  return { query, results, isSearching, setQuery, clear };
}