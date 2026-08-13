// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { type ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { InviteManagement } from './InviteManagement';
import { UserManagement } from './UserManagement';
import { ShareManagement } from './ShareManagement';
import { QueryCacheProvider } from '../../cache/QueryCacheContext';
import { setLang, t } from '../../i18n';

const { showToast, listInvites, createInvite, listShares, deleteShare, listUsers, toggleUser, revokeInvite, useInvalidationMock, authState } = vi.hoisted(() => ({
  showToast: vi.fn(),
  listInvites: vi.fn(),
  createInvite: vi.fn(),
  listShares: vi.fn(),
  deleteShare: vi.fn(),
  listUsers: vi.fn(),
  toggleUser: vi.fn(),
  revokeInvite: vi.fn(),
  useInvalidationMock: vi.fn(),
  authState: { api: {}, identityGeneration: 0 },
}));
vi.mock('../../hooks/useAuth', () => ({
  useAuth: () => authState,
}));

vi.mock('../ui/Toast', () => ({
  useToast: () => ({ showToast }),
}));

vi.mock('../../hooks/useInvalidation', () => ({ useInvalidation: useInvalidationMock }));

vi.mock('../../api/users', () => ({
  createUsersApi: () => ({
    list: listUsers,
    toggleUser,
    listInvites,
    createInvite,
    revokeInvite,
  }),
}));

vi.mock('../../api/shares', () => ({
  createSharesApi: () => ({
    list: listShares,
    delete: deleteShare,
  }),
}));

function renderView(ui: ReactNode) {
  return render(<QueryCacheProvider>{ui}</QueryCacheProvider>);
}

describe('admin management translations', () => {
  beforeEach(() => vi.stubGlobal('confirm', vi.fn(() => true)));
  afterEach(() => vi.unstubAllGlobals());
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    authState.identityGeneration = 0;
  });

  it.each([
    ['en', 'Invite code created!', 'Used', 'Active'],
    ['zh', '邀请码已创建！', '已使用', '有效'],
    ['ja', '招待コードを作成しました！', '使用済み', '有効'],
  ])('renders invite statuses and notification in %s', async (lang, created, used, active) => {
    setLang(lang as 'en' | 'zh' | 'ja');
    listInvites.mockResolvedValue({ invites: [
      { code: 'used-code', created_at: 101, revoked: false, used_by: 'user' },
      { code: 'active-code', created_at: 102, revoked: false, used_by: null },
      { code: 'revoked-code', created_at: 103, revoked: true, used_by: null },
    ] });
    createInvite.mockResolvedValue({ code: 'new-code' });

    renderView(<InviteManagement />);
    expect(await screen.findByText(used)).toBeDefined();
    expect(screen.getByText(active)).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: t('admin.generate_invite') }));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith(created, 'success'));
  });


  it('renders normalized user activity and sends active toggle', async () => {
    setLang('en');
    listUsers.mockResolvedValue({ users: [{ id: 7, username: 'member', role: 'user', active: true, created_at: 100 }] });
    renderView(<UserManagement />);
    expect(await screen.findByText('member')).toBeDefined();
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => expect(toggleUser).toHaveBeenCalledWith(7, false));
    await waitFor(() => expect(screen.getByText(t('admin.enable'))).toBeDefined());
  });

  it('refetches users on invalidation and after toggle uses the canonical response', async () => {
    listUsers.mockResolvedValueOnce({ users: [{ id: 7, username: 'member', role: 'user', active: true, created_at: 100 }] })
      .mockResolvedValueOnce({ users: [{ id: 7, username: 'member', role: 'user', active: false, created_at: 100 }] })
      .mockResolvedValueOnce({ users: [{ id: 7, username: 'canonical-user', role: 'user', active: false, created_at: 100 }] });
    toggleUser.mockResolvedValue(undefined);

    renderView(<UserManagement />);
    await screen.findByText('member');
    expect(useInvalidationMock).toHaveBeenCalledWith(['users'], expect.any(Function));

    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => expect(toggleUser).toHaveBeenCalledWith(7, false));
    await act(async () => {
      await useInvalidationMock.mock.calls[0]![1]!({ domains: ['users'], paths: [] });
    });
    expect(listUsers).toHaveBeenCalledTimes(3);
    expect(screen.getByText(t('admin.disable'))).toBeDefined();
    expect(screen.getByText('canonical-user')).toBeDefined();
  });

  it('ignores an older user response after invalidation refresh', async () => {
    let resolveFirst!: (value: { users: Array<{ id: number; username: string; role: string; active: boolean; created_at: number }> }) => void;
    let resolveSecond!: (value: { users: Array<{ id: number; username: string; role: string; active: boolean; created_at: number }> }) => void;
    listUsers
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve; }));

    renderView(<UserManagement />);
    await act(async () => { useInvalidationMock.mock.calls[0]![1]!({ domains: ['users'], paths: [] }); });
    await act(async () => {
      resolveSecond({ users: [{ id: 8, username: 'newer-canonical-user', role: 'user', active: true, created_at: 999 }] });
    });
    expect(screen.getByText('newer-canonical-user')).toBeDefined();

    await act(async () => {
      resolveFirst({ users: [{ id: 7, username: 'older-user', role: 'user', active: true, created_at: 1 }] });
    });
    expect(screen.queryByText('older-user')).toBeNull();
    expect(screen.getByText('newer-canonical-user')).toBeDefined();
  });

  it('clears the prior identity snapshot when identity generation changes', async () => {
    listUsers.mockResolvedValueOnce({ users: [{ id: 7, username: 'old-identity', role: 'user', active: true, created_at: 1 }] });

    const { rerender } = renderView(<UserManagement />);
    expect(await screen.findByText('old-identity')).toBeDefined();

    authState.identityGeneration = 1;
    rerender(<QueryCacheProvider><UserManagement /></QueryCacheProvider>);

    expect(screen.queryByText('old-identity')).toBeNull();
  });

  it.each([
    ['en', '2/5 downloads'],
    ['zh', '2/5 次下载'],
    ['ja', '2/5 ダウンロード'],
  ])('renders download count in %s', async (lang, downloads) => {
    setLang(lang as 'en' | 'zh' | 'ja');
    listShares.mockResolvedValue({ shares: [{ id: 'share-1', url: '/share/1', paths: [], created_by: 'admin', created_at: 0, allow_preview: true, download_count: 2, max_downloads: 5, has_password: false }] });

    renderView(<ShareManagement />);
    expect(await screen.findByText(downloads)).toBeDefined();
  });
});
