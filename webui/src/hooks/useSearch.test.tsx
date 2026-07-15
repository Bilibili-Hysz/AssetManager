// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useSearch } from './useSearch';

const search = vi.fn();
const api = {};

vi.mock('./useAuth', () => ({
  useAuth: () => ({ api }),
}));

vi.mock('../api/metadata', () => ({
  createMetadataApi: () => ({ search }),
}));

describe('useSearch', () => {
  afterEach(() => {
    vi.useRealTimers();
    search.mockReset();
  });

  it('ignores a response from a superseded search', async () => {
    vi.useFakeTimers();
    let resolveFirst!: (value: { results: Array<{ path: string }> }) => void;
    let resolveSecond!: (value: { results: Array<{ path: string }> }) => void;
    search
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve; }));
    const { result } = renderHook(() => useSearch());

    act(() => {
      result.current.setQuery('old');
      vi.advanceTimersByTime(200);
      result.current.setQuery('new');
      vi.advanceTimersByTime(200);
    });
    await act(async () => { resolveSecond({ results: [{ path: 'new' }] }); });
    expect(result.current.results[0]?.path).toBe('new');
    await act(async () => { resolveFirst({ results: [{ path: 'old' }] }); });
    expect(result.current.results[0]?.path).toBe('new');
  });
});
