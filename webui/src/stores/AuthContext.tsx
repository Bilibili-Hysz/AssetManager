import { createContext, useContext, useState, useCallback, useEffect, useMemo, useRef, type ReactNode } from 'react';
import { createApiClient, type ApiClient } from '../api/client';
import { createAuthApi, type AuthApi } from '../api/auth';
import { createSystemApi, type SystemApi } from '../api/system';
import type { Capabilities, ServerInfo, SessionPrincipal, User } from '../types/api';

const emptyCapabilities: Capabilities = {
  browse: false, preview: false, download: false, upload: false,
  manage_links: false, manage_users: false, settings: false, realtime: false,
};

const guestPrincipal: SessionPrincipal = {
  kind: 'guest', authenticated: false, role: 'guest', display_name: 'Guest',
  capabilities: emptyCapabilities,
};

export interface AuthState {
  token: string | null;
  user: User | null;
  role: 'admin' | 'user' | 'guest' | null;
  permissions: string[];
  principal: SessionPrincipal;
  capabilities: Capabilities;
  isAuthenticated: boolean;
  isLoading: boolean;
  authMode: ServerInfo['auth_mode'];
  serverInfo: ServerInfo | null;
}

export interface AuthContextValue extends AuthState {
  api: ApiClient;
  authApi: AuthApi;
  systemApi: SystemApi;
  setToken: (token: string | null, user?: User | null) => void;
  logout: () => void;
  refreshMe: () => Promise<boolean>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(null);
  const [role, setRole] = useState<AuthState['role']>(null);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [principal, setPrincipal] = useState<SessionPrincipal>(guestPrincipal);
  const [isLoading, setIsLoading] = useState(true);
  const [authMode, setAuthMode] = useState<ServerInfo['auth_mode']>('none');
  const [serverInfo, setServerInfo] = useState<ServerInfo | null>(null);
  const generationRef = useRef(0);
  const inFlightMeRef = useRef<{ generation: number; promise: Promise<boolean> } | null>(null);

  const clearGuest = useCallback(() => {
    setTokenState(null);
    setPrincipal(guestPrincipal);
    setRole('guest');
    setPermissions([]);
  }, []);

  const handleUnauthorized = useCallback(() => {
    generationRef.current += 1;
    clearGuest();
  }, [clearGuest]);

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
      setPrincipal(nextPrincipal);
      setRole(nextPrincipal.role);
      setPermissions([]);
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
  }, [authApi, clearGuest]);

  const setToken = useCallback((newToken: string | null, newUser?: User | null) => {
    const generation = ++generationRef.current;
    setTokenState(newToken);
    if (newToken) {
      setRole('guest');
      setPrincipal(newUser ? {
        kind: 'user', authenticated: true, role: 'user',
        display_name: newUser.username, capabilities: emptyCapabilities,
        user_profile: newUser,
      } : { ...guestPrincipal, authenticated: true, kind: 'password', role: 'user', display_name: 'Authenticated' });
      setPermissions([]);
      void refreshMeForGeneration(generation);
    } else {
      clearGuest();
    }
  }, [clearGuest, refreshMeForGeneration]);

  const logout = useCallback(() => {
    authApi.logout().catch(() => {});
    setToken(null);
  }, [authApi, setToken]);

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

        if (!info.auth_enabled) {
          const nextPrincipal = info.principal ?? guestPrincipal;
          setPrincipal(nextPrincipal);
          setRole(nextPrincipal.role);
          setPermissions([]);
          setIsLoading(false);
          return;
        }

        // /auth/me is cookie-authenticated, so this also restores sessions
        // whose HttpOnly credential is intentionally unavailable to JavaScript.
        await refreshMe();
      } catch {
        // Server unreachable — will show error in UI
      } finally {
        setIsLoading(false);
      }
    };
    init();
  }, [refreshMe, systemApi]);

  const value: AuthContextValue = {
    token,
    user: principal.user_profile ?? null,
    role,
    permissions,
    principal,
    capabilities: principal.capabilities,
    isAuthenticated: principal.authenticated,
    isLoading,
    authMode,
    serverInfo,
    api,
    authApi,
    systemApi,
    setToken,
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
