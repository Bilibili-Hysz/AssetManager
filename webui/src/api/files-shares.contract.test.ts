// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { createApiClient } from './client';
import { createFilesApi } from './files';
import { createSharesApi } from './shares';

describe('file and share API contracts', () => {
  it('posts selected download paths through the progress-aware API and returns the Blob', async () => {
    const client = createApiClient();
    const postBlobWithProgress = vi.spyOn(client, 'postBlobWithProgress').mockImplementation(async (_path, _body, onProgress) => {
      onProgress({ loaded: 4, total: 8 });
      return new Blob(['zip']);
    });
    const api = createFilesApi(client);

    const onProgress = vi.fn();
    const blob = await api.batchDownload(['projects/project/report.pdf'], onProgress);

    expect(postBlobWithProgress).toHaveBeenCalledWith('download/batch', { paths: ['projects/project/report.pdf'] }, onProgress);
    expect(onProgress).toHaveBeenCalledWith({ loaded: 4, total: 8 });
    expect(blob.size).toBe(3);
  });

  it('allows batch downloads without a progress callback', async () => {
    const client = createApiClient();
    const postBlobWithProgress = vi.spyOn(client, 'postBlobWithProgress').mockResolvedValue(new Blob(['zip']));
    const api = createFilesApi(client);

    const blob = await api.batchDownload(['projects/project/report.pdf']);

    expect(postBlobWithProgress).toHaveBeenCalledWith(
      'download/batch',
      { paths: ['projects/project/report.pdf'] },
      expect.any(Function),
    );
    expect(blob.size).toBe(3);
  });

  it('uses native scoped-cookie URLs without escaping path separators', () => {
    const shares = createSharesApi(createApiClient());

    expect(shares.getDownloadUrl('share-123', 'projects/project/report.pdf'))
      .toBe('/api/shares/share-123/download/projects/project/report.pdf');
    expect(shares.getPreviewUrl('share-123', 'projects/project/cover image.png'))
      .toBe('/api/shares/share-123/preview/projects/project/cover%20image.png');
  });
});
