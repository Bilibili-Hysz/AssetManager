import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from './client';
import { createTagsApi } from './tags';

function setup() {
  const get = vi.fn();
  const post = vi.fn();
  const put = vi.fn();
  const delete_ = vi.fn();
  const client = { get, post, put, delete: delete_ } as unknown as ApiClient;
  return { api: createTagsApi(client), get, post, put, delete: delete_ };
}

describe('tags API contract', () => {
  it('list gets tags', () => {
    const { api, get } = setup();
    api.list();
    expect(get).toHaveBeenCalledWith('tags');
  });

  it('add posts tag and file_path to tags', () => {
    const { api, post } = setup();
    api.add('hero', 'projects/project/assets/a.png');
    expect(post).toHaveBeenCalledWith('tags', { tag: 'hero', file_path: 'projects/project/assets/a.png' });
  });

  it('remove posts tag and file_path to tags/remove', () => {
    const { api, post } = setup();
    api.remove('hero', 'projects/project/assets/a.png');
    expect(post).toHaveBeenCalledWith('tags/remove', { tag: 'hero', file_path: 'projects/project/assets/a.png' });
  });

  it('rename PUTs the new name to tags/{encoded old name}', () => {
    const { api, put } = setup();
    api.rename('旧 tag', '新 tag');
    expect(put).toHaveBeenCalledWith('tags/%E6%97%A7%20tag', { new_name: '新 tag' });
  });

  it('delete DELETEs tags/{encoded name}', () => {
    const { api, delete: delete_ } = setup();
    api.delete('旧 tag');
    expect(delete_).toHaveBeenCalledWith('tags/%E6%97%A7%20tag');
  });
});
