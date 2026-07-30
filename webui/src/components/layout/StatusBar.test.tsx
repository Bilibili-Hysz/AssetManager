// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
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

  it('registers stats invalidation and reloads stats when triggered', () => {
    render(<StatusBar sidebarOpen={false} infoOpen={false} />);

    expect(useInvalidationMock.mock.calls[0]?.[0]).toEqual(['stats']);

    getStats.mockClear();
    act(() => useInvalidationMock.mock.calls[0]![1]!());

    expect(getStats).toHaveBeenCalledTimes(1);
  });

  it('does not let an older stats response overwrite a newer response', async () => {
    let resolveFirst!: (value: { connections: number; requests: number; bytes_transferred_fmt: string; uptime: number }) => void;
    let resolveSecond!: (value: { connections: number; requests: number; bytes_transferred_fmt: string; uptime: number }) => void;
    const firstResponse = new Promise(resolve => { resolveFirst = resolve; });
    const secondResponse = new Promise(resolve => { resolveSecond = resolve; });
    getStats.mockReset();
    getStats
      .mockImplementationOnce(() => firstResponse)
      .mockImplementationOnce(() => secondResponse);

    render(<StatusBar sidebarOpen={false} infoOpen={false} />);
    await waitFor(() => expect(getStats).toHaveBeenCalledTimes(1));
    act(() => useInvalidationMock.mock.calls[0]![1]!());
    await waitFor(() => expect(getStats).toHaveBeenCalledTimes(2));

    await act(async () => {
      resolveSecond({ connections: 20, requests: 30, bytes_transferred_fmt: '2 MB', uptime: 0 });
      await secondResponse;
    });
    expect(screen.getByText('20 connections')).toBeDefined();

    await act(async () => {
      resolveFirst({ connections: 1, requests: 2, bytes_transferred_fmt: '1 KB', uptime: 0 });
    });
    expect(screen.getByText('20 connections')).toBeDefined();
    expect(screen.queryByText('1 connection')).toBeNull();
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
