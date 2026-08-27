/**
 * App-wide degradation bus bridging the ApiClient's 429/503 hooks to UI
 * consumers (a global toast) without prop-drilling through every screen.
 *
 * Throttle policy (chosen default, one knob): at most one notification per
 * kind within DEGRADATION_THROTTLE_MS; a newer occurrence refreshes neither
 * timer nor content — quiet for burst storms during real outages.
 */
export type ApiDegradationKind = 'rate-limited' | 'service-unavailable';

export interface ApiDegradationEvent {
  kind: ApiDegradationKind;
  path: string;
  retryAfterSeconds: number | null;
}

type Listener = (event: ApiDegradationEvent) => void;

export const DEGRADATION_THROTTLE_MS = 10_000;

const listeners = new Set<Listener>();
let lastEmittedAt: Partial<Record<ApiDegradationKind, number>> = {};

const clock = () => Date.now();
let currentClock: () => number = clock;

export function resetApiDegradationThrottleForTests(): void {
  listeners.clear();
  lastEmittedAt = {};
  currentClock = clock;
}

export function subscribeApiDegradation(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function emitApiDegradation(
  kind: ApiDegradationKind,
  path: string,
  retryAfterSeconds: number | null = null,
): boolean {
  const now = currentClock();
  const previous = lastEmittedAt[kind] ?? Number.NEGATIVE_INFINITY;
  if (now - previous < DEGRADATION_THROTTLE_MS) return false;
  lastEmittedAt[kind] = now;
  const event: ApiDegradationEvent = { kind, path, retryAfterSeconds };
  listeners.forEach(l => l(event));
  return true;
}
