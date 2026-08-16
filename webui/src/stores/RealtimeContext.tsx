import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useAuthContext } from './AuthContext';
import { WebSocketTransportHost, type WebSocketStatus } from '../hooks/useWebSocket';
import type { InvalidationEvent, ProjectionDomain, RuntimeCursor } from '../types/contracts';

// Single-source re-exports: the runtime cursor / invalidation contract lives
// in the generated types/contracts.ts (backend DTO), not in this store.
export type { InvalidationEvent, ProjectionDomain, RuntimeCursor } from '../types/contracts';

export interface RealtimeContextValue extends RuntimeCursor {
  status: WebSocketStatus;
  registerInvalidation: (
    domains: readonly ProjectionDomain[],
    callback: (event: InvalidationEvent | null) => void,
  ) => () => void;
  recover: () => Promise<void>;
  /** True when the last recovery fetch failed or timed out; cleared on the next valid recovery response. */
  recoveryFailed: boolean;
}

const RealtimeContext = createContext<RealtimeContextValue | null>(null);
type Registration = { identity: string; domains: Set<ProjectionDomain>; callback: (event: InvalidationEvent | null) => void };
type PendingRecovery = { generation: number; promise: Promise<void> };
type RecoveryIntent = {
  generation: number;
  epoch: string;
  targetRevision: number;
  needsRecovery: boolean;
  retried: boolean;
};
/** Upper bound for a single recovery fetch; a hung request must not pin recoveryRef forever. */
const RECOVERY_TIMEOUT_MS = 10_000;
const projectionDomains = new Set<ProjectionDomain>([
  'files', 'tree', 'home', 'project_detail', 'metadata', 'favorites', 'tags', 'shares', 'users', 'activity', 'online_users', 'shop', 'orders', 'quota',
]);

function isCursor(value: unknown): value is RuntimeCursor {
  return typeof value === 'object' && value !== null
    && typeof (value as RuntimeCursor).epoch === 'string'
    && Number.isInteger((value as RuntimeCursor).revision)
    && (value as RuntimeCursor).revision >= 0;
}

