// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { createFilesApi } from './files';
import { createSharesApi } from './shares';

describe('file and share API contracts', () => {
  it('posts selected download paths as JSON and saves the Blob response', async () => {
    vi.useFakeTimers();
    const postBlob = vi.fn().mockResolvedValue(new Blob(['zip']));
    const api = createFilesApi({ postBlob } as never);
    const createObjectURL = vi.fn().mockReturnValue('blob:assets');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);

    await api.batchDownload(['projects/project/report.pdf']);

    expect(postBlob).toHaveBeenCalledWith('download/batch', { paths: ['projects/project/report.pdf'] });
    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(click).toHaveBeenCalledOnce();
    vi.runAllTimers();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:assets');
    vi.unstubAllGlobals();
    vi.useRealTimers();
    click.mockRestore();
  });

  it('uses native scoped-cookie URLs without escaping path separators', () => {
    const shares = createSharesApi({} as never);

    expect(shares.getDownloadUrl('share-123', 'projects/project/report.pdf'))
      .toBe('/api/shares/share-123/download/projects/project/report.pdf');
    expect(shares.getPreviewUrl('share-123', 'projects/project/cover image.png'))
      .toBe('/api/shares/share-123/preview/projects/project/cover%20image.png');
  });
});
