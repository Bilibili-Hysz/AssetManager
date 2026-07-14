import { createContext, useContext, useState, useCallback, useEffect, useMemo, type ReactNode } from 'react';
import { createApiClient, type ApiClient } from '../api/client';
import { createAuthApi, type AuthApi } from '../api/auth';
import { createSystemApi, type SystemApi } from '../api/system';
import type { ServerInfo, User } from '../types/api';

export interface AuthState {
  token: string | null;
  user: User | null;
  role: 'admin' | 'user' | 'guest' | null;
  permissions: string[];
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
  refreshMe: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [role, setRole] = useState<AuthState['role']>(null);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [authMode, setAuthMode] = useState<ServerInfo['auth_mode']>('none');
  const [serverInfo, setServerInfo] = useState<ServerInfo | null>(null);
  const handleUnauthorized = useCallback(() => {
    setTokenState(null);
    setUser(null);
    setRole('guest');
    setPermissions([]);
  }, []);

  const api = useMemo(
    () => createApiClient({ onUnauthorized: handleUnauthorized }),
    [handleUnauthorized],
  );
  const authApi = useMemo(() => createAuthApi(api), [api]);
  const systemApi = useMemo(() => createSystemApi(api), [api]);

  const setToken = useCallback((newToken: string | null, newUser?: User | null) => {
    setTokenState(newToken);
    if (newToken) {
      setRole(newUser?.role === 'admin' ? 'admin' : 'user');
      setUser(newUser ?? null);
      setPermissions(
        newUser?.role === 'admin'
          ? ['browse', 'download', 'upload', 'manage_links', 'manage_users', 'settings', 'preview']
          : ['browse', 'download', 'preview'],
      );
    } else {
      setUser(null);
      setRole('guest');
      setPermissions(['browse', 'preview']);
    }
  }, []);

  const logout = useCallback(() => {
    authApi.logout().catch(() => {});
    setToken(null);
  }, [authApi, setToken]);

  const refreshMe = useCallback(async () => {
    try {
      const res = await authApi.me();
      setUser(res.user);
      setRole(res.user.role === 'admin' ? 'admin' : 'user');
      setPermissions(
        res.user.role === 'admin'
          ? ['browse', 'download', 'upload', 'manage_links', 'manage_users', 'settings', 'preview']
          : ['browse', 'download', 'preview'],
      );
    } catch {
      setUser(null);
      setRole('guest');
      setPermissions(['browse', 'preview']);
    }
  }, [authApi]);

  useEffect(() => {
    const init = async () => {
      try {
        const info = await systemApi.getInfo();
        setServerInfo(info);
        setAuthMode(info.auth_mode);

        if (!info.auth_enabled) {
          setRole('guest');
          setPermissions(['browse', 'download', 'preview']);
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
    user,
    role,
    permissions,
    isAuthenticated: user !== null || role === 'guest',
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
