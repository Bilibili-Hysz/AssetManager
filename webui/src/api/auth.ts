import type { ApiClient } from './client';
import type { LoginResponse, RegisterResponse, MeResponse, OkResponse } from '../types/api';

export function createAuthApi(api: ApiClient) {
  return {
    login: (username: string, password: string) =>
      api.post<LoginResponse>('auth/login', { username, password }),

    loginWithPassword: (password: string) =>
      api.post<LoginResponse>('auth/login', { password }),

    register: (username: string, password: string, email?: string, invite_code?: string) =>
      api.post<RegisterResponse>('auth/register', { username, password, email, invite_code }),

    verifyKey: (key: string) =>
      api.post<LoginResponse>('auth/verify_key', { key }),

    logout: () =>
      api.post<OkResponse>('auth/logout'),

    me: () =>
      api.get<MeResponse>('auth/me'),
  };
}

export type AuthApi = ReturnType<typeof createAuthApi>;