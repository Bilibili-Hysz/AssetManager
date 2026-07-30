import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useAuthContext } from './AuthContext';
import { WebSocketTransportHost, type WebSocketStatus } from '../hooks/useWebSocket';

export type ProjectionDomain =
  | 'files' | 'tree' | 'home' | 'project_detail' | 'metadata'
  | 'tags' | 'shares' | 'users' | 'stats';

export interface RuntimeCursor { epoch: string; revision: number }
export interface InvalidationEvent extends RuntimeCursor {
  type: 'projection_invalidated';
  domains: ProjectionDomain[];
  paths: string[];
}

export interface RealtimeContextValue extends RuntimeCursor {
  status: WebSocketStatus;
  registerInvalidation: (
    domains: readonly ProjectionDomain[],
    callback: (event: InvalidationEvent | null) => void,
  ) => () => void;
  recover: () => Promise<void>;
}

const RealtimeContext = createContext<RealtimeContextValue | null>(null);
type Registration = { domains: Set<ProjectionDomain>; callback: (event: InvalidationEvent | null) => void };
type PendingRecovery = { generation: number; promise: Promise<void> };
type RecoveryIntent = {
  generation: number;
  epoch: string;
  targetRevision: number;
  needsRecovery: boolean;
  retried: boolean;
};
const projectionDomains = new Set<ProjectionDomain>([
  'files', 'tree', 'home', 'project_detail', 'metadata', 'tags', 'shares', 'users', 'stats',
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
  const { capabilities, principal } = useAuthContext();
  const enabled = capabilities.realtime;
  const identity = `${principal.kind}:${principal.authenticated}:${principal.user_profile?.id ?? ''}:${principal.user_profile?.username ?? principal.display_name}`;
  const [cursor, setCursor] = useState<RuntimeCursor>({ epoch: '', revision: 0 });
  const [status, setStatus] = useState<WebSocketStatus>('disconnected');
  const cursorRef = useRef(cursor);
  const registrationsRef = useRef(new Map<number, Registration>());
  const nextRegistrationRef = useRef(0);
  const recoveryGenerationRef = useRef(0);
  const recoveryRef = useRef<PendingRecovery | null>(null);
  const recoveryIntentRef = useRef<RecoveryIntent | null>(null);
  const mountedRef = useRef(true);
  cursorRef.current = cursor;

  const notify = useCallback((event: InvalidationEvent | null) => {
    for (const registration of registrationsRef.current.values()) {
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
    const recovery = fetch('/api/revision', { credentials: 'same-origin' })
      .then(response => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json() as Promise<unknown>;
      })
      .then(value => {
        if (!isCursor(value)) throw new Error('Invalid runtime cursor');
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
      .catch(() => undefined)
      .finally(() => {
        if (recoveryRef.current?.promise === recovery) recoveryRef.current = null;
      });
    recoveryRef.current = { generation, promise: recovery };
    return recovery;
  }, [notify]);

  const onEvent = useCallback((type: string, data: Record<string, unknown>) => {
    if (type === 'runtime_ready') {
      if (!isCursor(data)) return;
      const current = cursorRef.current;
      if (current.epoch === data.epoch && data.revision <= current.revision) return;
      const epochChanged = Boolean(current.epoch) && current.epoch !== data.epoch;
      recoveryGenerationRef.current += 1;
      recoveryIntentRef.current = null;
      cursorRef.current = data;
      setCursor(data);
      if (epochChanged || (current.epoch === data.epoch && data.revision > current.revision)) void recover(true);
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

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      registrationsRef.current.clear();
    };
  }, []);

  const registerInvalidation = useCallback((domains: readonly ProjectionDomain[], callback: (event: InvalidationEvent | null) => void) => {
    const id = nextRegistrationRef.current++;
    registrationsRef.current.set(id, { domains: new Set(domains), callback });
    return () => registrationsRef.current.delete(id);
  }, []);

  const value = useMemo(() => ({ ...cursor, status, registerInvalidation, recover }), [cursor, status, registerInvalidation, recover]);
  return (
    <WebSocketTransportHost key={identity} enabled={enabled} onEvent={onEvent} onStatus={setStatus}>
      <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>
    </WebSocketTransportHost>
  );
}

export function useRealtimeContext(): RealtimeContextValue {
  const context = useContext(RealtimeContext);
  if (!context) throw new Error('useRealtimeContext must be used within RealtimeProvider');
  return context;
}
