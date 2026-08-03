import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from './client';
import { createSharesApi } from './shares';

function setup() {
  const get = vi.fn();
  const post = vi.fn();
  const delete_ = vi.fn();
  const client = { get, post, delete: delete_ } as unknown as ApiClient;
  return { api: createSharesApi(client), get, post, delete: delete_ };
}

describe('shares API contract', () => {
  it('create posts the full request body to shares', () => {
    const { api, post } = setup();
    const data = { paths: ['projects/project'], expires_in_hours: 24, has_password: true };
    api.create(data);
    expect(post).toHaveBeenCalledWith('shares', data);
  });

  it('list gets shares', () => {
    const { api, get } = setup();
    api.list();
    expect(get).toHaveBeenCalledWith('shares');
  });

  it('delete sends DELETE to shares/{id}', () => {
    const { api, delete: delete_ } = setup();
    api.delete('share-123');
    expect(delete_).toHaveBeenCalledWith('shares/share-123');
  });

  it('getInfo gets shares/{id}/info and resolves the DTO', async () => {
    const { api, get } = setup();
    const sentinel = { share: { id: 'share-123', paths: [], expired: false } };
    get.mockResolvedValue(sentinel);
    await expect(api.getInfo('share-123')).resolves.toBe(sentinel);
    expect(get).toHaveBeenCalledWith('shares/share-123/info');
  });

  it('verifyPassword posts the password to shares/{id}/verify', () => {
    const { api, post } = setup();
    api.verifyPassword('share-123', 'pw');
    expect(post).toHaveBeenCalledWith('shares/share-123/verify', { password: 'pw' });
  });

  it('encodes each path segment but never the separators in download/preview URLs', () => {
    const api = createSharesApi({} as unknown as ApiClient);
    expect(api.getDownloadUrl('share-123', '目录/子 文件.svg'))
      .toBe('/api/shares/share-123/download/%E7%9B%AE%E5%BD%95/%E5%AD%90%20%E6%96%87%E4%BB%B6.svg');
    expect(api.getPreviewUrl('share-123', '目录/子 文件.svg'))
      .toBe('/api/shares/share-123/preview/%E7%9B%AE%E5%BD%95/%E5%AD%90%20%E6%96%87%E4%BB%B6.svg');
  });
});
