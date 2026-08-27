import {
  UnauthorizedError,
  ForbiddenError,
  ServiceUnavailableError,
  ApiError,
  NetworkError,
  type ApiErrorBody,
} from './errors';
import {
  backoffDelay,
  DEFAULT_MAX_RETRIES,
  retryAfterSeconds,
  sleep,
} from '../utils/backoff';

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export interface ApiClientOptions {
  baseUrl?: string;
  /** Fired for every 401 with the failing request path (e.g. 'auth/login'). */
  onUnauthorized?: (path: string) => void;
}

export interface DownloadProgress {
  loaded: number;
  total: number | null;
}

export interface BlobDownload {
  blob: Blob;
  filename?: string;
}

const DEFAULT_TIMEOUT_MS = 30_000;
/** Downloads stream for a while; give them a much longer stall budget. */
const DOWNLOAD_TIMEOUT_MS = 5 * 60_000;

function isAbortError(error: unknown): boolean {
  return typeof error === 'object'
    && error !== null
    && 'name' in error
    && (error as { name?: unknown }).name === 'AbortError';
}

function isTimeoutError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'TimeoutError';
}

/** Read a Retry-After value stored on an ApiError body (rate limit helper). */
function retryAfterFromError(error: unknown): number | null {
  if (!(error instanceof ApiError)) return null;
  const body = error.body as { headers?: Record<string, string>; details?: { retry_after?: unknown } } | undefined;
  const header = body?.headers?.['Retry-After'] ?? body?.headers?.['retry-after'];
  if (header) return retryAfterSeconds(header);
  const detail = body?.details?.retry_after;
  return typeof detail === 'number' ? detail : null;
}

/** Idempotent GET requests may retry network/503/429 failures (S3). */
function isRetryableError(error: unknown): boolean {
  if (error instanceof NetworkError || error instanceof ServiceUnavailableError) return true;
  return error instanceof ApiError && (error.status === 429 || error.status === 503);
}

function toNetworkError(error: unknown): never {
  if (isAbortError(error)) throw error;
  if (error instanceof TypeError) {
    throw new NetworkError('Network error. Please check your connection.');
  }
  if (isTimeoutError(error)) {
    throw new NetworkError('The request timed out. Please try again.');
  }
  throw error;
}

interface TimeoutHandle {
  signal: AbortSignal;
  dispose: () => void;
}

/**
 * Combine an optional caller-provided signal with a hard timeout.
 *
 * The caller signal keeps its existing semantics: cancelling it aborts the
 * request with a plain AbortError. A timeout aborts with a TimeoutError
 * DOMException reason so it can be classified separately from user
 * cancellation. Implemented with AbortController + setTimeout instead of
 * AbortSignal.timeout()/AbortSignal.any(), which require newer browsers than
 * this project's ES2020 target guarantees.
 */
function withTimeout(signal: AbortSignal | undefined, timeoutMs: number): TimeoutHandle {
  const controller = new AbortController();
  const onUserAbort = () => controller.abort();
  if (signal?.aborted) {
    controller.abort();
  } else {
    signal?.addEventListener('abort', onUserAbort, { once: true });
  }
  const timer = window.setTimeout(
    () => controller.abort(new DOMException('Request timed out', 'TimeoutError')),
    timeoutMs,
  );
  return {
    signal: controller.signal,
    dispose() {
      window.clearTimeout(timer);
      signal?.removeEventListener('abort', onUserAbort);
    },
  };
}

/** Build the 429 ApiError, forwarding Retry-After and X-RateLimit-* headers when present. */
async function parseErrorBody(response: Response): Promise<ApiErrorBody | undefined> {
  const raw = await response.text().catch(() => '');
  if (!raw) return undefined;
  try {
    return JSON.parse(raw) as ApiErrorBody;
  } catch {
    return { body: raw.slice(0, 1000) };
  }
}

function errorMessage(body: ApiErrorBody | undefined): string | undefined {
  if (typeof body !== 'object' || body === null || Array.isArray(body)) return undefined;
  const message = (body as { error?: unknown }).error;
  return typeof message === 'string' ? message : undefined;
}

function rateLimitErrorFrom(response: Response, body?: ApiErrorBody): ApiError {
  const info: Record<string, string> = {};
  const retryAfter = response.headers.get('Retry-After');
  if (retryAfter) info['Retry-After'] = retryAfter;
  response.headers.forEach((value, key) => {
    if (/^x-ratelimit-/i.test(key)) info[key] = value;
  });
  const headers = Object.keys(info).length > 0 ? { headers: info } : undefined;
  const mergedBody = body && typeof body === 'object' && !Array.isArray(body)
    ? { ...body, ...(headers ?? {}) }
    : headers;
  const message = errorMessage(body) ?? 'Rate limited';
  return new ApiError(message, 429, mergedBody);
}

