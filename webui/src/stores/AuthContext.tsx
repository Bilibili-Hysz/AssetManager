import { createContext, useContext, useState, useCallback, useEffect, useMemo, useRef, type ReactNode } from 'react';
import { createApiClient, type ApiClient } from '../api/client';
import { createAuthApi, type AuthApi } from '../api/auth';
import { createSystemApi, type SystemApi } from '../api/system';
import { isServiceUnavailableError, isNetworkError } from '../api/errors';
import type { Capabilities, ServerInfo, SessionPrincipal } from '../types/api';

const THUMBNAIL_CACHE_STORAGE_KEY = 'lan_thumb_cache';

const emptyCapabilities: Capabilities = {
  browse: false, preview: false, download: false, upload: false,
  manage_links: false, manage_users: false, settings: false, realtime: false,
};

const guestPrincipal: SessionPrincipal = {
  kind: 'guest', authenticated: false, role: 'guest', display_name: 'Guest',
  capabilities: emptyCapabilities,
};

function principalIdentity(principal: SessionPrincipal): string {
  return `${principal.kind}:${principal.authenticated}:${principal.user_profile?.id ?? ''}:${principal.user_profile?.username ?? principal.display_name}`;
}

export interface AuthState {
  user: SessionPrincipal['user_profile'] | null;
  role: 'admin' | 'user' | 'guest' | null;
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
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [role, setRole] = useState<AuthState['role']>(null);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [principal, setPrincipal] = useState<SessionPrincipal>(guestPrincipal);
  const [isLoading, setIsLoading] = useState(true);
  const [serviceUnavailable, setServiceUnavailable] = useState(false);
  const [authMode, setAuthMode] = useState<ServerInfo['auth_mode']>('none');
  const [serverInfo, setServerInfo] = useState<ServerInfo | null>(null);
  const generationRef = useRef(0);
  const [identityGeneration, setIdentityGeneration] = useState(0);
  const principalRef = useRef(guestPrincipal);
  const inFlightMeRef = useRef<{ generation: number; promise: Promise<boolean> } | null>(null);

  const applyPrincipal = useCallback((nextPrincipal: SessionPrincipal, forceGeneration = false) => {
    if (forceGeneration || principalIdentity(principalRef.current) !== principalIdentity(nextPrincipal)) {
      setIdentityGeneration(value => value + 1);
    }
    principalRef.current = nextPrincipal;
    setPrincipal(nextPrincipal);
    setRole(nextPrincipal.role);
    setPermissions([]);
  }, []);

  const clearGuest = useCallback((forceGeneration = false) => {
    applyPrincipal(guestPrincipal, forceGeneration);
    setRole('guest');
  }, [applyPrincipal]);

  const clearIdentityStorage = useCallback(() => {
    try {
      sessionStorage.removeItem(THUMBNAIL_CACHE_STORAGE_KEY);
    } catch { /* ignore storage failures */ }
  }, []);

  const handleUnauthorized = useCallback(() => {
    generationRef.current += 1;
    inFlightMeRef.current = null;
    clearIdentityStorage();
    clearGuest(true);
  }, [clearGuest, clearIdentityStorage]);

  const api = useMemo(
    () => createApiClient({ onUnauthorized: handleUnauthorized }),
    [handleUnauthorized],
  );
  const authApi = useMemo(() => createAuthApi(api), [api]);
  const systemApi = useMemo(() => createSystemApi(api), [api]);

  const refreshMeForGeneration = useCallback((generation: number) => {
    const current = inFlightMeRef.current;
    if (current?.generation === generation) return current.promise;

    const promise = authApi.me().then(res => {
      if (generation !== generationRef.current) return true;
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

  useEffect(() => {
    const init = async () => {
      try {
        const info = await systemApi.getInfo();
        setServerInfo(info);
        setAuthMode(info.auth_mode);
        setServiceUnavailable(false);

        if (!info.auth_enabled) {
          const nextPrincipal = info.principal ?? guestPrincipal;
          applyPrincipal(nextPrincipal);
          setIsLoading(false);
          return;
        }

        // /auth/me is cookie-authenticated, so this also restores sessions
        // whose HttpOnly credential is intentionally unavailable to JavaScript.
        await refreshMe();
      } catch (err) {
        if (isServiceUnavailableError(err) || isNetworkError(err)) {
          setServiceUnavailable(true);
        }
        // Server unreachable — will show error in UI
      } finally {
        setIsLoading(false);
      }
    };
    init();
  }, [refreshMe, systemApi]);

  const value: AuthContextValue = {
    user: principal.user_profile ?? null,
    role,
    permissions,
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
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuthContext(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuthContext must be used within AuthProvider');
  return ctx;
}
