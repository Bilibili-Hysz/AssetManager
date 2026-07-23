// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApiClient } from './client';

function responseWithChunks(chunks: Uint8Array[], contentLength?: string) {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach(chunk => controller.enqueue(chunk));
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: contentLength ? { 'Content-Length': contentLength } : undefined,
  });
}

describe('ApiClient blob download progress', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('uses the configured API base and same-origin credentials with determinate progress', async () => {
    const fetchMock = vi.fn().mockResolvedValue(responseWithChunks([
      new Uint8Array([1, 2]),
      new Uint8Array([3, 4]),
    ], '4'));
    vi.stubGlobal('fetch', fetchMock);
    const progress = vi.fn();

    const blob = await createApiClient({ baseUrl: '/library' })
      .postBlobWithProgress('download/batch', { paths: ['asset.png'] }, progress);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:3000/library/api/download/batch',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ paths: ['asset.png'] }),
        credentials: 'same-origin',
      }),
    );
    expect(progress).toHaveBeenNthCalledWith(1, { loaded: 2, total: 4 });
    expect(progress).toHaveBeenLastCalledWith({ loaded: 4, total: 4 });
    expect(blob.size).toBe(4);
  });

  it('reports an indeterminate transfer when Content-Length is absent', async () => {
    const fetchMock = vi.fn().mockResolvedValue(responseWithChunks([new Uint8Array([1, 2])])) ;
    vi.stubGlobal('fetch', fetchMock);
    const progress = vi.fn();

    await createApiClient().postBlobWithProgress('download/batch', { paths: ['asset.png'] }, progress);

    expect(progress).toHaveBeenCalledWith({ loaded: 2, total: null });
  });

  it('rejects non-2xx blob downloads', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ error: 'Batch download failed' }),
      { status: 500, headers: { 'Content-Type': 'application/json' } },
    )));

    await expect(createApiClient().postBlobWithProgress(
      'download/batch',
      { paths: ['asset.png'] },
      vi.fn(),
    )).rejects.toThrow('Batch download failed');
  });
});
