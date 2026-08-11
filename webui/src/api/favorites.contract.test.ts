import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from './client';
import { createFavoritesApi } from './favorites';

function setup() {
  const get = vi.fn();
  const post = vi.fn();
  const client = { get, post } as unknown as ApiClient;
  return { api: createFavoritesApi(client), get, post };
}

describe('favorites API contract', () => {
  it('loads principal-scoped favorites with an abort signal', () => {
    const { api, get } = setup();
    const signal = new AbortController().signal;

    api.list(signal);

    expect(get).toHaveBeenCalledWith('favorites', undefined, signal);
  });

  it('adds a favorite through the SQLite-backed mutation route', () => {
    const { api, post } = setup();
    const signal = new AbortController().signal;

    api.add('collection/art.png', signal);

    expect(post).toHaveBeenCalledWith(
      'favorites',
      { path: 'collection/art.png' },
      signal,
    );
  });

  it('removes a favorite through the compatibility POST route', () => {
    const { api, post } = setup();

    api.remove('collection/art.png');

    expect(post).toHaveBeenCalledWith(
      'favorites/remove',
      { path: 'collection/art.png' },
      undefined,
    );
  });
});
