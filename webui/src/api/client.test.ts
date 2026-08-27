// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApiClient } from './client';
import {
  DEGRADATION_THROTTLE_MS,
  emitApiDegradation,
  resetApiDegradationThrottleForTests,
  subscribeApiDegradation,
} from './degradationBus';
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
    const client = createApiClient({ baseUrl: '/library' });
    expect(client.scope).toBe('/library');
    expect(client.buildUrl('download/asset.txt')).toBe('/library/api/download/asset.txt');
  });

  it('normalizes a trailing base slash and builds the matching WebSocket URL', () => {
    const client = createApiClient({ baseUrl: '/library/' });

    expect(client.scope).toBe('/library');
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

  it('retries idempotent GET on network errors with exponential backoff', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('fail-1'))
      .mockRejectedValueOnce(new TypeError('fail-2'))
      .mockResolvedValueOnce(new Response(
        JSON.stringify({ ok: true }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ));
    vi.stubGlobal('fetch', fetchMock);
    vi.useFakeTimers();
    try {
      const promise = createApiClient().get('info');
      await vi.advanceTimersByTimeAsync(500);
      await vi.advanceTimersByTimeAsync(1000);
      await expect(promise).resolves.toEqual({ ok: true });
      expect(fetchMock).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it('retains canonical bodies for auth and rate-limit errors', async () => {
    const body = { error: 'Forbidden', code: 'forbidden', details: { reason: 'guest' } };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(
      JSON.stringify(body),
      { status: 403, headers: { 'Content-Type': 'application/json' } },
    )));

    await expect(createApiClient().post('files')).rejects.toMatchObject({
      status: 403,
      body,
      message: 'Forbidden',
    });

    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(
      JSON.stringify({ error: 'Rate limited', code: 'rate_limited', details: { retry_after: 4 } }),
      { status: 429, headers: { 'Content-Type': 'application/json', 'Retry-After': '4' } },
    )));
    await expect(createApiClient().post('files')).rejects.toMatchObject({
      status: 429,
      body: expect.objectContaining({ code: 'rate_limited', headers: { 'Retry-After': '4' } }),
    });
  });

  it('does not retry non-GET requests', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('fail'));
    vi.stubGlobal('fetch', fetchMock);
    await expect(createApiClient().post('auth/login', {})).rejects.toBeInstanceOf(NetworkError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('respects Retry-After when retrying a 429 GET', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(
        JSON.stringify({ error: 'Rate limited' }),
        { status: 429, headers: { 'Content-Type': 'application/json', 'Retry-After': '2' } },
      ))
      .mockResolvedValueOnce(new Response(
        JSON.stringify({ ok: true }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ));
    vi.stubGlobal('fetch', fetchMock);
    vi.useFakeTimers();
    try {
      const promise = createApiClient().get('info');
      await vi.advanceTimersByTimeAsync(2000);
      await expect(promise).resolves.toEqual({ ok: true });
      expect(fetchMock).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('retries a 503 GET then throws ServiceUnavailableError with the body attached', async () => {
    const body = { error: 'Quota unavailable', code: 'service_unavailable', details: {} };
    // A Response body can be read once, so each attempt needs a fresh one.
    const fetchMock = vi.fn().mockImplementation(() => new Response(
      JSON.stringify(body),
      { status: 503, headers: { 'Content-Type': 'application/json' } },
    ));
    vi.stubGlobal('fetch', fetchMock);
    vi.useFakeTimers();
    try {
      const captured: unknown[] = [];
      const promise = createApiClient()
        .get('quota')
        .catch((error) => {
          captured.push(error);
          throw error;
        })
        .catch((error) => {
          expect(error).toMatchObject({
            name: 'ServiceUnavailableError',
            status: 503,
            body,
            message: 'Quota unavailable',
          });
          return { recovered: true };
        });
      // Advance enough for both backoff sleeps (500ms + 1000ms) to elapse.
      await vi.advanceTimersByTimeAsync(5000);
      await expect(promise).resolves.toEqual({ recovered: true });
      // One initial attempt plus DEFAULT_MAX_RETRIES (2) retries.  Only the
      // terminal rejection surfaces to the outer promise; the first two
      // failures are consumed by the retry loop.
      expect(fetchMock).toHaveBeenCalledTimes(3);
      expect(captured).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('fires onRateLimited and onServiceUnavailable once per classified response', async () => {
    const rateLimited = vi.fn();
    const serviceDown = vi.fn();
    const client = createApiClient({ onRateLimited: rateLimited, onServiceUnavailable: serviceDown });

    const seq = [
      () => new Response(JSON.stringify({ error: 'Rate limited', code: 'rate_limited' }), { status: 429, headers: { 'Content-Type': 'application/json', 'Retry-After': '1' } }),
      () => new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    ];
    let call = 0;
    const sequential = vi.fn().mockImplementation(() => {
      const factory = seq[Math.min(call++, seq.length - 1)];
      return (factory ?? (() => new Response(null, { status: 500 })))();
    });
    vi.stubGlobal('fetch', sequential);
    vi.useFakeTimers();
    try {
      const pending = client.get('info');
      await vi.advanceTimersByTimeAsync(5000);
      await expect(pending).resolves.toEqual({ ok: true });
      expect(rateLimited).toHaveBeenCalledTimes(1);
      expect(rateLimited).toHaveBeenCalledWith('info', 1);
      expect(serviceDown).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }

    // POST 503: no retry, callback fires exactly once.
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => new Response(
      JSON.stringify({ error: 'Quota unavailable', code: 'service_unavailable' }),
      { status: 503, headers: { 'Content-Type': 'application/json' } },
    )));
    await expect(createApiClient({
      onRateLimited: rateLimited,
      onServiceUnavailable: serviceDown,
    }).post('shop/order')).rejects.toMatchObject({ status: 503 });
    expect(serviceDown).toHaveBeenCalledTimes(1);
    expect(serviceDown).toHaveBeenCalledWith('shop/order');
    expect(rateLimited).toHaveBeenCalledTimes(1); // unchanged by the 503
  });

  it('does not retry non-GET requests on 503 and throws ServiceUnavailableError once', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ error: 'Service unavailable' }),
      { status: 503, headers: { 'Content-Type': 'application/json' } },
    ));
    vi.stubGlobal('fetch', fetchMock);
    await expect(createApiClient().post('shop/order')).rejects.toMatchObject({
      name: 'ServiceUnavailableError',
      status: 503,
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
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

describe('api degradation bus throttle', () => {
  afterEach(() => resetApiDegradationThrottleForTests());

  it('emits at most one event per kind within the throttle window', () => {
    const seen: Array<{ kind: string; path: string; retryAfterSeconds: number | null }> = [];
    subscribeApiDegradation(event => seen.push({ ...event }));
    expect(emitApiDegradation('rate-limited', '/a', 3)).toBe(true);
    expect(emitApiDegradation('rate-limited', '/b', null)).toBe(false); // throttled
    expect(emitApiDegradation('service-unavailable', '/c')).toBe(true); // other kind passes
    expect(seen).toEqual([
      { kind: 'rate-limited', path: '/a', retryAfterSeconds: 3 },
      { kind: 'service-unavailable', path: '/c', retryAfterSeconds: null },
    ]);
  });

  it('allows a new notification once the throttle window elapses', () => {
    vi.useFakeTimers();
    try {
      const base = Date.now();
      const nowSpy = vi.spyOn(Date, 'now').mockReturnValue(base);
      const events: string[] = [];
      subscribeApiDegradation(e => events.push(`${e.kind}:${e.path}`));
      emitApiDegradation('rate-limited', '/first');
      nowSpy.mockReturnValue(base + DEGRADATION_THROTTLE_MS + 1);
      emitApiDegradation('rate-limited', '/second');
      expect(events).toEqual(['rate-limited:/first', 'rate-limited:/second']);
      nowSpy.mockRestore();
    } finally {
      vi.useRealTimers();
    }
  });
});
