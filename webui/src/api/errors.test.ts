// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import {
  ApiError,
  UnauthorizedError,
  ForbiddenError,
  ServiceUnavailableError,
  NetworkError,
  isApiError,
  isUnauthorizedError,
  isServiceUnavailableError,
  isNetworkError,
} from './errors';

describe('API error types', () => {
  it('ApiError carries status and body', () => {
    const err = new ApiError('Not found', 404, { detail: 'missing' });
    expect(err).toBeInstanceOf(Error);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.body).toEqual({ detail: 'missing' });
    expect(err.name).toBe('ApiError');
  });

  it('UnauthorizedError has status 401', () => {
    const err = new UnauthorizedError();
    expect(err.status).toBe(401);
    expect(err.name).toBe('UnauthorizedError');
    expect(isApiError(err)).toBe(true);
    expect(isUnauthorizedError(err)).toBe(true);
  });

  it('ForbiddenError has status 403', () => {
    const err = new ForbiddenError();
    expect(err.status).toBe(403);
    expect(err.name).toBe('ForbiddenError');
    expect(isApiError(err)).toBe(true);
  });

  it('ServiceUnavailableError has status 503', () => {
    const err = new ServiceUnavailableError('Starting up', { retry_after: 5 });
    expect(err.status).toBe(503);
    expect(err.body).toEqual({ retry_after: 5 });
    expect(isServiceUnavailableError(err)).toBe(true);
  });

  it('NetworkError is a plain Error', () => {
    const err = new NetworkError();
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe('NetworkError');
    expect(isNetworkError(err)).toBe(true);
    expect(isApiError(err)).toBe(false);
  });

  it('type guards return false for unrelated values', () => {
    expect(isApiError(new Error('plain'))).toBe(false);
    expect(isUnauthorizedError(new Error('plain'))).toBe(false);
    expect(isServiceUnavailableError(new Error('plain'))).toBe(false);
    expect(isNetworkError(new Error('plain'))).toBe(false);
    expect(isApiError(null)).toBe(false);
    expect(isApiError(undefined)).toBe(false);
  });
});
