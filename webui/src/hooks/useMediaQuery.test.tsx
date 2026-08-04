// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useMediaQuery } from './useMediaQuery';

describe('useMediaQuery', () => {
  afterEach(cleanup);

  it('returns the initial matchMedia value', () => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: query === '(min-width: 768px)',
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    });

    const { result } = renderHook(() => useMediaQuery('(min-width: 768px)'));
    expect(result.current).toBe(true);

    const { result: resultSmall } = renderHook(() => useMediaQuery('(max-width: 480px)'));
    expect(resultSmall.current).toBe(false);
  });

  it('updates when the media query changes', () => {
    let changeHandler: ((e: MediaQueryListEvent) => void) | undefined;
    const mq = {
      matches: false,
      addEventListener: vi.fn((_type: string, handler: (e: MediaQueryListEvent) => void) => {
        changeHandler = handler;
      }),
      removeEventListener: vi.fn(),
    };
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue(mq));

    const { result } = renderHook(() => useMediaQuery('(min-width: 768px)'));
    expect(result.current).toBe(false);

    act(() => {
      changeHandler!({ matches: true } as MediaQueryListEvent);
    });
    expect(result.current).toBe(true);

    act(() => {
      changeHandler!({ matches: false } as MediaQueryListEvent);
    });
    expect(result.current).toBe(false);
  });

  it('removes the change listener on unmount', () => {
    const mq = {
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    };
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue(mq));

    const { unmount } = renderHook(() => useMediaQuery('(min-width: 768px)'));
    unmount();
    expect(mq.removeEventListener).toHaveBeenCalledWith('change', expect.any(Function));
  });
});
