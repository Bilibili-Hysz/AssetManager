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

  it('refresh forces a new fetch', async () => {
    const queryFn = vi.fn(async () => 'payload');
    const { wrapper } = makeWrapper();
    const { result } = renderHook(
      () => useCachedQuery({ key: ['k'], queryFn }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.data).toBe('payload'));
    act(() => result.current.refresh());
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
});
