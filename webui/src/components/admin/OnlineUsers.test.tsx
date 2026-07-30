// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { OnlineUsers } from './OnlineUsers';

const { getOnlineUsers, useInvalidationMock } = vi.hoisted(() => ({
  getOnlineUsers: vi.fn(),
  useInvalidationMock: vi.fn(),
}));
let api: object = {};

vi.mock('../../hooks/useAuth', () => ({ useAuth: () => ({ api }) }));
vi.mock('../../api/users', () => ({ createUsersApi: () => ({ getOnlineUsers }) }));
vi.mock('../../hooks/useInvalidation', () => ({ useInvalidation: useInvalidationMock }));

describe('OnlineUsers', () => {
  afterEach(cleanup);
  beforeEach(() => {
    getOnlineUsers.mockReset();
    useInvalidationMock.mockReset();
    api = {};
  });

  it('ignores an older users response after invalidation refresh', async () => {
    let resolveFirst!: (value: { users: Array<{ username: string; ip: string }> }) => void;
    let resolveSecond!: (value: { users: Array<{ username: string; ip: string }> }) => void;
    getOnlineUsers
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve; }));

    render(<OnlineUsers />);
    await act(async () => { useInvalidationMock.mock.calls[0]![1]!(); });
    await act(async () => { resolveSecond({ users: [{ username: 'new-user', ip: '127.0.0.2' }] }); });
    expect(screen.getByText('new-user')).toBeDefined();

    await act(async () => { resolveFirst({ users: [{ username: 'old-user', ip: '127.0.0.1' }] }); });
    expect(screen.queryByText('old-user')).toBeNull();
    expect(screen.getByText('new-user')).toBeDefined();
  });
});
