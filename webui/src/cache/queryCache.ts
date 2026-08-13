/**
 * In-memory query cache core.
 *
 * Keys are JSON-serializable tuples; entries are shared between every
 * subscriber of the same key. Identity isolation is handled by the
 * QueryCacheProvider clearing the whole cache when identityGeneration
 * changes (login/logout/401), so keys deliberately carry no identity
 * scope of their own.
 *
 * Subscriber counts live in a registry keyed by the serialized key — NOT on
 * the entry objects — because `clear()` discards every entry while mounted
 * hooks stay subscribed. A registry lets a post-clear replacement entry be
 * created already knowing its live subscriber count (so setData eligibility
 * and gc behavior survive an identity flip without re-running any effects).
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
  /** Number of live useCachedQuery subscribers (mirrors the registry). */
  subscribers: number;
  /** In-flight request shared by concurrent subscribers (state flows through snapshots). */
  inFlight: { promise: Promise<void>; abort: () => void } | null;
  /** Garbage-collection timer; cancelled when subscribers return. */
  gcTimer: ReturnType<typeof setTimeout> | null;
}

export interface QueryCache {
  getEntry<T>(key: QueryKey): CacheEntry<T>;
  /** Look up an entry WITHOUT creating one (setData must not orphan entries). */
  peekEntry<T>(key: QueryKey): CacheEntry<T> | undefined;
  publish<T>(key: QueryKey, snapshot: QuerySnapshot<T>): void;
  clear(): void;
  subscribe(listener: () => void): () => void;
  addSubscriber(key: QueryKey): void;
  removeSubscriber(key: QueryKey): void;
  subscriberCount(key: QueryKey): number;
}

function serializeKey(key: QueryKey): string {
  return JSON.stringify(key);
}

export function createQueryCache(): QueryCache {
  const entries = new Map<string, CacheEntry<unknown>>();
  const listeners = new Set<() => void>();
  // Live-subscriber registry, keyed like the entry map. Survives clear();
  // pruned when a key's count reaches zero so it never grows unboundedly.
  const subscriptions = new Map<string, number>();

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
          // Re-created after a clear: inherit the preserved live count.
          subscribers: subscriptions.get(rawKey) ?? 0,
          inFlight: null,
          gcTimer: null,
        };
        entries.set(rawKey, entry);
      }
      return entry;
    },
    peekEntry<T>(key: QueryKey): CacheEntry<T> | undefined {
      return entries.get(serializeKey(key)) as CacheEntry<T> | undefined;
    },
    publish,
    clear(): void {
      for (const entry of entries.values()) {
        entry.inFlight?.abort();
        entry.inFlight = null;
        if (entry.gcTimer) clearTimeout(entry.gcTimer);
        entry.gcTimer = null;
        entry.snapshot = {
          status: 'idle', data: undefined, error: undefined, fetchedAt: 0,
        };
      }
      entries.clear();
      // subscriptions deliberately survives: mounted hooks are still live.
      notify();
    },
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    addSubscriber(key: QueryKey): void {
      const rawKey = serializeKey(key);
      const count = (subscriptions.get(rawKey) ?? 0) + 1;
      subscriptions.set(rawKey, count);
      const entry = entries.get(rawKey);
      if (entry) entry.subscribers = count;
    },
    removeSubscriber(key: QueryKey): void {
      const rawKey = serializeKey(key);
      const count = Math.max(0, (subscriptions.get(rawKey) ?? 0) - 1);
      if (count === 0) subscriptions.delete(rawKey);
      else subscriptions.set(rawKey, count);
      const entry = entries.get(rawKey);
      if (entry) entry.subscribers = count;
    },
    subscriberCount(key: QueryKey): number {
      return subscriptions.get(serializeKey(key)) ?? 0;
    },
  };
}
