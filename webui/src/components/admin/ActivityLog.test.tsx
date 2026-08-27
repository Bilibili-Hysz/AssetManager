// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ActivityLogView } from './ActivityLog';
import { QueryCacheProvider } from '../../cache/QueryCacheContext';

const { getActivity, useInvalidationMock, authState } = vi.hoisted(() => ({
  getActivity: vi.fn(),
  useInvalidationMock: vi.fn(),
  authState: { api: {}, identityGeneration: 0 },
}));
let api: object = {};

vi.mock('../../hooks/useAuth', () => ({ useAuth: () => authState }));
vi.mock('../../api/users', () => ({ createUsersApi: () => ({ getActivity }) }));
vi.mock('../../hooks/useInvalidation', () => ({ useInvalidation: useInvalidationMock }));

const renderView = () => render(<QueryCacheProvider><ActivityLogView /></QueryCacheProvider>);

describe('ActivityLogView', () => {
  afterEach(cleanup);
  beforeEach(() => {
    getActivity.mockReset();
    getActivity.mockResolvedValue({ activities: [] });
    useInvalidationMock.mockReset();
    api = {};
    authState.api = api;
    authState.identityGeneration = 0;
  });

  it('ignores an older activity response after invalidation refresh', async () => {
    let resolveFirst!: (value: { activities: Array<{ id: string; username: string; action: string; details: string; timestamp: number }> }) => void;
    let resolveSecond!: (value: { activities: Array<{ id: string; username: string; action: string; details: string; timestamp: number }> }) => void;
    getActivity
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve; }));

    renderView();
    await act(async () => { useInvalidationMock.mock.calls[0]![1]!({ domains: ['activity'], paths: [] }); });
    await act(async () => { resolveSecond({ activities: [{ id: 'new', username: 'new-user', action: 'updated', details: '', timestamp: 1767225600 }] }); });
    expect(screen.getByText('new-user')).toBeDefined();

    await act(async () => { resolveFirst({ activities: [{ id: 'old', username: 'old-user', action: 'created', details: '', timestamp: 1735689600 }] }); });
    expect(screen.queryByText('old-user')).toBeNull();
    expect(screen.getByText('new-user')).toBeDefined();
  });

  it('formats Unix epoch seconds as the correct calendar year', async () => {
    getActivity.mockResolvedValueOnce({
      activities: [{ id: 'known', username: 'alice', action: 'login', details: '', timestamp: 1767225600 }],
    });

    renderView();

    expect(await screen.findByText('alice')).toBeDefined();
    expect(screen.getByText(value => value.includes('2026'))).toBeDefined();
  });

  it('registers only the users domain', () => {
    renderView();
    expect(useInvalidationMock.mock.calls[0]?.[0]).toEqual(['activity']);
  });

  it('clears the prior identity snapshot when identity generation changes', async () => {
    getActivity.mockResolvedValueOnce({ activities: [{ id: 'old', username: 'old-user', action: 'created', details: '', timestamp: 1735689600 }] });

    const { rerender } = renderView();
    expect(await screen.findByText('old-user')).toBeDefined();

    authState.identityGeneration = 1;
    rerender(<QueryCacheProvider><ActivityLogView /></QueryCacheProvider>);

    expect(screen.queryByText('old-user')).toBeNull();
  });
});
