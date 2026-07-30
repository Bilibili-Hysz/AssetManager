import { useEffect, useRef } from 'react';
import { useRealtimeContext, type InvalidationEvent, type ProjectionDomain } from '../stores/RealtimeContext';

export function useInvalidation(
  domains: readonly ProjectionDomain[],
  callback: (event: InvalidationEvent | null) => void,
) {
  const realtime = useRealtimeContext();
  const callbackRef = useRef(callback);
  callbackRef.current = callback;
  const domainsKey = domains.join('|');
  useEffect(() => realtime.registerInvalidation(domains, event => callbackRef.current(event)), [realtime, domainsKey]);
  return realtime;
}
