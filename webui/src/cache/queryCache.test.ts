import { describe, expect, it, vi } from 'vitest';
import { createQueryCache } from './queryCache';

describe('queryCache core', () => {
  it('stores and publishes snapshots per key', () => {
    const cache = createQueryCache();
    const entry = cache.getEntry<number>(['a', 1]);
    expect(entry.snapshot.status).toBe('idle');
    cache.publish(['a', 1], { status: 'success', data: 42, error: undefined, fetchedAt: 1 });
    expect(cache.getEntry(['a', 1]).snapshot.data).toBe(42);
    expect(cache.getEntry(['a', 2]).snapshot.data).toBeUndefined();
  });

  it('invalidate resets matching keys and notifies listeners', () => {
    const cache = createQueryCache();
    const listener = vi.fn();
    cache.subscribe(listener);
    cache.getEntry(['files:list', 'p']);
    cache.getEntry(['tags:list']);
    cache.publish(['files:list', 'p'], { status: 'success', data: 'x', error: undefined, fetchedAt: 1 });
    cache.publish(['tags:list'], { status: 'success', data: 'y', error: undefined, fetchedAt: 1 });
    cache.invalidate(key => key[0] === 'files:list');
    expect(cache.getEntry(['files:list', 'p']).snapshot.data).toBeUndefined();
    expect(cache.getEntry(['tags:list']).snapshot.data).toBe('y');
    expect(listener).toHaveBeenCalled();
  });

  it('clear resets every entry and aborts in-flight requests', () => {
    const cache = createQueryCache();
    const abort = vi.fn();
    const entry = cache.getEntry<number>(['k']);
    entry.inFlight = { promise: Promise.resolve(), abort };
    cache.publish(['k'], { status: 'success', data: 1, error: undefined, fetchedAt: 1 });
    cache.clear();
    expect(abort).toHaveBeenCalled();
    expect(cache.getEntry(['k']).snapshot.data).toBeUndefined();
  });

  it('peekEntry never creates entries', () => {
    const cache = createQueryCache();
    expect(cache.peekEntry(['missing'])).toBeUndefined();
    expect(cache.peekEntry(['missing'])).toBeUndefined();
    cache.getEntry(['missing']);
    expect(cache.peekEntry(['missing'])).toBeDefined();
  });

  it('clear preserves live subscriber counts for re-created entries', () => {
    const cache = createQueryCache();
    cache.addSubscriber(['live']);
    cache.clear();
    // The entry map is wiped but the hook is still subscribed: the
    // replacement entry inherits the preserved count.
    expect(cache.getEntry(['live']).subscribers).toBe(1);
    cache.removeSubscriber(['live']);
    expect(cache.subscriberCount(['live'])).toBe(0);
    expect(cache.getEntry(['live']).subscribers).toBe(0);
  });

  it('removeSubscriber prunes the registry at zero so it cannot grow unboundedly', () => {
    const cache = createQueryCache();
    cache.addSubscriber(['k']);
    cache.removeSubscriber(['k']);
    expect(cache.subscriberCount(['k'])).toBe(0);
    // A fresh entry no longer knows about the released key.
    expect(cache.getEntry(['k']).subscribers).toBe(0);
  });
});
