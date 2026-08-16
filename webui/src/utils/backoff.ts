/**
 * Shared retry/backoff policy (S3).
 *
 * Single source for exponential backoff and Retry-After parsing used by both
 * the API client and the realtime recovery path, so web/client retry behavior
 * cannot drift apart.
 */

export const DEFAULT_BACKOFF_BASE_MS = 500;
export const DEFAULT_BACKOFF_MAX_MS = 15_000;
export const DEFAULT_MAX_RETRIES = 2;

/** Delay for `ms` milliseconds, aborting cleanly when `signal` fires. */
export function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('The operation was aborted.', 'AbortError'));
      return;
    }
    const onAbort = () => {
      window.clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
      reject(new DOMException('The operation was aborted.', 'AbortError'));
    };
    const timer = window.setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

/**
 * Parse a `Retry-After` header value into whole seconds.
 *
 * Accepts both the delta-seconds form ("30") and the HTTP-date form
 * ("Wed, 21 Oct 2015 07:28:00 GMT"). Returns null when absent/unparseable.
 */
export function retryAfterSeconds(value: string | null | undefined): number | null {
  if (!value) return null;
  const trimmed = value.trim();
  const seconds = Number(trimmed);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.ceil(seconds);
  const dateMs = Date.parse(trimmed);
  if (Number.isFinite(dateMs)) return Math.max(0, Math.ceil((dateMs - Date.now()) / 1000));
  return null;
}

/** Exponential backoff for the given 0-based attempt, capped at `maxMs`. */
export function backoffDelay(
  attempt: number,
  baseMs = DEFAULT_BACKOFF_BASE_MS,
  maxMs = DEFAULT_BACKOFF_MAX_MS,
): number {
  if (attempt < 0) attempt = 0;
  return Math.min(maxMs, baseMs * 2 ** attempt);
}
