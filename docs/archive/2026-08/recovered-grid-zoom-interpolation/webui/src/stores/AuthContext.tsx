import { createContext, useContext, useState, useCallback, useEffect, useMemo, type ReactNode } from 'react';
import { createApiClient, type ApiClient } from '../api/client';
import { createAuthApi, type AuthApi } from '../api/auth';
import { createSystemApi, type SystemApi } from '../api/system';
import type { ServerInfo, User } from '../types/api';

export interface AuthState {
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
  setSessionUser: (user?: User | null) => void;
  logout: () => void;
  refreshMe: () => Promise<boolean>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [role, setRole] = useState<AuthState['role']>(null);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [authMode, setAuthMode] = useState<ServerInfo['auth_mode']>('none');
  const [serverInfo, setServerInfo] = useState<ServerInfo | null>(null);
  const handleUnauthorized = useCallback(() => {
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

  const setSessionUser = useCallback((newUser?: User | null) => {
    if (newUser) {
      setRole(newUser.role === 'admin' ? 'admin' : 'user');
      setUser(newUser);
      setPermissions(
        newUser.role === 'admin'
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
    setSessionUser(null);
  }, [authApi, setSessionUser]);

  const refreshMe = useCallback(async () => {
    try {
      const res = await authApi.me();
      setSessionUser(res.user);
      return true;
    } catch {
      setSessionUser(null);
      return false;
    }
  }, [authApi, setSessionUser]);

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
    setSessionUser,
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
