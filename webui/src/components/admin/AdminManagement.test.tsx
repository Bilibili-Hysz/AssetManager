// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { InviteManagement } from './InviteManagement';
import { UserManagement } from './UserManagement';
import { ShareManagement } from './ShareManagement';
import { setLang, t } from '../../i18n';

const showToast = vi.fn();
const listInvites = vi.fn();
const createInvite = vi.fn();
const listShares = vi.fn();
const listUsers = vi.fn();
const toggleUser = vi.fn();

vi.mock('../../hooks/useAuth', () => ({
  useAuth: () => ({ api: {} }),
}));

vi.mock('../ui/Toast', () => ({
  useToast: () => ({ showToast }),
}));

vi.mock('../../api/users', () => ({
  createUsersApi: () => ({
    list: listUsers,
    toggleUser,
    listInvites,
    createInvite,
    revokeInvite: vi.fn(),
  }),
}));

vi.mock('../../api/shares', () => ({
  createSharesApi: () => ({
    list: listShares,
    delete: vi.fn(),
  }),
}));

describe('admin management translations', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
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

    render(<InviteManagement />);
    expect(await screen.findByText(used)).toBeDefined();
    expect(screen.getByText(active)).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: t('admin.generate_invite') }));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith(created, 'success'));
  });

  it('renders normalized user activity and sends active toggle', async () => {
    setLang('en');
    listUsers.mockResolvedValue({ users: [{ id: 7, username: 'member', role: 'user', active: true, created_at: 100 }] });
    render(<UserManagement />);
    expect(await screen.findByText('member')).toBeDefined();
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => expect(toggleUser).toHaveBeenCalledWith(7, false));
    await waitFor(() => expect(screen.getByText(t('admin.enable'))).toBeDefined());
  });

  it.each([
    ['en', '2/5 downloads'],
    ['zh', '2/5 次下载'],
    ['ja', '2/5 ダウンロード'],
  ])('renders download count in %s', async (lang, downloads) => {
    setLang(lang as 'en' | 'zh' | 'ja');
    listShares.mockResolvedValue({ shares: [{ id: 'share-1', url: '/share/1', paths: [], created_by: 'admin', created_at: 0, allow_preview: true, download_count: 2, max_downloads: 5, has_password: false }] });

    render(<ShareManagement />);
    expect(await screen.findByText(downloads)).toBeDefined();
  });
});
