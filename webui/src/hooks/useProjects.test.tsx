// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useProjects } from './useProjects';

const list = vi.fn<(...args: unknown[]) => Promise<{ items: Array<{ path: string }> }>>(
  () => Promise.resolve({ items: [] }),
);
const api = {};

vi.mock('./useAuth', () => ({
  useAuth: () => ({ api }),
}));

vi.mock('../api/files', () => ({
  createFilesApi: () => ({ list }),
}));

describe('useProjects', () => {
  beforeEach(() => {
    list.mockClear();
  });

  it('refreshes the listing when the requested path changes', async () => {
    const { result } = renderHook(() => useProjects('one'));
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

  it('does not refetch when rerendered with the same path', async () => {
    const { rerender } = renderHook(({ path }) => useProjects(path), {
      initialProps: { path: 'projects/one' },
    });
    await waitFor(() => expect(list).toHaveBeenCalledTimes(1));

    rerender({ path: 'projects/one' });

    expect(list).toHaveBeenCalledTimes(1);
  });

  it('refreshes the listing when sort changes', async () => {
    const { result } = renderHook(() => useProjects('projects'));
    await waitFor(() => expect(list).toHaveBeenCalledTimes(1));

    act(() => result.current.setSort({ sort: 'size', order: 'desc' }));

    await waitFor(() => expect(list).toHaveBeenLastCalledWith(
      expect.objectContaining({ path: 'projects', sort: 'size', order: 'desc' }),
      expect.any(AbortSignal),
    ));
  });

  it('ignores a response from a superseded listing request', async () => {
    let resolveFirst!: (value: { items: Array<{ path: string }> }) => void;
    let resolveSecond!: (value: { items: Array<{ path: string }> }) => void;
    list
      .mockImplementationOnce(() => new Promise<{ items: Array<{ path: string }> }>(resolve => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise<{ items: Array<{ path: string }> }>(resolve => { resolveSecond = resolve; }));

    const { result } = renderHook(() => useProjects('one'));
    await waitFor(() => expect(list).toHaveBeenCalledTimes(1));
    act(() => result.current.navigateTo('two'));
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));

    await act(async () => { resolveSecond({ items: [{ path: 'two' }] }); });
    expect(result.current.data?.items[0]?.path).toBe('two');
    await act(async () => { resolveFirst({ items: [{ path: 'one' }] }); });
    expect(result.current.data?.items[0]?.path).toBe('two');
  });
});
