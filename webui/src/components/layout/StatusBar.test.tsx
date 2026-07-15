// @vitest-environment jsdom
import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { StatusBar } from './StatusBar';
import { setLang } from '../../i18n';

const getStats = vi.fn().mockResolvedValue({
  connections: 2,
  requests: 3,
  bytes_transferred_fmt: '1 MB',
  uptime: 0,
});
const systemApi = { getStats };

vi.mock('../../hooks/useAuth', () => ({
  useAuth: () => ({ systemApi, user: null }),
}));

vi.mock('../../hooks/useWebSocket', () => ({
  useWebSocket: () => ({ status: 'disconnected' }),
}));

describe('StatusBar', () => {
  afterEach(() => setLang('en'));

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
