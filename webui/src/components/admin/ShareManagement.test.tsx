// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ShareManagement } from './ShareManagement';

const { list, deleteShare, useInvalidationMock, authState } = vi.hoisted(() => ({
  list: vi.fn(),
  deleteShare: vi.fn(),
  useInvalidationMock: vi.fn(),
  authState: { api: {}, identityGeneration: 0 },
}));

vi.mock('../../hooks/useAuth', () => ({ useAuth: () => authState }));
vi.mock('../../api/shares', () => ({ createSharesApi: () => ({ list, delete: deleteShare }) }));
vi.mock('../../hooks/useInvalidation', () => ({ useInvalidation: useInvalidationMock }));
vi.mock('../ui/Toast', () => ({ useToast: () => ({ showToast: vi.fn() }) }));

describe('ShareManagement', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });
  beforeEach(() => {
    vi.stubGlobal('confirm', vi.fn(() => true));
    list.mockReset();
    list.mockResolvedValue({ shares: [] });
    deleteShare.mockReset();
    useInvalidationMock.mockReset();
    authState.identityGeneration = 0;
  });

  it('refetches the canonical list after delete', async () => {
    list.mockResolvedValueOnce({ shares: [{ id: 'old', url: '/old', paths: [], created_by: 'admin', created_at: 0, allow_preview: true, download_count: 0, max_downloads: null, has_password: false }] })
      .mockResolvedValueOnce({ shares: [{ id: 'server-share', url: '/server-share', paths: [], created_by: 'admin', created_at: 1, allow_preview: true, download_count: 4, max_downloads: null, has_password: false }] });
    deleteShare.mockResolvedValue(undefined);

    render(<ShareManagement />);
    fireEvent.click(await screen.findByRole('button', { name: /Delete \/old/ }));

    await waitFor(() => expect(deleteShare).toHaveBeenCalledWith('old'));
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
    expect(screen.getByText('/server-share')).toBeDefined();
    expect(screen.queryByText('/old')).toBeNull();
  });

  it('refetches and replaces the rendered list on shares invalidation', async () => {
    list.mockResolvedValueOnce({ shares: [{ id: 'initial', url: '/initial', paths: [], created_by: 'admin', created_at: 0, allow_preview: true, download_count: 0, max_downloads: null, has_password: false }] })
      .mockResolvedValueOnce({ shares: [{ id: 'remote', url: '/remote', paths: [], created_by: 'admin', created_at: 1, allow_preview: true, download_count: 1, max_downloads: null, has_password: false }] });

    render(<ShareManagement />);
    await screen.findByText('/initial');
    expect(useInvalidationMock).toHaveBeenCalledWith(['shares'], expect.any(Function));

    await act(async () => {
      await useInvalidationMock.mock.calls[0]![1]!();
    });

    expect(list).toHaveBeenCalledTimes(2);
    expect(screen.getByText('/remote')).toBeDefined();
    expect(screen.queryByText('/initial')).toBeNull();
  });

  it('ignores an older share response after invalidation refresh', async () => {
    let resolveFirst!: (value: { shares: Array<{ id: string; url: string; paths: string[]; created_by: string; created_at: number; allow_preview: boolean; download_count: number; max_downloads: number | null; has_password: boolean }> }) => void;
    let resolveSecond!: (value: { shares: Array<{ id: string; url: string; paths: string[]; created_by: string; created_at: number; allow_preview: boolean; download_count: number; max_downloads: number | null; has_password: boolean }> }) => void;
    list
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve; }));

    render(<ShareManagement />);
    await act(async () => { useInvalidationMock.mock.calls[0]![1]!(); });
    await act(async () => {
      resolveSecond({ shares: [{ id: 'newer', url: '/newer-canonical-share', paths: [], created_by: 'admin', created_at: 999, allow_preview: true, download_count: 4, max_downloads: null, has_password: false }] });
    });
    expect(screen.getByText('/newer-canonical-share')).toBeDefined();

    await act(async () => {
      resolveFirst({ shares: [{ id: 'older', url: '/older-share', paths: [], created_by: 'admin', created_at: 1, allow_preview: true, download_count: 0, max_downloads: null, has_password: false }] });
    });
    expect(screen.queryByText('/older-share')).toBeNull();
    expect(screen.getByText('/newer-canonical-share')).toBeDefined();
  });

  it('clears the prior identity snapshot when identity generation changes', async () => {
    list.mockResolvedValueOnce({ shares: [{ id: 'old-identity', url: '/old-identity', paths: [], created_by: 'admin', created_at: 0, allow_preview: true, download_count: 0, max_downloads: null, has_password: false }] });

    const { rerender } = render(<ShareManagement />);
    expect(await screen.findByText('/old-identity')).toBeDefined();

    authState.identityGeneration = 1;
    rerender(<ShareManagement />);

    expect(screen.queryByText('/old-identity')).toBeNull();
  });
});
