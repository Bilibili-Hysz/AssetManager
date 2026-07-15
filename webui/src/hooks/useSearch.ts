import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
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
  const metaApi = useMemo(() => createMetadataApi(api), [api]);
  const [query, setQueryState] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const generationRef = useRef(0);

  const setQuery = useCallback((q: string) => {
    const generation = ++generationRef.current;
    setQueryState(q);
    if (timerRef.current) clearTimeout(timerRef.current);
    const generation = ++generationRef.current;

    if (!q.trim()) {
      setResults([]);
      setIsSearching(false);
      return;
    }

    setIsSearching(true);
    timerRef.current = setTimeout(() => {
      metaApi.search(q.trim())
        .then(res => {
          if (generation === generationRef.current) setResults(res.results ?? []);
        })
        .catch(() => {
          if (generation === generationRef.current) setResults([]);
        })
        .finally(() => {
          if (generation === generationRef.current) setIsSearching(false);
        });
    }, 200);
  }, [metaApi]);

  const clear = useCallback(() => {
    ++generationRef.current;
    if (timerRef.current) clearTimeout(timerRef.current);
    setQueryState('');
    setResults([]);
    setIsSearching(false);
  }, []);

  useEffect(() => {
    return () => {
      ++generationRef.current;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  return { query, results, isSearching, setQuery, clear };
}
