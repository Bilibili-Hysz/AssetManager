import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from 'react';
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

function getStoredToken(): string | null {
  try {
    return sessionStorage.getItem('lan_token');
  } catch {
    return null;
  }
}

function storeToken(token: string | null) {
  try {
    if (token) {
      sessionStorage.setItem('lan_token', token);
    } else {
      sessionStorage.removeItem('lan_token');
    }
  } catch {
    // localStorage not available
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(getStoredToken);
  const [user, setUser] = useState<User | null>(null);
  const [role, setRole] = useState<AuthState['role']>(null);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [authMode, setAuthMode] = useState<ServerInfo['auth_mode']>('none');
  const [serverInfo, setServerInfo] = useState<ServerInfo | null>(null);

  const handleUnauthorized = useCallback(() => {
    setTokenState(null);
    storeToken(null);
    setUser(null);
    setRole('guest');
    setPermissions([]);
  }, []);

  const api = createApiClient({
    getToken: () => token,
    onUnauthorized: handleUnauthorized,
  });

  const authApi = createAuthApi(api);
  const systemApi = createSystemApi(api);

  const setToken = useCallback((newToken: string | null, newUser?: User | null) => {
    setTokenState(newToken);
    storeToken(newToken);
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

  // 初始化：获取 server info 并尝试恢复会话
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

        if (token) {
          await refreshMe();
        } else {
          setRole('guest');
          setPermissions(['browse', 'preview']);
        }
      } catch {
        // Server unreachable — will show error in UI
      } finally {
        setIsLoading(false);
      }
    };
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const value: AuthContextValue = {
    token,
    user,
    role,
    permissions,
    isAuthenticated: !!token || role === 'guest',
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