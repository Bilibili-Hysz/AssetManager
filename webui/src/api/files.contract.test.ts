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
  it('downloads single files through the blob path and returns data', async () => {
    const { buildUrl } = setup();
    const getBlobWithMetadata = vi.fn().mockResolvedValue({
      blob: new Blob(['data'], { type: 'application/octet-stream' }),
      filename: 'hero.png',
    });

    const apiWithBlob = createFilesApi({ getBlobWithMetadata } as unknown as ApiClient);
    const result = await apiWithBlob.download('assets/hero.png');

    expect(getBlobWithMetadata).toHaveBeenCalledWith('download/assets%2Fhero.png', undefined, undefined);
    expect(result.filename).toBe('hero.png');
    expect(result.blob.size).toBe(4);
    // The api layer must not touch the DOM; triggerBlobDownload lives in
    // src/utils/download.ts and owns the save-dialog side effects.
    expect(buildUrl).not.toHaveBeenCalled();
  });

  it('rejects with the classified API error when the download fails', async () => {
    const {} = setup();
    const getBlobWithMetadata = vi.fn().mockRejectedValue(new Error('Forbidden'));
    const apiWithBlob = createFilesApi({ getBlobWithMetadata } as unknown as ApiClient);

    await expect(apiWithBlob.download('assets/hero.png')).rejects.toThrow('Forbidden');
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
