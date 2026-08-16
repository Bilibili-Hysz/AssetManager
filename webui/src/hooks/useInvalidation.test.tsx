// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useInvalidation } from './useInvalidation';
import type { InvalidationEvent, ProjectionDomain } from '../types/contracts';

const mockRegister = vi.fn();
const mockRealtime = {
  status: 'connected' as const,
  registerInvalidation: mockRegister,
  recover: vi.fn(),
  epoch: 'abc',
  revision: 3,
};

vi.mock('../stores/RealtimeContext', () => ({
  useRealtimeContext: () => mockRealtime,
}));

describe('useInvalidation', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('returns the realtime context', () => {
    const { result } = renderHook(() => useInvalidation(['files'], vi.fn()));
    expect(result.current).toBe(mockRealtime);
  });

  it('registers invalidation with the given domains and returns unregister', () => {
    const cb = vi.fn();
    mockRegister.mockReturnValue(vi.fn());
    const { unmount } = renderHook(() => useInvalidation(['files', 'tags'] as const, cb));

    expect(mockRegister).toHaveBeenCalledTimes(1);
    const [domains] = mockRegister.mock.calls[0] as [readonly ProjectionDomain[], (event: InvalidationEvent | null) => void];
    expect(domains).toEqual(['files', 'tags']);

    unmount();
    // register returns an unregister fn; unmount cleanup calls it
  });

  it('invokes the callback when an invalidation event arrives', () => {
    const cb = vi.fn();
    let capturedCb: (event: InvalidationEvent | null) => void;
    mockRegister.mockImplementation((_domains: readonly ProjectionDomain[], callback: (event: InvalidationEvent | null) => void) => {
      capturedCb = callback;
      return vi.fn();
    });
    renderHook(() => useInvalidation(['files'], cb));

    const event: InvalidationEvent = { type: 'projection_invalidated', epoch: 'abc', revision: 4, domains: ['files'], paths: ['/a'] };
    act(() => { capturedCb!(event); });

    expect(cb).toHaveBeenCalledTimes(1);
    expect(cb).toHaveBeenCalledWith(event);
  });

  it('calls callback with null on recovery', () => {
    const cb = vi.fn();
    let capturedCb: (event: InvalidationEvent | null) => void;
    mockRegister.mockImplementation((_domains: readonly ProjectionDomain[], callback: (event: InvalidationEvent | null) => void) => {
      capturedCb = callback;
      return vi.fn();
    });
    renderHook(() => useInvalidation(['files'], cb));

    act(() => { capturedCb!(null); });

    expect(cb).toHaveBeenCalledTimes(1);
    expect(cb).toHaveBeenCalledWith(null);
  });

  it('re-registers when domains change', () => {
    const cb = vi.fn();
    const { rerender } = renderHook(
      ({ domains }) => useInvalidation(domains, cb),
      { initialProps: { domains: ['files'] as readonly ProjectionDomain[] } },
    );

    expect(mockRegister).toHaveBeenCalledTimes(1);

    rerender({ domains: ['tags'] as readonly ProjectionDomain[] });
    // domainsKey changes → effect re-runs
    expect(mockRegister).toHaveBeenCalledTimes(2);
  });
});
