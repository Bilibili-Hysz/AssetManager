import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from './client';
import { createUsersApi } from './users';

function setup() {
  const get = vi.fn();
  const post = vi.fn();
  const client = { get, post } as unknown as ApiClient;
  return { api: createUsersApi(client), get, post };
}

describe('users API contract', () => {
  it('list gets users', () => {
    const { api, get } = setup();
    api.list();
    expect(get).toHaveBeenCalledWith('users');
  });

  it('toggleUser posts the active flag to users/{id}/toggle', () => {
    const { api, post } = setup();
    api.toggleUser(7, false);
    expect(post).toHaveBeenCalledWith('users/7/toggle', { active: false });
  });

  it('listInvites gets invites', () => {
    const { api, get } = setup();
    api.listInvites();
    expect(get).toHaveBeenCalledWith('invites');
  });

  it('createInvite posts an empty body to invites', () => {
    const { api, post } = setup();
    api.createInvite();
    expect(post).toHaveBeenCalledWith('invites', {});
  });

  it('revokeInvite encodes the invite code before embedding it in the path', () => {
    const { api, post } = setup();
    api.revokeInvite('ABC 12/x');
    expect(post).toHaveBeenCalledWith('invites/ABC%2012%2Fx/revoke', {});
  });

  it('getActivity and getOnlineUsers get their endpoints', () => {
    const { api, get } = setup();
    api.getActivity();
    api.getOnlineUsers();
    expect(get).toHaveBeenCalledWith('activity');
    expect(get).toHaveBeenCalledWith('online-users');
  });
});
