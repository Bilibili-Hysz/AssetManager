import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from './client';
import { createThumbnailsApi } from './thumbnails';

function setup() {
  const post = vi.fn();
  const client = { post } as unknown as ApiClient;
  return { api: createThumbnailsApi(client), post };
}

describe('thumbnails API contract', () => {
  it('batch posts paths with the default size', () => {
    const { api, post } = setup();
    api.batch(['projects/project/cover.png']);
    expect(post).toHaveBeenCalledWith('thumbnails/batch', { paths: ['projects/project/cover.png'], size: 512 });
  });

  it('batch forwards a custom size', () => {
    const { api, post } = setup();
    api.batch(['a.png', 'b.png'], 128);
    expect(post).toHaveBeenCalledWith('thumbnails/batch', { paths: ['a.png', 'b.png'], size: 128 });
  });
});
