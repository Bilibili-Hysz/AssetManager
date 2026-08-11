import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from './client';
import { createFilesApi } from './files';

function setup() {
  const get = vi.fn();
  const post = vi.fn();
  const buildUrl = vi.fn();
  const client = { get, post, buildUrl } as unknown as ApiClient;
  return { api: createFilesApi(client), get, post, buildUrl };
}

describe('files API contract (non-download paths)', () => {
  it('builds single-file download URLs through the configured baseUrl', () => {
    const { api, buildUrl } = setup();
    buildUrl.mockReturnValue('/library/api/download/assets%2Fhero.png');
    const open = vi.fn();
    vi.stubGlobal('window', { open });

    try {
      api.download('assets/hero.png');

      expect(buildUrl).toHaveBeenCalledWith('download/assets%2Fhero.png');
      expect(open).toHaveBeenCalledWith('/library/api/download/assets%2Fhero.png', '_blank');
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('list forwards browse query params and AbortSignal', () => {
    const { api, get } = setup();
    const signal = new AbortController().signal;
    api.list({ path: 'projects', sort: 'name', order: 'asc', filter: 'img', search: '猫', summaries: '1' }, signal);
    expect(get).toHaveBeenCalledWith('files', {
      path: 'projects',
      sort: 'name',
      order: 'asc',
      filter: 'img',
      search: '猫',
      summaries: '1',
    }, signal);
  });

  it('list keeps omitted params undefined for the client to drop', () => {
    const { api, get } = setup();
    api.list({});
    expect(get).toHaveBeenCalledWith('files', {
      path: undefined,
      sort: undefined,
      order: undefined,
      filter: undefined,
      search: undefined,
      summaries: undefined,
    }, undefined);
  });

  it('summaries posts parent_path and paths to files/summaries with AbortSignal', () => {
    const { api, post } = setup();
    const signal = new AbortController().signal;
    api.summaries('projects', ['projects/project/assets/a.png'], signal);
    expect(post).toHaveBeenCalledWith('files/summaries', {
      parent_path: 'projects',
      paths: ['projects/project/assets/a.png'],
    }, signal);
  });
});
