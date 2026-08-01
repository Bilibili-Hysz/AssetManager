// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { OnlineUsers } from './OnlineUsers';

const { getOnlineUsers, useInvalidationMock, authState } = vi.hoisted(() => ({
  getOnlineUsers: vi.fn(),
  useInvalidationMock: vi.fn(),
  authState: { api: {}, identityGeneration: 0 },
}));
let api: object = {};

vi.mock('../../hooks/useAuth', () => ({ useAuth: () => authState }));
vi.mock('../../api/users', () => ({ createUsersApi: () => ({ getOnlineUsers }) }));
vi.mock('../../hooks/useInvalidation', () => ({ useInvalidation: useInvalidationMock }));

describe('OnlineUsers', () => {
  afterEach(cleanup);
  beforeEach(() => {
    getOnlineUsers.mockReset();
    getOnlineUsers.mockResolvedValue({ users: [] });
    useInvalidationMock.mockReset();
    api = {};
    authState.api = api;
    authState.identityGeneration = 0;
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

  it('registers only the users domain', () => {
    render(<OnlineUsers />);
    expect(useInvalidationMock.mock.calls[0]?.[0]).toEqual(['online_users']);
  });

  it('clears the prior identity snapshot when identity generation changes', async () => {
    getOnlineUsers.mockResolvedValueOnce({ users: [{ username: 'old-user', ip: '127.0.0.1' }] });

    const { rerender } = render(<OnlineUsers />);
    expect(await screen.findByText('old-user')).toBeDefined();

    authState.identityGeneration = 1;
    rerender(<OnlineUsers />);

    expect(screen.queryByText('old-user')).toBeNull();
  });
});
