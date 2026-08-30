import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from './client';
import { createCollectionsApi } from './collections';

function setup() {
  const get = vi.fn();
  const post = vi.fn();
  const patch = vi.fn();
  const delete_ = vi.fn();
  const deleteWithBody = vi.fn();
  const client = {
    get, post, patch, delete: delete_, deleteWithBody,
  } as unknown as ApiClient;
  return { api: createCollectionsApi(client), get, post, patch, delete: delete_, deleteWithBody };
}

describe('collections API contract', () => {
  it('list gets collections', () => {
    const { api, get } = setup();
    api.list();
    expect(get).toHaveBeenCalledWith('collections');
  });

  it('create posts a manual collection by default', () => {
    const { api, post } = setup();
    api.create('hero');
    expect(post).toHaveBeenCalledWith('collections', { name: 'hero', kind: 'manual' });
  });

  it('create posts a smart collection with its query', () => {
    const { api, post } = setup();
    api.create('pngs', 'smart', { extensions: ['.png'] });
    expect(post).toHaveBeenCalledWith('collections', {
      name: 'pngs', kind: 'smart', query: { extensions: ['.png'] },
    });
  });

  it('update PATCHes name/query onto collections/{id}', () => {
    const { api, patch } = setup();
    api.update(7, { name: 'hero2', query: { tags: ['a'] } });
    expect(patch).toHaveBeenCalledWith('collections/7', { name: 'hero2', query: { tags: ['a'] } });
  });

  it('delete DELETEs collections/{id}', () => {
    const { api, delete: delete_ } = setup();
    api.delete(7);
    expect(delete_).toHaveBeenCalledWith('collections/7');
  });

  it('members gets the member list', () => {
    const { api, get } = setup();
    api.members(3);
    expect(get).toHaveBeenCalledWith('collections/3/members');
  });

  it('addMembers posts the path list', () => {
    const { api, post } = setup();
    api.addMembers(3, ['a.png', 'b/c.jpg']);
    expect(post).toHaveBeenCalledWith('collections/3/members', { paths: ['a.png', 'b/c.jpg'] });
  });

  it('removeMembers DELETEs with the path list body', () => {
    const { api, deleteWithBody } = setup();
    api.removeMembers(3, ['a.png']);
    expect(deleteWithBody).toHaveBeenCalledWith('collections/3/members', { paths: ['a.png'] });
  });

  it('evaluate gets the paginated evaluation endpoint', () => {
    const { api, get } = setup();
    api.evaluate(9, 50, 10);
    expect(get).toHaveBeenCalledWith('collections/9/evaluate?limit=50&offset=10');
  });
});
