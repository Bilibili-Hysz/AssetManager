import { createContext, useContext, useState, useCallback, useEffect, useMemo, useRef, type ReactNode } from 'react';
import { createApiClient, type ApiClient } from '../api/client';
import { emitApiDegradation } from '../api/degradationBus';
import { createAuthApi, type AuthApi } from '../api/auth';
import { createSystemApi, type SystemApi } from '../api/system';
import { isServiceUnavailableError, isNetworkError } from '../api/errors';
import type { Capabilities, ServerInfo, SessionPrincipal } from '../types/api';

const THUMBNAIL_CACHE_STORAGE_PREFIX = 'lan_thumb_cache:';
const LEGACY_THUMBNAIL_CACHE_STORAGE_KEY = 'lan_thumb_cache';

function clearThumbnailCacheStorage(): void {
  try {
    const keys: string[] = [];
    for (let index = 0; index < sessionStorage.length; index += 1) {
      const key = sessionStorage.key(index);
      if (key?.startsWith(THUMBNAIL_CACHE_STORAGE_PREFIX)) keys.push(key);
    }
    for (const key of keys) sessionStorage.removeItem(key);
    sessionStorage.removeItem(LEGACY_THUMBNAIL_CACHE_STORAGE_KEY);
  } catch { /* ignore storage failures */ }
}

/**
 * A failed login/registration attempt answers 401 through the same client as
 * a session-expired request elsewhere; resetting identity on those would log
 * the user out (and drop the thumbnail cache) for a mere bad password. The
 * client passes the failing path, so only non-auth endpoints trigger the
 * full identity reset.
 */
const AUTH_401_PATHS = new Set(['auth/login', 'auth/register', 'auth/verify_key']);

const emptyCapabilities: Capabilities = {
  browse: false, preview: false, download: false, upload: false,
  manage_links: false, manage_users: false, settings: false, realtime: false,
};

const guestPrincipal: SessionPrincipal = {
  kind: 'guest', authenticated: false, role: 'guest', display_name: 'Guest',
  capabilities: emptyCapabilities,
};

/**
 * B7: `permissions` was a dead state slot — every principal application reset
 * it to `[]` and nothing in webui/src ever wrote or read it (only
 * AuthContext.test.tsx asserts it equals `[]`, and the principal fixtures there
 * have enabled capabilities, so deriving from capabilities would break that
 * assertion). The state is removed; the field is kept only for test/type
 * compatibility and stays an empty array.
 */
const emptyPermissions: string[] = [];

function principalIdentity(principal: SessionPrincipal): string {
  return `${principal.kind}:${principal.authenticated}:${principal.user_profile?.id ?? ''}:${principal.user_profile?.username ?? principal.display_name}`;
}

function thumbnailNamespace(
  api: ApiClient,
  serverInfo: ServerInfo | null,
  principal: SessionPrincipal,
  fallbackNamespace: string,
): string {
  const origin = typeof window === 'undefined' ? '' : window.location.origin;
  const server = serverInfo?.thumbnail_cache_namespace || fallbackNamespace;
  return [origin, api.scope, server, principalIdentity(principal)].join('|');
}

export interface AuthState {
  user: SessionPrincipal['user_profile'] | null;
  role: 'admin' | 'user' | 'guest' | null;
  /** Always empty (dead field retained for compatibility); see emptyPermissions. */
  permissions: string[];
  principal: SessionPrincipal;
  capabilities: Capabilities;
  isAuthenticated: boolean;
  identityGeneration: number;
  isLoading: boolean;
  /** Server returned 503 or network is unreachable. */
  serviceUnavailable: boolean;
  authMode: ServerInfo['auth_mode'];
  serverInfo: ServerInfo | null;
}

export interface AuthContextValue extends AuthState {
  api: ApiClient;
  authApi: AuthApi;
  systemApi: SystemApi;
  logout: () => void;
  refreshMe: () => Promise<boolean>;
  retryConnect: () => Promise<boolean>;
  thumbnailCacheNamespace: string;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [role, setRole] = useState<AuthState['role']>(null);
  const [principal, setPrincipal] = useState<SessionPrincipal>(guestPrincipal);
  const [isLoading, setIsLoading] = useState(true);
  const [serviceUnavailable, setServiceUnavailable] = useState(false);
  const [authMode, setAuthMode] = useState<ServerInfo['auth_mode']>('none');
  const [serverInfo, setServerInfo] = useState<ServerInfo | null>(null);
  const generationRef = useRef(0);
  const [identityGeneration, setIdentityGeneration] = useState(0);
  const principalRef = useRef(guestPrincipal);
  const fallbackNamespaceRef = useRef(`page-${Math.random().toString(36).slice(2)}`);
  const inFlightMeRef = useRef<{ generation: number; promise: Promise<boolean> } | null>(null);

  const applyPrincipal = useCallback((nextPrincipal: SessionPrincipal, forceGeneration = false) => {
    if (forceGeneration || principalIdentity(principalRef.current) !== principalIdentity(nextPrincipal)) {
      setIdentityGeneration(value => value + 1);
    }
    principalRef.current = nextPrincipal;
    setPrincipal(nextPrincipal);
    setRole(nextPrincipal.role);
  }, []);

