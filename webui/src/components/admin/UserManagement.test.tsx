// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { UserManagement } from './UserManagement';
import { setLang, t } from '../../i18n';

const { list, toggleUser, useInvalidationMock, authState } = vi.hoisted(() => ({
  list: vi.fn(),
  toggleUser: vi.fn(),
  useInvalidationMock: vi.fn(),
  authState: { api: {}, identityGeneration: 0 },
}));

vi.mock('../../hooks/useAuth', () => ({ useAuth: () => authState }));
vi.mock('../../api/users', () => ({ createUsersApi: () => ({ list, toggleUser }) }));
vi.mock('../../hooks/useInvalidation', () => ({ useInvalidation: useInvalidationMock }));

describe('UserManagement canonical refresh', () => {
  afterEach(cleanup);
  beforeEach(() => {
    setLang('en');
    list.mockReset();
    toggleUser.mockReset();
    useInvalidationMock.mockReset();
    authState.identityGeneration = 0;
  });

  it('renders user rows with role and active status', async () => {
    list.mockResolvedValueOnce({
      users: [
        { id: 1, username: 'alice', role: 'user', active: true },
        { id: 2, username: 'bob', role: 'admin', active: false },
      ],
    });

    render(<UserManagement />);
    await screen.findByText('alice');
    expect(screen.getByText('bob')).toBeDefined();
    expect(screen.getByText('user')).toBeDefined();
    expect(screen.getByText('admin')).toBeDefined();
    expect(screen.getByText(t('admin.enable'))).toBeDefined();
    expect(screen.getByText(t('admin.disable'))).toBeDefined();
  });

  it('shows the empty state when there are no users', async () => {
    list.mockResolvedValueOnce({ users: [] });
    render(<UserManagement />);
    await screen.findByText(t('admin.no_users'));
  });

  it('toggles a user and refetches the canonical list', async () => {
    list
      .mockResolvedValueOnce({
        users: [{ id: 1, username: 'alice', role: 'user', active: true }],
      })
      .mockResolvedValueOnce({
        users: [{ id: 1, username: 'alice', role: 'user', active: false }],
      });
    toggleUser.mockResolvedValue(undefined);

    render(<UserManagement />);
    await screen.findByText('alice');
    fireEvent.click(screen.getAllByRole('button')[0]!);

    await waitFor(() => expect(toggleUser).toHaveBeenCalledWith(1, false));
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
    expect(screen.getByText(t('admin.disable'))).toBeDefined();
  });

  it('refetches on users invalidation', async () => {
    list
      .mockResolvedValueOnce({
        users: [{ id: 1, username: 'initial-user', role: 'user', active: true }],
      })
      .mockResolvedValueOnce({
        users: [{ id: 2, username: 'remote-user', role: 'user', active: true }],
      });

    render(<UserManagement />);
    await screen.findByText('initial-user');
    expect(useInvalidationMock).toHaveBeenCalledWith(['users'], expect.any(Function));

    await act(async () => {
      await useInvalidationMock.mock.calls[0]![1]!();
    });

    expect(list).toHaveBeenCalledTimes(2);
    expect(screen.getByText('remote-user')).toBeDefined();
    expect(screen.queryByText('initial-user')).toBeNull();
  });

  it('ignores an older user response after invalidation refresh', async () => {
    let resolveFirst!: (value: { users: Array<{ id: number; username: string; role: string; active: boolean }> }) => void;
    let resolveSecond!: (value: { users: Array<{ id: number; username: string; role: string; active: boolean }> }) => void;
    list
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve; }));

    render(<UserManagement />);
    await act(async () => { useInvalidationMock.mock.calls[0]![1]!(); });
    await act(async () => {
      resolveSecond({ users: [{ id: 2, username: 'newer-canonical-user', role: 'user', active: true }] });
    });
    expect(screen.getByText('newer-canonical-user')).toBeDefined();

    await act(async () => {
      resolveFirst({ users: [{ id: 1, username: 'older-user', role: 'user', active: true }] });
    });
    expect(screen.queryByText('older-user')).toBeNull();
    expect(screen.getByText('newer-canonical-user')).toBeDefined();
  });

  it('clears the prior identity snapshot when identity generation changes', async () => {
    list
      .mockResolvedValueOnce({
        users: [{ id: 1, username: 'old-identity', role: 'user', active: true }],
      })
      .mockResolvedValueOnce({
        users: [{ id: 2, username: 'new-identity', role: 'user', active: true }],
      });

    const { rerender } = render(<UserManagement />);
    await screen.findByText('old-identity');

    authState.identityGeneration = 1;
    rerender(<UserManagement />);

    await waitFor(() => expect(screen.getByText('new-identity')).toBeDefined());
    expect(screen.queryByText('old-identity')).toBeNull();
  });

  it('keeps the rendered list when the toggle request fails', async () => {
    list.mockResolvedValueOnce({
      users: [{ id: 1, username: 'alice', role: 'user', active: true }],
    });
    toggleUser.mockRejectedValue(new Error('boom'));

    render(<UserManagement />);
    await screen.findByText('alice');
    fireEvent.click(screen.getAllByRole('button')[0]!);

    await waitFor(() => expect(toggleUser).toHaveBeenCalledWith(1, false));
    expect(list).toHaveBeenCalledTimes(1);
    expect(screen.getByText('alice')).toBeDefined();
  });
});
