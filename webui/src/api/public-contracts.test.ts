import contracts from '../../../tests/contracts/lan_public_contracts.json';
import { describe, expect, it } from 'vitest';
import type { InviteResponse, StatsResponse, Tag, TreeItem, UserResponse } from '../types/api';

describe('LAN public DTO contracts', () => {
  it('normalizes users and invites without repository fields', () => {
    expect(contracts.records.user).toMatchObject({ is_active: 1, password_hash: 'secret' });
    expect(contracts.records.invite_used).toMatchObject({ is_active: 1, created_by: 'owner' });
    const user = contracts.responses.user as UserResponse;
    const invite = contracts.responses.invite_used as InviteResponse;

    expect(user).toEqual({ id: 1, username: 'owner', role: 'admin', active: true, created_at: 100 });
    expect(invite).toEqual({ code: 'USED', created_at: 101, used_by: null, revoked: false });
    expect(user).not.toHaveProperty('is_active');
    expect(user).not.toHaveProperty('password_hash');
    expect(invite).not.toHaveProperty('is_active');
    expect(invite).not.toHaveProperty('created_by');
    expect(user.active).toBe(Boolean(contracts.records.user.is_active));
    expect(user.created_at).toBe(Number(contracts.records.user.created_at));
    expect(invite.revoked).toBe(!Boolean(contracts.records.invite_used.is_active));
    expect(invite.used_by).toBeNull();
  });

  it('normalizes tags, tree nodes, and stats', () => {
    const tag = contracts.responses.tag as Tag;
    const tree = contracts.responses.tree as TreeItem;
    const stats = contracts.responses.stats as StatsResponse;

    expect(tag).toEqual({ id: null, name: 'hero', count: 3 });
    expect(tree).toEqual({
      name: 'project', path: 'project', type: 'dir', is_leaf: false,
      children: [
        { name: 'assets', path: 'project/assets', type: 'dir', is_leaf: true, children: [] },
        { name: 'source', path: 'project/source', type: 'dir', is_leaf: true, children: [] },
      ],
    });
    expect(stats).toEqual(contracts.responses.stats);
    expect(tree).not.toHaveProperty('is_file');
    expect(stats).not.toHaveProperty('secret');
  });
});
