/**
 * Query cache provider: owns one cache per app lifetime and clears it
 * whenever the authenticated identity changes (login, logout, 401 expiry),
 * which is the single isolation point for cached data.
 */
import {
  createContext, useContext, useEffect, useMemo, useRef, type ReactNode,
} from 'react';
import { useAuth } from '../hooks/useAuth';
import { createQueryCache, type QueryCache } from './queryCache';

const QueryCacheContext = createContext<QueryCache | null>(null);

export function QueryCacheProvider({
  children,
  cache: injected,
}: {
  children: ReactNode;
  /** Optional injected cache (tests share one instance across render trees). */
  cache?: QueryCache;
}) {
  const owned = useMemo(() => createQueryCache(), []);
  const cache = injected ?? owned;
  const { identityGeneration } = useAuth();
  const previousGeneration = useRef(identityGeneration);

  useEffect(() => {
    if (previousGeneration.current !== identityGeneration) {
      previousGeneration.current = identityGeneration;
      cache.clear();
    }
  }, [identityGeneration, cache]);

  return <QueryCacheContext.Provider value={cache}>{children}</QueryCacheContext.Provider>;
}

export function useQueryCache(): QueryCache {
  const cache = useContext(QueryCacheContext);
  if (!cache) throw new Error('useQueryCache must be used within QueryCacheProvider');
  return cache;
}
