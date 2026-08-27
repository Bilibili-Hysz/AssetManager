// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react';
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
let onUnauthorized: ((path: string) => void) | undefined;

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
  createApiClient: (options: { onUnauthorized?: (path: string) => void }) => {
    onUnauthorized = options.onUnauthorized;
    return {};
  },
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
    onUnauthorized = undefined;
    sessionStorage.clear();
  });

  it('does not expose browser-readable server credentials', async () => {
    me.mockResolvedValueOnce({ principal: {
      ...{
        kind: 'guest', authenticated: false, role: 'guest', display_name: 'Guest',
        capabilities: { browse: false, preview: false, download: false, upload: false, manage_links: false, manage_users: false, settings: false, realtime: false },
      },
    } });
    const { result } = renderHook(() => useAuthContext(), { wrapper: AuthProvider });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect('token' in result.current).toBe(false);
    expect('setToken' in result.current).toBe(false);
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
      expect(result.current.principal.kind).toBe('guest');
    });
  });

  it('increments identity generation and does not restore stale identity after logout', async () => {
    getInfo.mockResolvedValueOnce({ ...info, auth_enabled: false, auth_mode: 'none' });
    const pending = deferred<{ principal: { kind: 'user'; authenticated: true; role: 'user'; display_name: string; capabilities: Capabilities } }>();
    me.mockReturnValueOnce(pending.promise);
    const { result } = renderHook(() => useAuthContext(), { wrapper: AuthProvider });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    me.mockReturnValueOnce(pending.promise);
    const initialGeneration = result.current.identityGeneration;
    result.current.logout();
    pending.resolve({ principal: {
      kind: 'user', authenticated: true, role: 'user', display_name: 'stale',
      capabilities: { browse: true, preview: true, download: true, upload: true, manage_links: false, manage_users: false, settings: false, realtime: true },
    } });

    // The guest principal already has authenticated=false, so waiting only on
    // that flag would pass before logout's state updates flush. Wait for the
    // identity-generation bump instead, which only happens on logout.
    await waitFor(() => {
      expect(result.current.principal.authenticated).toBe(false);
      expect(result.current.identityGeneration).toBeGreaterThan(initialGeneration);
    });
    expect(result.current.principal.kind).toBe('guest');
  });

  it('clears identity-scoped thumbnail storage on logout', async () => {
    me.mockResolvedValueOnce({ principal: {
      kind: 'user', authenticated: true, role: 'user', display_name: 'alice',
      capabilities: { browse: true, preview: true, download: true, upload: false, manage_links: false, manage_users: false, settings: false, realtime: true },
    } });
    sessionStorage.setItem('lan_thumb_cache', JSON.stringify({ 'private.jpg': 'private-encoded' }));

    const { result } = renderHook(() => useAuthContext(), { wrapper: AuthProvider });
    await waitFor(() => expect(result.current.principal.display_name).toBe('alice'));

    act(() => result.current.logout());

    expect(sessionStorage.getItem('lan_thumb_cache')).toBeNull();
  });

  it('allows a new refresh after logout instead of reusing the stale refresh promise', async () => {
    getInfo.mockResolvedValueOnce({ ...info, auth_enabled: false, auth_mode: 'none' });
    const stale = deferred<{ principal: { kind: 'user'; authenticated: true; role: 'user'; display_name: string; capabilities: Capabilities } }>();
    me.mockReturnValueOnce(stale.promise);
    const { result } = renderHook(() => useAuthContext(), { wrapper: AuthProvider });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    const staleRefresh = result.current.refreshMe();
    await waitFor(() => expect(me).toHaveBeenCalledTimes(1));
    result.current.logout();

    me.mockResolvedValueOnce({ principal: {
      kind: 'user', authenticated: true, role: 'user', display_name: 'new-user',
      capabilities: { browse: true, preview: true, download: true, upload: false, manage_links: false, manage_users: false, settings: false, realtime: true },
    } });
    const currentRefresh = result.current.refreshMe();

    await waitFor(() => expect(me).toHaveBeenCalledTimes(2));
    await expect(currentRefresh).resolves.toBe(true);
    await waitFor(() => expect(result.current.principal.display_name).toBe('new-user'));

    stale.resolve({ principal: {
      kind: 'user', authenticated: true, role: 'user', display_name: 'stale-user',
      capabilities: { browse: true, preview: true, download: true, upload: false, manage_links: false, manage_users: false, settings: false, realtime: true },
    } });
    await expect(staleRefresh).resolves.toBe(false);
    expect(result.current.principal.display_name).toBe('new-user');
  });

  it('increments identity generation when an API request becomes unauthorized', async () => {
    me.mockResolvedValueOnce({ principal: {
      kind: 'user', authenticated: true, role: 'user', display_name: 'alice',
      capabilities: { browse: true, preview: true, download: true, upload: false, manage_links: false, manage_users: false, settings: false, realtime: true },
    } });
    const { result } = renderHook(() => useAuthContext(), { wrapper: AuthProvider });
    await waitFor(() => expect(result.current.principal.authenticated).toBe(true));
    const initialGeneration = result.current.identityGeneration;
    sessionStorage.setItem('lan_thumb_cache', JSON.stringify({ 'private.jpg': 'private-encoded' }));

    act(() => onUnauthorized?.('files/hero.png'));

    await waitFor(() => expect(result.current.principal.kind).toBe('guest'));
    expect(result.current.identityGeneration).toBeGreaterThan(initialGeneration);
    expect(sessionStorage.getItem('lan_thumb_cache')).toBeNull();
  });

  it('does not reset identity when an auth endpoint returns 401', async () => {
    me.mockResolvedValueOnce({ principal: {
      kind: 'user', authenticated: true, role: 'user', display_name: 'alice',
      capabilities: { browse: true, preview: true, download: true, upload: false, manage_links: false, manage_users: false, settings: false, realtime: true },
    } });
    const { result } = renderHook(() => useAuthContext(), { wrapper: AuthProvider });
    await waitFor(() => expect(result.current.principal.authenticated).toBe(true));
    const initialGeneration = result.current.identityGeneration;
    sessionStorage.setItem('lan_thumb_cache', JSON.stringify({ 'private.jpg': 'private-encoded' }));

    // A failed login must not log the user out or drop the thumbnail cache.
    act(() => onUnauthorized?.('auth/login'));

    expect(result.current.principal.kind).not.toBe('guest');
    expect(result.current.identityGeneration).toBe(initialGeneration);
    expect(sessionStorage.getItem('lan_thumb_cache')).not.toBeNull();
  });

  it('dedupes refreshMe and uses server capabilities without token state', async () => {
    getInfo.mockResolvedValueOnce({ ...info, auth_enabled: false, auth_mode: 'none' });
    const pending = deferred<{ principal: { kind: 'user'; authenticated: true; role: 'admin'; display_name: string; capabilities: Capabilities } }>();
    me.mockReturnValueOnce(pending.promise);
    const { result } = renderHook(() => useAuthContext(), { wrapper: AuthProvider });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

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