  const clearGuest = useCallback((forceGeneration = false) => {
    applyPrincipal(guestPrincipal, forceGeneration);
    setRole('guest');
  }, [applyPrincipal]);

  const clearIdentityStorage = useCallback(() => {
    clearThumbnailCacheStorage();
  }, []);

  const handleUnauthorized = useCallback((path: string) => {
    if (AUTH_401_PATHS.has(path)) return;
    generationRef.current += 1;
    inFlightMeRef.current = null;
    clearIdentityStorage();
    clearGuest(true);
  }, [clearGuest, clearIdentityStorage]);

  const api = useMemo(
    () => createApiClient({
      onUnauthorized: handleUnauthorized,
      onRateLimited: (path, retryAfterSeconds) =>
        emitApiDegradation('rate-limited', path, retryAfterSeconds),
      onServiceUnavailable: path => emitApiDegradation('service-unavailable', path),
    }),
    [handleUnauthorized],
  );
  const authApi = useMemo(() => createAuthApi(api), [api]);
  const systemApi = useMemo(() => createSystemApi(api), [api]);

  const refreshMeForGeneration = useCallback((generation: number) => {
    const current = inFlightMeRef.current;
    if (current?.generation === generation) return current.promise;

    const promise = authApi.me().then(res => {
      if (generation !== generationRef.current) return false;
      const nextPrincipal = res.principal ?? (res.user ? {
        kind: 'user' as const, authenticated: true, role: res.user.role,
        display_name: res.user.username, capabilities: emptyCapabilities,
        user_profile: res.user,
      } : guestPrincipal);
      applyPrincipal(nextPrincipal);
      return true;
    }).catch(() => {
      if (generation !== generationRef.current) return false;
      clearGuest();
      return false;
    }).finally(() => {
      if (inFlightMeRef.current?.promise === promise) inFlightMeRef.current = null;
    });
    inFlightMeRef.current = { generation, promise };
    return promise;
  }, [applyPrincipal, authApi, clearGuest]);

  const logout = useCallback(() => {
    authApi.logout().catch(() => {});
    generationRef.current += 1;
    inFlightMeRef.current = null;
    clearIdentityStorage();
    clearGuest(true);
  }, [authApi, clearGuest, clearIdentityStorage]);

  const refreshMe = useCallback(async () => {
    const current = inFlightMeRef.current;
    if (current) return current.promise;
    const generation = ++generationRef.current;
    return refreshMeForGeneration(generation);
  }, [refreshMeForGeneration]);

  const connect = useCallback(async () => {
    const info = await systemApi.getInfo();
    setServerInfo(info);
    setAuthMode(info.auth_mode);
    setServiceUnavailable(false);

    if (!info.auth_enabled) {
      applyPrincipal(info.principal ?? guestPrincipal);
      return;
    }

    // /auth/me is cookie-authenticated, so this also restores sessions
    // whose HttpOnly credential is intentionally unavailable to JavaScript.
    await refreshMe();
  }, [applyPrincipal, refreshMe, systemApi]);

  const retryConnect = useCallback(async (): Promise<boolean> => {
    try {
      await connect();
      return true;
    } catch (err) {
      if (isServiceUnavailableError(err) || isNetworkError(err)) {
        setServiceUnavailable(true);
      } else {
        // B6 (degraded): LandingPage only consumes `serviceUnavailable`
        // (503/network), so a generic connect failure (e.g. 500 on
        // /api/system/info) used to be silently swallowed into a guest session.
        // A visible `connectError` state needs a UI consumer outside this file;
        // until then surface the failure for diagnostics and keep behavior
        // unchanged (guest fallback, no serviceUnavailable flag).
        console.error('Auth connect failed:', err);
      }
      return false;
    }
  }, [connect]);

  useEffect(() => {
    const init = async () => {
      try {
        await connect();
      } catch (err) {
        if (isServiceUnavailableError(err) || isNetworkError(err)) {
          setServiceUnavailable(true);
        } else {
          // B6 (degraded): see retryConnect — no UI consumer for generic
          // connect errors yet; log instead of silently degrading to guest.
          console.error('Auth connect failed during initialization:', err);
        }
      } finally {
        setIsLoading(false);
      }
    };
    init();
  }, [connect]);

  const thumbnailCacheNamespace = useMemo(
    () => thumbnailNamespace(api, serverInfo, principal, fallbackNamespaceRef.current),
    [api, serverInfo, principal],
  );

  const value: AuthContextValue = useMemo(
    () => ({
      user: principal.user_profile ?? null,
      role,
      permissions: emptyPermissions,
      principal,
      capabilities: principal.capabilities,
      isAuthenticated: principal.authenticated,
      identityGeneration,
      isLoading,
      serviceUnavailable,
      authMode,
      serverInfo,
      api,
      authApi,
      systemApi,
      logout,
      refreshMe,
      retryConnect,
      thumbnailCacheNamespace,
    }),
    // B5: previously the value object was rebuilt every render, churning every
    // consumer. All callbacks below are useCallback-stable (api/authApi/systemApi
    // are useMemo'd), so the memo recomputes only on real state changes.
    [role, principal, identityGeneration, isLoading, serviceUnavailable, authMode, serverInfo,
      api, authApi, systemApi, logout, refreshMe, retryConnect, thumbnailCacheNamespace],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuthContext(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuthContext must be used within AuthProvider');
  return ctx;
}