/**
 * Parse a 2xx response as JSON. If the server returned a 200 with a non-JSON
 * body (e.g. an HTML error page), surface a structured ApiError carrying the
 * status and the raw payload instead of a bare SyntaxError. Abort and timeout
 * rejections are rethrown untouched so they keep their normal classification.
 */
async function parseJsonBody<T>(response: Response): Promise<T> {
  let raw: string;
  try {
    raw = await response.text();
  } catch (error) {
    if (isAbortError(error) || isTimeoutError(error)) throw error;
    raw = '';
  }
  try {
    return JSON.parse(raw) as T;
  } catch {
    throw new ApiError(
      raw
        ? `Invalid JSON response (HTTP ${response.status})`
        : `Empty response body (HTTP ${response.status})`,
      response.status,
      raw ? { body: raw.slice(0, 1000) } : undefined,
    );
  }
}

export function createApiClient(options: ApiClientOptions = {}) {
  const { baseUrl = '', onUnauthorized } = options;
  const normalizedBaseUrl = baseUrl.replace(/\/+$/, '');

  /**
   * Throw the typed error for a non-OK response. Shared by the JSON, blob
   * and progress request paths so the 401/403/429/503 classification stays
   * in exactly one place.
   */
  async function throwForErrorStatus(
    response: Response,
    path: string,
    onUnauthorized?: (path: string) => void,
  ): Promise<never> {
    const errBody = await parseErrorBody(response);
    if (response.status === 401) {
      onUnauthorized?.(path);
      throw new UnauthorizedError(
        errorMessage(errBody) ?? undefined,
        errBody,
      );
    }
    if (response.status === 403) {
      throw new ForbiddenError(
        errorMessage(errBody) ?? undefined,
        errBody,
      );
    }
    if (response.status === 429) {
      throw rateLimitErrorFrom(response, errBody);
    }
    if (response.status === 503) {
      throw new ServiceUnavailableError(
        errorMessage(errBody) ?? 'Service unavailable',
        errBody,
      );
    }
    throw new ApiError(
      errorMessage(errBody) ?? `HTTP ${response.status}`,
      response.status,
      errBody,
    );
  }

  async function request<T>(
    method: HttpMethod,
    path: string,
    body?: unknown,
    params?: Record<string, string | number | boolean | undefined | null>,
    signal?: AbortSignal,
  ): Promise<T> {
    // Only idempotent GET requests are retried (S3). Writes may have side
    // effects and must surface their first failure immediately.
    const maxAttempts = method === 'GET' ? 1 + DEFAULT_MAX_RETRIES : 1;

    for (let attempt = 0; ; attempt += 1) {
      const url = new URL(`${normalizedBaseUrl}/api/${path}`, window.location.origin);

      if (params) {
        Object.entries(params).forEach(([k, v]) => {
          if (v != null && v !== '') {
            url.searchParams.set(k, String(v));
          }
        });
      }

      const headers: Record<string, string> = {};

      if (body !== undefined) {
        headers['Content-Type'] = 'application/json';
      }

      const timeout = withTimeout(signal, DEFAULT_TIMEOUT_MS);
      try {
        const response = await fetch(url.toString(), {
          method,
          headers,
          body: body !== undefined ? JSON.stringify(body) : undefined,
          signal: timeout.signal,
          credentials: 'same-origin',
        });

        if (!response.ok) {
          await throwForErrorStatus(response, path, onUnauthorized);
        }

        return await parseJsonBody<T>(response);
      } catch (error) {
        if (isAbortError(error) || isTimeoutError(error)) throw error;

        let classified: unknown = error;
        try {
          toNetworkError(error);
        } catch (converted) {
          classified = converted;
        }

        if (attempt + 1 >= maxAttempts) throw classified;
        if (!isRetryableError(classified)) throw classified;

        const retryAfter = retryAfterFromError(classified);
        const waitMs = retryAfter != null
          ? retryAfter * 1000
          : backoffDelay(attempt);
        await sleep(waitMs, signal);
      } finally {
        timeout.dispose();
      }
    }
  }

  function parseContentDispositionFilename(value: string | null): string | undefined {
    if (!value) return undefined;
    const encoded = value.match(/filename\*=(?:UTF-8'')?([^;]+)/i)?.[1];
    if (encoded) {
      try {
        return decodeURIComponent(encoded.trim().replace(/^"|"$/g, ''));
      } catch {
        return encoded.trim().replace(/^"|"$/g, '');
      }
    }
    const plain = value.match(/filename="([^"]+)"|filename=([^;]+)/i);
    return (plain?.[1] ?? plain?.[2])?.trim();
  }

  async function requestBlobResponse(
    method: HttpMethod,
    path: string,
    body?: unknown,
    signal?: AbortSignal,
    extraHeaders?: Record<string, string>,
  ): Promise<Response> {
    const url = new URL(`${normalizedBaseUrl}/api/${path}`, window.location.origin);
    const headers: Record<string, string> = { ...extraHeaders };
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
    }

    const timeout = withTimeout(signal, DOWNLOAD_TIMEOUT_MS);
    try {
      const response = await fetch(url.toString(), {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: timeout.signal,
        credentials: 'same-origin',
      });

      if (!response.ok) {
        await throwForErrorStatus(response, path, onUnauthorized);
      }

      return response;
    } catch (error) {
      toNetworkError(error);
    } finally {
      timeout.dispose();
    }
  }

  async function requestBlob(
    method: HttpMethod,
    path: string,
    body?: unknown,
    signal?: AbortSignal,
    extraHeaders?: Record<string, string>,
  ): Promise<Blob> {
    const response = await requestBlobResponse(method, path, body, signal, extraHeaders);
    return response.blob();
  }

  async function requestBlobWithMetadata(
    method: HttpMethod,
    path: string,
    body?: unknown,
    signal?: AbortSignal,
    extraHeaders?: Record<string, string>,
  ): Promise<BlobDownload> {
    const response = await requestBlobResponse(method, path, body, signal, extraHeaders);
    return {
      blob: await response.blob(),
      filename: parseContentDispositionFilename(response.headers.get('Content-Disposition')),
    };
  }

  async function requestBlobWithProgress(
    method: HttpMethod,
    path: string,
    body: unknown,
    onProgress: (progress: DownloadProgress) => void,
    signal?: AbortSignal,
  ): Promise<Blob> {
    const url = new URL(`${normalizedBaseUrl}/api/${path}`, window.location.origin);

    // The timeout covers both the request and the streaming read, so a
    // stalled download cannot hang forever.
    const timeout = withTimeout(signal, DOWNLOAD_TIMEOUT_MS);
    try {
      const response = await fetch(url.toString(), {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: timeout.signal,
        credentials: 'same-origin',
      });

      if (!response.ok) {
        await throwForErrorStatus(response, path, onUnauthorized);
      }

      const contentLength = Number(response.headers.get('Content-Length'));
      const total = Number.isFinite(contentLength) && contentLength > 0 ? contentLength : null;
      if (!response.body) {
        const blob = await response.blob();
        onProgress({ loaded: blob.size, total });
        return blob;
      }

      const reader = response.body.getReader();
      const chunks: BlobPart[] = [];
      let loaded = 0;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        if (!value) continue;
        loaded += value.byteLength;
        chunks.push(value);
        onProgress({ loaded, total });
      }
      return new Blob(chunks, { type: response.headers.get('Content-Type') ?? 'application/zip' });
    } catch (error) {
      toNetworkError(error);
    } finally {
      timeout.dispose();
    }
  }

  return {
    /** Normalized API base path used to scope client-side caches. */
    scope: normalizedBaseUrl,
    /** Build an API URL honoring the configured baseUrl (useful for native links). */
    buildUrl: (path: string) => `${normalizedBaseUrl}/api/${path}`,
    /** Build a WebSocket URL that uses the same configured base path. */
    buildWebSocketUrl: (path: string) => {
      const url = new URL(`${normalizedBaseUrl}/${path.replace(/^\/+/, '')}`, window.location.origin);
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
      return url.toString();
    },
    get: <T>(path: string, params?: Record<string, string | number | boolean | undefined | null>, signal?: AbortSignal) =>
      request<T>('GET', path, undefined, params, signal),

    post: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
      request<T>('POST', path, body, undefined, signal),

    postBlob: (path: string, body?: unknown, signal?: AbortSignal) =>
      requestBlob('POST', path, body, signal),

    getBlob: (path: string, headers?: Record<string, string>, signal?: AbortSignal) =>
      requestBlob('GET', path, undefined, signal, headers),

    getBlobWithMetadata: (path: string, headers?: Record<string, string>, signal?: AbortSignal) =>
      requestBlobWithMetadata('GET', path, undefined, signal, headers),

    postBlobWithProgress: (path: string, body: unknown, onProgress: (progress: DownloadProgress) => void, signal?: AbortSignal) =>
      requestBlobWithProgress('POST', path, body, onProgress, signal),

    put: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
      request<T>('PUT', path, body, undefined, signal),

    patch: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
      request<T>('PATCH', path, body, undefined, signal),

    delete: <T>(path: string, signal?: AbortSignal) =>
      request<T>('DELETE', path, undefined, undefined, signal),

    deleteWithBody: <T>(path: string, body: unknown, signal?: AbortSignal) =>
      request<T>('DELETE', path, body, undefined, signal),
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
