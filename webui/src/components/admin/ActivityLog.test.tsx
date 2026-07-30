// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ActivityLogView } from './ActivityLog';

const { getActivity, useInvalidationMock } = vi.hoisted(() => ({
  getActivity: vi.fn(),
  useInvalidationMock: vi.fn(),
}));
let api: object = {};

vi.mock('../../hooks/useAuth', () => ({ useAuth: () => ({ api }) }));
vi.mock('../../api/users', () => ({ createUsersApi: () => ({ getActivity }) }));
vi.mock('../../hooks/useInvalidation', () => ({ useInvalidation: useInvalidationMock }));

describe('ActivityLogView', () => {
  afterEach(cleanup);
  beforeEach(() => {
    getActivity.mockReset();
    useInvalidationMock.mockReset();
    api = {};
  });

  it('ignores an older activity response after invalidation refresh', async () => {
    let resolveFirst!: (value: { activities: Array<{ id: string; username: string; action: string; details: string; timestamp: string }> }) => void;
    let resolveSecond!: (value: { activities: Array<{ id: string; username: string; action: string; details: string; timestamp: string }> }) => void;
    getActivity
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve; }));

    render(<ActivityLogView />);
    await act(async () => { useInvalidationMock.mock.calls[0]![1]!(); });
    await act(async () => { resolveSecond({ activities: [{ id: 'new', username: 'new-user', action: 'updated', details: '', timestamp: '2026-01-01T00:00:00Z' }] }); });
    expect(screen.getByText('new-user')).toBeDefined();

    await act(async () => { resolveFirst({ activities: [{ id: 'old', username: 'old-user', action: 'created', details: '', timestamp: '2025-01-01T00:00:00Z' }] }); });
    expect(screen.queryByText('old-user')).toBeNull();
    expect(screen.getByText('new-user')).toBeDefined();
  });
});
