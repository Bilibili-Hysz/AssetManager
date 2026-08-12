/**
 * useCachedQuery — the shared data-fetching primitive.
 *
 * Replaces the per-page boilerplate (state + AbortController + generation
 * guards + invalidation wiring) with one declarative hook:
 *
 * - concurrent subscribers of the same key share one in-flight request;
 * - invalidation flows from projection domains (WebSocket) and from the
 *   identityGeneration cache clear (login/logout/401);
 * - staleTime = 0 keeps the historical fetch-on-mount behavior.
 */
import { useCallback, useEffect, useRef, useSyncExternalStore } from 'react';
import { shouldInvalidate } from '../cache/invalidation';
import { useQueryCache } from '../cache/QueryCacheContext';
import type { QueryKey } from '../cache/queryCache';
import type { ProjectionDomain } from '../stores/RealtimeContext';
import { useInvalidation } from './useInvalidation';

export interface UseCachedQueryOptions<T> {
  key: QueryKey;
  queryFn: (signal: AbortSignal) => Promise<T>;
  /** Projection domains that invalidate this query. */
  domains?: readonly ProjectionDomain[];
  /** Extra path filter for invalidation events that carry paths. */
  pathFilter?: (paths: string[]) => boolean;
  /** Refetch when the last fetch is older than this; default 0 (fetch on mount). */
  staleTime?: number;
  /** Reset the entry this long after the last subscriber leaves; default 300s. */
  gcTime?: number;
  /** Poll interval in ms while mounted; undefined = no polling. */
  refreshInterval?: number;
  /** Disable fetching (data stays cached when previously fetched). */
  enabled?: boolean;
}

export interface UseCachedQueryResult<T> {
  data: T | undefined;
  error: unknown;
  /** No data yet and a fetch is running. */
  isLoading: boolean;
  /** A fetch is running (including background refreshes). */
  isFetching: boolean;
  refresh: () => void;
}

export function useCachedQuery<T>({
  key,
  queryFn,
  domains = [],
  pathFilter,
  staleTime = 0,
  gcTime = 300_000,
  refreshInterval,
  enabled = true,
}: UseCachedQueryOptions<T>): UseCachedQueryResult<T> {
  const cache = useQueryCache();
  const entry = cache.getEntry<T>(key);

  const snapshot = useSyncExternalStore(
    cache.subscribe,
    () => entry.snapshot,
  );

  const keyRef = useRef(key);
  keyRef.current = key;
  // Array keys get a fresh identity every render; depend on the serialized
  // form instead, otherwise the subscribe effect re-runs each render and
  // aborts the shared in-flight request in a loop.
  const keyString = JSON.stringify(key);
  const queryFnRef = useRef(queryFn);
  queryFnRef.current = queryFn;
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;
  const pathFilterRef = useRef(pathFilter);
  pathFilterRef.current = pathFilter;

  const startFetch = useCallback(() => {
    if (!enabledRef.current) return;
    const current = cache.getEntry<T>(keyRef.current);
    if (current.inFlight) return; // shared in-flight request
    const controller = new AbortController();
    const previous = current.snapshot;
    current.snapshot = {
      status: previous.data !== undefined ? 'success' : 'loading',
      data: previous.data,
      error: undefined,
      fetchedAt: previous.fetchedAt,
    };
    cache.publish(keyRef.current, current.snapshot);
    const promise: Promise<void> = queryFnRef.current(controller.signal).then(
      value => {
        current.inFlight = null;
        current.snapshot = {
          status: 'success',
          data: value,
          error: undefined,
          fetchedAt: Date.now(),
        };
        cache.publish(keyRef.current, current.snapshot);
      },
      (error: unknown) => {
        current.inFlight = null;
        if (controller.signal.aborted) return;
        current.snapshot = {
          status: 'error',
          data: undefined,
          error,
          fetchedAt: Date.now(),
        };
        cache.publish(keyRef.current, current.snapshot);
      },
    );
    current.inFlight = { promise, abort: () => controller.abort() };
  }, [cache]);

  const refresh = useCallback(() => {
    const current = cache.getEntry<T>(keyRef.current);
    current.inFlight?.abort();
    current.inFlight = null;
    startFetch();
  }, [cache, startFetch]);

  // Subscribe + fetch policy + teardown.
  useEffect(() => {
    const current = cache.getEntry<T>(keyRef.current);
    current.subscribers += 1;
    if (current.gcTimer) {
      clearTimeout(current.gcTimer);
      current.gcTimer = null;
    }
    const age = Date.now() - current.snapshot.fetchedAt;
    if (enabledRef.current && (current.snapshot.data === undefined || age > staleTime)) {
      startFetch();
    }
    return () => {
      const leaving = cache.getEntry<T>(keyRef.current);
      leaving.subscribers = Math.max(0, leaving.subscribers - 1);
      if (leaving.subscribers === 0) {
        leaving.inFlight?.abort();
        leaving.inFlight = null;
        leaving.gcTimer = setTimeout(() => {
          if (leaving.subscribers === 0 && !leaving.inFlight) {
            leaving.snapshot = {
              status: 'idle', data: undefined, error: undefined, fetchedAt: 0,
            };
            cache.publish(keyRef.current, leaving.snapshot);
          }
        }, gcTime);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keyString, staleTime, gcTime, enabled, startFetch]);

  // Self-healing: when the entry is reset (identity clear, gc) while
  // subscribed, refetch. Invalidation events call startFetch directly, so
  // the in-flight dedup keeps this cheap.
  useEffect(() => {
    if (enabledRef.current && snapshot.data === undefined && snapshot.status === 'idle') {
      startFetch();
    }
  }, [snapshot, enabled, startFetch]);

  // WebSocket invalidation.
  useInvalidation(
    domains,
    useCallback((event) => {
      if (!shouldInvalidate(event, domains, pathFilterRef.current)) return;
      const current = cache.getEntry<T>(keyRef.current);
      current.snapshot = {
        status: 'idle', data: undefined, error: undefined, fetchedAt: 0,
      };
      cache.publish(keyRef.current, current.snapshot);
      startFetch();
    }, [cache, domains, startFetch]),
  );

  // Optional polling.
  useEffect(() => {
    if (!refreshInterval) return;
    const timer = setInterval(refresh, refreshInterval);
    return () => clearInterval(timer);
  }, [refreshInterval, refresh]);

  const isFetching = entry.inFlight !== null;
  return {
    data: snapshot.data,
    error: snapshot.error,
    isLoading: snapshot.data === undefined && isFetching,
    isFetching,
    refresh,
  };
}
