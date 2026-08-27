import type { ErrorResponse } from '../types/api';

export type ApiErrorBody =
  | ErrorResponse
  | { error: string; [key: string]: unknown }
  | { body: string }
  | { headers: Record<string, string> }
  | Record<string, unknown>;

export function isErrorResponse(value: unknown): value is ErrorResponse {
  return typeof value === 'object'
    && value !== null
    && typeof (value as { error?: unknown }).error === 'string'
    && typeof (value as { code?: unknown }).code === 'string'
    && typeof (value as { details?: unknown }).details === 'object'
    && (value as { details?: unknown }).details !== null;
}

/** Structured API error with HTTP status and category. */
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly body?: ApiErrorBody,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export class UnauthorizedError extends ApiError {
  constructor(message = 'Unauthorized', body?: ApiErrorBody) {
    super(message, 401, body);
    this.name = 'UnauthorizedError';
  }
}

export class ForbiddenError extends ApiError {
  constructor(message = 'Forbidden', body?: ApiErrorBody) {
    super(message, 403, body);
    this.name = 'ForbiddenError';
  }
}

export class ServiceUnavailableError extends ApiError {
  constructor(message = 'Service unavailable', body?: ApiErrorBody) {
    super(message, 503, body);
    this.name = 'ServiceUnavailableError';
  }
}

/** Network-level error (fetch failed, no connectivity, CORS, etc.) */
export class NetworkError extends Error {
  constructor(message = 'Network error') {
    super(message);
    this.name = 'NetworkError';
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

export function isUnauthorizedError(value: unknown): value is UnauthorizedError {
  return value instanceof UnauthorizedError;
}

export function isServiceUnavailableError(value: unknown): value is ServiceUnavailableError {
  return value instanceof ServiceUnavailableError;
}

export function isNetworkError(value: unknown): value is NetworkError {
  return value instanceof NetworkError;
}
