// @vitest-environment jsdom
import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { AuthProvider, useAuthContext } from './AuthContext';
import type { Capabilities, ServerInfo } from '../types/api';

const info: ServerInfo = {
  version: '1', share_name: 'share', library_root: '/library', auth_enabled: true,
  auth_mode: 'user', theme_color: '#000', welcome_msg: '', footer_text: '',
  library_stats: { total_projects: 0, total_size: 0, total_size_fmt: '0 B' },
};
const getInfo = vi.fn().mockResolvedValue(info);
const me = vi.fn();

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

vi.mock('../api/client', () => ({
  createApiClient: () => ({}),
}));

vi.mock('../api/auth', () => ({
  createAuthApi: () => ({ logout: vi.fn().mockResolvedValue({}), me }),
}));

vi.mock('../api/system', () => ({
  createSystemApi: () => ({ getInfo, getStats: vi.fn() }),
}));

describe('AuthProvider', () => {
  beforeEach(() => {
    me.mockReset();
    getInfo.mockResolvedValue(info);
  });

  it('retains the supplied token after login', async () => {
    me.mockResolvedValueOnce({ principal: {
      ...{
        kind: 'guest', authenticated: false, role: 'guest', display_name: 'Guest',
        capabilities: { browse: false, preview: false, download: false, upload: false, manage_links: false, manage_users: false, settings: false, realtime: false },
      },
    } });
    const { result } = renderHook(() => useAuthContext(), { wrapper: AuthProvider });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    let resolveRefresh!: (value: unknown) => void;
    me.mockImplementationOnce(() => new Promise(resolve => { resolveRefresh = resolve; }));

    result.current.setToken('session-token', {
      id: 1,
      username: 'member',
      role: 'user',
      active: true,
      created_at: 1752537600,
    });

    await waitFor(() => expect(result.current.token).toBe('session-token'));
    expect(result.current.role).toBe('guest');
    expect(result.current.principal.role).toBe('user');
    resolveRefresh({ principal: {
      kind: 'user', authenticated: true, role: 'admin', display_name: 'member',
      capabilities: { browse: true, preview: true, download: true, upload: true, manage_links: true, manage_users: true, settings: true, realtime: true },
      user_profile: { id: 1, username: 'member', role: 'user', active: true, created_at: 1752537600 },
    } });
    await waitFor(() => expect(result.current.capabilities.manage_users).toBe(true));
  });

  it.each(['local_ui', 'share'] as const)('preserves %s principal from refresh', async kind => {
    const principal = {
      kind, authenticated: true, role: 'guest' as const, display_name: kind,
      capabilities: { browse: true, preview: true, download: true, upload: false, manage_links: false, manage_users: false, settings: false, realtime: false },
    };
    me.mockResolvedValueOnce({ principal });
    const { result } = renderHook(() => useAuthContext(), { wrapper: AuthProvider });
    await waitFor(() => expect(result.current.principal.kind).toBe(kind));
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.user).toBeNull();
  });

  it('represents an unauthenticated guest principal', async () => {
    me.mockResolvedValueOnce({ principal: {
      kind: 'guest', authenticated: false, role: 'guest', display_name: 'Guest',
      capabilities: { browse: true, preview: true, download: false, upload: false, manage_links: false, manage_users: false, settings: false, realtime: false },
    } });
    const { result } = renderHook(() => useAuthContext(), { wrapper: AuthProvider });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.principal.kind).toBe('guest');
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.capabilities).toEqual(result.current.principal.capabilities);
  });

  it.each(['password', 'access_key'] as const)('represents an authenticated %s principal without a user', async kind => {
    const capabilities = { browse: true, preview: true, download: true, upload: false, manage_links: false, manage_users: false, settings: false, realtime: true };
    me.mockResolvedValueOnce({ principal: { kind, authenticated: true, role: 'user', display_name: kind, capabilities } });
    const { result } = renderHook(() => useAuthContext(), { wrapper: AuthProvider });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.principal).toEqual({ kind, authenticated: true, role: 'user', display_name: kind, capabilities });
    expect(result.current.user).toBeNull();
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.capabilities).toEqual(capabilities);
  });

  it('uses the persisted user principal and refresh response as authority', async () => {
    const user = { id: 1, username: 'owner', role: 'admin' as const, active: true, created_at: 100 };
    const capabilities = { browse: true, preview: true, download: false, upload: false, manage_links: false, manage_users: true, settings: false, realtime: false };
    me.mockResolvedValueOnce({ principal: { kind: 'user', authenticated: true, role: 'admin', display_name: 'owner', capabilities, user_profile: user }, user });
    const { result } = renderHook(() => useAuthContext(), { wrapper: AuthProvider });
    await waitFor(() => expect(result.current.user?.username).toBe('owner'));
    expect(result.current.principal.user_profile).toEqual(user);
    expect(result.current.capabilities).toEqual(capabilities);
    expect(result.current.permissions).toEqual([]);
  });

  it('returns false and clears principal when session refresh fails', async () => {
    me.mockRejectedValueOnce(new Error('session unavailable'));
    me.mockRejectedValueOnce(new Error('session unavailable'));
    const { result } = renderHook(() => useAuthContext(), { wrapper: AuthProvider });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await expect(result.current.refreshMe()).resolves.toBe(false);

    await waitFor(() => {
      expect(result.current.principal.authenticated).toBe(false);
      expect(result.current.isAuthenticated).toBe(false);
      expect(result.current.user).toBeNull();
      expect(result.current.token).toBeNull();
    });
  });

  it('does not restore an authenticated principal from a stale refresh after logout', async () => {
    getInfo.mockResolvedValueOnce({ ...info, auth_enabled: false, auth_mode: 'none' });
    const pending = deferred<{ principal: { kind: 'user'; authenticated: true; role: 'user'; display_name: string; capabilities: Capabilities } }>();
    me.mockReturnValueOnce(pending.promise);
    const { result } = renderHook(() => useAuthContext(), { wrapper: AuthProvider });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    me.mockReturnValueOnce(pending.promise);
    result.current.setToken('session-token');
    result.current.logout();
    pending.resolve({ principal: {
      kind: 'user', authenticated: true, role: 'user', display_name: 'stale',
      capabilities: { browse: true, preview: true, download: true, upload: true, manage_links: false, manage_users: false, settings: false, realtime: true },
    } });

    await waitFor(() => expect(result.current.principal.authenticated).toBe(false));
    expect(result.current.principal.kind).toBe('guest');
    expect(result.current.token).toBeNull();
  });

  it('dedupes setToken and explicit refreshMe and uses server capabilities', async () => {
    getInfo.mockResolvedValueOnce({ ...info, auth_enabled: false, auth_mode: 'none' });
    const pending = deferred<{ principal: { kind: 'user'; authenticated: true; role: 'admin'; display_name: string; capabilities: Capabilities } }>();
    me.mockReturnValueOnce(pending.promise);
    const { result } = renderHook(() => useAuthContext(), { wrapper: AuthProvider });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    result.current.setToken('session-token');
    const refresh = result.current.refreshMe();
    expect(me).toHaveBeenCalledTimes(1);
    pending.resolve({ principal: {
      kind: 'user', authenticated: true, role: 'admin', display_name: 'server-user',
      capabilities: { browse: true, preview: true, download: true, upload: true, manage_links: true, manage_users: true, settings: true, realtime: true },
    } });

    await expect(refresh).resolves.toBe(true);
    await waitFor(() => expect(result.current.capabilities.manage_users).toBe(true));
    expect(result.current.principal.display_name).toBe('server-user');
  });
});
