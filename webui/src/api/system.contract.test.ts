import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from './client';
import { createSystemApi } from './system';

function setup() {
  const get = vi.fn();
  const client = { get } as unknown as ApiClient;
  return { api: createSystemApi(client), get };
}

describe('system API contract', () => {
  it('getInfo gets info and resolves the DTO', async () => {
    const { api, get } = setup();
    const sentinel = { library_name: 'lib', auth_mode: 'none', auth_enabled: false, version: '1' };
    get.mockResolvedValue(sentinel);
    await expect(api.getInfo()).resolves.toBe(sentinel);
    expect(get).toHaveBeenCalledWith('info');
  });

  it('getStats gets stats', () => {
    const { api, get } = setup();
    api.getStats();
    expect(get).toHaveBeenCalledWith('stats');
  });

  it('getQuota gets the optional quota endpoint', () => {
    const { api, get } = setup();
    api.getQuota();
    expect(get).toHaveBeenCalledWith('quota');
  });

  it('getTunnelStatus gets tunnel/status (admin-required route)', () => {
    const { api, get } = setup();
    api.getTunnelStatus();
    expect(get).toHaveBeenCalledWith('tunnel/status');
  });
});
