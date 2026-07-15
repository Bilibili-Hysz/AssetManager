// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useProjects } from './useProjects';

const list = vi.fn(() => Promise.resolve({ items: [] }));
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
});
