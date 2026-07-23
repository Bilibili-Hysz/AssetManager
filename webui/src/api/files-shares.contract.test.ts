// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { createApiClient } from './client';
import { createFilesApi } from './files';
import { createSharesApi } from './shares';

describe('file and share API contracts', () => {
  it('posts selected download paths through the progress-aware API and saves the Blob response', async () => {
    vi.useFakeTimers();
    const client = createApiClient();
    const postBlobWithProgress = vi.spyOn(client, 'postBlobWithProgress').mockImplementation(async (_path, _body, onProgress) => {
      onProgress({ loaded: 4, total: 8 });
      return new Blob(['zip']);
    });
    const api = createFilesApi(client);
    const createObjectURL = vi.fn().mockReturnValue('blob:assets');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);

    const onProgress = vi.fn();
    await api.batchDownload(['projects/project/report.pdf'], onProgress);

    expect(postBlobWithProgress).toHaveBeenCalledWith('download/batch', { paths: ['projects/project/report.pdf'] }, onProgress);
    expect(onProgress).toHaveBeenCalledWith({ loaded: 4, total: 8 });
    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(click).toHaveBeenCalledOnce();
    vi.runAllTimers();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:assets');
    vi.unstubAllGlobals();
    vi.useRealTimers();
    click.mockRestore();
  });

  it('allows batch downloads without a progress callback', async () => {
    vi.useFakeTimers();
    const client = createApiClient();
    const postBlobWithProgress = vi.spyOn(client, 'postBlobWithProgress').mockResolvedValue(new Blob(['zip']));
    const api = createFilesApi(client);
    const createObjectURL = vi.fn().mockReturnValue('blob:assets');
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);

    await api.batchDownload(['projects/project/report.pdf']);

    expect(postBlobWithProgress).toHaveBeenCalledWith(
      'download/batch',
      { paths: ['projects/project/report.pdf'] },
      expect.any(Function),
    );
    vi.runAllTimers();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    click.mockRestore();
  });

  it('uses native scoped-cookie URLs without escaping path separators', () => {
    const shares = createSharesApi(createApiClient());

    expect(shares.getDownloadUrl('share-123', 'projects/project/report.pdf'))
      .toBe('/api/shares/share-123/download/projects/project/report.pdf');
    expect(shares.getPreviewUrl('share-123', 'projects/project/cover image.png'))
      .toBe('/api/shares/share-123/preview/projects/project/cover%20image.png');
  });
});
