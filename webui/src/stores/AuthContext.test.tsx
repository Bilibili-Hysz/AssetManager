// @vitest-environment jsdom
import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AuthProvider, useAuthContext } from './AuthContext';

const getInfo = vi.fn().mockResolvedValue({ auth_enabled: false, auth_mode: 'none' });

vi.mock('../api/client', () => ({
  createApiClient: () => ({}),
}));

vi.mock('../api/auth', () => ({
  createAuthApi: () => ({ logout: vi.fn(), me: vi.fn() }),
}));

vi.mock('../api/system', () => ({
  createSystemApi: () => ({ getInfo, getStats: vi.fn() }),
}));

describe('AuthProvider', () => {
  it('retains the supplied token after login', async () => {
    const { result } = renderHook(() => useAuthContext(), { wrapper: AuthProvider });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    result.current.setToken('session-token', {
      id: 1,
      username: 'member',
      role: 'user',
      active: true,
      created_at: '2026-07-15T00:00:00Z',
    });

    await waitFor(() => expect(result.current.token).toBe('session-token'));
  });
});
