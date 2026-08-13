// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react';
import { type ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryCacheProvider } from '../cache/QueryCacheContext';
import { useSearch } from './useSearch';

const { search, useInvalidationMock, authState } = vi.hoisted(() => ({
  search: vi.fn(),
  useInvalidationMock: vi.fn(),
  authState: { api: {}, identityGeneration: 0 },
}));

vi.mock('./useAuth', () => ({
  useAuth: () => authState,
}));

vi.mock('../api/quicksearch', () => ({
  createQuickSearchApi: () => ({ search }),
}));

vi.mock('./useInvalidation', () => ({
  useInvalidation: useInvalidationMock,
}));

function makeWrapper() {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryCacheProvider>{children}</QueryCacheProvider>
  );
  return { wrapper };
}

describe('useSearch', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    search.mockReset();
    useInvalidationMock.mockReset();
    authState.identityGeneration = 0;
    search.mockResolvedValue({ results: [] });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('cancels a pending search when cleared', () => {
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useSearch(), { wrapper });

    act(() => result.current.setQuery('report'));
    act(() => result.current.clear());
    act(() => vi.advanceTimersByTime(200));

    expect(search).not.toHaveBeenCalled();
  });

  it('cancels a pending search when unmounted', () => {
    const { wrapper } = makeWrapper();
    const { result, unmount } = renderHook(() => useSearch(), { wrapper });

    act(() => result.current.setQuery('report'));
    unmount();
    act(() => vi.advanceTimersByTime(200));

    expect(search).not.toHaveBeenCalled();
  });

  it('ignores an in-flight result after clearing', async () => {
    let resolveSearch!: (value: { results: Array<{ path: string }> }) => void;
    search.mockReturnValue(new Promise(resolve => { resolveSearch = resolve; }));
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useSearch(), { wrapper });

    act(() => result.current.setQuery('report'));
    act(() => vi.advanceTimersByTime(200));
    act(() => result.current.clear());
    await act(async () => resolveSearch({ results: [{ path: 'stale-report' }] }));

    expect(result.current.results).toEqual([]);
    expect(result.current.isSearching).toBe(false);
  });

  it('refetches the active query after files or metadata invalidation', async () => {
    const first = Promise.resolve({ results: [{ path: 'before.jpg' }] });
    const refreshed = Promise.resolve({ results: [{ path: 'after.jpg' }] });
    search.mockReturnValueOnce(first).mockReturnValueOnce(refreshed);
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useSearch(), { wrapper });

    act(() => result.current.setQuery('report'));
    act(() => vi.advanceTimersByTime(200));
    await act(async () => { await first; });
    expect(result.current.results).toEqual([{ path: 'before.jpg' }]);

    expect(useInvalidationMock).toHaveBeenCalledWith(['files', 'metadata'], expect.any(Function));
    const onInvalidation = useInvalidationMock.mock.calls[0]?.[1] as ((event: unknown) => void) | undefined;
    expect(onInvalidation).toEqual(expect.any(Function));
    await act(async () => { onInvalidation?.({ domains: ['metadata'], paths: [] }); });
    expect(search).toHaveBeenCalledTimes(2);
    await act(async () => { await refreshed; });
    expect(result.current.results).toEqual([{ path: 'after.jpg' }]);
  });

  it('shares the in-flight request when invalidation refetches the same query', async () => {
    let resolveFirst!: (value: { results: Array<{ path: string }> }) => void;
    search.mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }));
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useSearch(), { wrapper });

    act(() => result.current.setQuery('report'));
    act(() => vi.advanceTimersByTime(200));
    expect(useInvalidationMock).toHaveBeenCalledWith(['files', 'metadata'], expect.any(Function));
    const onInvalidation = useInvalidationMock.mock.calls[0]?.[1] as ((event: unknown) => void) | undefined;
    if (!onInvalidation) return;
    await act(async () => { onInvalidation({ domains: ['files'], paths: [] }); });
    // The same query is still in flight: instances share one request instead
    // of firing a second identical quick-search.
    expect(search).toHaveBeenCalledTimes(1);
    await act(async () => { resolveFirst({ results: [{ path: 'report.jpg' }] }); });

    expect(result.current.results).toEqual([{ path: 'report.jpg' }]);
    expect(result.current.isSearching).toBe(false);
  });

  it('clears search state and rejects an older response after identity changes', async () => {
    let resolveSearch!: (value: { results: Array<{ path: string }> }) => void;
    search.mockImplementationOnce(() => new Promise(resolve => { resolveSearch = resolve; }));
    const { wrapper } = makeWrapper();
    const { result, rerender } = renderHook(() => useSearch(), { wrapper });

    act(() => result.current.setQuery('private'));
    act(() => vi.advanceTimersByTime(200));

    act(() => {
      authState.identityGeneration = 1;
      rerender();
    });
    expect(result.current.query).toBe('');
    expect(result.current.results).toEqual([]);
    expect(result.current.isSearching).toBe(false);

    await act(async () => resolveSearch({ results: [{ path: 'stale-private.jpg' }] }));
    expect(result.current.results).toEqual([]);
  });
});
