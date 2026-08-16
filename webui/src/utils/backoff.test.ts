// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { backoffDelay, retryAfterSeconds, sleep } from './backoff';

describe('backoff policy', () => {
  it('parses Retry-After delta seconds and clamps to whole seconds', () => {
    expect(retryAfterSeconds('30')).toBe(30);
    expect(retryAfterSeconds('0.5')).toBe(1);
    expect(retryAfterSeconds(null)).toBeNull();
    expect(retryAfterSeconds('garbage')).toBeNull();
  });

  it('parses Retry-After as an HTTP date', () => {
    const future = new Date(Date.now() + 5_000).toUTCString();
    const seconds = retryAfterSeconds(future);
    expect(seconds).not.toBeNull();
    expect(seconds!).toBeGreaterThanOrEqual(4);
    expect(seconds!).toBeLessThanOrEqual(6);
  });

  it('grows exponentially and caps at the max', () => {
    expect(backoffDelay(0)).toBe(500);
    expect(backoffDelay(1)).toBe(1000);
    expect(backoffDelay(2)).toBe(2000);
    expect(backoffDelay(10)).toBe(15_000);
    expect(backoffDelay(10, 1000, 8000)).toBe(8000);
  });

  it('sleep resolves after the delay', async () => {
    vi.useFakeTimers();
    const promise = sleep(100);
    const marker = vi.fn();
    promise.then(marker);
    await vi.advanceTimersByTimeAsync(100);
    expect(marker).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it('sleep rejects with AbortError when the signal aborts', async () => {
    const controller = new AbortController();
    const promise = sleep(10_000, controller.signal);
    controller.abort();
    await expect(promise).rejects.toMatchObject({ name: 'AbortError' });
  });
});
