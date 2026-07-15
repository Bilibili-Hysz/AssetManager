// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useSearch } from './useSearch';

const search = vi.fn();

vi.mock('./useAuth', () => ({
  useAuth: () => ({ api: {} }),
}));

vi.mock('../api/metadata', () => ({
  createMetadataApi: () => ({ search }),
}));

describe('useSearch', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    search.mockReset();
    search.mockResolvedValue({ results: [] });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('cancels a pending search when cleared', () => {
    const { result } = renderHook(() => useSearch());

    act(() => result.current.setQuery('report'));
    act(() => result.current.clear());
    act(() => vi.advanceTimersByTime(200));

    expect(search).not.toHaveBeenCalled();
  });

  it('cancels a pending search when unmounted', () => {
    const { result, unmount } = renderHook(() => useSearch());

    act(() => result.current.setQuery('report'));
    unmount();
    act(() => vi.advanceTimersByTime(200));

    expect(search).not.toHaveBeenCalled();
  });

  it('ignores an in-flight result after clearing', async () => {
    let resolveSearch!: (value: { results: Array<{ path: string }> }) => void;
    search.mockReturnValue(new Promise(resolve => { resolveSearch = resolve; }));
    const { result } = renderHook(() => useSearch());

    act(() => result.current.setQuery('report'));
    act(() => vi.advanceTimersByTime(200));
    act(() => result.current.clear());
    await act(async () => resolveSearch({ results: [{ path: 'stale-report' }] }));

    expect(result.current.results).toEqual([]);
    expect(result.current.isSearching).toBe(false);
  });
});
