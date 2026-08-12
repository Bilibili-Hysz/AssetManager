/**
 * Pure invalidation matching for the query cache.
 *
 * A query declares which projection domains it depends on and an optional
 * path filter. A projection_invalidated event invalidates the query when
 * its domains intersect the event's domains and (when the event carries
 * paths) one of those paths matches the filter. A null event (reconnect /
 * recovery) invalidates everything, mirroring useInvalidation semantics.
 */
import type { InvalidationEvent, ProjectionDomain } from '../stores/RealtimeContext';

/** Path matches when it equals the tracked path or either is a prefix of the other. */
export function pathRelated(trackedPath: string, eventPath: string): boolean {
  return (
    trackedPath === eventPath
    || eventPath.startsWith(`${trackedPath}/`)
    || trackedPath.startsWith(`${eventPath}/`)
  );
}

export function shouldInvalidate(
  event: InvalidationEvent | null,
  domains: readonly ProjectionDomain[],
  pathFilter: ((paths: string[]) => boolean) | undefined,
): boolean {
  if (event === null) return true;
  if (domains.length === 0) return false;
  const intersects = event.domains.some(domain => domains.includes(domain));
  if (!intersects) return false;
  if (event.paths.length === 0) return true;
  if (pathFilter === undefined) return true;
  return pathFilter(event.paths);
}
