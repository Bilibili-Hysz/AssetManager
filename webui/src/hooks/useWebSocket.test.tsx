// @vitest-environment jsdom
import { act, render, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useWebSocket } from './useWebSocket';
import { RealtimeProvider } from '../stores/RealtimeContext';

const authState = {
  capabilities: { realtime: true },
  api: { buildUrl: (path: string) => `/api/${path}`, buildWebSocketUrl: (path: string) => `ws://localhost:3000/${path}` },
  principal: { kind: 'user', authenticated: true, role: 'user', display_name: 'alice', user_profile: { id: 1, username: 'alice' } },
};

vi.mock('../stores/AuthContext', () => ({ useAuthContext: () => authState }));

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  close = vi.fn(() => this.onclose?.());
  url: string;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }
}

describe('useWebSocket', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    vi.stubGlobal('WebSocket', MockWebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('does not connect while unauthenticated', () => {
    renderHook(() => useWebSocket({ enabled: false }));

    expect(MockWebSocket.instances).toHaveLength(0);
  });

  it('connects to an explicitly configured WebSocket URL', () => {
    renderHook(() => useWebSocket({ enabled: true, url: 'wss://example.test/library/ws' }));

    expect(MockWebSocket.instances[0]?.url).toBe('wss://example.test/library/ws');
  });
  it('does not reconnect after intentional cleanup', () => {
    const { result, unmount } = renderHook(() => useWebSocket({ enabled: true }));
    const socket = MockWebSocket.instances[0];

    act(() => socket?.onopen?.());
    const statusBeforeUnmount = result.current.status;
    expect(statusBeforeUnmount).toBe('connected');
    unmount();
    act(() => {
      socket?.onclose?.();
      socket?.onerror?.();
    });
    act(() => vi.advanceTimersByTime(30_000));

    expect(socket?.close).toHaveBeenCalledTimes(2);
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(0);
    expect(result.current.status).toBe(statusBeforeUnmount);
  });

  it('reconnects through three consecutive unexpected close cycles', () => {
    renderHook(() => useWebSocket({ enabled: true }));
    expect(MockWebSocket.instances).toHaveLength(1);

    act(() => MockWebSocket.instances[0]?.onclose?.());
    act(() => vi.advanceTimersByTime(1_000));
    expect(MockWebSocket.instances).toHaveLength(2);

    act(() => MockWebSocket.instances[1]?.onclose?.());
    act(() => vi.advanceTimersByTime(2_000));
    expect(MockWebSocket.instances).toHaveLength(3);

    act(() => MockWebSocket.instances[2]?.onclose?.());
    act(() => vi.advanceTimersByTime(4_000));
    expect(MockWebSocket.instances).toHaveLength(4);
  });

  it('resets retry delay after a stable connection', () => {
    renderHook(() => useWebSocket({ enabled: true }));
    const first = MockWebSocket.instances[0];

    act(() => first?.onclose?.());
    act(() => vi.advanceTimersByTime(1_000));
    const second = MockWebSocket.instances[1];

    act(() => second?.onopen?.());
    act(() => second?.onclose?.());
    act(() => vi.advanceTimersByTime(999));
    expect(MockWebSocket.instances).toHaveLength(2);
    act(() => vi.advanceTimersByTime(1));
    expect(MockWebSocket.instances).toHaveLength(3);
  });

  it('keeps at most one pending reconnect timer', () => {
    renderHook(() => useWebSocket({ enabled: true }));
    const socket = MockWebSocket.instances[0];

    act(() => {
      socket?.onclose?.();
      socket?.onclose?.();
      socket?.onerror?.();
    });

    expect(vi.getTimerCount()).toBe(1);
    act(() => vi.advanceTimersByTime(1_000));
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it('schedules one reconnect when error closes the socket first', () => {
    renderHook(() => useWebSocket({ enabled: true }));
    const socket = MockWebSocket.instances[0];

    act(() => socket?.onerror?.());

    expect(socket?.close).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(1);
    act(() => vi.advanceTimersByTime(1_000));
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it('cancels reconnect timer and active socket when disabled or unmounted', () => {
    const { result, rerender, unmount } = renderHook(({ enabled }) => useWebSocket({ enabled }), {
      initialProps: { enabled: true },
    });
    const first = MockWebSocket.instances[0];

    act(() => first?.onopen?.());
    expect(result.current.status).toBe('connected');
    rerender({ enabled: false });
    expect(first?.close).toHaveBeenCalled();
    expect(result.current.status).toBe('disconnected');
    act(() => {
      first?.onclose?.();
      first?.onerror?.();
    });
    act(() => vi.advanceTimersByTime(30_000));
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(result.current.status).toBe('disconnected');

    rerender({ enabled: true });
    const second = MockWebSocket.instances[1];
    act(() => second?.onclose?.());
    rerender({ enabled: false });
    act(() => vi.advanceTimersByTime(30_000));
    expect(MockWebSocket.instances).toHaveLength(2);

    rerender({ enabled: true });
    const third = MockWebSocket.instances[2];
    unmount();
    expect(third?.close).toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(30_000));
    expect(MockWebSocket.instances).toHaveLength(3);
  });

  it('resets retry delay and ignores old callbacks across disable and re-enable', () => {
    const { result, rerender } = renderHook(({ enabled }) => useWebSocket({ enabled }), {
      initialProps: { enabled: true },
    });
    const first = MockWebSocket.instances[0];

    act(() => first?.onclose?.());
    act(() => vi.advanceTimersByTime(1_000));
    const second = MockWebSocket.instances[1];
    act(() => second?.onclose?.());
    expect(vi.getTimerCount()).toBe(1);

    rerender({ enabled: false });
    act(() => {
      first?.onclose?.();
      first?.onerror?.();
      second?.onclose?.();
      second?.onerror?.();
    });
    expect(vi.getTimerCount()).toBe(0);
    expect(MockWebSocket.instances).toHaveLength(2);
    expect(result.current.status).toBe('disconnected');

    rerender({ enabled: true });
    const third = MockWebSocket.instances[2];
    expect(result.current.status).toBe('connecting');
    act(() => third?.onclose?.());
    act(() => vi.advanceTimersByTime(999));
    expect(MockWebSocket.instances).toHaveLength(3);
    act(() => vi.advanceTimersByTime(1));
    expect(MockWebSocket.instances).toHaveLength(4);
  });

  it('publishes parsed asset changes and ignores malformed messages', () => {
    const onEvent = vi.fn();
    renderHook(() => useWebSocket({ onEvent, enabled: true }));
    const socket = MockWebSocket.instances[0];

    expect(() => {
      socket?.onmessage?.({
        data: JSON.stringify({ type: 'asset_changed', path: 'x' }),
      } as MessageEvent);
    }).not.toThrow();
    expect(onEvent).toHaveBeenCalledOnce();
    expect(onEvent).toHaveBeenCalledWith('asset_changed', {
      type: 'asset_changed',
      path: 'x',
    });

    expect(() => socket?.onmessage?.({ data: '{malformed json' } as MessageEvent)).not.toThrow();
    expect(onEvent).toHaveBeenCalledOnce();
  });

  it('ignores messages from a socket replaced during cleanup', () => {
    const onEvent = vi.fn();
    const { rerender } = renderHook(({ enabled }) => useWebSocket({ onEvent, enabled }), {
      initialProps: { enabled: true },
    });
    const first = MockWebSocket.instances[0];

    rerender({ enabled: false });
    rerender({ enabled: true });
    const second = MockWebSocket.instances[1];
    expect(second).toBeDefined();

    act(() => first?.onmessage?.({
      data: JSON.stringify({ type: 'runtime_ready', epoch: 'old', revision: 99 }),
    } as MessageEvent));

    expect(onEvent).not.toHaveBeenCalled();
  });

  it('ignores close and error callbacks from stale sockets', () => {
    const { result } = renderHook(() => useWebSocket({ enabled: true }));
    const first = MockWebSocket.instances[0];

    act(() => first?.onclose?.());
    act(() => vi.advanceTimersByTime(1_000));
    const second = MockWebSocket.instances[1];

    act(() => second?.onopen?.());
    act(() => second?.onclose?.());
    expect(vi.getTimerCount()).toBe(1);
    expect(result.current.status).toBe('disconnected');
    act(() => {
      first?.onclose?.();
      first?.onerror?.();
    });
    expect(vi.getTimerCount()).toBe(1);
    expect(result.current.status).toBe('disconnected');
    act(() => vi.advanceTimersByTime(2_000));

    expect(MockWebSocket.instances).toHaveLength(3);
  });

  it('caps exponential reconnect delay at 30 seconds', () => {
    renderHook(() => useWebSocket({ enabled: true }));

    for (const delay of [1_000, 2_000, 4_000, 8_000, 16_000]) {
      const socket = MockWebSocket.instances[MockWebSocket.instances.length - 1];
      act(() => socket?.onclose?.());
      act(() => vi.advanceTimersByTime(delay));
    }

    const sixth = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    act(() => sixth?.onclose?.());
    act(() => vi.advanceTimersByTime(29_999));
    expect(MockWebSocket.instances).toHaveLength(6);
    act(() => vi.advanceTimersByTime(1));
    expect(MockWebSocket.instances).toHaveLength(7);
  });

  it('replaces a socket when authentication becomes enabled', () => {
    const { rerender } = renderHook(({ enabled }) => useWebSocket({ enabled }), {
      initialProps: { enabled: false },
    });

    rerender({ enabled: true });

    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it('bridges provider transport to multiple legacy consumers', () => {
    const first = vi.fn();
    const second = vi.fn();
    function Consumers() {
      useWebSocket({ enabled: true, onEvent: first });
      useWebSocket({ enabled: true, onEvent: second });
      return null;
    }
    const { unmount } = render(<RealtimeProvider><Consumers /></RealtimeProvider>);
    expect(MockWebSocket.instances).toHaveLength(1);
    act(() => MockWebSocket.instances[0]?.onmessage?.({ data: JSON.stringify({ type: 'asset_changed', path: 'x' }) } as MessageEvent));
    expect(first).toHaveBeenCalledOnce();
    expect(second).toHaveBeenCalledOnce();
    const socket = MockWebSocket.instances[0];
    unmount();
    expect(socket?.close).toHaveBeenCalledOnce();
  });

  it('isolates provider bridge listener failures during fanout', () => {
    const first = vi.fn(() => { throw new Error('legacy consumer failed'); });
    const second = vi.fn();
    function Consumers() {
      useWebSocket({ enabled: true, onEvent: first });
      useWebSocket({ enabled: true, onEvent: second });
      return null;
    }
    render(<RealtimeProvider><Consumers /></RealtimeProvider>);
    const message = { type: 'asset_changed', path: 'same-message' };

    expect(() => act(() => MockWebSocket.instances[0]?.onmessage?.({ data: JSON.stringify(message) } as MessageEvent))).not.toThrow();
    expect(first).toHaveBeenCalledWith('asset_changed', message);
    expect(second).toHaveBeenCalledWith('asset_changed', message);
  });

  it('replaces the provider socket when principal identity changes', () => {
    const { rerender, unmount } = render(<RealtimeProvider><div /></RealtimeProvider>);
    expect(MockWebSocket.instances).toHaveLength(1);
    const first = MockWebSocket.instances[0];

    authState.principal = { kind: 'user', authenticated: true, role: 'user', display_name: 'bob', user_profile: { id: 2, username: 'bob' } };
    rerender(<RealtimeProvider><div /></RealtimeProvider>);

    expect(first?.close).toHaveBeenCalledOnce();
    expect(MockWebSocket.instances).toHaveLength(2);
    unmount();
    expect(MockWebSocket.instances[1]?.close).toHaveBeenCalledOnce();
  });
});
