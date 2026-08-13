// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryCacheProvider } from '../cache/QueryCacheContext';
import { createQueryCache } from '../cache/queryCache';
import { SellerAuthProvider, useSellerAuth } from './SellerAuthContext';

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  createApiClient: vi.fn(),
}));

vi.mock('../api/client', () => ({
  createApiClient: mocks.createApiClient,
}));
vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ identityGeneration: 0 }),
}));

function wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryCacheProvider>
      <SellerAuthProvider>{children}</SellerAuthProvider>
    </QueryCacheProvider>
  );
}

describe('SellerAuthContext', () => {
  beforeEach(() => {
    mocks.get.mockReset().mockResolvedValue({ enabled: true, authenticated: false });
    mocks.post.mockReset().mockResolvedValue({ ok: true });
    mocks.createApiClient.mockReset().mockReturnValue({ get: mocks.get, post: mocks.post });
  });

  it('creates an independent seller client without an ordinary-user 401 handler', async () => {
    renderHook(() => useSellerAuth(), { wrapper });
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith('auth/seller-status'));
    expect(mocks.createApiClient).toHaveBeenCalledWith({});
  });

  it('logs in and logs out through seller-specific routes', async () => {
    const { result } = renderHook(() => useSellerAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => { await result.current.login('seller-secret'); });
    expect(mocks.post).toHaveBeenCalledWith('auth/seller-login', { password: 'seller-secret' });
    expect(result.current.authenticated).toBe(true);

    await act(async () => { await result.current.logout(); });
    expect(mocks.post).toHaveBeenCalledWith('auth/seller-logout', {});
    expect(result.current.authenticated).toBe(false);
  });

  it('clears the query cache when the seller identity flips', async () => {
    const cache = createQueryCache();
    const wrapperWithCache = ({ children }: { children: React.ReactNode }) => (
      <QueryCacheProvider cache={cache}>
        <SellerAuthProvider>{children}</SellerAuthProvider>
      </QueryCacheProvider>
    );
    const { result } = renderHook(() => useSellerAuth(), { wrapper: wrapperWithCache });
    await waitFor(() => expect(result.current.loading).toBe(false));

    const entry = cache.getEntry(['seller-scoped']);
    entry.snapshot = { status: 'success', data: 'stale', error: undefined, fetchedAt: Date.now() };

    await act(async () => { await result.current.login('seller-secret'); });
    expect(result.current.authenticated).toBe(true);
    expect(cache.getEntry(['seller-scoped']).snapshot.data).toBeUndefined();
  });
});
