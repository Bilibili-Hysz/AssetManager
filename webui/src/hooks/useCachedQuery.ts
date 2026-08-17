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
 *
 * Query key contract (S5):
 * - Keys are JSON.stringify'd for identity; use a stable serializable tuple
 *   like `['project-detail', path]` or `['search', { q, tags, category }]`.
 * - Object-valued keys must keep property insertion order stable (callers
 *   construct them with a fixed literal shape).
 * - Never put functions, class instances, or DOM nodes in a key.
 * - Identity changes clear the whole cache, so keys do not need an explicit
 *   identityGeneration component.
 */
import { useCallback, useEffect, useRef, useSyncExternalStore } from 'react';
import { shouldInvalidate } from '../cache/invalidation';
import { useQueryCache } from '../cache/QueryCacheContext';
import type { QueryKey } from '../cache/queryCache';
import type { ProjectionDomain } from '../types/contracts';
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
  /** Called each time a new request actually starts (not on dedup hits). */
  onFetchStart?: () => void;
}

export interface UseCachedQueryResult<T> {
  data: T | undefined;
  error: unknown;
  /** No data yet and a fetch is running. */
  isLoading: boolean;
  /** A fetch is running (including background refreshes). */
  isFetching: boolean;
  refresh: () => void;
  /**
   * Patch the cached data without a network round-trip (optimistic updates,
   * hydration of extra fields). No-op while nobody is subscribed, so orphan
   * entries cannot be written after unmount or an identity clear.
   */
  setData: (updater: (prev: T | undefined) => T | undefined) => void;
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
  onFetchStart,
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
  const onFetchStartRef = useRef(onFetchStart);
  onFetchStartRef.current = onFetchStart;

  const startFetch = useCallback(() => {
    if (!enabledRef.current) return;
    const current = cache.getEntry<T>(keyRef.current);
    if (current.inFlight) return; // shared in-flight request
    onFetchStartRef.current?.();
    const controller = new AbortController();
    const previous = current.snapshot;
    current.snapshot = {
      status: previous.data !== undefined ? 'success' : 'loading',
      data: previous.data,
      error: undefined,
      fetchedAt: previous.fetchedAt,
    };
    cache.publish(keyRef.current, current.snapshot);
    // The handlers only touch the entry's in-flight slot when it is still
    // theirs: a refresh() aborts this request and starts a newer one, and
    // settling the aborted promise must not clear the newer request's slot.
    let inFlight: { promise: Promise<void>; abort: () => void };
    const promise: Promise<void> = queryFnRef.current(controller.signal).then(
      value => {
        if (current.inFlight === inFlight) current.inFlight = null;
        if (controller.signal.aborted) return;
        current.snapshot = {
          status: 'success',
          data: value,
          error: undefined,
          fetchedAt: Date.now(),
        };
        cache.publish(keyRef.current, current.snapshot);
      },
      (error: unknown) => {
        if (current.inFlight === inFlight) current.inFlight = null;
        if (controller.signal.aborted) return;
        // Like TanStack Query: an error keeps the last good data visible and
        // records the failure separately, so consumers keep their fail-open /
        // retain-last-value behavior across transient failures.
        current.snapshot = {
          status: 'error',
          data: previous.data,
          error,
          fetchedAt: Date.now(),
        };
        cache.publish(keyRef.current, current.snapshot);
      },
    );
    inFlight = { promise, abort: () => controller.abort() };
    current.inFlight = inFlight;
  }, [cache]);

  const refresh = useCallback(() => {
    const current = cache.getEntry<T>(keyRef.current);
    current.inFlight?.abort();
    current.inFlight = null;
    startFetch();
  }, [cache, startFetch]);

  const setData = useCallback((updater: (prev: T | undefined) => T | undefined) => {
    // peek, not getEntry: creating an entry here would leave an orphan (no
    // subscribers, no gcTimer) in the cache for every stale optimistic write.
    const current = cache.peekEntry<T>(keyRef.current);
    if (!current || current.subscribers === 0) return; // nobody would see it
    const next = updater(current.snapshot.data);
    if (next === current.snapshot.data) return;
    current.snapshot = next === undefined
      ? { status: 'idle', data: undefined, error: undefined, fetchedAt: 0 }
      : { status: 'success', data: next, error: undefined, fetchedAt: Date.now() };
    cache.publish(keyRef.current, current.snapshot);
  }, [cache]);

  // Subscribe + fetch policy + teardown. The key is captured when the effect
  // runs so the cleanup releases the entry this run subscribed to — reading
  // keyRef in the cleanup would touch the NEXT key and leak the old entry.
  // Subscriber counts live in the cache's registry (not on the entries) so a
  // cache clear — which discards entries — cannot orphan live subscriptions.
  useEffect(() => {
    const myKey = keyRef.current;
    cache.addSubscriber(myKey);
    const current = cache.getEntry<T>(myKey);
    if (current.gcTimer) {
      clearTimeout(current.gcTimer);
      current.gcTimer = null;
    }
    const age = Date.now() - current.snapshot.fetchedAt;
    // staleTime = 0 means fetch on every mount; >= also retries entries whose
    // last attempt failed (fetchedAt was stamped on the error).
    if (enabledRef.current && (current.snapshot.data === undefined || age >= staleTime)) {
      startFetch();
    }
    return () => {
      cache.removeSubscriber(myKey);
      if (cache.subscriberCount(myKey) > 0) return;
      const leaving = cache.peekEntry<T>(myKey);
      if (!leaving) return;
      leaving.inFlight?.abort();
      leaving.inFlight = null;
      leaving.gcTimer = setTimeout(() => {
        // Only reclaim when this exact entry still owns the key; a timer armed
        // by a stale entry must not clobber a replacement's snapshot.
        const live = cache.peekEntry<T>(myKey);
        if (live === leaving && cache.subscriberCount(myKey) === 0 && !leaving.inFlight) {
          leaving.snapshot = {
            status: 'idle', data: undefined, error: undefined, fetchedAt: 0,
          };
          cache.publish(myKey, leaving.snapshot);
        }
      }, gcTime);
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

  // WebSocket invalidation: refetch in the background, aborting any in-flight
  // request. An event means the projection changed, so a response started
  // before the event may be stale — aborting + restarting matches the legacy
  // generation-guard flows (stale responses dropped, newest response wins).
  // The previous data stays visible (no flash to the empty state).
  useInvalidation(
    domains,
    useCallback((event) => {
      if (!shouldInvalidate(event, domains, pathFilterRef.current)) return;
      refresh();
    }, [domains, refresh]),
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
    setData,
  };
}
