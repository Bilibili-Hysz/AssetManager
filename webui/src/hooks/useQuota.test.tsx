// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react';
import { type ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryCacheProvider } from '../cache/QueryCacheContext';
import { useQuota } from './useQuota';

const mocks = vi.hoisted(() => ({
  systemApi: { getQuota: vi.fn() },
  showToast: vi.fn(),
}));

vi.mock('./useAuth', () => ({ useAuth: () => ({ systemApi: mocks.systemApi, identityGeneration: 0 }) }));
vi.mock('../components/ui/Toast', () => ({ useToast: () => ({ showToast: mocks.showToast }) }));
vi.mock('./useI18n', () => ({ useI18n: () => ({ t: (key: string, ...args: unknown[]) => `${key}:${args.join(',')}` }) }));
vi.mock('./useInvalidation', () => ({
  useInvalidation: () => ({}),
}));

const quota = (remaining: number | null) => ({
  enabled: true, period: 'daily' as const, limit: 5, used: 5 - (remaining ?? 0), remaining,
  reset_at: null, min_interval_seconds: 0,
});

function makeWrapper() {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryCacheProvider>{children}</QueryCacheProvider>
  );
  return { wrapper };
}

describe('useQuota', () => {
  beforeEach(() => {
    mocks.systemApi.getQuota.mockReset();
    mocks.showToast.mockReset();
  });

  it('loads quota and blocks exhausted downloads while warning at low quota', async () => {
    mocks.systemApi.getQuota.mockResolvedValue(quota(0));
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useQuota(), { wrapper });
    await waitFor(() => expect(result.current.quota?.remaining).toBe(0));
    await expect(result.current.guardDownload()).resolves.toBe(false);
    expect(mocks.showToast).toHaveBeenCalledWith('quota.exhausted:', 'error');
  });

  it('fails open when quota is unavailable', async () => {
    mocks.systemApi.getQuota.mockRejectedValue(new Error('optional endpoint missing'));
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useQuota(), { wrapper });
    await act(async () => { await result.current.refresh(); });
    await expect(result.current.guardDownload()).resolves.toBe(true);
    expect(mocks.showToast).not.toHaveBeenCalled();
  });

  it('does not let an older refresh overwrite a newer generation', async () => {
    let resolve!: (value: ReturnType<typeof quota>) => void;
    mocks.systemApi.getQuota.mockImplementationOnce(() => new Promise<ReturnType<typeof quota>>(r => { resolve = r; }));
    const { wrapper } = makeWrapper();
    const { result, unmount } = renderHook(() => useQuota(), { wrapper });
    unmount();
    resolve(quota(1));
    await Promise.resolve();
    expect(result.current.quota).toBeNull();
  });
});