function asEvent(data: Record<string, unknown>): InvalidationEvent | null {
  if (!isCursor(data) || !Array.isArray(data.domains) || !Array.isArray(data.paths)) return null;
  if (!data.domains.every(domain => typeof domain === 'string' && projectionDomains.has(domain as ProjectionDomain))
    || !data.paths.every(path => typeof path === 'string')) return null;
  return {
    type: 'projection_invalidated', epoch: data.epoch, revision: data.revision,
    domains: data.domains as ProjectionDomain[], paths: data.paths as string[],
  };
}

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const { api, capabilities, principal, identityGeneration } = useAuthContext();
  const enabled = capabilities.realtime;
  const identity = `${identityGeneration}:${principal.kind}:${principal.authenticated}:${principal.user_profile?.id ?? ''}:${principal.user_profile?.username ?? principal.display_name}`;
  const [cursor, setCursor] = useState<RuntimeCursor>({ epoch: '', revision: 0 });
  const [status, setStatus] = useState<WebSocketStatus>('disconnected');
  const [recoveryFailed, setRecoveryFailed] = useState(false);
  const cursorRef = useRef(cursor);
  const registrationsRef = useRef(new Map<number, Registration>());
  const nextRegistrationRef = useRef(0);
  const recoveryGenerationRef = useRef(0);
  const recoveryRef = useRef<PendingRecovery | null>(null);
  const recoveryIntentRef = useRef<RecoveryIntent | null>(null);
  const mountedRef = useRef(true);
  const identityRef = useRef(identity);
  const activeIdentityRef = useRef(identity);
  const initialReadyRecoveryRef = useRef(false);
  activeIdentityRef.current = identity;
  cursorRef.current = cursor;

  const notify = useCallback((event: InvalidationEvent | null) => {
    for (const registration of registrationsRef.current.values()) {
      if (registration.identity !== activeIdentityRef.current) continue;
      if (event === null || event.domains.some(domain => registration.domains.has(domain))) {
        try {
          registration.callback(event);
        } catch {
          // One consumer must not prevent the recovery fan-out from continuing.
        }
      }
    }
  }, []);

  const recover = useCallback((notifyOnEqual = false): Promise<void> => {
    const generation = recoveryGenerationRef.current;
    const expectedCursor = cursorRef.current;
    const pending = recoveryRef.current;
    if (pending?.generation === generation) return pending.promise;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), RECOVERY_TIMEOUT_MS);
    // Recovery goes through the shared API client so the S3 retry/backoff
    // policy applies to the idempotent GET revision probe; the timer still
    // bounds a hung/retrying recovery to RECOVERY_TIMEOUT_MS.
    const recovery = api.get<unknown>('revision', undefined, controller.signal)
      .then(value => {
        if (!isCursor(value)) throw new Error('Invalid runtime cursor');
        return value;
      })
      .then(value => {
        if (!isCursor(value)) throw new Error('Invalid runtime cursor');
        // A valid cursor response means recovery reached the server; clear any
        // previous failure so consumers can observe that the channel recovered.
        if (mountedRef.current) setRecoveryFailed(false);
        const current = cursorRef.current;
        const intent = recoveryIntentRef.current;
        const intentMatches = intent?.generation === generation && intent.epoch === current.epoch;
        const responseLeavesGap = intentMatches
          && intent.needsRecovery
          && current.revision < intent.targetRevision
          && value.epoch === intent.epoch
          && value.revision <= current.revision;
        if (responseLeavesGap && !intent.retried && recoveryRef.current?.promise === recovery) {
          intent.retried = true;
          recoveryRef.current = null;
          void recover();
          return;
        }
        if (value.epoch === current.epoch && value.revision < current.revision) return;
        if (recoveryGenerationRef.current !== generation
          || cursorRef.current.epoch !== expectedCursor.epoch
          || cursorRef.current.revision !== expectedCursor.revision) {
          const cursorAdvancedDuringRecovery = recoveryGenerationRef.current === generation
            && cursorRef.current.epoch === expectedCursor.epoch
            && cursorRef.current.revision !== expectedCursor.revision
            && cursorRef.current.revision < value.revision;
          if (cursorAdvancedDuringRecovery && recoveryRef.current?.promise === recovery) {
            recoveryRef.current = null;
            void recover();
          }
          return;
        }
        if (value.epoch === current.epoch && value.revision === current.revision && !notifyOnEqual) return;
        cursorRef.current = value;
        if (intentMatches && value.epoch === intent?.epoch && value.revision >= intent.targetRevision) {
          intent.needsRecovery = false;
          recoveryIntentRef.current = null;
        }
        if (mountedRef.current) setCursor(value);
        notify(null);
      })
      .catch(error => {
        // Do not swallow recovery failures silently: a hung or failed fetch used
        // to leave recoveryRef pinned to a pending promise, so every later
        // invalidation deduplicated onto the same dead recovery and the page
        // stayed stale. The timeout above bounds the hang, the flag below makes
        // the failure observable, and `.finally` clears recoveryRef so the next
        // gap recovery can re-issue.
        console.error('Realtime recovery failed:', error);
        if (mountedRef.current) setRecoveryFailed(true);
      })
      .finally(() => {
        clearTimeout(timer);
        if (recoveryRef.current?.promise === recovery) recoveryRef.current = null;
      });
    recoveryRef.current = { generation, promise: recovery };
    return recovery;
  }, [api, notify]);

  const onEvent = useCallback((type: string, data: Record<string, unknown>) => {
    if (type === 'runtime_ready') {
      if (!isCursor(data)) return;
      const current = cursorRef.current;
      if (current.epoch === data.epoch && data.revision <= current.revision) return;
      const shouldRecoverAfterIdentityReset = initialReadyRecoveryRef.current;
      initialReadyRecoveryRef.current = false;
      const epochChanged = Boolean(current.epoch) && current.epoch !== data.epoch;
      recoveryGenerationRef.current += 1;
      recoveryIntentRef.current = null;
      cursorRef.current = data;
      setCursor(data);
      if (shouldRecoverAfterIdentityReset || epochChanged
        || (current.epoch === data.epoch && data.revision > current.revision)) void recover(true);
      return;
    }
    if (type !== 'projection_invalidated') return;
    const event = asEvent(data);
    if (!event) return;
    const current = cursorRef.current;
    if (!current.epoch || event.epoch !== current.epoch || event.revision > current.revision + 1) {
      if (event.epoch === current.epoch && event.revision > current.revision + 1) {
        const intent = recoveryIntentRef.current;
        if (!intent || intent.generation !== recoveryGenerationRef.current || intent.epoch !== event.epoch) {
          recoveryIntentRef.current = {
            generation: recoveryGenerationRef.current,
            epoch: event.epoch,
            targetRevision: event.revision,
            needsRecovery: true,
            retried: false,
          };
        } else {
          intent.targetRevision = Math.max(intent.targetRevision, event.revision);
          intent.needsRecovery = true;
        }
      }
      void recover();
      return;
    }
    if (event.revision <= current.revision) return;
    cursorRef.current = event;
    setCursor(event);
    notify(event);
  }, [notify, recover]);

  useLayoutEffect(() => {
    if (identityRef.current === identity) return;
    identityRef.current = identity;
    recoveryGenerationRef.current += 1;
    recoveryRef.current = null;
    recoveryIntentRef.current = null;
    initialReadyRecoveryRef.current = true;
    cursorRef.current = { epoch: '', revision: 0 };
    setCursor({ epoch: '', revision: 0 });
  }, [identity]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      registrationsRef.current.clear();
    };
  }, []);

  const registerInvalidation = useCallback((domains: readonly ProjectionDomain[], callback: (event: InvalidationEvent | null) => void) => {
    const id = nextRegistrationRef.current++;
    registrationsRef.current.set(id, { identity: activeIdentityRef.current, domains: new Set(domains), callback });
    return () => registrationsRef.current.delete(id);
  }, []);

  const value = useMemo(() => ({ ...cursor, status, registerInvalidation, recover, recoveryFailed }), [cursor, status, registerInvalidation, recover, recoveryFailed]);
  return (
    <WebSocketTransportHost key={identity} enabled={enabled} url={api.buildWebSocketUrl('ws')} onEvent={onEvent} onStatus={setStatus}>
      <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>
    </WebSocketTransportHost>
  );
}

export function useRealtimeContext(): RealtimeContextValue {
  const context = useContext(RealtimeContext);
  if (!context) throw new Error('useRealtimeContext must be used within RealtimeProvider');
  return context;
}
