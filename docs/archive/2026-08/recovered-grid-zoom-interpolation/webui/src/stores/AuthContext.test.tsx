// @vitest-environment jsdom
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, useAuthContext } from './AuthContext';

const getInfo = vi.fn().mockResolvedValue({ auth_enabled: false, auth_mode: 'none' });
const me = vi.fn();

vi.mock('../api/client', () => ({
  createApiClient: () => ({}),
}));

vi.mock('../api/auth', () => ({
  createAuthApi: () => ({ logout: vi.fn(), me }),
}));

vi.mock('../api/system', () => ({
  createSystemApi: () => ({ getInfo, getStats: vi.fn() }),
}));

describe('AuthProvider', () => {
  const user = {
    id: 1,
    username: 'member',
    role: 'user' as const,
    active: true,
    created_at: '2026-07-15T00:00:00Z',
  };

  beforeEach(() => {
    getInfo.mockResolvedValue({ auth_enabled: false, auth_mode: 'none' });
    me.mockReset();
  });

  it('keeps only the public session user after login', async () => {
    const { result } = renderHook(() => useAuthContext(), { wrapper: AuthProvider });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    result.current.setSessionUser(user);

    await waitFor(() => expect(result.current.user).toEqual(user));
    expect(result.current.role).toBe('user');
    expect(result.current.permissions).toEqual(['browse', 'download', 'preview']);
    expect('token' in result.current).toBe(false);
  });

  it('restores the public session from cookie-authenticated authApi.me', async () => {
    getInfo.mockResolvedValue({ auth_enabled: true, auth_mode: 'user' });
    me.mockResolvedValue({ user: { ...user, role: 'admin' } });

    const { result } = renderHook(() => useAuthContext(), { wrapper: AuthProvider });

    await waitFor(() => expect(me).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(result.current.user?.role).toBe('admin'));
    expect(result.current.role).toBe('admin');
    expect(result.current.permissions).toEqual([
      'browse', 'download', 'upload', 'manage_links', 'manage_users', 'settings', 'preview',
    ]);
    expect('token' in result.current).toBe(false);
  });

  it('returns false and exposes guest state when session refresh fails', async () => {
    me.mockRejectedValueOnce(new Error('session unavailable'));
    const { result } = renderHook(() => useAuthContext(), { wrapper: AuthProvider });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await expect(result.current.refreshMe()).resolves.toBe(false);

    await waitFor(() => {
      expect(result.current.role).toBe('guest');
      expect(result.current.user).toBeNull();
    });
  });
});
