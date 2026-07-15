// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useWebSocket } from './useWebSocket';

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  close = vi.fn(() => this.onclose?.());

  constructor(_url: string) {
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

  it('does not reconnect after intentional cleanup', () => {
    const { unmount } = renderHook(() => useWebSocket({ enabled: true }));
    const socket = MockWebSocket.instances[0];

    unmount();
    act(() => vi.advanceTimersByTime(30_000));

    expect(socket?.close).toHaveBeenCalledOnce();
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it('reconnects once after an unexpected close', () => {
    renderHook(() => useWebSocket({ enabled: true }));
    const socket = MockWebSocket.instances[0];
    expect(socket).toBeDefined();

    act(() => socket?.onclose?.());
    act(() => socket?.onclose?.());
    act(() => vi.advanceTimersByTime(1_000));

    expect(MockWebSocket.instances).toHaveLength(2);

    act(() => MockWebSocket.instances[1]?.onopen?.());
    act(() => MockWebSocket.instances[1]?.onclose?.());
    act(() => vi.advanceTimersByTime(30_000));

    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it('replaces a socket when authentication becomes enabled', () => {
    const { rerender } = renderHook(({ enabled }) => useWebSocket({ enabled }), {
      initialProps: { enabled: false },
    });

    rerender({ enabled: true });

    expect(MockWebSocket.instances).toHaveLength(1);
  });
});
