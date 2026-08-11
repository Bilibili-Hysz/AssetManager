import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from './client';
import { createGalleryApi } from './gallery';

function setup() {
  const get = vi.fn();
  const client = { get } as unknown as ApiClient;
  return { api: createGalleryApi(client), get };
}

describe('gallery API contract', () => {
  it('loads the home projection through the current API client', () => {
    const { api, get } = setup();
    const signal = new AbortController().signal;
    api.home(signal);
    expect(get).toHaveBeenCalledWith('gallery/home', undefined, signal);
  });

  it('passes collection path, sort and kind as query parameters', () => {
    const { api, get } = setup();
    api.collection('集合/项目 1', { sort: 'name', kind: 'artwork' });
    expect(get).toHaveBeenCalledWith('gallery/collection', {
      path: '集合/项目 1',
      sort: 'name',
      kind: 'artwork',
    }, undefined);
  });

  it('resolves a gallery context with an abort signal', () => {
    const { api, get } = setup();
    const signal = new AbortController().signal;
    api.resolve('set/art.png', signal);
    expect(get).toHaveBeenCalledWith('gallery/resolve', { path: 'set/art.png' }, signal);
  });
});
