import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { useAuth } from './useAuth';
import { useInvalidation } from './useInvalidation';
import { createQuickSearchApi } from '../api/quicksearch';
import type { SearchResult } from '../types/api';

interface UseSearchReturn {
  query: string;
  results: SearchResult[];
  isSearching: boolean;
  setQuery: (q: string) => void;
  clear: () => void;
}

export function useSearch(): UseSearchReturn {
  const { api, identityGeneration } = useAuth();
  const quickSearchApi = useMemo(() => createQuickSearchApi(api), [api]);
  const [query, setQueryState] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const generationRef = useRef(0);
  const queryRef = useRef(query);
  const identityGenerationRef = useRef(identityGeneration);

  const searchNow = useCallback((value: string, generation: number) => {
    quickSearchApi.search(value.trim())
      .then(res => {
        if (generation === generationRef.current) setResults(res.results ?? []);
      })
      .catch(() => {
        if (generation === generationRef.current) setResults([]);
      })
      .finally(() => {
        if (generation === generationRef.current) setIsSearching(false);
      });
  }, [quickSearchApi]);

  const setQuery = useCallback((q: string) => {
    setQueryState(q);
    queryRef.current = q;
    if (timerRef.current) clearTimeout(timerRef.current);
    const generation = ++generationRef.current;

    if (!q.trim()) {
      setResults([]);
      setIsSearching(false);
      return;
    }

    setIsSearching(true);
    timerRef.current = setTimeout(() => {
      searchNow(q, generation);
    }, 200);
  }, [searchNow]);

  const clear = useCallback(() => {
    ++generationRef.current;
    if (timerRef.current) clearTimeout(timerRef.current);
    setQueryState('');
    queryRef.current = '';
    setResults([]);
    setIsSearching(false);
  }, []);

  useInvalidation(['files', 'metadata'], () => {
    const activeQuery = queryRef.current.trim();
    if (!activeQuery) return;
    if (timerRef.current) clearTimeout(timerRef.current);
    const generation = ++generationRef.current;
    setIsSearching(true);
    searchNow(activeQuery, generation);
  });

  useEffect(() => {
    if (identityGenerationRef.current === identityGeneration) return;
    identityGenerationRef.current = identityGeneration;
    ++generationRef.current;
    if (timerRef.current) clearTimeout(timerRef.current);
    queryRef.current = '';
    setQueryState('');
    setResults([]);
    setIsSearching(false);
  }, [identityGeneration]);

  useEffect(() => {
    return () => {
      ++generationRef.current;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  return { query, results, isSearching, setQuery, clear };
}
