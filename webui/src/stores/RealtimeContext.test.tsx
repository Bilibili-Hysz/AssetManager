// @vitest-environment jsdom
import { act, render, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useEffect, type ReactNode } from 'react';
import { UnauthorizedError } from '../api/errors';
import { RealtimeProvider, useRealtimeContext } from './RealtimeContext';

const authState = {
  api: {
    buildUrl: (path: string) => `/api/${path}`,
    buildWebSocketUrl: (path: string) => `ws://localhost:3000/library/${path}`,
    get: vi.fn(async () => ({ epoch: 'a', revision: 3 })),
  },
  capabilities: { realtime: true },
  identityGeneration: 0,
  principal: { kind: 'user', authenticated: true, role: 'user', display_name: 'alice', user_profile: { id: 1, username: 'alice' } },
};
const transport = {
  onEvent: undefined as ((type: string, data: Record<string, unknown>) => void) | undefined,
  enabled: false,
  url: undefined as string | undefined,
  close: vi.fn(),
};

vi.mock('./AuthContext', () => ({
  useAuthContext: () => authState,
}));

vi.mock('../hooks/useWebSocket', () => ({
  useWebSocket: ({ onEvent, enabled }: { onEvent?: typeof transport.onEvent; enabled?: boolean }) => {
    useEffect(() => () => { transport.enabled = false; }, []);
    transport.onEvent = onEvent;
    transport.enabled = Boolean(enabled);
    return { status: enabled ? 'connected' : 'disconnected' };
  },
  WebSocketTransportHost: ({ children, enabled, onEvent, onStatus, url }: { children: ReactNode; enabled: boolean; onEvent?: typeof transport.onEvent; onStatus?: (status: 'connected' | 'disconnected') => void; url?: string }) => {
    useEffect(() => {
      transport.url = url;
      transport.onEvent = onEvent;
      transport.enabled = Boolean(enabled);
      onStatus?.(enabled ? 'connected' : 'disconnected');
      return () => {
        transport.close();
        transport.enabled = false;
      };
    }, [enabled, onEvent, onStatus, url]);
    return <>{children}</>;
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  return <RealtimeProvider>{children}</RealtimeProvider>;
}

function emit(data: Record<string, unknown>) {
  act(() => transport.onEvent?.(String(data.type), data));
}

describe('RealtimeProvider', () => {
  beforeEach(() => {
    authState.capabilities.realtime = true;
    authState.identityGeneration = 0;
    authState.principal = { kind: 'user', authenticated: true, role: 'user', display_name: 'alice', user_profile: { id: 1, username: 'alice' } };
    transport.onEvent = undefined;
    transport.enabled = false;
    transport.url = undefined;
    transport.close.mockClear();
    authState.api.get = vi.fn(async () => ({ epoch: 'a', revision: 3 }));
  });

  afterEach(() => vi.unstubAllGlobals());

  it('shares exactly one enabled transport between multiple consumers', () => {
    const first = vi.fn();
    const second = vi.fn();
    function Consumers() {
      const realtime = useRealtimeContext();
      useEffect(() => realtime.registerInvalidation(['files'], first), [realtime]);
      useEffect(() => realtime.registerInvalidation(['tree'], second), [realtime]);
      return null;
    }
    render(<RealtimeProvider><Consumers /></RealtimeProvider>);
    expect(transport.enabled).toBe(true);
    expect(transport.url).toBe('ws://localhost:3000/library/ws');
    emit({ type: 'runtime_ready', epoch: 'a', revision: 0 });
    emit({ type: 'projection_invalidated', epoch: 'a', revision: 1, domains: ['files'], paths: [] });
    expect(first).toHaveBeenCalledOnce();
    expect(second).not.toHaveBeenCalled();
  });

  it('accepts the favorites projection domain', () => {
    const callback = vi.fn();
    const { result } = renderHook(() => useRealtimeContext(), { wrapper });
    act(() => result.current.registerInvalidation(['favorites'], callback));

    emit({ type: 'runtime_ready', epoch: 'a', revision: 0 });
    emit({ type: 'projection_invalidated', epoch: 'a', revision: 1, domains: ['favorites'], paths: ['collection'] });

    expect(callback).toHaveBeenCalledOnce();
  });

  it('delivers collections invalidations, including events with other projection domains', () => {
    const collections = vi.fn();
    const files = vi.fn();
    const { result } = renderHook(() => useRealtimeContext(), { wrapper });
    act(() => {
      result.current.registerInvalidation(['collections'], collections);
      result.current.registerInvalidation(['files'], files);
    });

    emit({ type: 'runtime_ready', epoch: 'a', revision: 0 });
    emit({ type: 'projection_invalidated', epoch: 'a', revision: 1, domains: ['collections', 'files'], paths: ['workspace/hero.svg'] });

    expect(collections).toHaveBeenCalledOnce();
    expect(files).toHaveBeenCalledOnce();
    expect(collections.mock.calls[0]?.[0]).toMatchObject({ domains: ['collections', 'files'], revision: 1 });
  });

  it('enables and disables the socket with realtime capability', () => {
    const { rerender } = render(<RealtimeProvider><div /></RealtimeProvider>);
    expect(transport.enabled).toBe(true);
    authState.capabilities.realtime = false;
    rerender(<RealtimeProvider><div /></RealtimeProvider>);
    expect(transport.enabled).toBe(false);
  });

  it('establishes cursor, delivers only the next revision, and suppresses duplicates', () => {
    const callback = vi.fn();
    const { result } = renderHook(() => useRealtimeContext(), { wrapper });
    act(() => result.current.registerInvalidation(['files'], callback));
    emit({ type: 'runtime_ready', epoch: 'a', revision: 4 });
    emit({ type: 'projection_invalidated', epoch: 'a', revision: 5, domains: ['files'], paths: ['x'] });
    emit({ type: 'projection_invalidated', epoch: 'a', revision: 5, domains: ['files'], paths: ['x'] });
    expect(result.current.revision).toBe(5);
    expect(callback).toHaveBeenCalledOnce();
  });

  it('ignores an older runtime_ready in the same epoch', () => {
    const callback = vi.fn();
    const { result } = renderHook(() => useRealtimeContext(), { wrapper });
    act(() => result.current.registerInvalidation(['files'], callback));
    emit({ type: 'runtime_ready', epoch: 'a', revision: 9 });
    emit({ type: 'runtime_ready', epoch: 'a', revision: 2 });
    emit({ type: 'projection_invalidated', epoch: 'a', revision: 3, domains: ['files'], paths: [] });
    expect(result.current.revision).toBe(9);
    expect(callback).not.toHaveBeenCalled();
  });

  it('recovers and fans out when a newer runtime_ready advances the same epoch', async () => {
    const callback = vi.fn();
    authState.api.get = vi.fn(async () => ({ epoch: 'a', revision: 4 }));
    const { result } = renderHook(() => useRealtimeContext(), { wrapper });
    act(() => result.current.registerInvalidation(['files'], callback));

    emit({ type: 'runtime_ready', epoch: 'a', revision: 1 });
    emit({ type: 'runtime_ready', epoch: 'a', revision: 4 });

    await waitFor(() => expect(callback).toHaveBeenCalledOnce());
    expect(authState.api.get).toHaveBeenCalledOnce();
    expect(callback.mock.calls[0]?.[0]).toBeNull();
    expect(result.current.epoch).toBe('a');
    expect(result.current.revision).toBe(4);
  });

  it('replaces the transport when the principal identity changes while realtime remains enabled', () => {
    const firstConsumer = vi.fn();
    const { rerender } = render(<RealtimeProvider><div /></RealtimeProvider>);
    expect(transport.enabled).toBe(true);
    authState.principal = { kind: 'user', authenticated: true, role: 'user', display_name: 'bob', user_profile: { id: 2, username: 'bob' } };
    rerender(<RealtimeProvider><div /></RealtimeProvider>);
    expect(firstConsumer).not.toHaveBeenCalled();
    expect(transport.close).toHaveBeenCalledOnce();
    expect(transport.enabled).toBe(true);
  });

  it('resets the cursor on identity change and recovers once from the first ready', async () => {
    const callback = vi.fn();
    const { result, rerender } = renderHook(() => useRealtimeContext(), { wrapper });
    act(() => result.current.registerInvalidation(['files'], callback));
    emit({ type: 'runtime_ready', epoch: 'old-epoch', revision: 8 });
    expect(result.current).toMatchObject({ epoch: 'old-epoch', revision: 8 });

    authState.identityGeneration += 1;
    authState.principal = { kind: 'user', authenticated: true, role: 'user', display_name: 'bob', user_profile: { id: 2, username: 'bob' } };
    rerender();

    await waitFor(() => expect(result.current).toMatchObject({ epoch: '', revision: 0 }));

    act(() => result.current.registerInvalidation(['files'], callback));
    emit({ type: 'runtime_ready', epoch: 'new-epoch', revision: 0 });

    await waitFor(() => expect(authState.api.get).toHaveBeenCalledOnce());
    expect(callback).toHaveBeenCalledOnce();
    expect(callback.mock.calls[0]?.[0]).toBeNull();
  });

  it('drops projection registrations when identity changes', async () => {
    const callback = vi.fn();
    const { result, rerender } = renderHook(() => useRealtimeContext(), { wrapper });
    act(() => result.current.registerInvalidation(['files'], callback));

    authState.identityGeneration += 1;
    authState.principal = { kind: 'user', authenticated: true, role: 'user', display_name: 'bob', user_profile: { id: 2, username: 'bob' } };
    rerender();

    emit({ type: 'runtime_ready', epoch: 'new-epoch', revision: 0 });
    await waitFor(() => expect(authState.api.get).toHaveBeenCalledOnce());
    emit({ type: 'projection_invalidated', epoch: 'new-epoch', revision: 1, domains: ['files'], paths: ['stale.txt'] });

    expect(callback).not.toHaveBeenCalled();
  });

  it('recovers once for a gap and notifies every registered projection', async () => {
    const files = vi.fn();
    const tree = vi.fn();
    const { result } = renderHook(() => useRealtimeContext(), { wrapper });
    act(() => {
      result.current.registerInvalidation(['files'], files);
      result.current.registerInvalidation(['tree'], tree);
    });
    emit({ type: 'runtime_ready', epoch: 'a', revision: 1 });
    emit({ type: 'projection_invalidated', epoch: 'a', revision: 4, domains: ['files'], paths: [] });
    emit({ type: 'projection_invalidated', epoch: 'a', revision: 5, domains: ['files'], paths: [] });
    await waitFor(() => expect(files).toHaveBeenCalledOnce());
    expect(tree).toHaveBeenCalledOnce();
    expect(files.mock.calls[0]?.[0]).toBeNull();
    expect(authState.api.get).toHaveBeenCalledTimes(1);
  });

  it('retries once for a same-epoch stale recovery response without regressing or notifying', async () => {
    const callback = vi.fn();
    let resolveRecovery!: (value: unknown) => void;
    const recoveryResponse = new Promise<unknown>(resolve => { resolveRecovery = resolve; });
    authState.api.get = vi.fn(async () => recoveryResponse);

    const { result } = renderHook(() => useRealtimeContext(), { wrapper });
    act(() => result.current.registerInvalidation(['files'], callback));
    emit({ type: 'runtime_ready', epoch: 'a', revision: 10 });
    emit({ type: 'projection_invalidated', epoch: 'a', revision: 12, domains: ['files'], paths: [] });

    resolveRecovery({ epoch: 'a', revision: 9 });
    await waitFor(() => expect(authState.api.get).toHaveBeenCalledTimes(2));
    await act(async () => { await Promise.resolve(); });

    expect(result.current.epoch).toBe('a');
    expect(result.current.revision).toBe(10);
    expect(callback).not.toHaveBeenCalled();
    expect(authState.api.get).toHaveBeenCalledTimes(2);
  });

  it('isolates callback failures during recovery fan-out', async () => {
    const files = vi.fn(() => { throw new Error('files failed'); });
    const tree = vi.fn();
    const { result } = renderHook(() => useRealtimeContext(), { wrapper });
    act(() => {
      result.current.registerInvalidation(['files'], files);
      result.current.registerInvalidation(['tree'], tree);
    });
    emit({ type: 'runtime_ready', epoch: 'a', revision: 1 });

    expect(() => emit({
      type: 'projection_invalidated', epoch: 'a', revision: 4, domains: ['files'], paths: [],
    })).not.toThrow();
    await waitFor(() => expect(tree).toHaveBeenCalledOnce());
    expect(files).toHaveBeenCalledOnce();
    expect(tree.mock.calls[0]?.[0]).toBeNull();
  });

  it('replaces the epoch on ready and recovers on mismatched events', async () => {
    const callback = vi.fn();
    authState.api.get = vi.fn()
      .mockResolvedValueOnce({ epoch: 'b', revision: 2 })
      .mockResolvedValue({ epoch: 'b', revision: 3 });
    const { result } = renderHook(() => useRealtimeContext(), { wrapper });
    act(() => result.current.registerInvalidation(['files'], callback));
    emit({ type: 'runtime_ready', epoch: 'a', revision: 9 });
    emit({ type: 'runtime_ready', epoch: 'b', revision: 2 });
    // The epoch change clears consumers synchronously; the confirming probe
    // (equal cursor) does not fan out again.
    expect(callback).toHaveBeenCalledOnce();
    expect(result.current.epoch).toBe('b');
    expect(result.current.revision).toBe(2);
    await waitFor(() => expect(authState.api.get).toHaveBeenCalledTimes(1));
    emit({ type: 'projection_invalidated', epoch: 'a', revision: 10, domains: ['files'], paths: [] });
    await waitFor(() => expect(callback).toHaveBeenCalledTimes(2));
    expect(callback.mock.calls[0]?.[0]).toBeNull();
    expect(callback.mock.calls[1]?.[0]).toBeNull();
    expect(result.current).toMatchObject({ epoch: 'b', revision: 3 });
  });

  it('recovers and notifies immediately for a new runtime epoch, once per ready', async () => {
    const callback = vi.fn();
    authState.api.get = vi.fn(async () => ({ epoch: 'b', revision: 2 }));
    const { result } = renderHook(() => useRealtimeContext(), { wrapper });
    act(() => result.current.registerInvalidation(['files'], callback));
    emit({ type: 'runtime_ready', epoch: 'a', revision: 1 });

    emit({ type: 'runtime_ready', epoch: 'b', revision: 2 });
    // The stale-data clear happens synchronously, before the /api/revision
    // probe resolves.
    expect(callback).toHaveBeenCalledOnce();
    expect(callback.mock.calls[0]?.[0]).toBeNull();

    emit({ type: 'runtime_ready', epoch: 'b', revision: 2 });

    await waitFor(() => expect(authState.api.get).toHaveBeenCalledOnce());
    expect(callback).toHaveBeenCalledOnce();
    expect(result.current).toMatchObject({ epoch: 'b', revision: 2 });
  });

  it('fans out once when a new epoch keeps the same revision after equal recovery', async () => {
    const callback = vi.fn();
    authState.api.get = vi.fn(async () => ({ epoch: 'b', revision: 4 }));
    const { result } = renderHook(() => useRealtimeContext(), { wrapper });
    act(() => result.current.registerInvalidation(['files'], callback));

    emit({ type: 'runtime_ready', epoch: 'a', revision: 4 });
    emit({ type: 'runtime_ready', epoch: 'b', revision: 4 });

    await waitFor(() => expect(callback).toHaveBeenCalledOnce());
    expect(callback.mock.calls[0]?.[0]).toBeNull();
    expect(result.current.epoch).toBe('b');
    expect(result.current.revision).toBe(4);
    expect(authState.api.get).toHaveBeenCalledOnce();
  });

  it('drops a stale recovery response and allows recovery for the new epoch', async () => {
    const callback = vi.fn();
    let resolveFirst!: (value: unknown) => void;
    let resolveSecond!: (value: unknown) => void;
    const firstResponse = new Promise<unknown>(resolve => { resolveFirst = resolve; });
    const secondResponse = new Promise<unknown>(resolve => { resolveSecond = resolve; });
    authState.api.get = vi.fn()
      .mockImplementationOnce(async () => firstResponse)
      .mockImplementationOnce(async () => secondResponse);

    const { result } = renderHook(() => useRealtimeContext(), { wrapper });
    act(() => result.current.registerInvalidation(['files'], callback));
    emit({ type: 'runtime_ready', epoch: 'a', revision: 1 });
    emit({ type: 'projection_invalidated', epoch: 'a', revision: 4, domains: ['files'], paths: [] });
    emit({ type: 'runtime_ready', epoch: 'b', revision: 2 });
    // The epoch change clears consumers synchronously.
    expect(callback).toHaveBeenCalledOnce();

    resolveFirst({ epoch: 'a', revision: 99 });
    await Promise.resolve();
    expect(result.current.epoch).toBe('b');
    expect(result.current.revision).toBe(2);
    expect(callback).toHaveBeenCalledOnce(); // only the synchronous epoch-change clear so far

    await waitFor(() => expect(authState.api.get).toHaveBeenCalledTimes(2));
    resolveSecond({ epoch: 'b', revision: 3 });
    await waitFor(() => expect(callback).toHaveBeenCalledTimes(2));
    expect(result.current.epoch).toBe('b');
    expect(result.current.revision).toBe(3);
    expect(callback.mock.calls[0]?.[0]).toBeNull();
    expect(callback.mock.calls[1]?.[0]).toBeNull();
  });

  it('retries recovery when a valid event advances the cursor during recovery', async () => {
    const callback = vi.fn();
    let resolveFirst!: (value: unknown) => void;
    let resolveSecond!: (value: unknown) => void;
    const firstResponse = new Promise<unknown>(resolve => { resolveFirst = resolve; });
    const secondResponse = new Promise<unknown>(resolve => { resolveSecond = resolve; });
    authState.api.get = vi.fn()
      .mockImplementationOnce(async () => firstResponse)
      .mockImplementationOnce(async () => secondResponse);

    const { result } = renderHook(() => useRealtimeContext(), { wrapper });
    act(() => result.current.registerInvalidation(['files'], callback));
    emit({ type: 'runtime_ready', epoch: 'a', revision: 1 });
    emit({ type: 'projection_invalidated', epoch: 'a', revision: 4, domains: ['files'], paths: [] });
    emit({ type: 'projection_invalidated', epoch: 'a', revision: 2, domains: ['files'], paths: [] });

    resolveFirst({ epoch: 'a', revision: 5 });
    await waitFor(() => expect(authState.api.get).toHaveBeenCalledTimes(2));
    expect(result.current.epoch).toBe('a');
    expect(result.current.revision).toBe(2);
    expect(callback).toHaveBeenCalledOnce();
    expect(callback.mock.calls[0]?.[0]?.revision).toBe(2);

    resolveSecond({ epoch: 'a', revision: 5 });
    await waitFor(() => expect(callback).toHaveBeenCalledTimes(2));
    expect(result.current.revision).toBe(5);
    expect(callback.mock.calls[1]?.[0]).toBeNull();
  });

  it('retries recovery when a stale response still leaves the current gap unresolved', async () => {
    const callback = vi.fn();
    let resolveFirst!: (value: unknown) => void;
    let resolveSecond!: (value: unknown) => void;
    const firstResponse = new Promise<unknown>(resolve => { resolveFirst = resolve; });
    const secondResponse = new Promise<unknown>(resolve => { resolveSecond = resolve; });
    authState.api.get = vi.fn()
      .mockImplementationOnce(async () => firstResponse)
      .mockImplementationOnce(async () => secondResponse);

    const { result } = renderHook(() => useRealtimeContext(), { wrapper });
    act(() => result.current.registerInvalidation(['files'], callback));
    emit({ type: 'runtime_ready', epoch: 'a', revision: 1 });
    emit({ type: 'projection_invalidated', epoch: 'a', revision: 4, domains: ['files'], paths: [] });
    emit({ type: 'projection_invalidated', epoch: 'a', revision: 2, domains: ['files'], paths: [] });

    resolveFirst({ epoch: 'a', revision: 2 });
    await waitFor(() => expect(authState.api.get).toHaveBeenCalledTimes(2));
    expect(result.current.epoch).toBe('a');
    expect(result.current.revision).toBe(2);
    expect(callback).toHaveBeenCalledOnce();
    expect(callback.mock.calls[0]?.[0]?.revision).toBe(2);

    resolveSecond({ epoch: 'a', revision: 4 });
    await waitFor(() => expect(callback).toHaveBeenCalledTimes(2));
    expect(result.current.revision).toBe(4);
    expect(callback.mock.calls[1]?.[0]).toBeNull();
    expect(authState.api.get).toHaveBeenCalledTimes(2);
  });

  it('retries a stale response when the gap cursor has not advanced yet', async () => {
    const callback = vi.fn();
    let resolveFirst!: (value: unknown) => void;
    let resolveSecond!: (value: unknown) => void;
    const firstResponse = new Promise<unknown>(resolve => { resolveFirst = resolve; });
    const secondResponse = new Promise<unknown>(resolve => { resolveSecond = resolve; });
    authState.api.get = vi.fn()
      .mockImplementationOnce(async () => firstResponse)
      .mockImplementationOnce(async () => secondResponse);

    const { result } = renderHook(() => useRealtimeContext(), { wrapper });
    act(() => result.current.registerInvalidation(['files'], callback));
    emit({ type: 'runtime_ready', epoch: 'a', revision: 1 });
    emit({ type: 'projection_invalidated', epoch: 'a', revision: 4, domains: ['files'], paths: [] });

    resolveFirst({ epoch: 'a', revision: 1 });
    await waitFor(() => expect(authState.api.get).toHaveBeenCalledTimes(2));

    resolveSecond({ epoch: 'a', revision: 4 });
    await waitFor(() => expect(callback).toHaveBeenCalledOnce());
    expect(result.current.epoch).toBe('a');
    expect(result.current.revision).toBe(4);
    expect(callback.mock.calls[0]?.[0]).toBeNull();
  });

  it('marks recovery failed when the shared client rejects with UnauthorizedError', async () => {
    authState.api.get = vi.fn().mockRejectedValue(new UnauthorizedError());
    const { result } = renderHook(() => useRealtimeContext(), { wrapper });
    act(() => result.current.registerInvalidation(['files'], vi.fn()));
    emit({ type: 'runtime_ready', epoch: 'a', revision: 1 });
    emit({ type: 'projection_invalidated', epoch: 'a', revision: 4, domains: ['files'], paths: [] });

    await waitFor(() => expect(result.current.recoveryFailed).toBe(true));
  });

  it('fans out a null event when recovery fails so consumers re-probe', async () => {
    const callback = vi.fn();
    authState.api.get = vi.fn().mockRejectedValue(new Error('probe unreachable'));
    const { result } = renderHook(() => useRealtimeContext(), { wrapper });
    act(() => result.current.registerInvalidation(['files'], callback));
    emit({ type: 'runtime_ready', epoch: 'a', revision: 1 });
    emit({ type: 'projection_invalidated', epoch: 'a', revision: 4, domains: ['files'], paths: [] });

    await waitFor(() => expect(result.current.recoveryFailed).toBe(true));
    expect(callback).toHaveBeenCalledOnce();
    expect(callback.mock.calls[0]?.[0]).toBeNull();
  });

  it('ignores malformed and unrelated messages safely', () => {
    const callback = vi.fn();
    renderHook(() => useRealtimeContext(), { wrapper });
    expect(() => {
      emit({ type: 'projection_invalidated', epoch: 3, revision: 'bad' });
      transport.onEvent?.('unknown', { type: 'unknown' });
    }).not.toThrow();
    expect(callback).not.toHaveBeenCalled();
  });

  it('unsubscribes callbacks and cleans them on unmount', () => {
    const callback = vi.fn();
    const { result, unmount } = renderHook(() => useRealtimeContext(), { wrapper });
    let unsubscribe: (() => void) | undefined;
    act(() => { unsubscribe = result.current.registerInvalidation(['files'], callback); });
    unsubscribe?.();
    emit({ type: 'runtime_ready', epoch: 'a', revision: 0 });
    emit({ type: 'projection_invalidated', epoch: 'a', revision: 1, domains: ['files'], paths: [] });
    expect(callback).not.toHaveBeenCalled();
    unmount();
    expect(transport.enabled).toBe(false);
  });
});
