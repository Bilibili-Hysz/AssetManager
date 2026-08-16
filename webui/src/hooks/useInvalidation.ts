import { useEffect, useRef } from 'react';
import { useRealtimeContext } from '../stores/RealtimeContext';
import type { InvalidationEvent, ProjectionDomain } from '../types/contracts';

export function useInvalidation(
  domains: readonly ProjectionDomain[],
  callback: (event: InvalidationEvent | null) => void,
) {
  const realtime = useRealtimeContext();
  const callbackRef = useRef(callback);
  callbackRef.current = callback;
  const domainsKey = domains.join('|');
  // registerInvalidation is a stable reference (useCallback([]) in
  // RealtimeProvider), so depending on the whole context value would re-register
  // on every cursor revision advance. We only re-register when the domains
  // change or the runtime environment changes: identity switches and reconnects
  // always surface as a status/epoch change in RealtimeProvider, while plain
  // invalidation events only bump the revision.
  useEffect(
    () => {
      // Queries with no projection domains never match an event; skip the
      // registration (the hook itself stays unconditional).
      if (domains.length === 0) return;
      return realtime.registerInvalidation(domains, event => callbackRef.current(event));
    },
    [realtime.registerInvalidation, realtime.epoch, realtime.status, domainsKey],
  );
  return realtime;
}
