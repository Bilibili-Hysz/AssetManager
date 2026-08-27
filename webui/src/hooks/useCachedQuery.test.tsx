// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react';
import { type ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { QueryCacheProvider } from '../cache/QueryCacheContext';
import { createQueryCache } from '../cache/queryCache';
import { useCachedQuery } from './useCachedQuery';

vi.mock('../api/client', () => ({
  createApiClient: () => ({}),
}));
vi.mock('../api/auth', () => ({
  createAuthApi: () => ({ logout: vi.fn().mockResolvedValue({}) }),
}));
vi.mock('../api/system', () => ({
  createSystemApi: () => ({}),
}));
vi.mock('./useAuth', () => ({
  useAuth: () => ({ identityGeneration: 0 }),
}));
vi.mock('./useInvalidation', () => ({
  useInvalidation: () => ({}),
}));

/** Each test gets one shared cache instance across its render trees. */
function makeWrapper() {
  const cache = createQueryCache();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryCacheProvider cache={cache}>{children}</QueryCacheProvider>
  );
  return { cache, wrapper };
}

describe('useCachedQuery', () => {
  it('fetches on mount and publishes data', async () => {
    const queryFn = vi.fn(async () => 'payload');
    const { wrapper } = makeWrapper();
    const { result } = renderHook(
      () => useCachedQuery({ key: ['k'], queryFn }),
      { wrapper },
    );
    expect(result.current.isLoading).toBe(true);
    await waitFor(() => expect(result.current.data).toBe('payload'));
    expect(result.current.isLoading).toBe(false);
    expect(queryFn).toHaveBeenCalledTimes(1);
  });

  it('deduplicates concurrent subscribers of the same key', async () => {
    let resolveFn!: (value: string) => void;
    const queryFn = vi.fn(() => new Promise<string>(resolve => { resolveFn = resolve; }));
    const { wrapper } = makeWrapper();
    const first = renderHook(
      () => useCachedQuery({ key: ['k'], queryFn }),
      { wrapper },
    );
    const second = renderHook(
      () => useCachedQuery({ key: ['k'], queryFn }),
      { wrapper },
    );
    // Both mount while the first fetch is still in flight: one request.
    expect(queryFn).toHaveBeenCalledTimes(1);
    act(() => resolveFn('shared'));
    await waitFor(() => expect(first.result.current.data).toBe('shared'));
    await waitFor(() => expect(second.result.current.data).toBe('shared'));
    expect(queryFn).toHaveBeenCalledTimes(1);
  });

  it('refresh forces a new fetch and keeps the previous data visible', async () => {
    const queryFn = vi.fn(async () => 'payload');
    const { wrapper } = makeWrapper();
    const { result } = renderHook(
      () => useCachedQuery({ key: ['k'], queryFn }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.data).toBe('payload'));
    act(() => result.current.refresh());
    // Background refresh: the last good data stays on screen.
    expect(result.current.data).toBe('payload');
    await waitFor(() => expect(queryFn).toHaveBeenCalledTimes(2));
  });

  it('a cache clear resets the entry and triggers a refetch', async () => {
    const queryFn = vi.fn(async () => 'payload');
    const { cache, wrapper } = makeWrapper();
    const { result } = renderHook(
      () => useCachedQuery({ key: ['k'], queryFn }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.data).toBe('payload'));

    act(() => cache.clear());
    await waitFor(() => expect(result.current.data).toBe('payload'));
    expect(queryFn.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it('keeps the last good data when a fetch fails and reports the error', async () => {
    const queryFn = vi
      .fn<() => Promise<string>>()
      .mockResolvedValueOnce('payload')
      .mockRejectedValueOnce(new Error('boom'));
    const { wrapper } = makeWrapper();
    const { result } = renderHook(
      () => useCachedQuery({ key: ['k'], queryFn }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.data).toBe('payload'));

    act(() => result.current.refresh());
    await waitFor(() => expect(result.current.error).toEqual(new Error('boom')));
    expect(result.current.data).toBe('payload');
    expect(result.current.isLoading).toBe(false);
  });

  it('clears data when the very first fetch fails', async () => {
    const queryFn = vi.fn(async () => { throw new Error('first failure'); });
    const { wrapper } = makeWrapper();
    const { result } = renderHook(
      () => useCachedQuery({ key: ['k'], queryFn }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.error).toEqual(new Error('first failure')));
    expect(result.current.data).toBeUndefined();
  });

  it('setData patches the cached snapshot for subscribers', async () => {
    const queryFn = vi.fn(async () => ({ count: 1 }));
    const { wrapper } = makeWrapper();
    const { result } = renderHook(
      () => useCachedQuery<{ count: number }>({ key: ['k'], queryFn }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.data).toEqual({ count: 1 }));

    act(() => result.current.setData(prev => prev && { count: prev.count + 1 }));
    expect(result.current.data).toEqual({ count: 2 });
    // No refetch was triggered by the local patch.
    expect(queryFn).toHaveBeenCalledTimes(1);
  });

  it('setData is a no-op without live subscribers', async () => {
    const queryFn = vi.fn(async () => 'payload');
    const { cache, wrapper } = makeWrapper();
    const { result, unmount } = renderHook(
      () => useCachedQuery({ key: ['k'], queryFn }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.data).toBe('payload'));
    const before = cache.getEntry(['k']).snapshot;
    unmount();
    act(() => result.current.setData(() => 'stale'));
    expect(cache.getEntry(['k']).snapshot).toBe(before);
  });

  it('a stale setData after unmount and clear leaves no orphan entry', async () => {
    const queryFn = vi.fn(async () => 'payload');
    const { cache, wrapper } = makeWrapper();
    const { result, unmount } = renderHook(
      () => useCachedQuery({ key: ['k'], queryFn }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.data).toBe('payload'));
    unmount();
    act(() => cache.clear());
    act(() => result.current.setData(() => 'stale'));
    // setData must not create an entry for a key that no longer exists.
    expect(cache.peekEntry(['k'])).toBeUndefined();
  });

  it('setData still applies after a cache clear (subscription re-established)', async () => {
    const queryFn = vi.fn(async () => 'payload');
    const { cache, wrapper } = makeWrapper();
    const { result } = renderHook(
      () => useCachedQuery({ key: ['k'], queryFn }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.data).toBe('payload'));

    act(() => cache.clear());
    await waitFor(() => expect(result.current.data).toBe('payload'));

    act(() => result.current.setData(() => 'patched'));
    expect(result.current.data).toBe('patched');
  });

  it('fires onFetchStart per real request, not per dedup hit', async () => {
    let resolveFn!: (value: string) => void;
    const queryFn = vi.fn(() => new Promise<string>(resolve => { resolveFn = resolve; }));
    const onFetchStart = vi.fn();
    const { wrapper } = makeWrapper();
    const first = renderHook(
      () => useCachedQuery({ key: ['k'], queryFn, onFetchStart }),
      { wrapper },
    );
    const second = renderHook(
      () => useCachedQuery({ key: ['k'], queryFn, onFetchStart }),
      { wrapper },
    );
    expect(onFetchStart).toHaveBeenCalledTimes(1);
    await act(async () => { resolveFn('shared'); });
    await waitFor(() => expect(first.result.current.data).toBe('shared'));
    await waitFor(() => expect(second.result.current.data).toBe('shared'));
    expect(onFetchStart).toHaveBeenCalledTimes(1);
  });

  it('does not publish an old response into a new key after rerender', async () => {
    let resolveOld!: (value: string) => void;
    let resolveNew!: (value: string) => void;
    const queryFn = vi.fn(() => {
      if (queryFn.mock.calls.length === 1) {
        return new Promise<string>(resolve => { resolveOld = resolve; });
      }
      return new Promise<string>(resolve => { resolveNew = resolve; });
    });
    const { wrapper } = makeWrapper();
    const { result, rerender } = renderHook(
      ({ key }: { key: string }) => useCachedQuery({ key: ['search', key], queryFn }),
      { initialProps: { key: 'old' }, wrapper },
    );
    await waitFor(() => expect(queryFn).toHaveBeenCalledTimes(1));
    rerender({ key: 'new' });
    await waitFor(() => expect(queryFn).toHaveBeenCalledTimes(2));

    await act(async () => { resolveOld('stale'); });
    expect(result.current.data).not.toBe('stale');
    await act(async () => { resolveNew('fresh'); });
    await waitFor(() => expect(result.current.data).toBe('fresh'));
  });

  it('an aborted refresh settling does not clear the newer in-flight request', async () => {
    let resolveFirst!: (value: string) => void;
    let resolveSecond!: (value: string) => void;
    const queryFn = vi
      .fn<() => Promise<string>>()
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve; }));
    const { wrapper } = makeWrapper();
    const { result } = renderHook(
      () => useCachedQuery({ key: ['k'], queryFn }),
      { wrapper },
    );
    await waitFor(() => expect(queryFn).toHaveBeenCalledTimes(1));
    act(() => result.current.refresh());
    await waitFor(() => expect(queryFn).toHaveBeenCalledTimes(2));

    // The aborted first request settles: the second, still pending request
    // must remain the tracked in-flight one.
    await act(async () => { resolveFirst('stale'); });
    expect(result.current.isFetching).toBe(true);
    await act(async () => { resolveSecond('fresh'); });
    await waitFor(() => expect(result.current.data).toBe('fresh'));
  });
});
