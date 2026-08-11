// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApiClient } from './client';
import { NetworkError } from './errors';

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

describe('ApiClient request contracts', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('builds native API URLs with the configured base path', () => {
    expect(createApiClient({ baseUrl: '/library' }).buildUrl('download/asset.txt')).toBe('/library/api/download/asset.txt');
  });

  it('normalizes a trailing base slash and builds the matching WebSocket URL', () => {
    const client = createApiClient({ baseUrl: '/library/' });

    expect(client.buildUrl('revision')).toBe('/library/api/revision');
    expect(client.buildWebSocketUrl('/ws')).toBe('ws://localhost:3000/library/ws');
  });
  it('maps fetch TypeError failures to NetworkError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(createApiClient().get('info')).rejects.toBeInstanceOf(NetworkError);
  });

  it('preserves AbortError for cancelled requests', async () => {
    const abortError = new DOMException('The operation was aborted.', 'AbortError');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(abortError));
    await expect(createApiClient().get('info', undefined, new AbortController().signal)).rejects.toBe(abortError);
  });
});

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

  it('sends custom headers for cookie-authenticated GET blob downloads', async () => {
    const fetchMock = vi.fn().mockResolvedValue(responseWithChunks([new Uint8Array([1, 2, 3])]));
    vi.stubGlobal('fetch', fetchMock);

    const blob = await createApiClient({ baseUrl: '/library' }).getBlob(
      'shop/order/7/delivery',
      { 'Idempotency-Key': 'delivery-attempt-1' },
    );

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:3000/library/api/shop/order/7/delivery',
      expect.objectContaining({
        method: 'GET',
        headers: { 'Idempotency-Key': 'delivery-attempt-1' },
        credentials: 'same-origin',
      }),
    );
    expect(blob.size).toBe(3);
  });

  it('preserves the server-suggested filename for metadata blob downloads', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      new Blob(['zip'], { type: 'application/zip' }),
      { status: 200, headers: { 'Content-Disposition': 'attachment; filename="asset-pack.zip"' } },
    )));

    const result = await createApiClient().getBlobWithMetadata('shop/order/7/delivery');

    expect(result.filename).toBe('asset-pack.zip');
    expect(result.blob.size).toBeGreaterThan(0);
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
