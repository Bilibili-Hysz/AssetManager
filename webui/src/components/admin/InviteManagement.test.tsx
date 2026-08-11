// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { InviteManagement } from './InviteManagement';
import { setLang, t } from '../../i18n';

const { listInvites, createInvite, revokeInvite, useInvalidationMock, authState } = vi.hoisted(() => ({
  listInvites: vi.fn(),
  createInvite: vi.fn(),
  revokeInvite: vi.fn(),
  useInvalidationMock: vi.fn(),
  authState: { api: {}, identityGeneration: 0 },
}));

vi.mock('../../hooks/useAuth', () => ({ useAuth: () => authState }));
vi.mock('../../api/users', () => ({ createUsersApi: () => ({ listInvites, createInvite, revokeInvite }) }));
vi.mock('../ui/Toast', () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock('../../hooks/useInvalidation', () => ({ useInvalidation: useInvalidationMock }));

describe('InviteManagement canonical refresh', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });
  beforeEach(() => {
    vi.stubGlobal('confirm', vi.fn(() => true));
    setLang('en');
    listInvites.mockReset();
    createInvite.mockReset();
    revokeInvite.mockReset();
    useInvalidationMock.mockReset();
    authState.identityGeneration = 0;
  });

  it('refetches the canonical invite list after create', async () => {
    listInvites.mockResolvedValueOnce({ invites: [{ code: 'initial-code', created_at: 101, revoked: false, used_by: null }] })
      .mockResolvedValueOnce({ invites: [{ code: 'canonical-code', created_at: 999, revoked: false, used_by: null }] });
    createInvite.mockResolvedValue({ code: 'new-code' });

    render(<InviteManagement />);
    await screen.findByText('initial-code');
    fireEvent.click(screen.getByRole('button', { name: t('admin.generate_invite') }));

    await waitFor(() => expect(createInvite).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(listInvites).toHaveBeenCalledTimes(2));
    expect(screen.getByText('canonical-code')).toBeDefined();
    expect(screen.queryByText('new-code')).toBeNull();
  });

  it('refetches the canonical invite list after revoke', async () => {
    listInvites.mockResolvedValueOnce({ invites: [{ code: 'active-code', created_at: 102, revoked: false, used_by: null }] })
      .mockResolvedValueOnce({ invites: [{ code: 'server-replacement', created_at: 103, revoked: false, used_by: null }] });
    revokeInvite.mockResolvedValue(undefined);

    render(<InviteManagement />);
    const revoke = await screen.findByRole('button', { name: /Revoke active-code/ });
    fireEvent.click(revoke);

    await waitFor(() => expect(revokeInvite).toHaveBeenCalledWith('active-code'));
    await waitFor(() => expect(listInvites).toHaveBeenCalledTimes(2));
    expect(screen.getByText('server-replacement')).toBeDefined();
    expect(screen.queryByText('active-code')).toBeNull();
  });

  it('refetches and replaces the rendered list on users invalidation', async () => {
    listInvites.mockResolvedValueOnce({ invites: [{ code: 'initial-code', created_at: 101, revoked: false, used_by: null }] })
      .mockResolvedValueOnce({ invites: [{ code: 'remote-code', created_at: 202, revoked: false, used_by: null }] });

    render(<InviteManagement />);
    await screen.findByText('initial-code');
    expect(useInvalidationMock).toHaveBeenCalledWith(['users'], expect.any(Function));

    await act(async () => {
      await useInvalidationMock.mock.calls[0]![1]!();
    });

    expect(listInvites).toHaveBeenCalledTimes(2);
    expect(screen.getByText('remote-code')).toBeDefined();
    expect(screen.queryByText('initial-code')).toBeNull();
  });

  it('ignores an older invite response after invalidation refresh', async () => {
    let resolveFirst!: (value: { invites: Array<{ code: string; created_at: number; revoked: boolean; used_by: string | null }> }) => void;
    let resolveSecond!: (value: { invites: Array<{ code: string; created_at: number; revoked: boolean; used_by: string | null }> }) => void;
    listInvites
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve; }));

    render(<InviteManagement />);
    await act(async () => { useInvalidationMock.mock.calls[0]![1]!(); });
    await act(async () => {
      resolveSecond({ invites: [{ code: 'newer-canonical-code', created_at: 999, revoked: false, used_by: null }] });
    });
    expect(screen.getByText('newer-canonical-code')).toBeDefined();

    await act(async () => {
      resolveFirst({ invites: [{ code: 'older-code', created_at: 101, revoked: false, used_by: null }] });
    });
    expect(screen.queryByText('older-code')).toBeNull();
    expect(screen.getByText('newer-canonical-code')).toBeDefined();
  });

  it('clears the prior identity snapshot when identity generation changes', async () => {
    listInvites
      .mockResolvedValueOnce({ invites: [{ code: 'old-identity', created_at: 101, revoked: false, used_by: null }] })
      .mockResolvedValueOnce({ invites: [] });

    const { rerender } = render(<InviteManagement />);
    expect(await screen.findByText('old-identity')).toBeDefined();

    authState.identityGeneration = 1;
    rerender(<InviteManagement />);

    expect(screen.queryByText('old-identity')).toBeNull();
  });
});
