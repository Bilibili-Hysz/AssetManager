import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from './client';
import { createAuthApi } from './auth';

function setup() {
  const get = vi.fn();
  const post = vi.fn();
  const client = { get, post } as unknown as ApiClient;
  return { api: createAuthApi(client), get, post };
}

describe('auth API contract', () => {
  it('login posts username/password to auth/login', () => {
    const { api, post } = setup();
    api.login('alice', 's3cret');
    expect(post).toHaveBeenCalledWith('auth/login', { username: 'alice', password: 's3cret' });
  });

  it('loginWithPassword posts only the password to auth/login', () => {
    const { api, post } = setup();
    api.loginWithPassword('s3cret');
    expect(post).toHaveBeenCalledWith('auth/login', { password: 's3cret' });
  });

  it('register posts optional email and invite_code when provided', () => {
    const { api, post } = setup();
    api.register('alice', 'pw', 'alice@example.com', 'CODE-1');
    expect(post).toHaveBeenCalledWith('auth/register', {
      username: 'alice',
      password: 'pw',
      email: 'alice@example.com',
      invite_code: 'CODE-1',
    });
  });

  it('register keeps email and invite_code keys when omitted', () => {
    const { api, post } = setup();
    api.register('alice', 'pw');
    expect(post).toHaveBeenCalledWith('auth/register', {
      username: 'alice',
      password: 'pw',
      email: undefined,
      invite_code: undefined,
    });
  });

  it('verifyKey posts the raw access key to auth/verify_key', () => {
    const { api, post } = setup();
    api.verifyKey('KEY with spaces/and/slashes');
    expect(post).toHaveBeenCalledWith('auth/verify_key', { key: 'KEY with spaces/and/slashes' });
  });

  it('logout posts to auth/logout without a body', () => {
    const { api, post } = setup();
    api.logout();
    expect(post).toHaveBeenCalledWith('auth/logout');
  });

  it('me gets auth/me and resolves the returned DTO', async () => {
    const { api, get } = setup();
    const sentinel = { principal: { kind: 'guest' } };
    get.mockResolvedValue(sentinel);
    await expect(api.me()).resolves.toBe(sentinel);
    expect(get).toHaveBeenCalledWith('auth/me');
  });
});
