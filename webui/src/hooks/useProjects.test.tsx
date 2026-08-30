// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react';
import { type ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryCacheProvider } from '../cache/QueryCacheContext';
import { useProjects } from './useProjects';

type ListItem = { path: string; type?: 'dir' | 'file'; size_fmt?: string };

type ListResponse = {
  current_path?: string;
  items: ListItem[];
  total_count?: number;
  total?: number;
  limit?: number;
  offset?: number;
};

const list = vi.fn<(...args: unknown[]) => Promise<ListResponse>>(
  () => Promise.resolve({ items: [] }),
);
const summaries = vi.fn();
const api = {};

vi.mock('./useAuth', () => ({
  useAuth: () => ({ api, identityGeneration: 0 }),
}));

vi.mock('../api/files', () => ({
  createFilesApi: () => ({ list, summaries }),
}));

vi.mock('./useInvalidation', () => ({
  useInvalidation: () => ({}),
}));

function makeWrapper() {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryCacheProvider>{children}</QueryCacheProvider>
  );
  return { wrapper };
}

describe('useProjects', () => {
  beforeEach(() => {
    list.mockClear();
    summaries.mockClear();
  });

  it('refreshes the listing when the requested path changes', async () => {
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useProjects('one'), { wrapper });
    await waitFor(() => expect(list).toHaveBeenCalledWith(
      expect.objectContaining({ path: 'one' }),
      expect.any(AbortSignal),
    ));

    act(() => result.current.navigateTo('two'));

    await waitFor(() => expect(list).toHaveBeenLastCalledWith(
      expect.objectContaining({ path: 'two' }),
      expect.any(AbortSignal),
    ));
  });

  it('explicitly requests an initial listing without eager summaries', async () => {
    const { wrapper } = makeWrapper();
    renderHook(() => useProjects('one'), { wrapper });

    await waitFor(() => expect(list).toHaveBeenCalledWith(
      expect.objectContaining({ path: 'one', summaries: false }),
      expect.any(AbortSignal),
    ));
  });

  it('does not refetch when rerendered with the same path', async () => {
    const { wrapper } = makeWrapper();
    const { rerender } = renderHook(({ path }) => useProjects(path), {
      initialProps: { path: 'projects/one' },
      wrapper,
    });
    await waitFor(() => expect(list).toHaveBeenCalledTimes(1));

    rerender({ path: 'projects/one' });

    expect(list).toHaveBeenCalledTimes(1);
  });

  it('refreshes the listing when sort changes', async () => {
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useProjects('projects'), { wrapper });
    await waitFor(() => expect(list).toHaveBeenCalledTimes(1));

    act(() => result.current.setSort({ sort: 'size', order: 'desc' }));

    await waitFor(() => expect(list).toHaveBeenLastCalledWith(
      expect.objectContaining({ path: 'projects', sort: 'size', order: 'desc' }),
      expect.any(AbortSignal),
    ));
  });

  it('ignores a response from a superseded listing request', async () => {
    let resolveFirst!: (value: { current_path?: string; items: ListItem[] }) => void;
    let resolveSecond!: (value: { current_path?: string; items: ListItem[] }) => void;
    list
      .mockImplementationOnce(() => new Promise<{ current_path?: string; items: ListItem[] }>(resolve => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise<{ current_path?: string; items: ListItem[] }>(resolve => { resolveSecond = resolve; }));

    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useProjects('one'), { wrapper });
    await waitFor(() => expect(list).toHaveBeenCalledTimes(1));
    act(() => result.current.navigateTo('two'));
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));

    await act(async () => { resolveSecond({ items: [{ path: 'two' }] }); });
    expect(result.current.data?.items[0]?.path).toBe('two');
    await act(async () => { resolveFirst({ items: [{ path: 'one' }] }); });
    expect(result.current.data?.items[0]?.path).toBe('two');
  });

  it('requests the first page with the bounded limit', async () => {
    const { wrapper } = makeWrapper();
    renderHook(() => useProjects('one'), { wrapper });

    await waitFor(() => expect(list).toHaveBeenCalledWith(
      expect.objectContaining({ path: 'one', summaries: false, limit: 500 }),
      expect.any(AbortSignal),
    ));
  });

  it('appends load-more pages into the cached listing', async () => {
    list
      .mockResolvedValueOnce({
        current_path: 'one', items: [{ path: 'a' }, { path: 'b' }],
        total_count: 4, total: 4, limit: 500, offset: 0,
      })
      .mockResolvedValueOnce({
        current_path: 'one', items: [{ path: 'c' }, { path: 'd' }],
        total_count: 4, total: 4, limit: 500, offset: 2,
      });
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useProjects('one'), { wrapper });
    await waitFor(() => expect(result.current.canLoadMore).toBe(true));

    await act(() => result.current.loadMore());

    expect(list).toHaveBeenLastCalledWith(
      expect.objectContaining({ path: 'one', limit: 500, offset: 2 }),
    );
    expect(result.current.data?.items.map(item => item.path)).toEqual(['a', 'b', 'c', 'd']);
    expect(result.current.canLoadMore).toBe(false);
  });

  it('does not fetch more pages when the response carries no total', async () => {
    list.mockResolvedValueOnce({ current_path: 'one', items: [{ path: 'a' }] });
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useProjects('one'), { wrapper });
    await waitFor(() => expect(result.current.data?.items).toHaveLength(1));

    await act(() => result.current.loadMore());

    expect(list).toHaveBeenCalledTimes(1);
    expect(result.current.canLoadMore).toBe(false);
  });

  it('keeps the loaded listing when a load-more request fails', async () => {
    list
      .mockResolvedValueOnce({
        current_path: 'one', items: [{ path: 'a' }],
        total_count: 2, total: 2, limit: 500, offset: 0,
      })
      .mockRejectedValueOnce(new Error('HTTP 500'));
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useProjects('one'), { wrapper });
    await waitFor(() => expect(result.current.canLoadMore).toBe(true));

    await act(() => result.current.loadMore());

    expect(result.current.data?.items.map(item => item.path)).toEqual(['a']);
    expect(result.current.error).toBeNull();
    expect(result.current.canLoadMore).toBe(true);
  });

  it('ignores an old hydration response after a same-path refresh', async () => {
    let resolveSummary!: (value: { items: Array<{ path: string; size_fmt: string; thumbnail_url: null }> }) => void;
    list
      .mockResolvedValueOnce({ current_path: 'one', items: [{ path: 'folder', type: 'dir', size_fmt: '0 B' }] })
      .mockResolvedValueOnce({ current_path: 'one', items: [{ path: 'folder', type: 'dir', size_fmt: 'fresh' }] });
    summaries.mockImplementationOnce(() => new Promise(resolve => { resolveSummary = resolve; }));

    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useProjects('one'), { wrapper });
    await waitFor(() => expect(result.current.data?.items[0]?.path).toBe('folder'));
    const signal = new AbortController().signal;
    const hydration = result.current.hydrateDirectories(['folder'], signal, result.current.listingGeneration);
    act(() => result.current.refresh());
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
    await act(async () => { resolveSummary({ items: [{ path: 'folder', size_fmt: 'stale', thumbnail_url: null }] }); await hydration; });

    expect(result.current.data?.items[0]?.size_fmt).toBe('fresh');
  });
});
