// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { StatusBar } from './StatusBar';
import { setLang } from '../../i18n';

const { getStats, useInvalidationMock } = vi.hoisted(() => ({
  getStats: vi.fn().mockResolvedValue({
    connections: 2,
    requests: 3,
    bytes_transferred_fmt: '1 MB',
    uptime: 0,
  }),
  useInvalidationMock: vi.fn(),
}));

const systemApi = { getStats };

vi.mock('../../hooks/useInvalidation', () => ({
  useInvalidation: useInvalidationMock,
}));

vi.mock('../../hooks/useAuth', () => ({
  useAuth: () => ({ systemApi, user: null }),
}));

vi.mock('../../hooks/useQuota', () => ({
  useQuota: () => ({ quota: null }),
}));

vi.mock('../../stores/RealtimeContext', () => ({
  useRealtimeContext: () => ({ status: 'disconnected' }),
}));

describe('StatusBar', () => {
  afterEach(() => {
    cleanup();
    getStats.mockReset().mockResolvedValue({
      connections: 2,
      requests: 3,
      bytes_transferred_fmt: '1 MB',
      uptime: 0,
    });
    useInvalidationMock.mockClear();
    setLang('en');
  });

  it('does not register a projection invalidation domain for stats', () => {
    render(<StatusBar sidebarOpen={false} infoOpen={false} />);

    // The backend has no "stats" ProjectionDomain; stats refresh comes from
    // the 10s polling interval, not from the realtime invalidation fan-out.
    expect(useInvalidationMock).not.toHaveBeenCalled();
  });

  it('polls stats again when the polling interval fires', async () => {
    vi.useFakeTimers();
    try {
      render(<StatusBar sidebarOpen={false} infoOpen={false} />);
      await act(async () => { await Promise.resolve(); });
      expect(getStats).toHaveBeenCalledTimes(1);

      await act(async () => { vi.advanceTimersByTime(10_000); });
      expect(getStats).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('rerenders status text when the language changes', async () => {
    render(<StatusBar sidebarOpen={false} infoOpen={false} />);
    await screen.findByText('2 connections');

    act(() => setLang('zh'));

    expect(screen.getByText('2 个连接')).toBeDefined();
    expect(screen.getByText('3 个请求')).toBeDefined();
  });

  it('keeps one polling interval across rerenders and clears it on unmount', () => {
    const setIntervalSpy = vi.spyOn(window, 'setInterval');
    const clearIntervalSpy = vi.spyOn(window, 'clearInterval');
    const { rerender, unmount } = render(<StatusBar sidebarOpen={false} infoOpen={false} />);

    rerender(<StatusBar sidebarOpen={true} infoOpen={true} />);
    expect(setIntervalSpy).toHaveBeenCalledTimes(1);

    unmount();
    expect(clearIntervalSpy).toHaveBeenCalledTimes(1);
    setIntervalSpy.mockRestore();
    clearIntervalSpy.mockRestore();
  });
});
