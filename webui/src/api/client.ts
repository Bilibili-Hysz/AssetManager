import { UnauthorizedError, ForbiddenError, ServiceUnavailableError, ApiError, NetworkError } from './errors';

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE';

export interface ApiClientOptions {
  baseUrl?: string;
  onUnauthorized?: () => void;
}

export interface DownloadProgress {
  loaded: number;
  total: number | null;
}

export function createApiClient(options: ApiClientOptions = {}) {
  const { baseUrl = '', onUnauthorized } = options;

  async function request<T>(
    method: HttpMethod,
    path: string,
    body?: unknown,
    params?: Record<string, string | number | boolean | undefined | null>,
    signal?: AbortSignal,
  ): Promise<T> {
    const url = new URL(`${baseUrl}/api/${path}`, window.location.origin);

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

    const response = await fetch(url.toString(), {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
      credentials: 'same-origin',
    });

    if (response.status === 401) {
      onUnauthorized?.();
      throw new UnauthorizedError();
    }

    if (response.status === 403) {
      throw new ForbiddenError();
    }

    if (response.status === 429) {
      throw new ApiError('Rate limited', 429);
    }

    if (response.status === 503) {
      const errBody = await response.json().catch(() => ({}));
      throw new ServiceUnavailableError(
        (errBody as { error?: string }).error ?? 'Service unavailable',
        errBody,
      );
    }

    if (!response.ok) {
      const errBody = await response.json().catch(() => ({}));
      throw new ApiError(
        (errBody as { error?: string }).error ?? `HTTP ${response.status}`,
        response.status,
        errBody,
      );
    }

    return response.json() as Promise<T>;
  }

  async function requestBlob(
    method: HttpMethod,
    path: string,
    body?: unknown,
    signal?: AbortSignal,
  ): Promise<Blob> {
    const url = new URL(`${baseUrl}/api/${path}`, window.location.origin);
    const headers: Record<string, string> = {};
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
    }

    let response: Response;
    try {
      response = await fetch(url.toString(), {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal,
        credentials: 'same-origin',
      });
    } catch (err) {
      if (err instanceof TypeError) {
        throw new NetworkError('Network error. Please check your connection.');
      }
      throw err;
    }

    if (response.status === 401) {
      onUnauthorized?.();
      throw new UnauthorizedError();
    }
    if (response.status === 403) {
      throw new ForbiddenError();
    }
    if (response.status === 429) {
      throw new ApiError('Rate limited', 429);
    }
    if (response.status === 503) {
      const errBody = await response.json().catch(() => ({}));
      throw new ServiceUnavailableError(
        (errBody as { error?: string }).error ?? 'Service unavailable',
        errBody,
      );
    }
    if (!response.ok) {
      const errBody = await response.json().catch(() => ({}));
      throw new ApiError(
        (errBody as { error?: string }).error ?? `HTTP ${response.status}`,
        response.status,
        errBody,
      );
    }

    return response.blob();
  }

  async function requestBlobWithProgress(
    method: HttpMethod,
    path: string,
    body: unknown,
    onProgress: (progress: DownloadProgress) => void,
    signal?: AbortSignal,
  ): Promise<Blob> {
    const url = new URL(`${baseUrl}/api/${path}`, window.location.origin);
    let response: Response;
    try {
      response = await fetch(url.toString(), {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal,
        credentials: 'same-origin',
      });
    } catch (err) {
      if (err instanceof TypeError) {
        throw new NetworkError('Network error. Please check your connection.');
      }
      throw err;
    }

    if (response.status === 401) {
      onUnauthorized?.();
      throw new UnauthorizedError();
    }
    if (response.status === 403) throw new ForbiddenError();
    if (response.status === 429) throw new ApiError('Rate limited', 429);
    if (response.status === 503) {
      const errBody = await response.json().catch(() => ({}));
      throw new ServiceUnavailableError(
        (errBody as { error?: string }).error ?? 'Service unavailable',
        errBody,
      );
    }
    if (!response.ok) {
      const errBody = await response.json().catch(() => ({}));
      throw new ApiError(
        (errBody as { error?: string }).error ?? `HTTP ${response.status}`,
        response.status,
        errBody,
      );
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
  }

  return {
    get: <T>(path: string, params?: Record<string, string | number | boolean | undefined | null>, signal?: AbortSignal) =>
      request<T>('GET', path, undefined, params, signal),

    post: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
      request<T>('POST', path, body, undefined, signal),

    postBlob: (path: string, body?: unknown, signal?: AbortSignal) =>
      requestBlob('POST', path, body, signal),

    postBlobWithProgress: (path: string, body: unknown, onProgress: (progress: DownloadProgress) => void, signal?: AbortSignal) =>
      requestBlobWithProgress('POST', path, body, onProgress, signal),

    put: <T>(path: string, body?: unknown) =>
      request<T>('PUT', path, body),

    delete: <T>(path: string) =>
      request<T>('DELETE', path),
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
