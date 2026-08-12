/**
 * In-memory query cache core.
 *
 * Keys are JSON-serializable tuples; entries are shared between every
 * subscriber of the same key. Identity isolation is handled by the
 * QueryCacheProvider clearing the whole cache when identityGeneration
 * changes (login/logout/401), so keys deliberately carry no identity
 * scope of their own.
 *
 * Mutations replace the entry's `snapshot` object and notify listeners;
 * useSyncExternalStore consumers therefore re-render only on real changes.
 */
export type QueryKey = readonly unknown[];

export interface QuerySnapshot<T> {
  status: 'idle' | 'loading' | 'success' | 'error';
  data: T | undefined;
  error: unknown;
  fetchedAt: number;
}

export interface CacheEntry<T> {
  snapshot: QuerySnapshot<T>;
  /** Number of live useCachedQuery subscribers. */
  subscribers: number;
  /** In-flight request shared by concurrent subscribers (state flows through snapshots). */
  inFlight: { promise: Promise<void>; abort: () => void } | null;
  /** Garbage-collection timer; cancelled when subscribers return. */
  gcTimer: ReturnType<typeof setTimeout> | null;
}

export interface QueryCache {
  getEntry<T>(key: QueryKey): CacheEntry<T>;
  publish<T>(key: QueryKey, snapshot: QuerySnapshot<T>): void;
  invalidate(predicate: (key: QueryKey) => boolean): void;
  clear(): void;
  subscribe(listener: () => void): () => void;
}

function serializeKey(key: QueryKey): string {
  return JSON.stringify(key);
}

export function createQueryCache(): QueryCache {
  const entries = new Map<string, CacheEntry<unknown>>();
  const listeners = new Set<() => void>();

  const notify = () => {
    for (const listener of listeners) listener();
  };

  const publish = <T>(key: QueryKey, snapshot: QuerySnapshot<T>) => {
    const entry = entries.get(serializeKey(key));
    if (!entry) return;
    entry.snapshot = snapshot as QuerySnapshot<unknown>;
    notify();
  };

  return {
    getEntry<T>(key: QueryKey): CacheEntry<T> {
      const rawKey = serializeKey(key);
      let entry = entries.get(rawKey) as CacheEntry<T> | undefined;
      if (!entry) {
        entry = {
          snapshot: { status: 'idle', data: undefined, error: undefined, fetchedAt: 0 },
          subscribers: 0,
          inFlight: null,
          gcTimer: null,
        };
        entries.set(rawKey, entry);
      }
      return entry;
    },
    publish,
    invalidate(predicate: (key: QueryKey) => boolean): void {
      let changed = false;
      for (const [rawKey, entry] of entries) {
        if (!predicate(JSON.parse(rawKey) as QueryKey)) continue;
        if (entry.snapshot.data !== undefined || entry.snapshot.error !== undefined) {
          entry.snapshot = {
            status: 'idle', data: undefined, error: undefined, fetchedAt: 0,
          };
          changed = true;
        }
      }
      if (changed) notify();
    },
    clear(): void {
      for (const entry of entries.values()) {
        entry.inFlight?.abort();
        entry.inFlight = null;
        if (entry.gcTimer) clearTimeout(entry.gcTimer);
        entry.gcTimer = null;
        entry.subscribers = 0;
        entry.snapshot = {
          status: 'idle', data: undefined, error: undefined, fetchedAt: 0,
        };
      }
      entries.clear();
      notify();
    },
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
