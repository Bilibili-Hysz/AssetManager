import type { ApiClient } from './client';
import type { UsersResponse, InvitesResponse, ActivityResponse, OnlineUsersResponse, OkResponse } from '../types/api';

export function createUsersApi(api: ApiClient) {
  return {
    list: () => api.get<UsersResponse>('users'),
    toggleUser: (id: number, active: boolean) =>
      api.post<OkResponse>(`users/${id}/toggle`, { active }),
    listInvites: () => api.get<InvitesResponse>('invites'),
    createInvite: () => api.post<{ code: string }>('invites', {}),
    revokeInvite: (code: string) =>
      api.post<OkResponse>(`invites/${encodeURIComponent(code)}/revoke`, {}),
    getActivity: () => api.get<ActivityResponse>('activity'),
    getOnlineUsers: () => api.get<OnlineUsersResponse>('online-users'),
  };
}

export type UsersApi = ReturnType<typeof createUsersApi>;