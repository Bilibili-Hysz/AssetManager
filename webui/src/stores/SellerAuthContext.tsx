import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { createApiClient, type ApiClient } from '../api/client';
import { isNetworkError, isServiceUnavailableError } from '../api/errors';

export interface SellerStatusResponse {
  enabled: boolean;
  authenticated: boolean;
}

interface SellerAuthState {
  /** Dedicated client intentionally has no global 401 identity-reset handler. */
  sellerApi: ApiClient;
  enabled: boolean;
  authenticated: boolean;
  loading: boolean;
  /** Server answered 503 or the network is unreachable: the seller feature may still be enabled, we just cannot tell. */
  serviceUnavailable: boolean;
  login: (password: string, username?: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Retry entry: re-runs the status probe; safe to call repeatedly. */
  refresh: () => Promise<void>;
}

const SellerAuthContext = createContext<SellerAuthState | null>(null);

export function SellerAuthProvider({ children }: { children: ReactNode }) {
  const sellerApi = useMemo(() => createApiClient({}), []);
  const [enabled, setEnabled] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [serviceUnavailable, setServiceUnavailable] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const status = await sellerApi.get<SellerStatusResponse>('auth/seller-status');
      setServiceUnavailable(false);
      setEnabled(status.enabled);
      setAuthenticated(status.authenticated);
    } catch (err) {
      // 503 / network failures must not be conflated with "seller feature not
      // enabled": the server may still have the feature, we just could not
      // reach it. enabled=false semantics are preserved for safety.
      setEnabled(false);
      setAuthenticated(false);
      if (isServiceUnavailableError(err) || isNetworkError(err)) {
        setServiceUnavailable(true);
      } else {
        setServiceUnavailable(false);
        console.error('Seller status check failed:', err);
      }
    } finally {
      setLoading(false);
    }
  }, [sellerApi]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(async (password: string, username?: string) => {
    const body = username ? { username, password } : { password };
    const result = await sellerApi.post<{ ok: boolean }>('auth/seller-login', body);
    if (result.ok) {
      setEnabled(true);
      setAuthenticated(true);
    }
  }, [sellerApi]);

  const logout = useCallback(async () => {
    try {
      await sellerApi.post('auth/seller-logout', {});
    } catch {
      // The seller cookie may already be gone; clear local seller state anyway.
    }
    setAuthenticated(false);
  }, [sellerApi]);

  const value = useMemo(
    () => ({ sellerApi, enabled, authenticated, loading, serviceUnavailable, login, logout, refresh }),
    [sellerApi, enabled, authenticated, loading, serviceUnavailable, login, logout, refresh],
  );

  return <SellerAuthContext.Provider value={value}>{children}</SellerAuthContext.Provider>;
}

export function useSellerAuth(): SellerAuthState {
  const ctx = useContext(SellerAuthContext);
  if (!ctx) throw new Error('useSellerAuth must be used within SellerAuthProvider');
  return ctx;
}
